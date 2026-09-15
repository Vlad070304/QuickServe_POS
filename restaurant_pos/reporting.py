"""Reporting and sales summary utilities for the POS."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import List

from .payments import Order


class SalesReport:
    """Generates sales summaries from processed orders."""

    def __init__(self) -> None:
        """Create an empty sales report."""
        self.orders: List[Order] = []

    def add_order(self, order: Order) -> None:
        """Record a non-empty processed order."""
        if not order.items:
            raise ValueError("Cannot add an empty order to the sales report.")
        self.orders.append(order)

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
