"""Reporting and sales summary utilities for the POS."""

from __future__ import annotations

import csv
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path
from typing import Iterable, List

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

    def refund(
        self,
        order_number: str,
        amount: float | Decimal | None = None,
        *,
        session_token: str | None = None,
    ) -> Decimal:
        """Record a negative sale for a full or partial refund."""
        actor = "local"
        if self.store:
            if session_token is None:
                raise PermissionError("A valid staff session is required for refunds.")
            actor, role = self.store.get_session_role(session_token)
            if role not in {"manager", "admin"}:
                raise PermissionError("Manager or administrator approval is required.")
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
            self.store.audit(actor, "refund_issued", f"{order_number}:{refund_amount}")
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

    @staticmethod
    def _period(
        start: date | datetime | None, end: date | datetime | None
    ) -> tuple[datetime | None, datetime | None]:
        """Normalize report dates to a half-open datetime interval."""
        start_value = (
            datetime.combine(start, time.min) if isinstance(start, date) and
            not isinstance(start, datetime) else start
        )
        end_value = (
            datetime.combine(end + timedelta(days=1), time.min)
            if isinstance(end, date) and not isinstance(end, datetime) else end
        )
        if start_value and end_value and start_value >= end_value:
            raise ValueError("Report start must be before report end.")
        return start_value, end_value

    def _rows(
        self, start: date | datetime | None = None,
        end: date | datetime | None = None,
    ) -> list:
        """Return persisted reporting rows, or synthesized in-memory rows."""
        start_value, end_value = self._period(start, end)
        if self.store:
            def to_text(value: datetime | None) -> str | None:
                return value.isoformat() if value else None

            return self.store.reporting_orders(to_text(start_value), to_text(end_value))
        rows = []
        for order in self.orders:
            if start_value and order.created_at < start_value:
                continue
            if end_value and order.created_at >= end_value:
                continue
            totals = order.calculate_totals()
            for item in order.items:
                rows.append({
                    "order_number": order.order_number, "created_at": order.created_at.isoformat(),
                    "customer": order.customer, "employee": getattr(order, "employee", ""),
                    "subtotal": totals["subtotal"], "tax": totals["tax"],
                    "discount": totals["discount_amount"], "total": totals["total"],
                    "payment_status": "paid", "sku": item.sku, "name": item.name,
                    "category": getattr(item, "category", "Uncategorized"),
                    "quantity": item.quantity, "unit_price": item.unit_price,
                })
        return rows

    @staticmethod
    def _sum(values: Iterable[Decimal]) -> Decimal:
        """Sum currency values and normalize them to cents."""
        return sum(values, Decimal("0")).quantize(Decimal("0.01"))

    def period_totals(
        self, start: date | datetime | None = None,
        end: date | datetime | None = None,
    ) -> dict[str, Decimal]:
        """Return persisted or in-memory totals for a half-open date range."""
        rows = self._rows(start, end)
        orders = {row["order_number"]: row for row in rows}
        gross = self._sum(Decimal(str(row["total"])) for row in orders.values())
        subtotal = self._sum(Decimal(str(row["subtotal"])) for row in orders.values())
        tax = self._sum(Decimal(str(row["tax"])) for row in orders.values())
        discount = self._sum(Decimal(str(row["discount"])) for row in orders.values())
        refunds = self._adjustment_totals(start, end)["refunds"]
        return {
            "orders": Decimal(len(orders)), "subtotal": subtotal, "discount": discount,
            "tax": tax, "gross_sales": gross, "refunds": refunds,
            "net_sales": (gross - refunds).quantize(Decimal("0.01")),
        }

    def tax_totals(
        self, start: date | datetime | None = None,
        end: date | datetime | None = None,
    ) -> Decimal:
        """Return tax collected for the selected date range."""
        return self.period_totals(start, end)["tax"]

    def net_sales(
        self, start: date | datetime | None = None,
        end: date | datetime | None = None,
    ) -> Decimal:
        """Return gross sales less refunds (voids are tracked separately)."""
        return self.period_totals(start, end)["net_sales"]

    def discounts_by_category(
        self, start: date | datetime | None = None,
        end: date | datetime | None = None,
    ) -> dict[str, Decimal]:
        """Allocate each order discount across its item categories."""
        result: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for group in self._group_rows(self._rows(start, end)).items():
            line_values = [Decimal(str(row["unit_price"])) * row["quantity"] for row in group]
            line_total = sum(line_values, Decimal("0"))
            discount = Decimal(str(group[0]["discount"]))
            for row, value in zip(group, line_values):
                if line_total:
                    result[row["category"]] += discount * value / line_total
        return {key: value.quantize(Decimal("0.01")) for key, value in result.items()}

    def discounts_by_employee(
        self, start: date | datetime | None = None,
        end: date | datetime | None = None,
    ) -> dict[str, Decimal]:
        """Return discounts grouped by the employee recorded on each order."""
        result: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for row in self._unique_orders(self._rows(start, end)):
            result[row["employee"] or "Unassigned"] += Decimal(str(row["discount"]))
        return {key: value.quantize(Decimal("0.01")) for key, value in result.items()}

    def discounts_by_period(
        self, start: date | datetime | None = None,
        end: date | datetime | None = None,
    ) -> dict[str, Decimal]:
        """Return discounts grouped by calendar day in the selected range."""
        result: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for row in self._unique_orders(self._rows(start, end)):
            day = str(row["created_at"])[:10]
            result[day] += Decimal(str(row["discount"]))
        return {key: value.quantize(Decimal("0.01")) for key, value in sorted(result.items())}

    def payment_totals(
        self, start: date | datetime | None = None,
        end: date | datetime | None = None,
    ) -> dict[str, Decimal]:
        """Return settled payment totals by tender method."""
        if self.store:
            start_value, end_value = self._period(start, end)
            payments = self.store.reporting_payments(
                start_value.isoformat() if start_value else None,
                end_value.isoformat() if end_value else None,
            )
            return {method: self._sum(
                Decimal(str(row["amount"])) for row in payments
                if row["method"] == method and row["status"] == "paid"
            ) for method in sorted({row["method"] for row in payments})}
        return self._payment_totals_in_memory(start, end)

    def drawer_reconciliation(
        self, counted_cash: float | Decimal, *,
        opening_cash: float | Decimal = Decimal("0"),
        start: date | datetime | None = None,
        end: date | datetime | None = None,
    ) -> dict[str, Decimal]:
        """Compare expected cash in the drawer with a counted closing balance."""
        cash_sales = self.payment_totals(start, end).get("cash", Decimal("0"))
        adjustments = self._adjustment_totals(start, end)
        opening = Decimal(str(opening_cash)).quantize(Decimal("0.01"))
        counted = Decimal(str(counted_cash)).quantize(Decimal("0.01"))
        expected = opening + cash_sales - adjustments["cash_adjustments"]
        return {"opening_cash": opening, "cash_sales": cash_sales,
                "cash_adjustments": adjustments["cash_adjustments"],
                "expected_cash": expected, "counted_cash": counted,
                "variance": (counted - expected).quantize(Decimal("0.01"))}

    def voids_vs_refunds(
        self, start: date | datetime | None = None,
        end: date | datetime | None = None,
    ) -> dict[str, Decimal]:
        """Return separate totals for voided payments and customer refunds."""
        return self._adjustment_totals(start, end)

    def export_accounting_csv(
        self, path: str | Path | None = None,
        start: date | datetime | None = None,
        end: date | datetime | None = None,
    ) -> str:
        """Export accounting-friendly journal rows for sales and adjustments."""
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(["date", "order", "entry_type", "account", "method", "amount"])
        for row in self._unique_orders(self._rows(start, end)):
            writer.writerow([row["created_at"], row["order_number"], "sale",
                             "sales", "", row["total"]])
            writer.writerow([row["created_at"], row["order_number"], "tax",
                             "tax_payable", "", row["tax"]])
        for row in self._adjustment_rows(start, end):
            writer.writerow([row["created_at"], row["order_number"], row["kind"],
                             "sales_returns", "", row["amount"]])
        value = output.getvalue()
        if path:
            Path(path).write_text(value, encoding="utf-8", newline="")
        return value

    @staticmethod
    def _group_rows(rows: list) -> dict[str, list]:
        grouped: dict[str, list] = defaultdict(list)
        for row in rows:
            grouped[row["order_number"]].append(row)
        return grouped

    @staticmethod
    def _unique_orders(rows: list) -> list:
        """Keep one row per order while preserving chronological order."""
        return list({row["order_number"]: row for row in rows}.values())

    def _adjustment_rows(self, start, end) -> list:
        if self.store:
            start_value, end_value = self._period(start, end)
            return self.store.reporting_adjustments(
                start_value.isoformat() if start_value else None,
                end_value.isoformat() if end_value else None,
            )
        return []

    def _adjustment_totals(self, start, end) -> dict[str, Decimal]:
        rows = self._adjustment_rows(start, end)
        refunds = self._sum(Decimal(str(row["amount"])) for row in rows if row["kind"] == "refund")
        voids = self._sum(Decimal(str(row["amount"])) for row in rows if row["kind"] == "void")
        return {"refunds": refunds, "voids": voids, "cash_adjustments": refunds + voids}

    def _payment_totals_in_memory(self, start, end) -> dict[str, Decimal]:
        result: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for order in self.orders:
            start_value, end_value = self._period(start, end)
            if start_value and order.created_at < start_value:
                continue
            if end_value and order.created_at >= end_value:
                continue
            result["cash"] += order.calculate_totals()["total"]
        return {key: value.quantize(Decimal("0.01")) for key, value in result.items()}
