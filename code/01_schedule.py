"""Step 1 - Build the review calendar (stages B/P/A/M/L, reference date, event window).

Input : config/reviews.csv
Output: data/interim/review_schedule.csv
"""
from __future__ import annotations

import pandas as pd

from common import CONFIG, INTERIM, REF_OFFSET, WINDOW_DAYS, MATCH_LOOKBACK, offset, trading_days


def main() -> None:
    reviews = pd.read_csv(CONFIG / "reviews.csv", parse_dates=["announcement_date", "implementation_date"])
    days = trading_days()
    rows = []
    for r in reviews.itertuples():
        a, e = r.announcement_date, r.implementation_date
        if a not in days or e not in days:
            raise ValueError(f"{r.review_id}: announcement/implementation date is not an ASX trading day")
        ia = days.get_loc(a)
        m_days = days.get_loc(e) - ia
        ref = offset(a, REF_OFFSET)
        rows.append({
            "review_id": r.review_id,
            "review_name": r.review_name,
            "announcement_date": a,
            "implementation_date": e,
            "reference_date": ref,
            "stage_B_start": offset(a, -30), "stage_B_end": offset(a, -11),
            "stage_P_start": offset(a, -10), "stage_P_end": offset(a, -1),
            "stage_M_start": offset(a, 1), "stage_M_end": e, "stage_M_days": m_days,
            "stage_L_start": offset(e, 1), "stage_L_end": offset(e, 20),
            "window_start": offset(a, -WINDOW_DAYS), "window_end": offset(a, WINDOW_DAYS),
            # earliest date needed: tradability lookback before the reference date
            "lookback_start": offset(ref, -MATCH_LOOKBACK),
        })
    out = pd.DataFrame(rows)
    out.to_csv(INTERIM / "review_schedule.csv", index=False, date_format="%Y-%m-%d")
    print(out[["review_id", "announcement_date", "reference_date", "implementation_date",
               "window_start", "window_end", "stage_M_days"]].to_string(index=False))


if __name__ == "__main__":
    main()
