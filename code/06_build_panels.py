"""Step 6 - Assemble the six regression-ready review panels and coverage tables.

One row per review x stock x trading date (121 event days, -60..+60). Stacked 1 addition : N controls
groups keep an explicit `matched_group_id`. Rows are never dropped: missing / zero-volume days stay in
the panel with a flag so coverage rules can be applied (or varied) transparently at analysis time.

Liquidity and Trading Metrics Included:
  - Amihud illiquidity: |return_t| / (Close_t x Volume_t) x 1e6
  - Dollar volume: Close_t x Volume_t
  - Log dollar volume: ln(DollarVolume_t) (NaN on zero-volume days)
  - Shares outstanding: cleaned point-in-time shares as of date t (split-adjusted, filtered for unit-basis
    anomalies and transient Yahoo scraper jitter into a clean step function)
  - Daily market cap: Close_t x shares_outstanding_t
  - Share turnover rate: Volume_t / shares_outstanding_t (NaN on zero-volume days)
  - Log turnover rate: ln(turnover_rate_t) (NaN on zero-volume days)

Output: data/output/review_01.csv .. review_06.csv, stock_stage_coverage.csv, group_stage_usable.csv
"""
from __future__ import annotations

import json
import numpy as np
import pandas as pd

from common import (CACHE, CONFIG, GICS_CODES, INTERIM, N_CONTROLS, OUTPUT, STAGE_MIN_COVERAGE, event_calendar,
                    load_schedule, offset, trading_days)

PRICE_COLS = ["open", "high", "low", "close", "adj_close", "volume"]


def daily_frame(ts: pd.DataFrame | None, days: pd.DatetimeIndex) -> pd.DataFrame:
    df = pd.DataFrame(index=days)
    if ts is not None:
        df = df.join(ts[PRICE_COLS])
    ret = df["adj_close"].pct_change(fill_method=None)
    dv = df["close"] * df["volume"]
    ok = (df["volume"] > 0) & (df["close"] > 0) & ret.notna()
    df["daily_return"] = ret
    df["amihud"] = np.where(ok, ret.abs() / dv * 1e6, np.nan)
    df["dollar_volume"] = np.where((df["close"] > 0) & (df["volume"] >= 0), dv, np.nan)
    pos_dv = df["dollar_volume"].where(df["dollar_volume"] > 0)
    df["log_dollar_volume"] = np.log(pos_dv)

    flag = np.select(
        [df["close"].isna(), df["volume"].fillna(0) <= 0, ret.isna()],
        ["MISSING_PRICE", "ZERO_VOLUME", "NO_RETURN"], default="OK")
    df["data_quality_flag"] = flag
    df["missing_observation"] = df["close"].isna().astype(int)
    return df


def get_daily_shares_series(code: str, dates: pd.DatetimeIndex, ref_date: pd.Timestamp,
                            yshares: dict, splits_by_t: dict, ref_shares: float | None) -> pd.Series:
    """Cleaned point-in-time share count as of each date, adjusted for subsequent splits."""
    dates_idx = pd.DatetimeIndex(dates)
    if ref_shares is None or pd.isna(ref_shares) or ref_shares <= 0:
        return pd.Series(np.nan, index=dates_idx)
    raw = [(pd.Timestamp(d), float(s)) for d, s in yshares.get(code, []) if float(s) > 0]
    # Prevent mid-window vendor switching if no Yahoo PIT record existed on/before reference_date
    if not raw or not any(d <= ref_date for d, _ in raw):
        return pd.Series(float(ref_shares), index=dates_idx)
    sp_list = splits_by_t.get(code, [])
    adj = {}
    for d, s in raw:
        sp_fac = 1.0
        for sd, sr in sp_list:
            if sd > d and sr > 0:
                sp_fac *= sr
        s_adj = s * sp_fac
        # Reject unit-basis glitches (e.g., 20x UK AIM parent shares on GGP) outside [0.4x, 2.5x] of ref_shares
        if 0.4 * ref_shares <= s_adj <= 2.5 * ref_shares:
            adj[d] = s_adj
    if not adj or not any(d <= ref_date for d in adj):
        return pd.Series(float(ref_shares), index=dates_idx)
    ser = pd.Series(adj).sort_index()
    # Keep statutory share counts confirmed (within 0.05%) on at least two distinct dates
    vals = ser.values
    confirmed_mask = []
    for i, v in enumerate(vals):
        others = np.delete(vals, i)
        confirmed_mask.append(bool(np.any(np.abs(others - v) / v <= 0.0005)) if len(others) > 0 else True)
    ser_conf = ser[confirmed_mask]
    if len(ser_conf) == 0 or not any(d <= ref_date for d in ser_conf.index):
        ser_conf = ser
    # 5-observation rolling median + monotone non-reverting step filter to strip temporary scraper excursions
    ser_med = ser_conf.rolling(5, center=True, min_periods=1).median()
    ser_monotone = ser_med.iloc[::-1].cummin().iloc[::-1].cummax()
    out = []
    for dt in dates_idx:
        sub = ser_monotone[ser_monotone.index <= dt]
        out.append(float(sub.iloc[-1]) if len(sub) else float(ref_shares))
    s_daily = pd.Series(out, index=dates_idx)
    # 1% deadband step filter to suppress sub-1% FX/rounding jitter while preserving corporate issuances
    stepped = []
    cur = float(s_daily.iloc[0])
    for val in s_daily:
        if abs(val - cur) / cur >= 0.01:
            cur = float(val)
        stepped.append(cur)
    return pd.Series(stepped, index=dates_idx)


def main() -> None:
    sched = load_schedule()
    groups = pd.read_csv(OUTPUT / "matched_controls.csv")
    caps = pd.read_csv(INTERIM / "reference_caps.csv", parse_dates=["reference_date"])
    prices = pd.read_pickle(CACHE / "yahoo_prices.pkl")
    yshares = json.loads((CACHE / "yahoo_shares.json").read_text(encoding="utf-8")) if (CACHE / "yahoo_shares.json").exists() else {}
    splits = pd.read_csv(CACHE / "yahoo_splits.csv", parse_dates=["date"])
    splits_by_t = {t: list(zip(pd.to_datetime(g["date"]), g["splits"].astype(float))) for t, g in splits.groupby("ticker")}

    by_t = {t: g.set_index("date").sort_index() for t, g in prices.groupby("ticker")}
    all_days = trading_days()

    cov_rows, usable_rows = [], []
    for r in sched.itertuples():
        rid = r.review_id
        cal = event_calendar(r._asdict())
        i0, i1 = all_days.get_loc(r.lookback_start), all_days.get_loc(r.window_end)
        days = all_days[i0:i1 + 1]
        c_rev = caps[caps["review_id"] == rid].set_index("ticker")

        members = []
        for g in groups[groups["review_id"] == rid].itertuples():
            members.append((g.addition_ticker, 1, g.matched_group_id, g.matching_tier))
            for k in range(1, N_CONTROLS + 1):
                t = getattr(g, f"control_{k}_ticker")
                if isinstance(t, str) and t != "NONE":
                    members.append((t, 0, g.matched_group_id, g.matching_tier))

        frames = []
        for code, treat, gid, tier in members:
            d = daily_frame(by_t.get(code), days)
            # matching-window Amihud: mean over the last 10 trading days up to the reference date (descriptive)
            lb = d.loc[offset(r.reference_date, -9):r.reference_date, "amihud"]
            mw = lb.mean() if lb.notna().any() else np.nan
            d = d.loc[cal["trading_date"]].copy()
            d.index.name = "trading_date"
            d = d.reset_index()
            d["event_day"] = cal["event_day"].values
            d["stage"] = cal["stage"].values

            crow = c_rev.loc[code] if code in c_rev.index else None
            sector = None if crow is None else crow["gics_sector"]
            ref_shares = None if crow is None else crow["shares_pit"]

            # Daily point-in-time shares outstanding and derived liquidity/size series
            daily_sh = get_daily_shares_series(code, cal["trading_date"], r.reference_date,
                                               yshares, splits_by_t, ref_shares)
            d["shares_outstanding"] = daily_sh.values
            d["daily_market_cap_aud"] = np.where((d["close"] > 0) & (d["shares_outstanding"] > 0),
                                                 d["close"] * d["shares_outstanding"], np.nan)
            valid_turn = (d["close"] > 0) & (d["volume"] > 0) & (d["shares_outstanding"] > 0)
            d["turnover_rate"] = np.where(valid_turn, d["volume"] / d["shares_outstanding"], np.nan)
            pos_turn = d["turnover_rate"].where(d["turnover_rate"] > 0)
            d["log_turnover_rate"] = np.log(pos_turn)

            d.insert(0, "review_id", rid)
            d.insert(1, "stock_id", f"{code}.AX")
            d.insert(3, "treatment", treat)
            d.insert(4, "matched_group_id", gid)
            d["announcement_date"] = r.announcement_date.date()
            d["effective_date"] = r.implementation_date.date()
            d["reference_date"] = r.reference_date.date()
            d["reference_market_cap_aud"] = None if crow is None else crow["market_cap_aud"]
            d["reference_cap_rank"] = None if crow is None else crow["cap_rank"]
            d["gics_code"] = GICS_CODES.get(sector)
            d["gics_name"] = sector
            d["matching_window_amihud"] = mw
            d["matching_tier"] = tier
            d["cap_qa_flags"] = None if crow is None else crow["qa_flags"]
            frames.append(d)

        panel = pd.concat(frames, ignore_index=True).rename(columns={"adj_close": "adjusted_close"})
        cols = ["review_id", "stock_id", "trading_date", "treatment", "matched_group_id", "event_day", "stage",
                "announcement_date", "effective_date", "reference_date", "open", "high", "low", "close", "volume",
                "adjusted_close", "daily_return", "amihud", "dollar_volume", "log_dollar_volume",
                "shares_outstanding", "daily_market_cap_aud", "turnover_rate", "log_turnover_rate",
                "reference_market_cap_aud", "reference_cap_rank", "gics_code", "gics_name",
                "matching_window_amihud", "matching_tier", "cap_qa_flags", "data_quality_flag", "missing_observation"]
        panel = panel[cols]
        fn = OUTPUT / f"review_{int(rid[1:]):02d}.csv"
        panel.to_csv(fn, index=False, date_format="%Y-%m-%d")
        print(f"{rid}: {len(panel):,} rows, {panel['stock_id'].nunique()} stocks, "
              f"{panel['matched_group_id'].nunique()} groups -> {fn.name}")

        # ---- stage coverage
        stages = ["B", "P", "M", "L"]
        pst = panel[panel["stage"].isin(stages)]
        cov = (pst.groupby(["review_id", "matched_group_id", "stock_id", "treatment", "stage"])
               .agg(expected_days=("stage", "size"), valid_amihud_days=("amihud", "count"),
                    mean_amihud=("amihud", "mean"), zero_volume_days=("data_quality_flag", lambda s: (s == "ZERO_VOLUME").sum()),
                    missing_price_days=("missing_observation", "sum")).reset_index())
        cov["coverage_pct"] = cov["valid_amihud_days"] / cov["expected_days"]
        cov["passes_stage_coverage"] = cov["coverage_pct"] >= STAGE_MIN_COVERAGE
        cov["analysis_mean_amihud"] = np.where(cov["passes_stage_coverage"], cov["mean_amihud"], np.nan)
        cov_rows.append(cov)

        for (gid, stg), g in cov.groupby(["matched_group_id", "stage"]):
            usable = bool(g["passes_stage_coverage"].all())
            base = cov[(cov["matched_group_id"] == gid) & (cov["stage"] == "B")]["passes_stage_coverage"].all()
            usable_rows.append({"review_id": rid, "matched_group_id": gid, "stage": stg,
                                "group_stage_usable": usable, "baseline_usable": bool(base),
                                "stage_and_baseline_usable": bool(usable and base)})

    pd.concat(cov_rows, ignore_index=True).to_csv(OUTPUT / "stock_stage_coverage.csv", index=False)
    u = pd.DataFrame(usable_rows)
    u.to_csv(OUTPUT / "group_stage_usable.csv", index=False)
    print("\nUsable groups (stage AND baseline) by review/stage:")
    print(u.pivot_table(index="review_id", columns="stage", values="stage_and_baseline_usable", aggfunc="sum")
          .to_string())


if __name__ == "__main__":
    main()
