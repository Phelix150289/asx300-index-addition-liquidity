"""Step 5 - Match two controls to every addition (plan rule, no re-use inside a review).

Plan rule (tier 1): same GICS sector, control cap / addition cap in [0.5, 2.0], pick the two closest
in size (|ln ratio|). If tier 1 cannot fill two controls the plan's fallback protocol is applied and
RECORDED in `matching_tier`, so analyses can be restricted to tier-1 groups:

  T1  same sector, ratio in [0.5, 2.0]
  T2  same sector, ratio in [0.33, 3.0]
  T3  any sector,  ratio in [0.33, 3.0]
  T4  any sector,  closest size (last resort, logged)

Eligible controls (all gates use information available at or before the reference date, except the
unavoidable requirement that the control has prices through the event window):
  * ASX 'Common Stock' in AUD, not one of the 84 additions (any review) and not a known member
  * priced at the reference date, listed throughout the 60-day look-back with >= 50% traded days
  * point-in-time share count available and no blocking QA flag (units / splits / CDI risk)
  * second-source check: EODHD market cap agrees with Yahoo market cap (today)
  * prices on >= 90% of the 121 event days
  * baseline (Stage B, days -30..-11) median daily traded value >= A$100,000 (with A$50,000 fallback)
Amihud levels never influence selection.

Output: data/output/matched_controls.csv, data/output/control_candidates_log.csv,
        data/output/additions_status.csv
"""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import yfinance as yf

from common import (BASELINE, CACHE, CONFIG, FALLBACK_BASELINE_DOLLAR_VOL, INTERIM, LOGS, MATCH_LOOKBACK,
                    MIN_BASELINE_DOLLAR_VOL, MIN_LOOKBACK_PRICE_SHARE, MIN_TRADED_SHARE,
                    MIN_WINDOW_PRICE_COVERAGE, N_CONTROLS, OUTPUT, PRIMARY_BAND, WIDE_BAND, YAHOO_CAP_TOL,
                    event_calendar, load_schedule)

YCAP_FILE = CACHE / "yahoo_marketcap.json"
_ycap = json.loads(YCAP_FILE.read_text()) if YCAP_FILE.exists() else {}
_fund = json.loads((CACHE / "fundamentals_compact.json").read_text(encoding="utf-8"))


def yahoo_marketcap(code: str):
    if code in _ycap:
        return _ycap[code]
    val = None
    try:
        fi = yf.Ticker(f"{code}.AX").fast_info
        v = fi.get("marketCap")
        if v and fi.get("currency") in ("AUD", None):
            val = float(v)
    except Exception:
        val = None
    _ycap[code] = val
    YCAP_FILE.write_text(json.dumps(_ycap))
    return val


def second_source(code: str) -> tuple[bool, str]:
    mc_e = (_fund.get(code) or {}).get("mcap_now")
    mc_y = yahoo_marketcap(code)
    if not mc_y or not mc_e:
        return True, "YAHOO_UNAVAILABLE"
    if abs(math.log(mc_e / mc_y)) > YAHOO_CAP_TOL:
        return False, f"YAHOO_MISMATCH(eodhd={mc_e:,.0f};yahoo={mc_y:,.0f})"
    return True, "YAHOO_OK"


def main() -> None:
    sched = load_schedule()
    adds = pd.read_csv(CONFIG / "additions.csv", keep_default_na=False)
    caps = pd.read_csv(INTERIM / "reference_caps.csv", parse_dates=["reference_date"])
    prices = pd.read_pickle(CACHE / "yahoo_prices.pkl")
    known = pd.read_csv(CONFIG / "known_members.csv")
    all_additions = set(adds["ticker"])

    groups, cand_log, status = [], [], []
    for r in sched.itertuples():
        rid = r.review_id
        cal = event_calendar(r._asdict())
        win_dates = set(cal["trading_date"])
        win = prices[prices["date"].isin(win_dates)]
        win_cov = (win.groupby("ticker")["close"].count() / len(cal)).to_dict()

        base_dates = set(cal[(cal["event_day"] >= BASELINE[0]) & (cal["event_day"] <= BASELINE[1])]["trading_date"])
        base_px = win[win["date"].isin(base_dates)].copy()
        base_px["dv"] = base_px["close"] * base_px["volume"]
        base_med_dv = base_px.groupby("ticker")["dv"].median().to_dict()

        c = caps[caps["review_id"] == rid].copy()
        c["win_cov"] = c["ticker"].map(win_cov).fillna(0.0)
        c["baseline_med_dv"] = c["ticker"].map(base_med_dv).fillna(0.0)
        members = set(known[known["review_id"] == rid]["ticker"])

        c["lookback_ok"] = ((c["n_price_days_lb"].fillna(0) / MATCH_LOOKBACK >= MIN_LOOKBACK_PRICE_SHARE)
                            & (c["n_traded_days_lb"].fillna(0) / MATCH_LOOKBACK >= MIN_TRADED_SHARE))
        base_pool = c[(~c["ticker"].isin(all_additions)) & (~c["ticker"].isin(members))
                      & (~c["qa_blocking"]) & c["market_cap_aud"].notna() & (c["market_cap_aud"] > 0)
                      & c["gics_sector"].notna() & (c["currency"] == "AUD")
                      & c["lookback_ok"] & (c["win_cov"] >= MIN_WINDOW_PRICE_COVERAGE)].copy()
        pool = base_pool[base_pool["baseline_med_dv"] >= MIN_BASELINE_DOLLAR_VOL].copy()
        pool_fallback = base_pool[base_pool["baseline_med_dv"] >= FALLBACK_BASELINE_DOLLAR_VOL].copy()
        print(f"{rid}: universe {len(c)} -> eligible control pool {len(pool)} (>=A$100k) / {len(pool_fallback)} (>=A$50k)")

        rev_adds = adds[adds["review_id"] == rid].reset_index(drop=True)
        rev_adds["gid"] = [f"{rid}_G{i + 1:02d}" for i in range(len(rev_adds))]
        info = rev_adds.merge(c, on=["review_id", "ticker"], how="left")

        # hardest first: fewest tier-1 candidates
        def n_t1(row):
            if pd.isna(row["market_cap_aud"]) or pd.isna(row["gics_sector"]):
                return 10 ** 6
            p = pool[pool["gics_sector"] == row["gics_sector"]]
            ratio = p["market_cap_aud"] / row["market_cap_aud"]
            return int(((ratio >= PRIMARY_BAND[0]) & (ratio <= PRIMARY_BAND[1])).sum())

        info["n_t1"] = info.apply(n_t1, axis=1)
        order = info.sort_values(["n_t1", "ticker"])
        used: set[str] = set()
        results = {}

        tiers = [
            ("T1", PRIMARY_BAND, True, pool),
            ("T1", PRIMARY_BAND, True, pool_fallback),
            ("T2", WIDE_BAND, True, pool),
            ("T2", WIDE_BAND, True, pool_fallback),
            ("T3", WIDE_BAND, False, pool),
            ("T4", (0.0, 1e12), False, pool_fallback),
        ]
        for a in order.itertuples():
            if pd.isna(a.market_cap_aud) or pd.isna(a.gics_sector):
                reason = "NO_PRICE_OR_SHARES" if pd.isna(a.market_cap_aud) else "NO_SECTOR"
                status.append({"review_id": rid, "ticker": a.ticker, "status": "UNMATCHED", "reason": reason,
                               "qa_flags": a.qa_flags})
                results[a.gid] = None
                continue
            chosen = []
            for tier, band, same_sector, cur_pool in tiers:
                need = N_CONTROLS - len(chosen)
                if need <= 0:
                    break
                p = cur_pool[~cur_pool["ticker"].isin(used | {x["ticker"] for x in chosen})]
                if same_sector:
                    p = p[p["gics_sector"] == a.gics_sector]
                p = p.assign(ratio=p["market_cap_aud"] / a.market_cap_aud)
                p = p[(p["ratio"] >= band[0]) & (p["ratio"] <= band[1])]
                p = p.assign(dist=np.abs(np.log(p["ratio"]))).sort_values(["dist", "ticker"])
                for rank_i, cand in enumerate(p.itertuples(), 1):
                    ok, why = second_source(cand.ticker)
                    cand_log.append({"review_id": rid, "group_id": a.gid, "addition": a.ticker, "tier": tier,
                                     "candidate": cand.ticker, "candidate_name": cand.name,
                                     "candidate_sector": cand.gics_sector, "cap_aud": cand.market_cap_aud,
                                     "cap_ratio": cand.ratio, "baseline_med_dv": cand.baseline_med_dv,
                                     "order_in_tier": rank_i,
                                     "second_source": why, "selected": bool(ok and len(chosen) < N_CONTROLS)})
                    if ok and len(chosen) < N_CONTROLS:
                        chosen.append({"ticker": cand.ticker, "name": cand.name, "cap": cand.market_cap_aud,
                                       "ratio": cand.ratio, "tier": tier, "rank": cand.cap_rank,
                                       "sector": cand.gics_sector, "flags": why})
                    if len(chosen) >= N_CONTROLS:
                        break
            used |= {x["ticker"] for x in chosen}
            results[a.gid] = chosen
            status.append({"review_id": rid, "ticker": a.ticker,
                           "status": "MATCHED" if len(chosen) == N_CONTROLS else "PARTIAL",
                           "reason": "", "qa_flags": a.qa_flags})

        for a in info.itertuples():
            ch = results.get(a.gid)
            if not ch:
                continue
            row = {"review_id": rid, "matched_group_id": a.gid, "addition_ticker": a.ticker,
                   "addition_name": a.company_name, "gics_sector": a.gics_sector,
                   "addition_cap_aud": a.market_cap_aud, "addition_cap_rank": a.cap_rank,
                   "addition_shares_date": a.shares_date, "addition_qa_flags": a.qa_flags,
                   "num_controls": len(ch)}
            for i in range(N_CONTROLS):
                if i < len(ch):
                    x = ch[i]
                    row.update({f"control_{i + 1}_ticker": x["ticker"], f"control_{i + 1}_name": x["name"],
                                f"control_{i + 1}_sector": x["sector"], f"control_{i + 1}_cap_aud": x["cap"],
                                f"control_{i + 1}_cap_ratio": round(x["ratio"], 4),
                                f"control_{i + 1}_cap_rank": x["rank"], f"control_{i + 1}_tier": x["tier"],
                                f"control_{i + 1}_second_source": x["flags"]})
                else:
                    row[f"control_{i + 1}_ticker"] = "NONE"
            tiers_used = sorted({x["tier"] for x in ch})
            row["matching_tier"] = tiers_used[-1] if len(ch) == N_CONTROLS else "INCOMPLETE"
            groups.append(row)

    mg = pd.DataFrame(groups)
    mg.to_csv(OUTPUT / "matched_controls.csv", index=False)
    pd.DataFrame(cand_log).to_csv(LOGS / "control_candidates_log.csv", index=False)
    st = pd.DataFrame(status)
    st.to_csv(LOGS / "additions_status.csv", index=False)

    print("\nStatus:", st["status"].value_counts().to_dict())
    print("Matching tier:", mg["matching_tier"].value_counts().to_dict())
    print("Unmatched additions:\n", st[st["status"] != "MATCHED"].to_string(index=False))


if __name__ == "__main__":
    main()
