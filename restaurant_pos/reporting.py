"""Reporting and sales summary utilities for the POS."""

from __future__ import annotations

import csv
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from io import StringIO
from pathlib import Path
from typing import List

from .payments import Order
from .storage import SQLiteStore


class SalesReport:
    """Generates sales summaries from processed orders."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        """Create an empty sales report."""
        self.orders: List[Order] = []
        self.store = SQLiteStore(db_path) if db_path else None
        self.last_payment: list[dict] = []
        self._refunds: list[Decimal] = []

    def add_order(self, order: Order, *, persist: bool = True) -> None:
        """Record a non-empty processed order."""
        if not order.items:
            raise ValueError("Cannot add an empty order to the sales report.")
        self.orders.append(order)
        if self.store and persist:
            self.store.save_order(order, self.last_payment)

    def search(self, query: str = "") -> list[Order]:
        """Search recorded order history by SKU or item name."""
        term = query.casefold()
        return [order for order in self.orders if not term or
                term in (order.order_number + " " + order.customer).casefold() or
                any(term in (item.name + " " + item.sku).casefold() for item in order.items)]

    def search_orders(self, query: str = "", on_date: date | None = None) -> list[Order]:
        """Search order number, customer, items, and optional calendar date."""
        return [o for o in self.search(query)
                if on_date is None or o.created_at.date() == on_date]

    def daily_totals(self, on_date: date | None = None) -> dict[str, Decimal]:
        """Return order count and revenue for the selected calendar date."""
        target = on_date or datetime.now().date()
        orders = [o for o in self.orders if o.created_at.date() == target]
        revenue = sum(
            (o.calculate_totals()["total"] for o in orders), Decimal("0")
        ).quantize(Decimal("0.01"))
        return {"orders": Decimal(len(orders)), "revenue": revenue}

    def best_sellers(self, limit: int | None = None) -> dict[str, int]:
        """Return sold item quantities ordered from most to least popular."""
        result = dict(sorted(self.items_sold().items(), key=lambda pair: (-pair[1], pair[0])))
        return dict(list(result.items())[:limit]) if limit else result

    def hourly_sales(self) -> dict[int, Decimal]:
        """Return sales totals grouped by the order creation hour."""
        result: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
        for order in self.orders:
            result[order.created_at.hour] += order.calculate_totals()["total"]
        return {hour: value.quantize(Decimal("0.01")) for hour, value in sorted(result.items())}

    def refund(self, order_number: str, amount: float | Decimal | None = None) -> Decimal:
        """Record a negative sale for a full or partial refund."""
        original = next((o for o in self.orders if o.order_number == order_number), None)
        if original is None:
            raise KeyError(order_number)
        refund_amount = (
            Decimal(str(amount))
            if amount is not None
            else original.calculate_totals()["total"]
        )
        if refund_amount <= 0 or refund_amount > original.calculate_totals()["total"]:
            raise ValueError("Refund amount is outside the order total.")
        refund_amount = refund_amount.quantize(Decimal("0.01"))
        self._refunds.append(refund_amount)
        if self.store:
            self.store.save_refund(order_number, refund_amount)
        return refund_amount

    def category_sales(self) -> dict[str, Decimal]:
        """Return sales totals grouped by menu category."""
        result: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for order in self.orders:
            for item in order.items:
                result[getattr(item, "category", "Uncategorized")] += item.line_total()
        return {key: value.quantize(Decimal("0.01")) for key, value in result.items()}

    def apply_time_discount(self, order: Order, percentage: float | Decimal,
                            start_hour: int, end_hour: int) -> bool:
        """Apply a discount when the order timestamp falls in the inclusive window."""
        if not 0 <= start_hour <= 23 or not 0 <= end_hour <= 23:
            raise ValueError("Hours must be between 0 and 23.")
        hour = order.created_at.hour
        active = (start_hour <= hour <= end_hour) if start_hour <= end_hour else (
            hour >= start_hour or hour <= end_hour)
        if active:
            order.apply_discount(percentage)
        return active

    def export_csv(self, path: str | Path | None = None) -> str:
        """Export order/item reporting as CSV, optionally writing a file."""
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(["order", "sku", "item", "quantity", "unit_price", "total"])
        for number, order in enumerate(self.orders, 1):
            for item in order.items:
                writer.writerow([number, item.sku, item.name, item.quantity,
                                 item.unit_price, item.line_total()])
        value = output.getvalue()
        if path:
            Path(path).write_text(value, encoding="utf-8", newline="")
        return value

    def search_history(self, query: str = "") -> list:
        """Search both the in-memory session and persisted order history."""
        if self.store:
            return self.store.search_orders(query)
        return self.search(query)

    def total_revenue(self) -> Decimal:
        """Return the rounded revenue across all recorded orders."""
        total = Decimal("0")
        for order in self.orders:
            total += order.calculate_totals()["total"]
        return total.quantize(Decimal("0.01"))

    def items_sold(self) -> dict[str, int]:
        """Return quantities sold grouped by item name."""
        sold: dict[str, int] = defaultdict(int)
        for order in self.orders:
            for item in order.items:
                sold[item.name] += item.quantity
        return dict(sold)

    def summary_text(self) -> str:
        """Return a human-readable daily sales summary."""
        item_counts = self.items_sold()
        revenue = self.total_revenue()
        lines = ["Daily Sales Summary", "===================", f"Revenue: ${revenue:.2f}"]
        if not item_counts:
            lines.append("No sales recorded.")
            return "\n".join(lines)

        for name, qty in sorted(item_counts.items()):
            lines.append(f"{name}: {qty} sold")
        return "\n".join(lines)
