# Data Manifest (`docs/data-manifest.md`)

This document records the provenance, structure, and verification checksums of all raw and derived datasets in the repository.

---

## 1. Raw Data (`data/raw/`) — Immutable Inputs

| File | Rows | Description & Provenance |
| :--- | :---: | :--- |
| `data/raw/reviews.csv` | 6 | Official announcement dates (`announcement_date`) and effective implementation dates (`implementation_date`) for S&P/ASX 300 semi-annual reviews `R01` (Sep 2023) through `R06` (Mar 2026), sourced from S&P Dow Jones Indices press releases. |
| `data/raw/additions.csv` | 84 | Complete list of 84 announced S&P/ASX 300 index additions across `R01`–`R06` (`review_id`, `ticker`, `company_name`). |
| `data/raw/cap_overrides.csv` | 8 | Point-in-time share count and split-factor corrections verified against official ASX Appendix 2A/3B filings for stocks with vendor split/CDI anomalies (`PNR`, `PMT`, `DTR`, `GMD`, `MYR`, `ALK`, `LOT`, `PDI`). |
| `data/raw/known_members.csv` | 0 | Optional exclusion list for pre-existing index constituents outside the addition announcements. |

---

## 2. Derived Data (`data/derived/`) — Analysis-Ready Outputs

Generated deterministically by `code/01_schedule.py` through `code/06_build_panels.py`. Full SHA-256 hashes are stored in `docs/MANIFEST_SHA256.csv`.

| File | Rows | Columns | Description |
| :--- | :---: | :---: | :--- |
| `data/derived/review_01.csv` | 5,082 | 33 | Stacked DiD daily panel for `R01` (Sep 2023): 14 matched groups (42 stocks $\times$ 121 event days $[-60, +60]$). |
| `data/derived/review_02.csv` | 4,719 | 33 | Stacked DiD daily panel for `R02` (Mar 2024): 13 matched groups (39 stocks $\times$ 121 event days). |
| `data/derived/review_03.csv` | 3,993 | 33 | Stacked DiD daily panel for `R03` (Sep 2024): 11 matched groups (33 stocks $\times$ 121 event days). |
| `data/derived/review_04.csv` | 4,719 | 33 | Stacked DiD daily panel for `R04` (Mar 2025): 13 matched groups (39 stocks $\times$ 121 event days). |
| `data/derived/review_05.csv` | 3,630 | 33 | Stacked DiD daily panel for `R05` (Sep 2025): 10 matched groups (30 stocks $\times$ 121 event days). |
| `data/derived/review_06.csv` | 5,808 | 33 | Stacked DiD daily panel for `R06` (Mar 2026): 16 matched groups (48 stocks $\times$ 121 event days). |
| `data/derived/matched_controls.csv` | 77 | 22 | 1-addition-to-2-controls matching table across all 77 retained additions (76 Tier 1, 1 Tier 2, 0 control reuse within review). |
| `data/derived/group_stage_usable.csv` | 308 | 7 | Group-by-stage usability flags under the $\ge 80\%$ valid trading-day coverage rule (`77/77` usable across all stages). |
| `data/derived/stock_stage_coverage.csv` | 924 | 9 | Stock-by-stage count and share of valid Amihud trading days across stages `B`, `P`, `M`, `L`. |

---

## 3. Panel Schema (`review_01.csv` .. `review_06.csv`)

Each review CSV contains 33 columns:
- **Identifiers & Event Timing:** `review_id`, `stock_id`, `ticker`, `company_name`, `treatment` (`1` = addition, `0` = control), `matched_group_id`, `Addition_Code`, `Control_Type`, `trading_date`, `event_day` ($-60$ to $+60$), `announcement_date`, `effective_date`, `reference_date`.
- **Stage Indicators:** `stage` (`PRE_B`, `B`, `P`, `A`, `M`, `L`, `POST_L`), `is_baseline`, `is_pre_announcement`, `is_mark_up`, `is_post_effective`.
- **Sector & Static Size:** `gics_sector`, `gics_code`, `reference_market_cap_aud`.
- **Daily Market & Liquidity Variables:** `close`, `volume`, `daily_return`, `amihud`, `dollar_volume`, `log_dollar_volume`, `shares_outstanding`, `daily_market_cap_aud`, `turnover_rate`, `log_turnover_rate`.
- **Quality Flags:** `missing_observation`, `data_quality_flag` (`OK`, `ZERO_VOLUME`, `MISSING_PRICE`, `MISSING_RETURN`).
