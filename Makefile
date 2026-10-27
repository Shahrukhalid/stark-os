# STARK OS developer commands (macOS / Linux). Requires Python 3.11+, Node 20+, uv (or pip).
PY ?= services/api/.venv/bin/python

.PHONY: setup api web dev lint test test-api test-web e2e docker
# first Python >= 3.11 found (macOS ships 3.9 as python3, which is too old)
PYTHON ?= $(shell for p in python3.13 python3.12 python3.11 python3; do command -v $$p >/dev/null 2>&1 && $$p -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null && command -v $$p && break; done)

setup:
	@test -n "$(PYTHON)" || { echo "Python 3.11+ not found. Install it: brew install python@3.12"; exit 1; }
	@test -x services/api/.venv/bin/python && services/api/.venv/bin/python -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null || rm -rf services/api/.venv
	cd services/api && (uv venv .venv --python 3.12 2>/dev/null || $(PYTHON) -m venv .venv) && \
	  (uv pip install --python .venv/bin/python --require-hashes -r requirements.lock || .venv/bin/pip install --require-hashes -r requirements.lock) && \
	  (uv pip install --python .venv/bin/python --no-deps -e . || .venv/bin/pip install --no-deps -e .) && \
	  (uv pip install --python .venv/bin/python "pytest>=8" "pytest-asyncio>=0.23" "playwright>=1.45" || .venv/bin/pip install "pytest>=8" "pytest-asyncio>=0.23" "playwright>=1.45")
	cd apps/web && npm ci --no-audit --no-fund
	$(PY) scripts/setup.py
	@echo "Optional for browser.render: $(PY) -m playwright install chromium"

api:
	cd services/api && .venv/bin/python -m stark.main

web:
	cd apps/web && npm run dev

dev:
	./scripts/dev.sh

lint:
	cd services/api && (.venv/bin/ruff --version >/dev/null 2>&1 || .venv/bin/pip install -q "ruff==0.17.2") && \
	  .venv/bin/ruff check stark tests ../../scripts ../../apps/web/e2e/mock_llm.py

test: test-api test-web

test-api:
	cd services/api && .venv/bin/python -m pytest -q

test-web:
	cd apps/web && npx tsc --noEmit && npm test

e2e:
	cd apps/web && npm run build && npx playwright test

docker:
	docker compose up --build
