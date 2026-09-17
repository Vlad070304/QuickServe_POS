# QuickServe POS

A desktop point-of-sale application built with Python and Tkinter for fast restaurant ordering, receipt generation, and sales tracking.

## Features

- Menu cards for appetizers, mains, drinks, and sides
- Order creation with automatic subtotal, discount, and tax handling
- Payment processing with validation and rollback on payment failures
- SQLite-backed menu inventory with stock decremented after successful sales
- Persistent order history with order numbers, customer names, timestamps, and search
- Cash/card split payments and configurable tax administration
- Menu administration, time-based discounts, refunds, sales reports, and CSV export
- Receipt generation for customer checkout
- PDF receipts, thermal-printer output, and separate kitchen tickets
- Sales summary logic for reporting and auditing

## Project layout

- `restaurant_pos/menu.py` – menu definitions and stock handling
- `restaurant_pos/payments.py` – order totals, discounts, tax, payments, and receipts
- `restaurant_pos/services.py` – UI-independent checkout and inventory orchestration
- `restaurant_pos/storage.py` – SQLite persistence for inventory and completed orders
- `restaurant_pos/admin.py` – tax and menu administration facade
- `restaurant_pos/app.py` – Tkinter user interface
- `tests/test_pos_system.py` – pytest coverage for totals, discounts, tax, and payment rollback

## Run the app

```bash
python main.py
```

For local development, `make start` (or `python scripts/start_dev.py`) starts
the app against `quickserve-dev.db`. A new database is automatically seeded
with the demo menu; existing data is never overwritten. Set `QUICKSERVE_DB`
to use another database path.

Menu and completed sales can be transferred without opening SQLite directly:

```bash
python -c "from restaurant_pos.operations import export_menu; export_menu('quickserve-dev.db', 'menu.csv')"
python -c "from restaurant_pos.operations import import_menu; import_menu('quickserve-dev.db', 'menu.csv')"
python -c "from restaurant_pos.operations import export_sales; export_sales('quickserve-dev.db', 'sales.csv')"
python -c "from restaurant_pos.operations import import_sales; import_sales('quickserve-dev.db', 'sales.csv')"
```

`SalesBackupScheduler` in `restaurant_pos.operations` provides consistent
background SQLite backups. It reports filesystem/database errors through its
`on_error` callback rather than hiding failures. Payment input is validated
before settlement and invalid or insufficient tenders leave the order unpaid.

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
