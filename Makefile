PY ?= python
PIP ?= pip

.PHONY: help install test eval report skills gate lint smoke clean

help:
	@echo "make install   pip install -e .[dev]"
	@echo "make test      run the offline test suite (no key, no network)"
	@echo "make eval      run the full 12-arm benchmark and write docs/BENCHMARK.md"
	@echo "make report    render the stored benchmark as markdown"
	@echo "make skills    distill candidate skill cards from graded traces"
	@echo "make gate      run the holdout promotion gate over the candidates"
	@echo "make lint      byte-compile the tree (ruff if installed)"
	@echo "make smoke     run every scenario on the default arm"

install:
	$(PIP) install -e ".[dev]"

test:
	PYTHONPATH=src $(PY) -m pytest tests -q

eval:
	PYTHONPATH=src $(PY) -m ballast.cli eval \
		--arms naive,ballast,no_offload,no_compaction,no_context_control,static_briefing,tight_budget,no_budget,hierarchical,defective,noisy,bloated \
		--reps 3 --workers 6 --out bench/results/eval.md
	@echo "wrote bench/results/eval.md and eval.json — copy into docs/BENCHMARK.md"

report:
	PYTHONPATH=src $(PY) -m ballast.cli report bench/results/eval.json

skills:
	PYTHONPATH=src $(PY) -m ballast.cli skills distill

gate:
	PYTHONPATH=src $(PY) -m ballast.cli skills gate

lint:
	@$(PY) -m compileall -q src tests && echo "compileall ok"
	@command -v ruff >/dev/null && ruff check src tests || echo "ruff not installed (skipped)"

smoke:
	PYTHONPATH=src $(PY) -m ballast.cli eval --arms ballast --reps 1 --workers 4 --out /tmp/ballast-smoke.md

clean:
	rm -rf .pytest_cache .ruff_cache .ballast **/__pycache__ src/ballast/**/__pycache__
