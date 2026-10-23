"""Master runner for the ASX 300 Index-Addition Liquidity Study pipeline.

Runs steps 1 through 7 in sequential order:
  Step 1: code/01_schedule.py           - Event calendar and stage schedules
  Step 2: code/02_fetch_fundamentals.py - EODHD universe & fundamentals cache
  Step 3: code/03_fetch_prices.py       - Yahoo prices and split history
  Step 4: code/04_reference_caps.py     - Reference-date PIT market caps & QA flags
  Step 5: code/05_match_controls.py     - 1-addition-to-2-controls matching
  Step 6: code/06_build_panels.py       - Regression panels (review_01..06.csv)
  Step 7: code/07_validate.py           - Validation & QA report (qa_report.md)
"""
from __future__ import annotations

import subprocess
import sys
import time

SCRIPTS = [
    ("Step 1: Event Schedule", "code/01_schedule.py"),
    ("Step 2: Fundamentals & Sectors", "code/02_fetch_fundamentals.py"),
    ("Step 3: Price & Split History", "code/03_fetch_prices.py"),
    ("Step 4: Reference Market Caps & QA", "code/04_reference_caps.py"),
    ("Step 5: Control Matching", "code/05_match_controls.py"),
    ("Step 6: Build Review Panels", "code/06_build_panels.py"),
    ("Step 7: Validation & QA Report", "code/07_validate.py"),
]


def run_pipeline() -> None:
    t0 = time.time()
    print("=====================================================================")
    print("ASX 300 Index Addition Liquidity Study - Pipeline Execution")
    print("=====================================================================")

    for label, script in SCRIPTS:
        print(f"\n--- Running {label} ({script}) ---")
        t_start = time.time()
        res = subprocess.run([sys.executable, script])
        if res.returncode != 0:
            print(f"\nERROR: {script} failed with exit code {res.returncode}")
            sys.exit(res.returncode)
        print(f"Completed in {time.time() - t_start:.1f}s")

    elapsed = time.time() - t0
    print("\n=====================================================================")
    print(f"PIPELINE COMPLETED SUCCESSFULLY IN {elapsed:.1f}s")
    print("Deliverables generated in `data/derived/` and `output/logs/`:")
    print("  - data/derived/review_01.csv .. review_06.csv (regression panels)")
    print("  - data/derived/matched_controls.csv")
    print("  - data/derived/group_stage_usable.csv & stock_stage_coverage.csv")
    print("  - output/logs/qa_report.md")
    print("=====================================================================")


if __name__ == "__main__":
    run_pipeline()
