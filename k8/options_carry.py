"""Dated Massive carry inputs; no network calls or implicit dividend forecasts."""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime
import math
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")
CUTOFF = date(2023, 12, 31)
TENOR_MONTHS = {
    "yield_1_month": 1, "yield_2_month": 2, "yield_3_month": 3,
    "yield_4_month": 4, "yield_6_month": 6, "yield_1_year": 12,
    "yield_2_year": 24, "yield_3_year": 36, "yield_5_year": 60,
    "yield_7_year": 84, "yield_10_year": 120, "yield_20_year": 240,
    "yield_30_year": 360,
}


def _aware_clock(value: str | datetime) -> datetime:
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("asof_at requires an explicit timezone")
    return stamp.astimezone(NEW_YORK)


def asof_clock(value: str | datetime, *, cutoff: str | date = CUTOFF) -> datetime:
    local = _aware_clock(value)
    boundary = _date(cutoff)
    if local.date() > boundary:
        raise ValueError("Observation exceeds the requested research cutoff")
    return local


def _date(value: str | date) -> date:
    if isinstance(value, datetime):
        raise ValueError("expected a calendar date, not a timestamp")
    return date.fromisoformat(value) if isinstance(value, str) else value


def _months_after(day: date, months: int) -> date:
    year, month = divmod(day.year * 12 + day.month - 1 + months, 12)
    month += 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def _available(row: Mapping, observed_day: date, clock: datetime) -> bool:
    # Date-only releases become eligible the following calendar day. A source
    # timestamp can tighten this rule only when its availability is verified.
    if observed_day > CUTOFF or observed_day > clock.date():
        return False
    if row.get("available_at_verified") is True and row.get("available_at"):
        available = _aware_clock(row["available_at"])
        if available.date() < observed_day:
            raise ValueError("verified availability cannot precede its observation/declaration date")
        return available <= clock
    return observed_day < clock.date()


@dataclass(frozen=True)
class RateInput:
    observation_date: date
    asof_date: date
    expiration_date: date
    age_calendar_days: int
    continuous_rate: float
    discount_factor: float
    lower_tenor: str
    upper_tenor: str
    lower_yield_percent: float
    upper_yield_percent: float
    construction: str = "CMT_as_zero_proxy_log_discount_interpolation"
    availability: str = "prior_date_proxy_not_verified_publication_or_vintage"
    historical_vintage_verified: bool = False


def treasury_rate_input(rows: Sequence[Mapping], asof_at: str | datetime,
                        expiration_date: str | date, max_age_days: int = 7) -> RateInput:
    """Latest eligible CMT row, BEY conversion and bracketed log-discount proxy.

    The output is a maturity-matched continuously compounded flat-rate proxy,
    not a bootstrapped zero curve. Missing tenors are never extrapolated.
    """
    clock = asof_clock(asof_at)
    expiry = _date(expiration_date)
    years = (expiry - clock.date()).days / 365.0
    if years <= 0 or max_age_days < 0:
        raise ValueError("positive maturity and nonnegative maximum rate age required")
    eligible = [(_date(row["date"]), row) for row in rows
                if _available(row, _date(row["date"]), clock)]
    if not eligible:
        raise ValueError("no eligible dated Treasury observation")
    observed = max(day for day, _ in eligible)
    latest = [row for day, row in eligible if day == observed]
    if len(latest) != 1:
        raise ValueError("duplicate Treasury observation date requires reconciliation")
    age = (clock.date() - observed).days
    if age > max_age_days:
        raise ValueError("stale Treasury observation")
    row = latest[0]
    nodes = []
    for field, months in TENOR_MONTHS.items():
        if row.get(field) is None:
            continue
        percent = float(row[field])
        if not math.isfinite(percent) or percent <= -200:
            raise ValueError("invalid Treasury percent yield")
        tenor = (_months_after(clock.date(), months) - clock.date()).days / 365.0
        # Treasury's CMT quotes are semiannual bond-equivalent percent yields.
        continuous = 2 * math.log1p(percent / 200.0)
        nodes.append((tenor, field, percent, -continuous * tenor))
    lower = [node for node in nodes if node[0] <= years]
    upper = [node for node in nodes if node[0] >= years]
    if not lower or not upper:
        raise ValueError("missing Treasury tenor bracket; extrapolation prohibited")
    lo, hi = max(lower), min(upper)
    weight = 0.0 if hi[0] == lo[0] else (years - lo[0]) / (hi[0] - lo[0])
    log_discount = (1 - weight) * lo[3] + weight * hi[3]
    availability = ("verified_availability_timestamp_vintage_unverified"
                    if row.get("available_at_verified") is True and row.get("available_at")
                    else "prior_date_proxy_not_verified_publication_or_vintage")
    return RateInput(observed, clock.date(), expiry, age, -log_discount / years,
                     math.exp(log_discount), lo[1], hi[1], lo[2], hi[2], availability=availability)


@dataclass(frozen=True)
class CashDividend:
    ex_date: date
    amount: float
    source_id: str
    declaration_date: date
    provenance: str


@dataclass(frozen=True)
class DividendInput:
    declared: tuple[CashDividend, ...]
    forecast: tuple[CashDividend, ...]
    expectation: str
    share_basis: str
    historical_vintage_verified: bool = False

    @property
    def cashflows(self) -> tuple[tuple[date, float], ...]:
        return tuple((item.ex_date, item.amount)
                     for item in sorted(self.declared + self.forecast, key=lambda x: x.ex_date))


def cash_on_asof_share_basis(amount: float, cash_share_date: str | date,
                             splits: Sequence[Mapping], ticker: str,
                             asof_at: str | datetime) -> float:
    """Normalize original historical cash using only splits effective by asof.

    This helper does not establish split-history completeness; callers must do
    that separately. Split records use Massive execution_date/split_from/to.
    """
    clock = asof_clock(asof_at)
    basis_day = _date(cash_share_date)
    if basis_day > clock.date():
        raise ValueError("cannot normalize an unobserved future cash share basis")
    amount = float(amount)
    if not math.isfinite(amount) or amount < 0:
        raise ValueError("invalid original dividend cash")
    seen = set()
    for split in splits:
        if split.get("ticker") != ticker:
            continue
        effective = _date(split["execution_date"])
        if not basis_day < effective <= clock.date():
            continue
        # Split shares are effective from the session open; no pre-open use.
        if effective == clock.date() and (clock.hour, clock.minute) < (9, 30):
            continue
        identity = (effective, ticker)
        if identity in seen:
            raise ValueError("duplicate split date requires reconciliation")
        seen.add(identity)
        old, new = float(split["split_from"]), float(split["split_to"])
        if not all(math.isfinite(value) and value > 0 for value in (old, new)):
            raise ValueError("invalid split ratio")
        amount *= old / new
    return amount


def dividend_input(rows: Sequence[Mapping], splits: Sequence[Mapping], ticker: str,
                   asof_at: str | datetime, expiration_date: str | date, *,
                   forecast_recurring: bool = False,
                   split_history_complete: bool = False) -> DividendInput:
    """Declared future cash plus an optional, explicitly named forecast proxy.

    Future declarations are excluded even if their actual ex-date is known in
    today's API response. No cash is read from split_adjusted_cash_amount.
    """
    clock = asof_clock(asof_at)
    expiry = _date(expiration_date)
    if expiry <= clock.date():
        raise ValueError("positive maturity required")
    known = []
    seen = set()
    for row in rows:
        if row.get("ticker") != ticker or not row.get("declaration_date"):
            continue
        declared_day = _date(row["declaration_date"])
        if not _available(row, declared_day, clock):
            continue
        ex_day = _date(row["ex_dividend_date"])
        if declared_day > ex_day:
            raise ValueError("dividend declaration follows ex-date")
        if row.get("currency") != "USD":
            raise ValueError("USD original cash dividends required")
        cash = float(row["cash_amount"])
        if not math.isfinite(cash) or cash < 0:
            raise ValueError("invalid original dividend cash")
        identity = (ticker, ex_day, row.get("distribution_type"))
        if identity in seen:
            raise ValueError("duplicate dividend requires reconciliation")
        seen.add(identity)
        known.append((ex_day, declared_day, cash, row))
    declared = tuple(CashDividend(ex, cash, str(row.get("id", "")), declaration,
                                  "declared_original_cash_verified_availability"
                                  if row.get("available_at_verified") is True and row.get("available_at")
                                  else "declared_original_cash_date_lag")
                     for ex, declaration, cash, row in sorted(known, key=lambda x: x[0])
                     if clock.date() < ex <= expiry)
    forecast = []
    expectation = "declared_only_incomplete_future_expectation"
    if forecast_recurring:
        if not split_history_complete:
            raise ValueError("verified complete split history required for dividend forecasts")
        recurring = [item for item in known if item[3].get("distribution_type") == "recurring"
                     and item[3].get("frequency") in (1, 2, 4, 12)]
        if not recurring:
            raise ValueError("no eligible recurring dividend history for forecast")
        ex, declaration, cash, row = max(recurring, key=lambda x: x[0])
        interval = 12 // int(row["frequency"])
        if _months_after(ex, 2 * interval) < clock.date():
            raise ValueError("stale recurring dividend history")
        if ex <= clock.date():
            cash = cash_on_asof_share_basis(cash, ex, splits, ticker, clock)
        # A future declared cash amount already belongs to its declared series;
        # no future effective split is applied to it or to the forecast.
        index = 1
        while (forecast_date := _months_after(ex, index * interval)) <= expiry:
            if forecast_date > clock.date():
                forecast.append(CashDividend(forecast_date, cash, str(row.get("id", "")),
                                              declaration, "frozen_cash_calendar_cadence_forecast_proxy"))
            index += 1
        expectation = "declared_plus_frozen_recurring_forecast_proxy"
    basis = ("original_cash_with_verified_effective_asof_splits"
             if split_history_complete else "original_cash_split_history_unverified")
    return DividendInput(declared, tuple(forecast), expectation, basis)
