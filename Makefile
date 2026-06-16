PYTHON ?= .venv/bin/python
UVICORN ?= .venv/bin/uvicorn

.PHONY: venv install run test redis docker-build docker-up docker-down

venv:
	python3 -m venv .venv

install:
	$(PYTHON) -m pip install -r requirements.txt

run:
	$(UVICORN) app.main:app --reload

test:
	$(PYTHON) -m pytest tests/ --cov=app --cov-report=term-missing -q

redis:
	docker run --rm -p 6379:6379 redis:7-alpine

docker-build:
	docker build -t instant-food-decision-engine:latest .

docker-up:
	docker compose up --build

docker-down:
	docker compose down
