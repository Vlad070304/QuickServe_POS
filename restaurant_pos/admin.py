"""Administrator controls for tax, discounts, and menu maintenance."""
from __future__ import annotations

from decimal import Decimal

from .menu import Menu, MenuItem
from .payments import PaymentProcessor


class AdminControls:
    """Small UI-independent facade suitable for an admin settings screen."""

    def __init__(self, menu: Menu, processor: PaymentProcessor) -> None:
        """Create administrator controls for the supplied menu and processor."""
        self.menu = menu
        self.processor = processor

    def set_tax_rate(self, rate: float | Decimal) -> Decimal:
        """Set and return the processor tax rate."""
        if Decimal(str(rate)) < 0:
            raise ValueError("Tax rate cannot be negative.")
        self.processor.tax_rate = Decimal(str(rate)).quantize(Decimal("0.01"))
        return self.processor.tax_rate

    def create_menu_item(self, item: MenuItem) -> None:
        """Add a menu item through the administrator interface."""
        self.menu.add_item(item)

    def update_menu_item(self, sku: str, **changes) -> MenuItem:
        """Update and return a menu item through the administrator interface."""
        return self.menu.update_item(sku, **changes)

    def delete_menu_item(self, sku: str) -> None:
        """Remove a menu item through the administrator interface."""
        self.menu.remove_item(sku)

    @staticmethod
    def validate_discount(percentage: float | Decimal) -> Decimal:
        """Validate and return a discount percentage."""
        value = Decimal(str(percentage))
        if not 0 <= value <= 100:
            raise ValueError("Discount percentage must be between 0 and 100.")
        return value
