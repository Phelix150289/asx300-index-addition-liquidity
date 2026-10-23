# Empirical & Pipeline Decision Log (`docs/decision-log.md`)

This log records the key methodological, data-engineering, and econometric decisions made during the S&P/ASX 300 Index Addition Liquidity Study, following the **ETF5560 Module 3** reproducibility standard.

---

## Decision 1: Point-in-Time (PIT) Market Capitalization & Share-Count Reconciliation
- **Date:** October 2026
- **Context:** Naive EODHD quarterly share counts contained unadjusted reverse splits (`PNR` valued at $\text{A}\$15.75\text{B}$ instead of $\text{A}\$903.6\text{M}$), 10:1 CDI-to-share unit mismatches (`PMT` valued at $\text{A}\$137.1\text{M}$ instead of $\text{A}\$1.40\text{B}$), and stale pre-merger share counts (`DTR`, `GMD`, `MYR`, `ALK`).
- **Decision:** Implemented a dual-source PIT reconciliation in `code/04_reference_caps.py` combining Yahoo Finance `get_shares_full()` (adjusted for subsequent splits) with EODHD filings and verified ASX Appendix 2A overrides (`data/raw/cap_overrides.csv`). Enforced automated blocking QA gates (`CUR_MISMATCH`, `SPLIT_AFTER_RECORD`, `SHARES_JUMP`, `SHARES_SOURCES_DISAGREE`) on all control candidates.
- **Outcome:** All 77 priced additions rank within `#56` to `#389` on the ASX at their respective reference dates, eliminating micro-cap and mega-cap matching mismatches.

---

## Decision 2: Baseline Minimum Traded Value Gate ($\text{A}\$100,000$ Median Daily Dollar Volume)
- **Date:** October 2026
- **Context:** Even with valid market capitalizations and $\ge 80\%$ non-zero volume days, several dual-listed NZ/foreign stocks (`MCY`, `RYM`, `AIZ`, `SNZ`, `ZIM`, `QAL`, `JMS`) traded only a few hundred or thousand dollars per day on the ASX. In `Amihud = |Return| / DollarVolume * 1e6`, near-zero denominators created extreme pre-announcement Amihud spikes (up to `1,775.83`), distorting pre-trend tests.
- **Decision:** Added a pre-treatment liquidity floor in `code/05_match_controls.py` requiring control candidates to have a median daily traded value $\ge \text{A}\$100,000$ (`MIN_BASELINE_DOLLAR_VOL = 100_000.0`, with $\text{A}\$50,000$ fallback) strictly within the baseline window `[-30, -11]`. Because the gate is evaluated purely in the pre-announcement baseline period and uses dollar volume rather than Amihud or returns, it avoids conditioning on post-treatment outcomes.
- **Outcome:** Replaced 7 thin/dual-listed controls in Tier 1 (`76/77` Tier 1 matches, `1/77` Tier 2, `0` control reuse). Maximum stage-average Amihud fell by **99.66%** (from `1,775.83` to `6.10`), and group usability across stages increased to **100% (`77/77`)**.

---

## Decision 3: Daily Share-Count Decontamination & Zero-Volume Missingness Rule
- **Date:** October 2026
- **Context:** Raw daily Yahoo `get_shares_full()` series exhibited 20x unit oscillation in `R05 GGP.AX`, a 4.35x mid-window vendor switch in `R04 DGT.AX`, and 1-day scraper jitter in 187 of 231 stock-windows. Additionally, replacing zero-volume days with `log(0 + 1e-6) = -13.82` in `log_turnover_rate` introduced artificial regression outliers.
- **Decision:**
  1. Implemented a three-layer decontamination filter in `code/06_build_panels.py`: an envelope screen ($[0.4\times, 2.5\times]$ validated reference shares), reference-share anchoring when pre-reference Yahoo history is absent, and a monotone non-reverting step filter with a 1% deadband.
  2. Enforced strict missingness on non-trading days (`volume <= 0` $\rightarrow$ `NaN` for `amihud`, `log_dollar_volume`, `turnover_rate`, `log_turnover_rate`).
- **Outcome:** Zero share-count direction flips (`0/231` stock-windows) and zero artificial `-13.82` outlier spikes across all 27,951 panel rows.

---

## Decision 4: Window-Level Stacked DiD Estimation & Inference Protocol
- **Date:** October 2026
- **Context:** Daily Amihud is highly right-skewed and noisy on single days, and stocks appearing in multiple reviews create cross-review error correlation.
- **Decision:** In `code/08_run_asx300_analysis.R`:
  1. Collapse daily observations into six event windows (`EP` $[-60,-41]$, `B` $[-40,-21]$, `PA` $[-20,0]$, `AP` $[+1,+10]$, `SP` $[+11,+30]$, `LP` $[+31,+60]$) by taking the natural log of the window-mean daily Amihud (`log(mean(Amihud))`), with `B` as the omitted reference stage.
  2. Estimate review-heterogeneous and pooled stacked DiD models using WLS (`1` for treated additions, `0.5` for each of the two matched controls), controlling for baseline log market cap and early-pre return volatility interacted with stage dummies.
  3. Cluster standard errors at the unique stock ticker level (`187` clusters, `CR1` small-sample correction with $df = G - 1 = 186$) and apply Holm step-down multiplicity adjustments across the 5 non-baseline windows.
- **Outcome:** Clean pre-trends ($F = 0.73, p = 0.5365$ across four 10-day pre-treatment bins) and statistically significant, persistent liquidity improvements across `AP` ($-39.2\%$), `SP` ($-32.1\%$), and `LP` ($-22.6\%$).
