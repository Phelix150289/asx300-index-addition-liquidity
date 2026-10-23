"""Step 4 - Point-in-time reference-date market capitalisation for the whole ASX universe.

Primary point-in-time share count = Yahoo Finance `get_shares_full` (latest record dated on or before
the reference date, cached in `data/cache/yahoo_shares.json`), multiplied by the product of any
subsequent Yahoo split/consolidation ratios dated after that share record so that shares and
Yahoo's backwards-split-adjusted `Close` are on the exact same basis.

EODHD quarterly/annual share series (`shares_q`, `bs_shares_q`, `shares_a`, `bs_shares_a`) serve as:
  1. An independent cross-check: if Yahoo PIT shares and EODHD PIT shares disagree by > 25%,
     `SHARES_SOURCES_DISAGREE` is raised (blocking the stock from the control pool, while additions
     retain the Yahoo price-unit-consistent share count unless manually overridden).
  2. A fallback when Yahoo has no point-in-time share record on/before the reference date (e.g. DGT).

Explicit QA flags:
  CUR_MISMATCH             Yahoo price today x shares today disagrees with vendor market cap today
  CUR_UNCHECKED            current-cap consistency check cannot be run
  SPLIT_AFTER_RECORD       a split/consolidation happened after an unverified EODHD share record
  SHARES_JUMP              shares today / shares at the reference date is > 5x or < 1/5x
  SHARES_SOURCES_DISAGREE  Yahoo PIT shares and EODHD PIT shares disagree by > 25%
  STALE_SHARES             latest share record older than MAX_SHARES_AGE_DAYS
  CAP_RANK_IMPLAUSIBLE     addition market-cap rank outside [30, 450]
  NO_SHARES / NO_PRICE / STALE_PRICE / NO_SECTOR

Outputs:
  data/interim/reference_caps.csv        (one row per review x ticker)
  data/output/additions_cap_review.csv   (side-by-side comparison of naive EODHD vs fixed PIT caps)
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import math
import time

import numpy as np
import pandas as pd
import yfinance as yf

from common import (CACHE, CONFIG, CUR_CAP_TOL, GICS_CODES, INTERIM, LOGS, MATCH_LOOKBACK, MAX_PRICE_STALENESS_DAYS,
                    MAX_SHARES_AGE_DAYS, OUTPUT, SECTOR_FALLBACK, SHARES_JUMP_MAX, load_schedule, offset, trading_days)

BLOCKING = {"CUR_MISMATCH", "CUR_UNCHECKED", "SPLIT_AFTER_RECORD", "SHARES_JUMP", "SHARES_SOURCES_DISAGREE",
            "STALE_SHARES", "NO_SHARES", "NO_PRICE", "STALE_PRICE", "NO_SECTOR"}

YSHARES_FILE = CACHE / "yahoo_shares.json"


def ensure_yahoo_shares(tickers: list[str]) -> dict[str, list[list]]:
    """Load cached Yahoo get_shares_full series; fetch any missing tickers in parallel."""
    existing = json.loads(YSHARES_FILE.read_text(encoding="utf-8")) if YSHARES_FILE.exists() else {}
    todo = [t for t in tickers if t not in existing]
    if not todo:
        return existing

    print(f"Fetching Yahoo get_shares_full for {len(todo)} uncached tickers...")

    def fetch_one(t: str):
        for attempt in range(2):
            try:
                s = yf.Ticker(f"{t}.AX").get_shares_full(start="2022-01-01")
                if s is not None and len(s) > 0:
                    s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
                    s = s[~s.index.duplicated(keep="last")].sort_index()
                    recs = [[d.strftime("%Y-%m-%d"), int(round(float(v)))]
                            for d, v in s.items() if pd.notna(v) and float(v) > 0]
                    return t, recs
                return t, []
            except Exception:
                time.sleep(0.5 * (attempt + 1))
        return t, []

    done = 0
    with ThreadPoolExecutor(max_workers=24) as ex:
        futs = {ex.submit(fetch_one, t): t for t in todo}
        for fut in as_completed(futs):
            t, recs = fut.result()
            existing[t] = recs
            done += 1
            if done % 200 == 0 or done == len(todo):
                YSHARES_FILE.write_text(json.dumps(existing), encoding="utf-8")
    return existing


def sector_of(f: dict) -> tuple[str | None, str]:
    s = f.get("gic_sector")
    if s in GICS_CODES:
        return s, "gics"
    leg = SECTOR_FALLBACK.get(f.get("sector_legacy") or "")
    return (leg, "legacy_fallback") if leg else (None, "none")


def split_factor_after(splits_t: list[tuple[pd.Timestamp, float]], rec_date: str) -> float:
    """Product of Yahoo split ratios dated strictly after `rec_date`."""
    dt = pd.Timestamp(rec_date)
    fac = 1.0
    for sd, sr in splits_t:
        if sd > dt and sr > 0:
            fac *= float(sr)
    return fac


def yahoo_pit_shares(y_recs: list[list], ref: pd.Timestamp, splits_t: list[tuple[pd.Timestamp, float]]):
    """Latest Yahoo get_shares_full record on/before `ref`, adjusted for subsequent splits."""
    ref_s = ref.strftime("%Y-%m-%d")
    valid = [(d, float(s)) for d, s in (y_recs or []) if d <= ref_s and s and float(s) > 0]
    if not valid:
        return None
    d, s_raw = valid[-1]
    age = (ref - pd.Timestamp(d)).days
    sp_fac = split_factor_after(splits_t, d)
    s_adj = s_raw * sp_fac
    src = "yahoo_pit_split_adj" if abs(sp_fac - 1.0) > 1e-6 else "yahoo_pit"
    return {"src": src, "date": d, "shares_raw": s_raw, "shares": s_adj, "age": age, "split_factor": sp_fac}


def eodhd_pit_shares(f: dict, ref: pd.Timestamp, splits_t: list[tuple[pd.Timestamp, float]]):
    """Freshest share-count record dated on/before `ref` across EODHD + balance-sheet series."""
    ref_s = ref.strftime("%Y-%m-%d")
    pri = {"eodhd_q": 0, "bs_q": 1, "eodhd_a": 2, "bs_a": 3}
    recs = []
    for src, key in (("eodhd_q", "shares_q"), ("bs_q", "bs_shares_q"), ("eodhd_a", "shares_a"), ("bs_a", "bs_shares_a")):
        valid = [(d, float(s)) for d, s in (f.get(key) or []) if d <= ref_s and s and float(s) > 0]
        if valid:
            d, s = valid[-1]
            recs.append((src, d, s, (ref - pd.Timestamp(d)).days))
    if not recs:
        return None
    recs.sort(key=lambda r: (r[3], pri[r[0]]))
    best = recs[0]
    disagree = False
    for r in recs[1:]:
        if abs((pd.Timestamp(r[1]) - pd.Timestamp(best[1])).days) <= 35 and r[2] > 0:
            if abs(math.log(r[2] / best[2])) > math.log(1.25):
                disagree = True
    sp_fac = split_factor_after(splits_t, best[1])
    return {"src": best[0], "date": best[1], "shares": best[2], "shares_split_adj": best[2] * sp_fac,
            "age": best[3], "disagree": disagree, "split_factor": sp_fac}


def lookback_stats(prices: pd.DataFrame, ref: pd.Timestamp) -> pd.DataFrame:
    lb_start = offset(ref, -(MATCH_LOOKBACK - 1))
    lb = prices[(prices["date"] >= lb_start) & (prices["date"] <= ref)].copy()
    lb["dv"] = lb["close"] * lb["volume"]
    traded = lb[lb["volume"] > 0]
    g = lb.groupby("ticker")
    out = pd.DataFrame({
        "n_price_days_lb": g["close"].count(),
        "n_traded_days_lb": traded.groupby("ticker")["close"].count(),
        "median_dollar_vol_lb": traded.groupby("ticker")["dv"].median(),
    }).fillna({"n_traded_days_lb": 0})
    last = lb.sort_values("date").groupby("ticker").tail(1).set_index("ticker")
    out["close_ref"] = last["close"]
    out["close_ref_date"] = last["date"]
    return out


def main() -> None:
    sched = load_schedule()
    fund = json.loads((CACHE / "fundamentals_compact.json").read_text(encoding="utf-8"))
    prices = pd.read_pickle(CACHE / "yahoo_prices.pkl")
    splits = pd.read_csv(CACHE / "yahoo_splits.csv", parse_dates=["date"])
    adds = pd.read_csv(CONFIG / "additions.csv")
    overrides = pd.read_csv(CONFIG / "cap_overrides.csv")

    priced_tickers = sorted(set(prices["ticker"].astype(str).unique()) | set(adds["ticker"].astype(str).unique()))
    yshares_all = ensure_yahoo_shares(priced_tickers)

    split_by_t: dict[str, list[tuple[pd.Timestamp, float]]] = {}
    for t, g in splits.groupby("ticker"):
        split_by_t[str(t)] = list(zip(pd.to_datetime(g["date"]), g["splits"].astype(float)))

    # latest price (current-cap consistency check)
    latest = prices.sort_values("date").groupby("ticker").tail(1).set_index("ticker")[["close", "date"]]
    latest_cut = prices["date"].max() - pd.Timedelta(days=30)
    latest = latest[latest["date"] >= latest_cut]

    all_rows = []
    add_review_rows = []
    add_pairs = set(zip(adds["review_id"], adds["ticker"]))

    for r in sched.itertuples():
        ref = r.reference_date
        lb = lookback_stats(prices, ref)
        universe = sorted(set(pd.read_csv(INTERIM / "universe_symbols.csv")["Code"].astype(str)) | set(adds["ticker"]))
        rows = []
        for t in universe:
            f = fund.get(t)
            splits_t = split_by_t.get(t, [])
            flags: list[str] = []
            row = {"review_id": r.review_id, "ticker": t, "reference_date": ref,
                   "name": (f or {}).get("name"), "currency": (f or {}).get("currency"),
                   "domestic": (f or {}).get("domestic"), "ipo_date": (f or {}).get("ipo_date")}
            sec, sec_src = sector_of(f or {})
            row.update({"gics_sector": sec, "gics_source": sec_src,
                        "gics_code": GICS_CODES.get(sec), "gic_group": (f or {}).get("gic_group")})
            if sec is None:
                flags.append("NO_SECTOR")

            if t in lb.index and not pd.isna(lb.loc[t, "close_ref"]):
                l = lb.loc[t]
                stale = (ref - l["close_ref_date"]).days
                row.update({"close_ref": l["close_ref"], "close_ref_date": l["close_ref_date"],
                            "price_staleness_days": stale, "n_price_days_lb": int(l["n_price_days_lb"]),
                            "n_traded_days_lb": int(l["n_traded_days_lb"]),
                            "median_dollar_vol_lb": l["median_dollar_vol_lb"]})
                if stale > MAX_PRICE_STALENESS_DAYS:
                    flags.append("STALE_PRICE")
            else:
                flags.append("NO_PRICE")

            ys = yahoo_pit_shares(yshares_all.get(t, []), ref, splits_t)
            es = eodhd_pit_shares(f, ref, splits_t) if f else None

            # Choose primary PIT shares: Yahoo split-adjusted PIT if fresh, else EODHD PIT
            dual_verified = False
            if ys is not None and ys["age"] <= MAX_SHARES_AGE_DAYS:
                chosen_shares = ys["shares"]
                chosen_date = ys["date"]
                chosen_age = ys["age"]
                chosen_src = ys["src"]
                if es is not None and es["shares"] > 0:
                    # Check agreement with either EODHD raw (if EODHD already restated splits, e.g. LOT/PDI)
                    # or EODHD split-adjusted (if EODHD left pre-split shares unadjusted, e.g. PNR)
                    diff_raw = abs(math.log(ys["shares"] / es["shares"]))
                    diff_adj = abs(math.log(ys["shares"] / es["shares_split_adj"])) if es["shares_split_adj"] > 0 else diff_raw
                    if min(diff_raw, diff_adj) <= math.log(1.25):
                        dual_verified = True
                    else:
                        flags.append("SHARES_SOURCES_DISAGREE")
            elif es is not None:
                # Fallback to EODHD PIT shares
                chosen_shares = es["shares"]
                chosen_date = es["date"]
                chosen_age = es["age"]
                chosen_src = es["src"]
                if es["age"] > MAX_SHARES_AGE_DAYS:
                    flags.append("STALE_SHARES")
                if es["disagree"]:
                    flags.append("SHARES_SOURCES_DISAGREE")
                if abs(es["split_factor"] - 1.0) > 1e-6:
                    flags.append("SPLIT_AFTER_RECORD")
            elif ys is not None:
                chosen_shares = ys["shares"]
                chosen_date = ys["date"]
                chosen_age = ys["age"]
                chosen_src = ys["src"]
                flags.append("STALE_SHARES")
            else:
                chosen_shares = None
                chosen_date = None
                chosen_age = None
                chosen_src = None
                flags.append("NO_SHARES")

            if chosen_shares is not None:
                row.update({"shares_pit": chosen_shares, "shares_date": chosen_date,
                            "shares_age_days": chosen_age, "shares_src": chosen_src})
                # Current share count comparison (prefer Yahoo latest if available in price units, else EODHD)
                y_now_list = yshares_all.get(t, [])
                sn = float(y_now_list[-1][1]) if y_now_list else (f or {}).get("shares_now")
                if sn and sn > 0:
                    row["shares_now_over_pit"] = sn / chosen_shares
                    if sn / chosen_shares > SHARES_JUMP_MAX or sn / chosen_shares < 1 / SHARES_JUMP_MAX:
                        flags.append("SHARES_JUMP")

            # Today's unit consistency: Yahoo price x shares_now vs vendor market cap
            sn_e, mc_e = (f or {}).get("shares_now"), (f or {}).get("mcap_now")
            if t in latest.index and sn_e and mc_e:
                ratio = latest.loc[t, "close"] * sn_e / mc_e
                row["cur_cap_ratio"] = ratio
                if (ratio <= 0 or abs(math.log(ratio)) > CUR_CAP_TOL) and not dual_verified:
                    flags.append("CUR_MISMATCH")
            elif not dual_verified:
                flags.append("CUR_UNCHECKED")

            if "close_ref" in row and "shares_pit" in row:
                row["market_cap_aud"] = row["close_ref"] * row["shares_pit"]

            # Store both estimates for additions review audit
            if (r.review_id, t) in add_pairs:
                cr = row.get("close_ref", np.nan)
                e_raw_cap = (cr * es["shares"]) if (pd.notna(cr) and es is not None) else np.nan
                e_adj_cap = (cr * es["shares_split_adj"]) if (pd.notna(cr) and es is not None) else np.nan
                y_raw_cap = (cr * ys["shares_raw"]) if (pd.notna(cr) and ys is not None) else np.nan
                y_adj_cap = (cr * ys["shares"]) if (pd.notna(cr) and ys is not None) else np.nan
                add_review_rows.append({
                    "review_id": r.review_id, "ticker": t, "name": row["name"],
                    "reference_date": ref.strftime("%Y-%m-%d"),
                    "close_ref": cr,
                    "eodhd_unadj_shares": es["shares"] if es else np.nan,
                    "eodhd_shares_date": es["date"] if es else None,
                    "eodhd_unadj_cap_aud": e_raw_cap,
                    "eodhd_split_adj_cap_aud": e_adj_cap,
                    "yahoo_raw_shares": ys["shares_raw"] if ys else np.nan,
                    "yahoo_split_factor": ys["split_factor"] if ys else np.nan,
                    "yahoo_split_adj_shares": ys["shares"] if ys else np.nan,
                    "yahoo_shares_date": ys["date"] if ys else None,
                    "yahoo_pit_cap_aud": y_adj_cap,
                    "final_shares_src": chosen_src,
                    "final_market_cap_aud": row.get("market_cap_aud", np.nan),
                })

            row["qa_flags"] = ";".join(flags) if flags else "OK"
            row["qa_blocking"] = any(x in BLOCKING for x in flags)
            rows.append(row)

        df = pd.DataFrame(rows)
        # explicit manual overrides (config/cap_overrides.csv)
        for o in overrides[overrides["review_id"] == r.review_id].itertuples():
            m = (df["ticker"] == o.ticker)
            df.loc[m, "market_cap_aud"] = o.market_cap_aud
            df.loc[m, "qa_flags"] = f"OVERRIDE({o.source})"
            df.loc[m, "qa_blocking"] = False
        df["cap_rank"] = df["market_cap_aud"].rank(ascending=False, method="min")

        # Flag implausible addition cap ranks outside [30, 450]
        is_add = df["ticker"].isin(set(adds[adds["review_id"] == r.review_id]["ticker"]))
        implausible = is_add & df["cap_rank"].notna() & ((df["cap_rank"] < 30) | (df["cap_rank"] > 450))
        for idx in df[implausible].index:
            cur_f = df.loc[idx, "qa_flags"]
            df.loc[idx, "qa_flags"] = "CAP_RANK_IMPLAUSIBLE" if cur_f == "OK" else f"{cur_f};CAP_RANK_IMPLAUSIBLE"

        all_rows.append(df)

    out = pd.concat(all_rows, ignore_index=True)
    out.to_csv(INTERIM / "reference_caps.csv", index=False, date_format="%Y-%m-%d")

    # Enrich additions_cap_review.csv with final cap_rank and qa_flags
    add_df = pd.DataFrame(add_review_rows)
    add_df = add_df.merge(
        out[["review_id", "ticker", "cap_rank", "qa_flags"]],
        on=["review_id", "ticker"], how="left"
    )
    add_df["ratio_final_vs_eodhd_unadj"] = add_df["final_market_cap_aud"] / add_df["eodhd_unadj_cap_aud"]
    add_df.to_csv(LOGS / "additions_cap_review.csv", index=False)

    print(f"{len(out)} rows. Share with a market cap: {out['market_cap_aud'].notna().mean():.1%}; "
          f"blocking QA flag: {out['qa_blocking'].mean():.1%}")
    flag_counts = out["qa_flags"].str.split(";").explode().value_counts()
    print(flag_counts.to_string())
    chk = out.merge(adds[["review_id", "ticker"]], on=["review_id", "ticker"])
    print("\nAdditions: QA flags")
    print(chk["qa_flags"].value_counts().to_string())
    print("\nAdditions cap rank range:", chk["cap_rank"].min(), "to", chk["cap_rank"].max())


if __name__ == "__main__":
    main()
