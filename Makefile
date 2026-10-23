.PHONY: all data analysis check

# Full reproduction from existing derived panels (runs validation + R regressions)
all: check analysis

# Rebuild derived datasets from raw inputs and cached market data (Steps 1-7)
data:
	python run_all.py

# Run QA validation on derived panels
check:
	python code/07_validate.py

# Run stacked DiD econometric analysis and generate all report tables & figures
analysis:
	Rscript code/08_run_asx300_analysis.R data/derived output/tables
