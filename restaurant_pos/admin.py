"""Administrator controls for tax, discounts, and menu maintenance."""
from __future__ import annotations

from decimal import Decimal
from enum import Enum

from .menu import Menu, MenuItem
from .payments import PaymentProcessor
from .storage import SQLiteStore


class StaffRole(str, Enum):
    """Roles that control access to POS administration actions."""

    CASHIER = "cashier"
    MANAGER = "manager"
    ADMIN = "admin"


class AdminControls:
    """Small UI-independent facade suitable for an admin settings screen."""

    def __init__(
        self,
        menu: Menu,
        processor: PaymentProcessor,
        role: StaffRole | str = StaffRole.ADMIN,
        store: SQLiteStore | None = None,
    ) -> None:
        """Create administrator controls for the supplied menu and processor."""
        self.menu = menu
        self.processor = processor
        self.store = store
        if self.store:
            saved_rate = self.store.get_setting("tax_rate")
            if saved_rate is not None:
                self.processor.tax_rate = Decimal(saved_rate)
        saved_discount = (
            self.store.get_setting("discount_percentage")
            if self.store else None
        )
        self.discount_percentage = Decimal(saved_discount or "10")
        try:
            self.role = StaffRole(role)
        except ValueError as exc:
            raise ValueError(f"Unknown staff role: {role}") from exc

    def require_manager(self) -> None:
        """Require manager or administrator access for a protected action."""
        if self.role not in (StaffRole.MANAGER, StaffRole.ADMIN):
            raise PermissionError("Manager or administrator access is required.")

    def set_tax_rate(self, rate: float | Decimal) -> Decimal:
        """Set and return the processor tax rate."""
        self.require_manager()
        if Decimal(str(rate)) < 0:
            raise ValueError("Tax rate cannot be negative.")
        self.processor.tax_rate = Decimal(str(rate)).quantize(Decimal("0.01"))
        if self.store:
            self.store.set_setting("tax_rate", str(self.processor.tax_rate))
        return self.processor.tax_rate

    def set_discount_percentage(self, percentage: float | Decimal) -> Decimal:
        """Set and persist the default order discount percentage."""
        self.require_manager()
        value = self.validate_discount(percentage)
        self.discount_percentage = value
        if self.store:
            self.store.set_setting("discount_percentage", str(value))
        return value

    def create_menu_item(self, item: MenuItem) -> None:
        """Add a menu item through the administrator interface."""
        self.require_manager()
        self.menu.add_item(item)

    def update_menu_item(self, sku: str, **changes) -> MenuItem:
        """Update and return a menu item through the administrator interface."""
        self.require_manager()
        return self.menu.update_item(sku, **changes)

    def delete_menu_item(self, sku: str) -> None:
        """Remove a menu item through the administrator interface."""
        self.require_manager()
        self.menu.remove_item(sku)

    @staticmethod
    def validate_discount(percentage: float | Decimal) -> Decimal:
        """Validate and return a discount percentage."""
        value = Decimal(str(percentage))
        if not 0 <= value <= 100:
            raise ValueError("Discount percentage must be between 0 and 100.")
        return value
