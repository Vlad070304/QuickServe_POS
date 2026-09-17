"""Application services coordinating POS domain operations."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from .menu import Menu
from .payments import Order, OrderItem, PaymentProcessor
from .reporting import SalesReport


class CheckoutService:
    """Coordinate menu validation, payment settlement, and sales recording."""

    def __init__(
        self,
        menu: Menu,
        processor: PaymentProcessor,
        sales_report: SalesReport,
    ) -> None:
        """Create a checkout service using the supplied domain collaborators."""
        self.menu = menu
        self.processor = processor
        self.sales_report = sales_report

    def add_item(self, order: Order, sku: str, quantity: int = 1) -> None:
        """Validate inventory and add a menu item to an order."""
        menu_item = self.menu.get_item(sku)
        existing_quantity = next(
            (item.quantity for item in order.items if item.sku == sku),
            0,
        )
        if existing_quantity + quantity > menu_item.stock:
            raise ValueError(f"Not enough stock for {menu_item.name}.")
        order.add_item(menu_item, quantity)

    def checkout(
        self,
        order: Order,
        tendered_amount: float | Decimal,
        *,
        tenders: dict[str, float | Decimal] | None = None,
    ) -> dict[str, Any]:
        """Settle an order, update inventory, and record the completed sale."""
        self._validate_stock(order)
        result = (self.processor.process_split_payment(order, tenders)
                  if tenders is not None else self.processor.process_payment(order, tendered_amount))
        self._decrement_stock(order)
        self.sales_report.last_payment = result.get("payments", [])
        self.sales_report.add_order(self._copy_order(order))
        order.rollback()
        return result

    def _validate_stock(self, order: Order) -> None:
        """Ensure all order quantities can be fulfilled before payment."""
        for item in order.items:
            menu_item = self.menu.get_item(item.sku)
            if item.quantity > menu_item.stock:
                raise ValueError(f"Not enough stock for {menu_item.name}.")

    def _decrement_stock(self, order: Order) -> None:
        """Remove sold quantities from the menu inventory."""
        for item in order.items:
            self.menu.update_stock(item.sku, -item.quantity)

    @staticmethod
    def _copy_order(order: Order) -> Order:
        """Create an independent sales record before the active order is reset."""
        snapshot = Order(tax_rate=order.tax_rate, customer=order.customer,
                         order_number=order.order_number, created_at=order.created_at)
        snapshot.items = [
            OrderItem(
                sku=item.sku,
                name=item.name,
                quantity=item.quantity,
                unit_price=item.unit_price,
                category=item.category,
            )
            for item in order.items
        ]
        snapshot.discount_percentage = order.discount_percentage
        snapshot.paid = order.paid
        return snapshot
