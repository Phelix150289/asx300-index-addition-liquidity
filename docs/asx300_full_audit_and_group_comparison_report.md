# ASX 300 Index-Addition Liquidity Study - Quality Assurance & Validation Report

Generated from pipeline execution (`src/s1_schedule.py` through `src/s6_build_panels.py`).

## 1. Regression Panels Overview (review_01.csv .. review_06.csv)

| Review ID | Total Rows | Stocks (1 Add + 2 Ctrl) | Matched Groups | Event Days / Stock | Panel File |
| :--- | :---: | :---: | :---: | :---: | :--- |
| R01 | 3,630 | 30 | 10 | 121 | `review_01.csv` |
| R02 | 4,356 | 36 | 12 | 121 | `review_02.csv` |
| R03 | 4,356 | 36 | 12 | 121 | `review_03.csv` |
| R04 | 3,993 | 33 | 11 | 121 | `review_04.csv` |
| R05 | 5,808 | 48 | 16 | 121 | `review_05.csv` |
| R06 | 5,808 | 48 | 16 | 121 | `review_06.csv` |
| **Total** | **27,951** | **231** | **77** | **121** | 6 panels |

## 2. Additions Retention and Attrition Audit

- **Total Additions in S&P/ASX 300 Announcements (R01..R06):** 84
- **Successfully Matched Additions:** 77 (91.7%)
- **Unmatched Additions (Data Attrition):** 7 (8.3%)

### Unmatched Additions Detail
| Review | Ticker | Name / Status | Reason | Attrition Category |
| :---: | :---: | :--- | :--- | :--- |
| R02 | LRS | Delisted / Acquired | No price series on Yahoo Finance | Unavoidable vendor survivorship attrition |
| R02 | MRM | Delisted / Acquired | No price series on Yahoo Finance | Unavoidable vendor survivorship attrition |
| R03 | MAC | Delisted / Acquired | No price series on Yahoo Finance | Unavoidable vendor survivorship attrition |
| R03 | OPT | Delisted / Acquired | No price series on Yahoo Finance | Unavoidable vendor survivorship attrition |
| R03 | RUL | Delisted / Acquired | No price series on Yahoo Finance | Unavoidable vendor survivorship attrition |
| R03 | SPR | Delisted / Acquired | No price series on Yahoo Finance | Unavoidable vendor survivorship attrition |
| R05 | QOR | Delisted / Acquired | No price series on Yahoo Finance | Unavoidable vendor survivorship attrition |

*Note: `OPT` (R03) has daily prices cached in Data B (`R03_daily_provisional.csv`), while all 7 tickers lack active Yahoo Finance series as of October 2026.*

## 3. Point-in-Time Market Cap & Share-Count Fix Audit

All 77 priced additions now rank between **#56 and #389** on the ASX (plausibility band [30, 450]), with zero implausible micro-cap or mega-cap outliers.

| Review | Ticker | Issue Type | Naive EODHD Cap | Fixed PIT Cap | New Rank | Explanation |
| :---: | :---: | :--- | :---: | :---: | :---: | :--- |
| R04 | **PNR** | 1:17 Reverse Split (Apr 2025) | $15,750.2M (#45) | **$903.6M** | #273 | Adjusted pre-split shares by 0.0588 split factor; replaced South32/Alcoa with mid-cap peers (BOE, ZIM) |
| R01 | **PMT** | 10:1 CDI Unit Discrepancy | $137.1M (#582) | **$1,396.8M** | #192 | Used CDI-equivalent share series (1.027B CDIs vs 100.8M parent shares); replaced micro-caps (GT1, HAS) with CHN, NUF |
| R06 | **DTR** | Stale Quarterly Shares | $48.2M (#945) | **$1,035.5M** | #285 | Updated from stale 169M quarterly filing to 3.63B PIT shares; replaced $48M micro-caps (PXX, VTX) with FML, GNG |
| R01 | **GMD** | Leonora Acquisition Issuance | $571.2M (#317) | **$1,485.5M** | #188 | Captured 1.05B shares post-June 2023 Leonora acquisition instead of 405M quarterly weighted average |
| R04 | **MYR** | Apparel Brands Merger | $692.4M (#313) | **$1,417.0M** | #215 | Captured Feb 2025 Premier Apparel Brands merger issuance prior to R04 reference date |
| R05 | **ALK** | Mandalay Resources Merger | $567.0M (#344) | **$1,262.5M** | #243 | Captured Aug 2025 Mandalay merger share issuance prior to R05 reference date |
| R02 | **LOT** | Consolidation Cross-Check | $560.5M (#324) | **$562.4M** | #316 | Yahoo pre-split shares (1.73B x 0.0870 split) independently verified EODHD restated shares within 0.3% |
| R02 | **PDI** | Consolidation Cross-Check | $440.0M (#359) | **$425.6M** | #350 | Yahoo pre-split shares (2.08B x 0.2000 split) independently verified EODHD restated shares within 3.3% |

## 4. Matching Protocol and Tier Quality

Every matched addition was assigned 2 unique controls in the same review without replacement.

- **Tier 1 (Same GICS Sector, Size Ratio in [0.5x, 2.0x]):** 76 (98.7%)
- **Tier 2 (Same GICS Sector, Widened Band [0.33x, 3.0x]):** 1 (`R01 MAQ`: Control 1 `EVT` at 1.14x [T1], Control 2 `NEC` at 2.12x [T2])
- **Tier 3 (Any GICS Sector, Widened Band [0.33x, 3.0x]):** 0
- **Tier 4 (Any GICS Sector, Closest Size Fallback):** 0

### Market Capitalization Ratios (Control Cap / Addition Cap)
- **Primary Control (Control 1):** Range = [0.812, 1.517], Median = 1.010
- **Secondary Control (Control 2):** Range = [0.744, 2.116], Median = 1.014

## 5. Usable Groups by Event Stage (>= 80% Valid Amihud Days)

Stages: B = Baseline [-30, -11], P = Pre-announcement [-10, -1], M = Mid-window [+1, E], L = Post-effective [E+1, E+20].

| Review ID | Total Groups | Baseline (B) Usable | Pre (P) Usable | Mid (M) Usable | Post (L) Usable |
| :--- | :---: | :---: | :---: | :---: | :---: |
| R01 | 10 | 10/10 | 10/10 | 10/10 | 10/10 |
| R02 | 12 | 12/12 | 12/12 | 12/12 | 12/12 |
| R03 | 12 | 12/12 | 12/12 | 12/12 | 12/12 |
| R04 | 11 | 11/11 | 11/11 | 11/11 | 11/11 |
| R05 | 16 | 16/16 | 16/16 | 16/16 | 16/16 |
| R06 | 16 | 16/16 | 15/16 | 15/16 | 16/16 |
| **Total** | **77** | **77/77 (100.0%)** | **76/77 (98.7%)** | **76/77 (98.7%)** | **77/77 (100.0%)** |

## 6. Unbiased Methodological & Empirical Comparison: Data A vs. Data B

| Dimension | Data A (This Pipeline) | Data B (Groupmate Package) | Impact / Assessment |
| :--- | :--- | :--- | :--- |
| **Retained Additions** | **77 of 84** (91.7%) | **63 of 84** (75.0%) | Data A retains 15 large/mid-cap additions dropped by Data B; Data B retains `OPT` (R03) |
| **Usable Groups (>=80% valid days)** | **76–77 of 84** (90.5%–91.7%) | **41–45 of 84** (48.8%–53.6%) | Data B loses ~20 groups because it lacks a pre-reference tradability screen for controls |
| **Control Reuse Within Review** | **0 reused** (strictly without replacement) | **26 control slots reused** | Data B reuses controls up to 3x in the same review (`GMN`, `BRE`, `WGN`), correlating errors |
| **Point-in-Time Share Basis** | **Dual-source PIT** (Yahoo `get_shares_full` + EODHD cross-check) | **Single-source PIT** (EODHD periodic shares <= ref date) | Both avoid Early v1's 2026 share look-ahead; Data A resolves intra-quarter issuances |
| **CDI & Dual-Listing Units** | **Fixed via price-unit share series + QA block** | **Unadjusted** (`PMT` valued at $141.6M) | Data A fixes `PMT` ($1.40B) and `DTR` ($1.04B) and blocks unit-discrepant controls |
| **Reverse Splits / Consolidations** | **Automated post-record split adjustment** | **Unadjusted** (`PNR` valued at $16.31B) | Data A fixes `PNR` ($903.6M vs $16.3B) and cross-verifies `LOT` and `PDI` |
| **Announcement Day 0 Alignment** | **Quarantined as Stage `A`**; B(20), P(10), M(10), L(20) | **Included inside Stage `M`**; B(20), P(9), M(11), L(20) | S&P announces after Friday close; Data A starts Stage `M` on Monday Day +1 |
| **ASX 300 Non-Membership Screen** | Excludes the 84 additions (`known_members.csv` empty) | Screened via 299-stock FNArena list + 7 review lists | Data B enforced tighter index non-membership; Data A trades this off to retain large additions |

## 7. Caveats for Thesis and Reporting

1. **Vendor Delisting Attrition:** 7 additions were delisted/acquired prior to 2026 and lack active Yahoo price history.
2. **Industry Classification:** GICS sector is sourced from current EODHD fundamentals (historical GICS changes are not tracked).
3. **Point-in-Time Share Counts:** Dual-source PIT reconciliation (Yahoo `get_shares_full` adjusted for subsequent splits + EODHD filings) eliminates extreme split/CDI errors, though vendor filing dates can slightly lag ASX Appendix 2A announcements.
4. **Index Non-Membership Screen:** Without a complete historical S&P/ASX 300 constituent rollback list in `config/known_members.csv`, controls for large-cap additions can include existing ASX 200/300 incumbents.
5. **Event-Window Survivorship Gate:** Requiring controls to have prices on >= 90% of the 121-day window conditions on survival through day +60.