PYTHON ?= python

.PHONY: install lint test check build

install:
	$(PYTHON) -m pip install -r requirements.txt -r requirements-dev.txt

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m compileall -q .

test:
	$(PYTHON) -m tests.test_unityscraper
	$(PYTHON) -m tests.test_integration

check: lint test
	$(PYTHON) scripts/check_version.py

build:
	$(PYTHON) -m PyInstaller --clean --noconfirm UnityScraper.spec
