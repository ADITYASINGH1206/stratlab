.PHONY: setup test lint demo template clean

PYTHON ?= python3
VENV ?= .venv

setup:
	uv venv $(VENV)
	uv pip install --python $(VENV)/bin/python -e ".[dev]"
	mkdir -p $(HOME)/stratlab-home/data $(HOME)/stratlab-home/specs $(HOME)/stratlab-home/runs $(HOME)/stratlab-home/artifacts
	cp -f sample_data/*.parquet $(HOME)/stratlab-home/data/ 2>/dev/null || true
	$(VENV)/bin/python -c "from stratlab.config import init_environment; init_environment()"

test:
	$(VENV)/bin/pytest -v

lint:
	$(VENV)/bin/ruff check .

demo:
	$(VENV)/bin/stratlab --help

template:
	$(VENV)/bin/python switch/build_template.py

clean:
	rm -rf build/ dist/ *.egg-info .pytest_cache .ruff_cache
