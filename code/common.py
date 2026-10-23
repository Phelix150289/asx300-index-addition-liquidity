"""Shared paths, study-design constants, ASX trading calendar and event-window helpers.

Every study parameter lives here so the whole pipeline can be audited in one place.
"""
from __future__ import annotations

import functools
import os
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CONFIG = DATA / "raw"
CACHE = DATA / "cache"
INTERIM = DATA / "interim"
OUTPUT = DATA / "derived"
LOGS = ROOT / "output" / "logs"
for _p in (CACHE, INTERIM, OUTPUT, LOGS):
    _p.mkdir(parents=True, exist_ok=True)

# --------------------------------------------------------------------------------------
# Study design (from the project plan)
# --------------------------------------------------------------------------------------
WINDOW_DAYS = 60                 # event days -60..+60 around announcement day A* (= day 0)
BASELINE = (-30, -11)            # Stage B (20 trading days)
PRE = (-10, -1)                  # Stage P (10 trading days)
L_DAYS = 20                      # Stage L = E+1 .. E+20 ; Stage M = A*+1 .. E
REF_OFFSET = -11                 # reference date = last day of Stage B (A* - 11)
N_CONTROLS = 2

PRIMARY_BAND = (0.5, 2.0)        # tier 1: same GICS sector, cap ratio in [0.5, 2.0]
WIDE_BAND = (0.33, 3.0)          # tier 2/3: widened band when tier 1 cannot fill 2 controls

# --------------------------------------------------------------------------------------
# Data-quality gates (documented in README). None of them uses Amihud levels.
# --------------------------------------------------------------------------------------
MATCH_LOOKBACK = 60              # trading days up to the reference date used for tradability screen
MIN_LOOKBACK_PRICE_SHARE = 0.80  # share of lookback days with a price (rejects new listings)
MIN_TRADED_SHARE = 0.80          # share of lookback days with volume > 0 (matches 80% stage rule)
MAX_PRICE_STALENESS_DAYS = 7     # calendar days between reference date and last price on/before it
MAX_SHARES_AGE_DAYS = 400        # age of the share-count record used at the reference date
CUR_CAP_TOL = 0.35               # |ln(Yahoo price x EODHD shares / EODHD market cap)| today
YAHOO_CAP_TOL = 0.50             # |ln(EODHD market cap / Yahoo market cap)| today
SHARES_JUMP_MAX = 5.0            # reject if shares today / shares at reference date > 5 or < 1/5
MIN_WINDOW_PRICE_COVERAGE = 0.90 # control must have prices on >= 90% of the 121 event days
MIN_BASELINE_DOLLAR_VOL = 100_000.0      # primary gate: median daily traded value (AUD) in Stage B (-30..-11)
FALLBACK_BASELINE_DOLLAR_VOL = 50_000.0  # fallback gate if primary gate cannot fill two controls
STAGE_MIN_COVERAGE = 0.80        # stage average usable if >= 80% valid Amihud days

GICS_CODES = {
    "Energy": 10, "Materials": 15, "Industrials": 20, "Consumer Discretionary": 25,
    "Consumer Staples": 30, "Health Care": 35, "Financials": 40,
    "Information Technology": 45, "Communication Services": 50, "Utilities": 55,
    "Real Estate": 60,
}
# EODHD legacy "Sector" labels -> GICS sector (used only when GicSector is missing)
SECTOR_FALLBACK = {
    "Basic Materials": "Materials", "Energy": "Energy", "Industrials": "Industrials",
    "Consumer Cyclical": "Consumer Discretionary", "Consumer Defensive": "Consumer Staples",
    "Healthcare": "Health Care", "Financial Services": "Financials",
    "Technology": "Information Technology", "Communication Services": "Communication Services",
    "Utilities": "Utilities", "Real Estate": "Real Estate",
}


def api_key() -> str:
    key = os.getenv("EODHD_API_KEY", "")
    if not key and (ROOT / ".env").exists():
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("EODHD_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not key:
        raise RuntimeError("EODHD_API_KEY not found in environment or .env")
    return key


# --------------------------------------------------------------------------------------
# ASX trading calendar
# --------------------------------------------------------------------------------------
_HOLIDAYS = {
    date(2023, 1, 2), date(2023, 1, 26), date(2023, 4, 7), date(2023, 4, 10), date(2023, 4, 25),
    date(2023, 6, 12), date(2023, 12, 25), date(2023, 12, 26),
    date(2024, 1, 1), date(2024, 1, 26), date(2024, 3, 29), date(2024, 4, 1), date(2024, 4, 25),
    date(2024, 6, 10), date(2024, 12, 25), date(2024, 12, 26),
    date(2025, 1, 1), date(2025, 1, 27), date(2025, 4, 18), date(2025, 4, 21), date(2025, 4, 25),
    date(2025, 6, 9), date(2025, 12, 25), date(2025, 12, 26),
    date(2026, 1, 1), date(2026, 1, 26), date(2026, 4, 3), date(2026, 4, 6),
    date(2026, 6, 8), date(2026, 12, 25), date(2026, 12, 28),
}


@functools.lru_cache(maxsize=1)
def trading_days() -> pd.DatetimeIndex:
    """All ASX trading days 2023-01-01 .. 2026-12-31 (weekdays minus public holidays)."""
    days, d = [], date(2023, 1, 1)
    while d <= date(2026, 12, 31):
        if d.weekday() < 5 and d not in _HOLIDAYS:
            days.append(pd.Timestamp(d))
        d += timedelta(days=1)
    return pd.DatetimeIndex(days)


def offset(anchor: pd.Timestamp, k: int) -> pd.Timestamp:
    """Trading day that is k trading days after (k>0) or before (k<0) `anchor`."""
    days = trading_days()
    i = days.get_loc(anchor)
    return days[i + k]


def stage_label(k: int, m_end: int) -> str:
    """Stage of event day k. Day 0 (announcement day) is its own stage 'A' and is excluded
    from B/P/M/L, exactly as in the plan (P ends at A*-1, M starts at A*+1)."""
    if BASELINE[0] <= k <= BASELINE[1]:
        return "B"
    if PRE[0] <= k <= PRE[1]:
        return "P"
    if k == 0:
        return "A"
    if 1 <= k <= m_end:
        return "M"
    if m_end < k <= m_end + L_DAYS:
        return "L"
    return "PRE_WINDOW" if k < BASELINE[0] else "POST_WINDOW"


def load_schedule() -> pd.DataFrame:
    df = pd.read_csv(INTERIM / "review_schedule.csv")
    for c in df.columns:
        if c.endswith("_date") or c.startswith("window_") or c in ("lookback_start",):
            df[c] = pd.to_datetime(df[c])
    return df


def event_calendar(sched_row) -> pd.DataFrame:
    """121-row calendar for one review: date, event_day, stage."""
    a = pd.Timestamp(sched_row["announcement_date"])
    e = pd.Timestamp(sched_row["implementation_date"])
    days = trading_days()
    ia = days.get_loc(a)
    m_end = days.get_loc(e) - ia
    rows = []
    for k in range(-WINDOW_DAYS, WINDOW_DAYS + 1):
        rows.append({"trading_date": days[ia + k], "event_day": k, "stage": stage_label(k, m_end)})
    return pd.DataFrame(rows)
