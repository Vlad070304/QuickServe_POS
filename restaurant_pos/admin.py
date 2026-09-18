"""Administrator controls for tax, discounts, and menu maintenance."""
from __future__ import annotations

from decimal import Decimal
from enum import Enum
from dataclasses import dataclass

from .menu import Menu, MenuItem
from .payments import PaymentProcessor
from .storage import SQLiteStore


class StaffRole(str, Enum):
    """Roles that control access to POS administration actions."""

    CASHIER = "cashier"
    MANAGER = "manager"
    ADMIN = "admin"


@dataclass(frozen=True)
class StaffSession:
    """Authenticated staff session used for protected operations."""

    token: str
    username: str
    role: StaffRole


class AdminControls:
    """Small UI-independent facade suitable for an admin settings screen."""

    def __init__(
        self,
        menu: Menu,
        processor: PaymentProcessor,
        role: StaffRole | str = StaffRole.ADMIN,
        store: SQLiteStore | None = None,
        session: StaffSession | None = None,
    ) -> None:
        """Create administrator controls for the supplied menu and processor."""
        self.menu = menu
        self.processor = processor
        self.store = store
        self.session = session
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
        role = self.role
        if self.store:
            if self.session is None:
                raise PermissionError("Log in as a staff member before continuing.")
            username, stored_role = self.store.get_session_role(self.session.token)
            if username != self.session.username:
                raise PermissionError("Staff session identity mismatch.")
            role = StaffRole(stored_role)
        if role not in (StaffRole.MANAGER, StaffRole.ADMIN):
            raise PermissionError("Manager or administrator access is required.")

    def login(self, username: str, password: str, *, ttl: int = 28800) -> StaffSession:
        """Authenticate a staff member and return a protected session."""
        if self.store is None:
            raise RuntimeError("Persistent storage is required for staff login.")
        token = self.store.authenticate_staff(username, password, ttl=ttl)
        _, role = self.store.get_session_role(token)
        self.session = StaffSession(token, username.strip(), StaffRole(role))
        self.role = self.session.role
        self.store.audit(self.session.username, "login")
        return self.session

    def logout(self) -> None:
        """Revoke the current authenticated staff session."""
        if self.store and self.session:
            self.store.revoke_session(self.session.token)
            self.store.audit(self.session.username, "logout")
        self.session = None

    def set_tax_rate(self, rate: float | Decimal) -> Decimal:
        """Set and return the processor tax rate."""
        self.require_manager()
        if Decimal(str(rate)) < 0:
            raise ValueError("Tax rate cannot be negative.")
        self.processor.tax_rate = Decimal(str(rate)).quantize(Decimal("0.01"))
        if self.store:
            self.store.set_setting("tax_rate", str(self.processor.tax_rate))
            self.store.audit(self._actor(), "tax_changed", str(self.processor.tax_rate))
        return self.processor.tax_rate

    def set_discount_percentage(self, percentage: float | Decimal) -> Decimal:
        """Set and persist the default order discount percentage."""
        self.require_manager()
        value = self.validate_discount(percentage)
        self.discount_percentage = value
        if self.store:
            self.store.set_setting("discount_percentage", str(value))
            self.store.audit(self._actor(), "discount_changed", str(value))
        return value

    def create_menu_item(self, item: MenuItem) -> None:
        """Add a menu item through the administrator interface."""
        self.require_manager()
        self.menu.add_item(item)
        self._audit("menu_item_created", item.sku)

    def update_menu_item(self, sku: str, **changes) -> MenuItem:
        """Update and return a menu item through the administrator interface."""
        self.require_manager()
        updated = self.menu.update_item(sku, **changes)
        self._audit("menu_item_updated", sku)
        return updated

    def delete_menu_item(self, sku: str) -> None:
        """Remove a menu item through the administrator interface."""
        self.require_manager()
        self.menu.remove_item(sku)
        self._audit("menu_item_deleted", sku)

    def adjust_stock(self, sku: str, quantity: int) -> None:
        """Adjust inventory through an authorized and auditable operation."""
        self.require_manager()
        self.menu.update_stock(sku, quantity)
        self._audit("stock_adjusted", f"{sku}:{quantity}")

    def apply_discount(self, order, percentage: float | Decimal) -> None:
        """Apply a discount and audit the action when storage is enabled."""
        value = self.validate_discount(percentage)
        if value > Decimal("10"):
            self.require_manager()
        order.apply_discount(value)
        self._audit("discount_applied", str(value))

    def _actor(self) -> str:
        """Return the authenticated actor or the local compatibility identity."""
        return self.session.username if self.session else "local"

    def _audit(self, action: str, details: str) -> None:
        """Write an audit record when persistent storage is enabled."""
        if self.store:
            self.store.audit(self._actor(), action, details)

    @staticmethod
    def validate_discount(percentage: float | Decimal) -> Decimal:
        """Validate and return a discount percentage."""
        value = Decimal(str(percentage))
        if not 0 <= value <= 100:
            raise ValueError("Discount percentage must be between 0 and 100.")
        return value
