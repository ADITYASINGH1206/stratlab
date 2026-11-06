.PHONY: setup test lint demo ui template template-check data clean

PYTHON ?= python3
VENV ?= .venv
HOME_DIR ?= $(HOME)/stratlab-home
BIN := $(VENV)/bin

# One command for judges: virtualenv, editable install, shared workspace, and the
# ~/stratlab-home/bin/stratlab shim that every Switch agent calls by absolute path.
setup:
	@if command -v uv >/dev/null 2>&1; then \
		uv venv $(VENV) && uv pip install --python $(BIN)/python -e ".[dev]"; \
	else \
		$(PYTHON) -m venv $(VENV) && $(BIN)/pip install -q --upgrade pip && $(BIN)/pip install -q -e ".[dev]"; \
	fi
	mkdir -p $(HOME_DIR)/bin
	ln -sf "$(CURDIR)/$(BIN)/stratlab" "$(HOME_DIR)/bin/stratlab"
	$(BIN)/python -c "from stratlab.config import init_environment; init_environment()"
	@echo "StratLab ready. Agents call: $(HOME_DIR)/bin/stratlab"

test:
	$(BIN)/pytest -q

lint:
	$(BIN)/ruff check .

# Offline smoke test: no Switch, no network, no keys. Replays the #lab room with real numbers,
# then builds the StratLab Desk page.
demo:
	$(BIN)/stratlab demo
	$(BIN)/stratlab ui

ui:
	$(BIN)/stratlab ui

template:
	$(BIN)/python switch/build_template.py

# CI: fail if someone edited switch/*.md without regenerating the template.
template-check:
	$(BIN)/python switch/build_template.py >/dev/null && git diff --exit-code switch/stratlab.template.yaml

data:
	$(BIN)/stratlab data fetch BTCUSDT 4h --from 2021-01-01 --to 2025-12-31

clean:
	rm -rf build/ dist/ *.egg-info .pytest_cache .ruff_cache
