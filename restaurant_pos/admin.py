"""Administrator controls for tax, discounts, and menu maintenance."""
from __future__ import annotations

from decimal import Decimal

from .menu import Menu, MenuItem
from .payments import PaymentProcessor


class AdminControls:
    """Small UI-independent facade suitable for an admin settings screen."""

    def __init__(self, menu: Menu, processor: PaymentProcessor) -> None:
        self.menu = menu
        self.processor = processor

    def set_tax_rate(self, rate: float | Decimal) -> Decimal:
        if Decimal(str(rate)) < 0:
            raise ValueError("Tax rate cannot be negative.")
        self.processor.tax_rate = Decimal(str(rate)).quantize(Decimal("0.01"))
        return self.processor.tax_rate

    def create_menu_item(self, item: MenuItem) -> None:
        self.menu.add_item(item)

    def update_menu_item(self, sku: str, **changes) -> MenuItem:
        return self.menu.update_item(sku, **changes)

    def delete_menu_item(self, sku: str) -> None:
        self.menu.remove_item(sku)

    @staticmethod
    def validate_discount(percentage: float | Decimal) -> Decimal:
        value = Decimal(str(percentage))
        if not 0 <= value <= 100:
            raise ValueError("Discount percentage must be between 0 and 100.")
        return value
