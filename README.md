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
- `restaurant_pos/app.py` – Tkinter user interface
- `tests/test_pos_system.py` – pytest coverage for totals, discounts, tax, and payment rollback

## Run the app

```bash
python main.py
```

## Run tests

```bash
pytest -q
```

## QA checklist

- Invalid menu item lookups should fail cleanly.
- Discounts cannot exceed 100% or go below 0%.
- Payment failures roll back the active order.
- Cash amounts below the order total are rejected.
- Receipt output includes item details and final totals.
