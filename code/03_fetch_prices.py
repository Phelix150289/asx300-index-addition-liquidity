"""Step 3 - Yahoo Finance daily prices for the whole listed universe (plus every addition).

Why Yahoo: EODHD end-of-day prices are not included in the current EODHD plan (HTTP 403).
Yahoo 'Close' is split-adjusted (not dividend-adjusted); 'Adj Close' is split+dividend adjusted.
Volume is split-adjusted too, so Close x Volume is a consistent dollar volume.

Only the rows needed are kept: for every review [lookback_start, window_end] plus the last two
weeks (current price for unit checks). All split events are kept (needed to detect unit breaks).

Output: data/cache/yahoo_prices.pkl, data/cache/yahoo_splits.csv, data/cache/yahoo_missing.csv
"""
from __future__ import annotations

import time
import warnings
from datetime import date, timedelta

import pandas as pd
import yfinance as yf

from common import CACHE, CONFIG, INTERIM, load_schedule

warnings.filterwarnings("ignore")
BATCH = 60
BATCH_DIR = CACHE / "yahoo_batches"
BATCH_DIR.mkdir(exist_ok=True)
FIELDS = {"Open": "open", "High": "high", "Low": "low", "Close": "close", "Adj Close": "adj_close",
          "Volume": "volume", "Dividends": "dividends", "Stock Splits": "splits"}


def needed_intervals() -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    s = load_schedule()
    ivs = [(r.lookback_start - pd.Timedelta(days=10), r.window_end + pd.Timedelta(days=5)) for r in s.itertuples()]
    ivs.append((pd.Timestamp(date.today() - timedelta(days=21)), pd.Timestamp(date.today() + timedelta(days=2))))
    return ivs


def tidy(raw: pd.DataFrame, batch: list[str]) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame()
    if not isinstance(raw.columns, pd.MultiIndex):
        raw.columns = pd.MultiIndex.from_product([[batch[0]], raw.columns])
    frames = []
    for t in raw.columns.get_level_values(0).unique():
        sub = raw[t].copy()
        sub = sub[[c for c in FIELDS if c in sub.columns]].rename(columns=FIELDS)
        if "close" not in sub:
            continue
        sub = sub.dropna(subset=["close"])
        if sub.empty:
            continue
        sub.index = pd.to_datetime(sub.index).tz_localize(None).normalize()
        sub["ticker"] = t.replace(".AX", "")
        sub["date"] = sub.index
        frames.append(sub.reset_index(drop=True))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def download(batch: list[str], start: str, end: str) -> pd.DataFrame:
    for attempt in range(3):
        try:
            raw = yf.download(batch, start=start, end=end, auto_adjust=False, actions=True,
                              group_by="ticker", threads=True, progress=False)
            return tidy(raw, batch)
        except Exception as exc:  # network / throttling
            print(f"    retry {attempt + 1} after error: {str(exc)[:80]}")
            time.sleep(5 * (attempt + 1))
    return pd.DataFrame()


def main() -> None:
    univ = pd.read_csv(INTERIM / "universe_symbols.csv")
    adds = pd.read_csv(CONFIG / "additions.csv")
    codes = sorted(set(univ["Code"].astype(str)) | set(adds["ticker"].astype(str)))
    ymap = [f"{c}.AX" for c in codes]
    start, end = "2023-04-01", (date.today() + timedelta(days=1)).isoformat()
    ivs = needed_intervals()
    n_batches = (len(ymap) + BATCH - 1) // BATCH
    print(f"{len(codes)} tickers, {n_batches} batches, {start} -> {end}")

    kept, splits = [], []
    for i in range(n_batches):
        f = BATCH_DIR / f"batch_{i:03d}.pkl"
        if f.exists():
            df = pd.read_pickle(f)
        else:
            batch = ymap[i * BATCH:(i + 1) * BATCH]
            df = download(batch, start, end)
            got = set(df["ticker"]) if not df.empty else set()
            miss = [b for b in batch if b.replace(".AX", "") not in got]
            if miss:  # second chance, one request per ticker
                extra = [download([m], start, end) for m in miss[:25]]
                extra = [e for e in extra if not e.empty]
                if extra:
                    df = pd.concat([df] + extra, ignore_index=True)
            df.to_pickle(f)
            time.sleep(1.0)
        print(f"  batch {i + 1}/{n_batches}: {df['ticker'].nunique() if not df.empty else 0} tickers", flush=True)
        if df.empty:
            continue
        if "splits" in df:
            s = df[(df["splits"].fillna(0) > 0) & (df["splits"].fillna(1) != 1)][["ticker", "date", "splits"]]
            splits.append(s)
        mask = pd.Series(False, index=df.index)
        for lo, hi in ivs:
            mask |= (df["date"] >= lo) & (df["date"] <= hi)
        kept.append(df[mask])

    prices = pd.concat(kept, ignore_index=True)
    prices = prices.drop_duplicates(["ticker", "date"]).sort_values(["ticker", "date"])
    prices.to_pickle(CACHE / "yahoo_prices.pkl")
    sp = pd.concat(splits, ignore_index=True) if splits else pd.DataFrame(columns=["ticker", "date", "splits"])
    sp.to_csv(CACHE / "yahoo_splits.csv", index=False)
    missing = sorted(set(codes) - set(prices["ticker"]))
    pd.DataFrame({"ticker": missing}).to_csv(CACHE / "yahoo_missing.csv", index=False)
    print(f"Prices: {len(prices):,} rows, {prices['ticker'].nunique()} tickers; "
          f"splits/consolidations: {len(sp)}; tickers with no Yahoo data: {len(missing)}")


if __name__ == "__main__":
    main()
