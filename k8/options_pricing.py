"""American discrete-cash-dividend IV using an explicitly pinned QuantLib model.

No European fallback. QuantLib settings are serialized and restored within this
module; independent processes, not concurrent library threads, should scale it.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
import importlib
import math
import threading
from typing import Sequence

from .options_carry import asof_clock, CUTOFF as PRICING_CUTOFF

QUANTLIB_VERSION = "1.40"
_LOCK = threading.RLock()
MODEL = "QuantLib_American_FD_BlackScholes_discrete_dividend_Spot"


def _quantlib():
    try:
        ql = importlib.import_module("QuantLib")
    except ImportError as error:
        raise ImportError("American pricing requires approved QuantLib==1.40; no European fallback") from error
    if ql.__version__ != QUANTLIB_VERSION:
        raise RuntimeError(f"QuantLib=={QUANTLIB_VERSION} required; found {ql.__version__}")
    return ql


def _day(value: str | date) -> date:
    if isinstance(value, datetime):
        raise ValueError("expiration/dividend requires a calendar date")
    return date.fromisoformat(value) if isinstance(value, str) else value


def _inputs(spot, strike, asof_at, expiration_date, continuous_rate, kind, dividends,
            time_steps, space_points, continuous_dividend_yield=0.0, research_cutoff=PRICING_CUTOFF):
    clock = asof_clock(asof_at, cutoff=research_cutoff)
    expiry = _day(expiration_date)
    if not all(math.isfinite(float(value)) for value in (spot, strike, continuous_rate)):
        raise ValueError("finite spot, strike and continuous rate required")
    if min(spot, strike) <= 0 or expiry <= clock.date() or kind not in {"call", "put"}:
        raise ValueError("positive spot/strike/maturity and call/put required")
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 25
           for value in (time_steps, space_points)):
        raise ValueError("integer finite-difference grids of at least25 required")
    schedule = []
    for day, amount in dividends:
        day, amount = _day(day), float(amount)
        if not math.isfinite(amount) or amount < 0 or not clock.date() < day <= expiry:
            raise ValueError("cash dividends must be nonnegative and strictly future through expiry")
        schedule.append((day, amount))
    if len({day for day, _ in schedule}) != len(schedule):
        raise ValueError("aggregate same-ex-date cash dividends explicitly before pricing")
    if not math.isfinite(continuous_dividend_yield) or continuous_dividend_yield < 0:
        raise ValueError("continuous dividend yield must be finite and nonnegative")
    if schedule and continuous_dividend_yield != 0:
        raise ValueError("choose discrete dividends or continuous yield; do not double count")
    return clock.date(), expiry, sorted(schedule)


@contextmanager
def _price_function(spot, strike, valuation, expiry, rate, kind, schedule, tgrid, xgrid,
                    continuous_dividend_yield=0.0):
    ql = _quantlib()
    with _LOCK:
        settings = ql.Settings.instance()
        saved_date = settings.evaluationDate
        try:
            qdate = lambda day: ql.Date(day.day, day.month, day.year)
            today = qdate(valuation)
            settings.evaluationDate = today
            day_count = ql.Actual365Fixed()
            risk_free = ql.YieldTermStructureHandle(ql.FlatForward(today, rate, day_count, ql.Continuous))
            dividend_yield = ql.YieldTermStructureHandle(
                ql.FlatForward(today, continuous_dividend_yield, day_count, ql.Continuous))
            quote = ql.SimpleQuote(0.3)
            volatility = ql.BlackVolTermStructureHandle(
                ql.BlackConstantVol(today, ql.NullCalendar(), ql.QuoteHandle(quote), day_count))
            process = ql.BlackScholesMertonProcess(
                ql.QuoteHandle(ql.SimpleQuote(float(spot))), dividend_yield, risk_free, volatility)
            option = ql.VanillaOption(ql.PlainVanillaPayoff(ql.Option.Call if kind == "call" else ql.Option.Put,
                                                          float(strike)),
                                      ql.AmericanExercise(today, qdate(expiry)))
            cash = ql.DividendSchedule()
            for day, amount in schedule:
                cash.append(ql.FixedDividend(amount, qdate(day)))
            engine = ql.FdBlackScholesVanillaEngine.make(
                process, dividends=cash, tGrid=tgrid, xGrid=xgrid, dampingSteps=2,
                schemeDesc=ql.FdmSchemeDesc.Douglas(),
                cashDividendModel=ql.FdBlackScholesVanillaEngine.Spot)
            option.setPricingEngine(engine)

            def price(sigma):
                quote.setValue(float(sigma))
                value = float(option.NPV())
                if not math.isfinite(value) or value < 0:
                    raise RuntimeError("invalid American model price")
                return value

            yield price
        finally:
            settings.evaluationDate = saved_date


def american_option_price(spot: float, strike: float, asof_at: str | datetime,
                          expiration_date: str | date, continuous_rate: float,
                          sigma: float, kind: str, dividends: Sequence[tuple[date, float]], *,
                          time_steps: int = 200, space_points: int = 400,
                          continuous_dividend_yield: float = 0.0,
                          research_cutoff: str | date = PRICING_CUTOFF) -> float:
    """Price with explicit American exercise and a dated discrete cash schedule.

    Date-only ACT/365 is a declared proxy for the intraday quote clock. The rate
    is continuously compounded, annualized and flattened to the contract expiry.
    """
    valuation, expiry, cash = _inputs(spot, strike, asof_at, expiration_date,
                                     continuous_rate, kind, dividends, time_steps, space_points,
                                     continuous_dividend_yield, research_cutoff)
    if not math.isfinite(sigma) or sigma <= 0:
        raise ValueError("positive finite annualized volatility required")
    with _price_function(spot, strike, valuation, expiry, continuous_rate, kind,
                          cash, time_steps, space_points, continuous_dividend_yield) as price:
        return price(sigma)


@dataclass(frozen=True)
class AmericanIV:
    iv: float
    status: str
    repriced: float = math.nan
    repricing_error: float = math.nan
    grid_price_difference: float = math.nan
    grid_iv_difference: float = math.nan
    library_version: str = QUANTLIB_VERSION
    model: str = MODEL
    time_convention: str = "NY_calendar_date_ACT365_intraday_time_proxy"
    rate_convention: str = "continuous_annual_flat_to_contract_expiry_proxy"


def american_implied_volatility(price: float, spot: float, strike: float,
                                asof_at: str | datetime, expiration_date: str | date,
                                continuous_rate: float, kind: str,
                                dividends: Sequence[tuple[date, float]], *,
                                time_steps: int = 200, space_points: int = 400,
                                min_vol: float = 0.01, max_vol: float = 5.0,
                                price_tolerance: float = 0.005,
                                iv_tolerance: float = 0.0005,
                                continuous_dividend_yield: float = 0.0,
                                research_cutoff: str | date = PRICING_CUTOFF) -> AmericanIV:
    """Invert this exact engine twice; reject poor repricing/grid convergence.

    Tolerances are price dollars/share and absolute decimal annualized IV.
    Empty dividends must be an explicit declared-only/zero-dividend scenario,
    not an inference that a company will pay no future dividends.
    """
    valuation, expiry, cash = _inputs(spot, strike, asof_at, expiration_date,
                                     continuous_rate, kind, dividends, time_steps, space_points,
                                     continuous_dividend_yield, research_cutoff)
    metadata = {'model': 'QuantLib_American_FD_BlackScholes_continuous_yield'
                if continuous_dividend_yield else MODEL}
    numeric = (price, min_vol, max_vol, price_tolerance, iv_tolerance)
    if not all(math.isfinite(value) for value in numeric) or not 0 < min_vol < max_vol:
        raise ValueError("finite price and positive ordered volatility bounds required")
    if min(price_tolerance, iv_tolerance) <= 0:
        raise ValueError("positive convergence tolerances required")
    intrinsic = max(spot - strike, 0) if kind == "call" else max(strike - spot, 0)
    if price <= intrinsic + 1e-8:
        return AmericanIV(math.nan, "at_or_below_intrinsic_no_identified_positive_IV", **metadata)
    from scipy.optimize import brentq

    def solve(tgrid, xgrid):
        with _price_function(spot, strike, valuation, expiry, continuous_rate, kind,
                              cash, tgrid, xgrid, continuous_dividend_yield) as model_price:
            low, high = model_price(min_vol), model_price(max_vol)
            if not low < price < high:
                return None
            value = float(brentq(lambda sigma: model_price(sigma) - price,
                                  min_vol, max_vol, xtol=1e-8, maxiter=100))
            return value, model_price(value)

    coarse = solve(time_steps, space_points)
    if coarse is None:
        return AmericanIV(math.nan, "outside_declared_volatility_search_bounds", **metadata)
    fine = solve(time_steps * 2, space_points * 2)
    if fine is None:
        return AmericanIV(math.nan, "fine_grid_outside_declared_volatility_search_bounds", **metadata)
    iv, repriced = fine
    with _price_function(spot, strike, valuation, expiry, continuous_rate, kind,
                          cash, time_steps, space_points, continuous_dividend_yield) as model_price:
        difference = abs(model_price(iv) - repriced)
    iv_difference, error = abs(coarse[0] - iv), abs(repriced - price)
    status = ("solved" if error <= price_tolerance and difference <= price_tolerance
              and iv_difference <= iv_tolerance else "grid_or_repricing_tolerance_failed")
    return AmericanIV(iv if status == "solved" else math.nan, status, repriced, error,
                      difference, iv_difference, **metadata)
