# STARK OS developer commands (macOS / Linux). Requires Python 3.11+, Node 20+, uv (or pip).
PY ?= services/api/.venv/bin/python

.PHONY: setup api web dev test test-api test-web e2e docker
setup:
	cd services/api && (uv venv .venv --python 3.12 || python3 -m venv .venv) && \
	  (uv pip install --python .venv/bin/python -e ".[browser,dev]" || .venv/bin/pip install -e ".[browser,dev]")
	cd apps/web && npm install
	$(PY) scripts/setup.py
	@echo "Optional for browser.render: $(PY) -m playwright install chromium"

api:
	cd services/api && .venv/bin/python -m stark.main

web:
	cd apps/web && npm run dev

dev:
	./scripts/dev.sh

test: test-api test-web

test-api:
	cd services/api && .venv/bin/python -m pytest -q

test-web:
	cd apps/web && npx tsc --noEmit && npm test

e2e:
	cd apps/web && npm run build && npx playwright test

docker:
	docker compose up --build
