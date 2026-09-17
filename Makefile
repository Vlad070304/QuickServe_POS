.PHONY: install start test lint typecheck smoke check release-check

install:
	python -m pip install -r requirements-dev.txt

start:
	python scripts/start_dev.py

test:
	python -m pytest --cov=restaurant_pos --cov-report=term-missing

lint:
	python -m ruff check .

typecheck:
	python -m mypy restaurant_pos

smoke:
	python -m scripts.smoke_test

check: lint typecheck test

release-check:
	python scripts/release_check.py
