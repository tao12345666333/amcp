.PHONY: install test lint format clean

install:
	pip install -e ".[dev]"

test:
	pytest

test-cov:
	pytest --cov --cov-report=html --cov-report=term

lint:
	ruff check src/ tests/

format:
	ruff format src/ tests/

type-check:
	mypy src/amcp --ignore-missing-imports

clean:
	rm -rf build/ dist/ *.egg-info .pytest_cache .coverage htmlcov/
	find . -type d -name __pycache__ -exec rm -rf {} +
