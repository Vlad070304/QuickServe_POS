# QuickServe POS

A desktop point-of-sale application built with Python and Tkinter for fast restaurant ordering, receipt generation, and sales tracking.

## Features

- Menu cards for appetizers, mains, drinks, and sides
- Order creation with automatic subtotal, discount, and tax handling
- Payment processing with validation and rollback on payment failures
- Receipt generation for customer checkout
- Sales summary logic for reporting and auditing

## Project layout

- `restaurant_pos/menu.py` – menu definitions and stock handling
- `restaurant_pos/payments.py` – order totals, discounts, tax, payments, and receipts
- `restaurant_pos/services.py` – UI-independent checkout and inventory orchestration
- `restaurant_pos/app.py` – Tkinter user interface
- `tests/test_pos_system.py` – pytest coverage for totals, discounts, tax, and payment rollback

## Run the app

```bash
python main.py
```

## Run tests

```bash
python -m pytest --cov=restaurant_pos --cov-report=term-missing
```

Development dependencies are listed in `requirements-dev.txt`. Install them with:

```bash
python -m pip install -r requirements-dev.txt
pre-commit install
```

Run the complete local quality gate before opening a pull request:

```bash
python scripts/release_check.py
```

This checks syntax compilation, Ruff linting, mypy typing, pytest coverage
(with a 70% minimum for the testable business-logic modules), and application
startup. The same checks run automatically on every push and pull request in
GitHub Actions. On Linux, the CI smoke test uses `xvfb-run` for Tkinter's
display requirement.

The `Makefile` provides equivalent shortcuts such as `make test`, `make check`,
and `make release-check`.

## QA checklist

- Invalid menu item lookups should fail cleanly.
- Discounts cannot exceed 100% or go below 0%.
- Payment failures roll back the active order.
- Cash amounts below the order total are rejected.
- Receipt output includes item details and final totals.
