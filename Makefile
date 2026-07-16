.PHONY: run dev test lint

run:
	uv run gunicorn -w 4 -b 127.0.0.1:5000 policyassist.app:app

dev:
	uv run flask --app policyassist.app run --port 5000

test:
	uv run pytest

lint:
	uv run ruff check . && uv run ruff format --check . && uv run mypy monitoring
