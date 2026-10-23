# S&P/ASX 300 Index Addition Liquidity Study

**Course:** ETF5560 Case Studies in Econometrics (Monash University)  
**Group E:** Haonan Li, Sunny Nguyen, Salomo Octavianus, Phelix Lee

---

## 1. Research Question & One-Sentence Conclusion

- **Research Question:** Does addition to the S&P/ASX 300 index improve stock liquidity across semi-annual index rebalances (September 2023 – March 2026), and is this improvement transient around passive index implementation or persistent in the post-rebalance window?
- **One-Sentence Conclusion:** Using a stacked matched difference-in-differences design across 77 index additions and 154 sector-and-size matched controls (231 stock-review units; 1,386 stage observations), S&P/ASX 300 inclusion significantly reduces Amihud illiquidity by **39.2%** ($p_{\text{Holm}} = 1.22 \times 10^{-6}$) during the announcement-to-effective window (`AP`), **32.1%** ($p_{\text{Holm}} = 4.39 \times 10^{-5}$) over the first 20 post-effective trading days (`SP`), and **22.6%** ($p_{\text{Holm}} = 0.0213$) over trading days $+31$ to $+60$ (`LP`).

---

## 2. What to Install (Software, Packages & Versions)

### R Environment (for Econometric Estimation & Figures)
- **R:** Version 4.5.1 (or $\ge 4.2.0$)
- **Required R Packages:** `dplyr` (1.2.0), `tidyr` (1.3.2), `ggplot2` (4.0.2), `sandwich` (3.1-1)
- Install in R with:
  ```r
  install.packages(c("dplyr", "tidyr", "ggplot2", "sandwich"))
  ```

### Python Environment (for Data Pipeline & Validation)
- **Python:** Version 3.10+
- **Required Python Packages:** `pandas`, `numpy`, `yfinance`, `requests`, `exchange_calendars`
- Install via `pip`:
  ```bash
  pip install -r requirements.txt
  ```
- *(Optional)* To re-fetch raw fundamentals from EODHD (`code/02_fetch_fundamentals.py`), copy `.env.example` to `.env` and add your `EODHD_API_KEY`. This is **not** required to validate the derived panels or reproduce the econometric tables and figures.

---

## 3. How to Run (Exact Commands & Expected Run Time)

### Option A: Reproduce All Econometric Tables & Figures from Derived Panels (~5 seconds)
The six cleaned review panels (`data/derived/review_01.csv` .. `review_06.csv`) are included in the repository. From the project root:

```bash
# Run R stacked DiD regressions, robustness checks, and figure generation
Rscript code/08_run_asx300_analysis.R data/derived output/tables

# Run Python panel integrity and QA validation
python code/07_validate.py
```

Or using `make`:
```bash
make all
```

### Option B: Rebuild Derived Panels from Raw Schedules (`data/raw/`)
If rebuilding the derived panels from the raw announcement lists (`data/raw/additions.csv`, `data/raw/reviews.csv`):

```bash
python run_all.py
```
- **Expected Run Time:** ~15 seconds using local price/fundamentals caches (`data/cache/`); ~20 minutes if downloading fresh EODHD fundamentals and Yahoo Finance price series from scratch.

---

## 4. Expected Output & Key Verification Numbers

Running `code/08_run_asx300_analysis.R` writes regression tables to `output/tables/`, plots to `output/figures/`, and session logs to `output/logs/`. A stranger's reproduction is verified if `output/tables/report_table_5_main_effects.csv` and `output/tables/pretrend_joint_tests.csv` match these headline benchmarks:

| Metric / Stage | Window (Event Days) | Log Coefficient ($\hat{\beta}$) | Clustered SE | Relative Effect (%) | Holm-Adjusted $p$-value |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Early Pre (`EP`)** | $[-60, -41]$ | $+0.0437$ | $0.0671$ | $+4.46\%$ | $0.5159$ |
| **Baseline (`B`)** | $[-40, -21]$ | $0.0000$ | *(omitted ref)* | $0.00\%$ | — |
| **Pre-Announcement (`PA`)** | $[-20, 0]$ | $-0.0869$ | $0.0710$ | $-8.32\%$ | $0.4449$ |
| **Announcement-to-Effective (`AP`)** | $[+1, +10]$ | $-0.4973$ | $0.0928$ | **$-39.18\%$** | **$1.22 \times 10^{-6}$** |
| **Short Post-Effective (`SP`)** | $[+11, +30]$ | $-0.3869$ | $0.0856$ | **$-32.09\%$** | **$4.39 \times 10^{-5}$** |
| **Long Post-Effective (`LP`)** | $[+31, +60]$ | $-0.2559$ | $0.0940$ | **$-22.58\%$** | **$0.0213$** |

- **Sample Verification:** `77` matched groups, `231` stock-review units (`77` additions + `154` controls), `1,386` stage observations, `187` unique ticker clusters (`output/tables/sample_counts_and_review_weights.csv`).
- **Pre-Trend Joint Test:** $F(3, 186) = 0.7279, p = 0.5365$ in the heterogeneous specification (`output/tables/pretrend_joint_tests.csv`), supporting parallel pre-announcement trends.
- **Post-Rebalance Persistence Test (`SP = LP = 0`):** $F(2, 186) = 10.7216, p = 3.92 \times 10^{-5}$ (`output/tables/homogeneity_and_joint_tests.csv`).
- **Cryptographic Checksums:** Full SHA-256 hashes for all data and output files are recorded in `docs/MANIFEST_SHA256.csv`.

---

## 5. Data Sources, Access & Licences

| Dataset / Source | Files | Provenance & Access | Licence / Terms |
| :--- | :--- | :--- | :--- |
| **S&P Dow Jones Indices Announcements** | `data/raw/reviews.csv`, `data/raw/additions.csv` | Public S&P/ASX 300 semi-annual rebalance press releases (Sep 2023 – Mar 2026). Hand-verified against official ASX market announcements. | Public factual event dates & ticker lists. |
| **Yahoo Finance Daily Market Data** | `code/03_fetch_prices.py` $\rightarrow$ `data/derived/review_01..06.csv` | Daily OHLCV prices, stock splits, and `get_shares_full()` point-in-time share series fetched via `yfinance`. | Public market data for academic/educational research use. |
| **EODHD Fundamentals & Universe** | `code/02_fetch_fundamentals.py` | ASX common-stock universe, GICS sector classifications, and historical quarterly share filings via EODHD API (`EODHD_API_KEY`). | Commercial API subscription (raw cache excluded from Git via `.gitignore`; derived variables included for replication). |

---

## Repository Directory Structure (ETF5560 Module 3 Standard)

```text
ASX_review/
├── README.md                  <- Project overview, setup, and replication guide
├── AGENTS.md                  <- Standing instructions and guardrails for AI coding agents
├── Makefile                   <- One-command build targets (make all, make data, make analysis)
├── requirements.txt           <- Python package dependencies
├── .env.example               <- Template for EODHD_API_KEY (actual .env is git-ignored)
├── .gitignore                 <- Excludes .env, heavy caches, interim scratch, and archive/
├── run_all.py                 <- Master Python runner for Steps 01 to 07
├── data/
│   ├── raw/                   <- Immutable inputs: reviews.csv, additions.csv, cap_overrides.csv
│   ├── interim/               <- Intermediate schedules & reference caps (git-ignored)
│   └── derived/               <- Analysis-ready panels: review_01..06.csv, matched_controls.csv
├── code/
│   ├── common.py              <- Shared paths, study parameters, and ASX trading calendar helpers
│   ├── 01_schedule.py         <- Step 1: Event calendar & stage schedules
│   ├── 02_fetch_fundamentals.py <- Step 2: EODHD ASX universe & GICS sector extraction
│   ├── 03_fetch_prices.py     <- Step 3: Yahoo Finance daily OHLCV & split history
│   ├── 04_reference_caps.py   <- Step 4: Point-in-time market caps & QA flags
│   ├── 05_match_controls.py   <- Step 5: 1:2 sector-and-size control matching with liquidity screen
│   ├── 06_build_panels.py     <- Step 6: Build 121-day stacked DiD panels (review_01..06.csv)
│   ├── 07_validate.py         <- Step 7: Automated panel integrity & QA audit
│   └── 08_run_asx300_analysis.R <- Step 8: R stacked DiD regressions, tables, and figures
├── output/
│   ├── tables/                <- Regression tables (report_table_5..8.csv, pretrend & joint tests)
│   ├── figures/               <- Publication figures (report_figure_1..4.png)
│   └── logs/                  <- QA report (qa_report.md), VALIDATION.txt, R_session_info.txt
├── docs/
│   ├── data-manifest.md       <- Provenance and schema documentation for all datasets
│   ├── decision-log.md        <- Chronological log of empirical & data-cleaning decisions
│   ├── MANIFEST_SHA256.csv    <- Cryptographic SHA-256 verification hashes
│   ├── added_columns_methodology_report.md <- Methodology for share decontamination & turnover
│   └── asx300_full_audit_and_group_comparison_report.md <- Full pipeline audit report
└── report/
    ├── ETF5560_Group_E.pdf    <- Final submitted econometric report (PDF)
    ├── ETF5560_Report_V3.docx <- Final econometric report manuscript (Word)
    └── ASX300_Control_Selection_and_Parallel_Trends.pptx <- Presentation slide deck
```
