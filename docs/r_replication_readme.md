# ASX 300 replication package

## Quick start

Unzip this folder and keep its structure unchanged. Install R and the four packages below, then run from this folder:

```r
install.packages(c("dplyr", "tidyr", "ggplot2", "sandwich"))
source("run_asx300_analysis.R")
```

In RStudio, open the script and select Source. It automatically finds the six inputs in the adjacent `data` folder. Alternatively, from a terminal:

```sh
Rscript run_asx300_analysis.R data results
```

Without an explicit output directory, results are written to `data/asx300_results_baseline_cap`. Existing output files with matching names are overwritten. The first installation of packages needs an internet connection; analysis uses only the included files and does not call financial data APIs.

## Package contents and scope

- `data/review_01.csv` through `review_06.csv`: final supplied daily inputs, already collected and matched. All six are required.
- `data/matched_controls.csv`: final 77 matched groups for inspection; not a separate regression input.
- `audit/additions_status.csv`: supplied sample-selection inventory. It is supporting provenance rather than an input to the estimation script.
- `expected_results/`: reference tables and the R session information from the validated final run. Compare newly generated results with these tables.
- `MANIFEST_SHA256.csv`: checksums of all other package files.

This package reproduces data preparation and statistical analysis from the supplied matched panels. It does not download vendor data or reconstruct the matching process. There are 77 retained additions and 154 control slots across six reviews (10, 12, 12, 11, 16, 16 groups). Controls can recur across reviews. The 121-day grids contain 27,951 rows before stage aggregation. The main sample has 231 stock-review units, 1,386 stage observations and 187 ticker clusters. Control slots are not a count of distinct stocks.

## Main specification

- Six stages relative to announcement day 0: EP [-60,-41], B [-40,-21], PA [-20,0], AP [1,10], SP [11,30], LP [31,60]. Day +10 is the Friday rebalance close; +11 starts effective membership.
- Daily Amihud = `1e6 * abs(daily_return) / (close * volume)`. Returns are decimals; closing price is unadjusted and volume is in shares. The script recomputes the ratio, rather than applying an additional scale factor to the supplied Amihud column.
- Main outcome: natural log of the arithmetic stage mean. No filling, arbitrary epsilon, or winsorising in the main outcome. Non-positive volume is invalid; genuine zero returns remain valid daily zeros.
- At least 60% valid days and a positive mean in each stage. Entire matched groups must pass every stage and covariate requirement.
- Covariates: log mean baseline daily market cap [-40,-21]; sample return volatility over EP [-60,-41], multiplied by 100. Each requires at least 12 valid observations. Both interact with non-baseline stages.
- Stock-review and matched-group-by-stage fixed effects. WLS weights: addition 1; each of its two controls 0.5.
- Heterogeneous review-stage coefficients, aggregated by retained addition counts. Homogeneous and unadjusted specifications are exported as comparisons.
- Ticker-clustered CR1, retaining cross-review covariance; full parameter count includes absorbed fixed effects. The script independently checks main coefficients and covariance against explicit-dummy WLS and `sandwich::vcovCL`.
- Holm correction is applied across five non-baseline stage effects and separately across three post-stage contrasts, within each specification/outcome. These are not adjustments across the entire collection of sensitivity models.

## Checks added for the final report

1. Raw Amihud, mean daily turnover in percentage points, and log mean turnover. Daily turnover is `100 * volume / shares_outstanding`; share counts must be in shares, not thousands. The script uses the supplied share histories and does not fill missing shares. A turnover model runs only if the same main sample passes coverage.
2. Fixed pre-event P99 capping before averaging/logging; reference-date cap; stricter 80% coverage.
3. Exclusion of day +10 from AP, leaving days +1 through +9. The denominator is nine expected days. No stock or group is silently removed to make this sensitivity work; coverage failure is reported and the sensitivity is skipped.
4. LP-AP, SP-AP and LP-SP contrasts for the alternative specifications, using each model's full covariance matrix. Leave-one-review-out contrast tests are also exported.
5. Baseline characteristics on raw and log Amihud scales, with matched-group fixed effects and ticker-clustered CR1 for differences.
6. Four report figures, including review paths with a sequential legend and extra y-axis padding.

The script does **not** implement an alternative-baseline analysis, placebo dates, new matching, historical membership reconstruction, or a timeline graphic. These should not be described as completed robustness checks.

## Useful output files

| Output | Purpose |
|---|---|
| `clean_daily.csv` | Aligned daily input and validity flags |
| `regression_panel.csv` | Main balanced stage-level dataset |
| `baseline_characteristics.csv` | Baseline table including log mean Amihud |
| `pretrend_joint_tests.csv` | Conditional pre-trend joint tests |
| `report_table_5_main_effects.csv` | Main effects, intervals, nominal and Holm p-values |
| `report_table_6_contrasts.csv` | Three post-stage contrasts |
| `report_table_7_robustness.csv` | Alternative stage effects plus LP-AP |
| `report_table_8_complementary_outcomes.csv` | Raw Amihud and turnover results; units are explicit |
| `exclude_rebalance_coverage.csv` | Eligibility audit for AP [+1,+9] |
| `exclude_rebalance_effects.csv` | Effects excluding rebalance day |
| `reversion_robustness.csv` | All sensitivity contrasts with intervals and p-values |
| `reversion_leave_one_review_out.csv` | Contrasts after each review omission |
| `report_figure_1_pretrend.png` through `report_figure_4_leave_one_out.png` | Report figures; figure 3 is named `report_figure_3_review_paths.png` |
| `fitted_models.rds`, `additional_fitted_models.rds` | Estimates, covariance matrices and aggregation weights |
| `input_file_fingerprints.csv`, `R_session_info.txt` | Input provenance and R/package versions |

The 84-addition initial inventory and historical exclusion reasons require the separate notice/sample audit; they cannot be recovered from the six retained-sample CSVs alone. The script does not invent missing inventory records.

## Validation on the report inputs

The complete script was run against all six source CSVs. It retained 77 groups, 231 stock-review units, 1,386 stage observations and 187 ticker clusters. Main AP/SP/LP effects reproduce -39.2%, -32.1%, -22.6%. Excluding +10 gives AP -35.7% and LP-AP +20.4% (Holm p approximately 0.095). These are validation targets for these particular inputs, not hard-coded estimates.

Interpret log-model percentages as `100 * (exp(beta) - 1)`. Raw Amihud coefficients are absolute changes; dividing them by a baseline mean does not reproduce the log-model estimate. Turnover measures activity and should not be treated as identical to Amihud price impact.
