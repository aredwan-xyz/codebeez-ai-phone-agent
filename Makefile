.PHONY: setup dev test lint typecheck docker-up docker-down seed-kb

setup:
	bash scripts/setup.sh

dev:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

test:
	pytest tests/ -v --tb=short

lint:
	ruff check app tests

typecheck:
	mypy app --ignore-missing-imports

format:
	ruff format app tests

docker-up:
	docker compose -f docker/docker-compose.yml up -d

docker-down:
	docker compose -f docker/docker-compose.yml down

seed-kb:
	python scripts/seed_kb.py

ngrok:
	ngrok http 8000
