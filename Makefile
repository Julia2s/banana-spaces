COMPOSE = docker compose
PYTHON = python

.PHONY: up down build logs test lint install seed e2e perf-smoke reset-demo gateway-test gateway-lint gateway-install

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

build:
	$(COMPOSE) build

logs:
	$(COMPOSE) logs -f

install: gateway-install

gateway-install:
	$(PYTHON) -m pip install -e "services/gateway[dev]"

test: gateway-test

lint: gateway-lint

gateway-test:
	$(PYTHON) -m pytest services/gateway/tests -v

gateway-lint:
	$(PYTHON) -m ruff check services/gateway/src services/gateway/tests

seed:
	$(PYTHON) scripts/seed_demo.py --corpus demo/seed_data/

e2e:
	$(PYTHON) scripts/e2e_smoke.py

perf-smoke:
	$(PYTHON) scripts/perf_smoke.py

reset-demo:
	$(COMPOSE) down -v
	rm -rf data/raw_uploads data/normalized
