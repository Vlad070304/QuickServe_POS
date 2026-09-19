"""Tkinter-based restaurant POS application.

This module is the application controller: it owns the domain objects
(menu, order, payment processor, sales report, admin controls) and wires
them to the view components in :mod:`restaurant_pos.ui`. The view
components handle their own widget layout and styling; this file only
coordinates user actions, validation errors, and status updates between
them.
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk  # noqa: F401  (see note below)  # pylint: disable=unused-import
from decimal import Decimal
from pathlib import Path

from .menu import Menu, MenuItem, build_demo_menu
from .payments import Order, PaymentError, PaymentProcessor
from .reporting import SalesReport
from .services import CheckoutService
from .admin import AdminControls, StaffRole
from .operations import SalesBackupScheduler
from .ui.settings import AppSettings
from .ui.theme import apply_theme
from .ui.dialogs import DialogService
from .ui.menu_panel import MenuPanel
from .ui.order_panel import OrderPanel
from .ui.admin_panel import AdminPanel
from .ui.status_bar import StatusBar
from .ui.history_window import OrderHistoryWindow

# `messagebox`, `simpledialog`, and `ttk` are imported here (and not just in
# restaurant_pos.ui.dialogs) so that patching restaurant_pos.app.messagebox.*
# in tests still reaches the same shared tkinter.messagebox module object
# that DialogService calls into, and so ttk remains available for any
# direct styling callers of this module.


class RestaurantPOSApp(tk.Tk):
    """Provide the graphical user interface for the restaurant POS."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        staff_role: StaffRole | str = StaffRole.ADMIN,
        settings: AppSettings | None = None,
    ) -> None:
        """Initialize application state, domain services, and the UI."""
        super().__init__()
        self.settings = settings or AppSettings()
        self.title(self.settings.title)
        self.geometry(self.settings.geometry)
        apply_theme(self, self.settings)
        self.dialogs = DialogService()

        self._init_domain(db_path, staff_role)

        self.build_ui()
        self._bind_shortcuts()
        self.refresh_order_panel()

    # ------------------------------------------------------------------
    # Domain / service wiring
    # ------------------------------------------------------------------
    def _init_domain(
        self, db_path: str | Path | None, staff_role: StaffRole | str,
    ) -> None:
        """Create the menu, order, payment, reporting, and admin services."""
        self.menu = build_demo_menu() if db_path is None else Menu(db_path)
        if db_path is not None and not self.menu.list_items():
            for item in build_demo_menu().list_items():
                self.menu.add_item(item)

        self.order = Order()
        self.processor = PaymentProcessor(tax_rate=self.settings.default_tax_rate)
        self.sales_report = SalesReport(db_path)
        self.backup_scheduler = self._build_backup_scheduler(db_path)
        self.checkout_service = CheckoutService(
            self.menu, self.processor, self.sales_report)
        self.admin = AdminControls(
            self.menu, self.processor, role=staff_role, store=self.sales_report.store)

    def _build_backup_scheduler(
        self, db_path: str | Path | None,
    ) -> SalesBackupScheduler | None:
        """Start a background backup scheduler when configured via env vars."""
        backup_path = os.getenv("QUICKSERVE_BACKUP_PATH")
        if db_path is None or not backup_path:
            return None
        if self.sales_report.store is None:
            raise RuntimeError("Persistent sales storage is required for backups.")
        interval = float(os.getenv(
            "QUICKSERVE_BACKUP_INTERVAL", str(self.settings.default_backup_interval_seconds)))
        if interval <= 0:
            raise ValueError("QUICKSERVE_BACKUP_INTERVAL must be greater than zero.")
        scheduler = SalesBackupScheduler(
            self.sales_report.store, backup_path, interval,
            on_error=self._on_backup_error,
        )
        scheduler.start()
        return scheduler

    def _on_backup_error(self, exc: Exception) -> None:
        """Report a backup failure from the scheduler's background thread.

        This runs on the scheduler's worker thread, so it must not touch
        Tkinter state directly; ``StatusBar.report_error_threadsafe``
        marshals the update onto the main thread via ``after``.
        """
        self.status_bar.report_error_threadsafe(f"Backup error: {exc}")

    def destroy(self) -> None:
        """Stop background work before closing the Tk application."""
        if self.backup_scheduler is not None:
            self.backup_scheduler.stop()
        if self.menu.store is not None:
            self.menu.store.close()
        if self.sales_report.store is not None and self.sales_report.store is not self.menu.store:
            self.sales_report.store.close()
        super().destroy()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _bind_shortcuts(self) -> None:
        """Register keyboard shortcuts for frequent point-of-sale actions."""
        self.bind_all("<Control-Return>", lambda _event: self.checkout())
        self.bind_all("<Escape>", lambda _event: self.clear_order())
        self.bind_all("<Control-d>", lambda _event: self.apply_discount())

    def build_ui(self) -> None:
        """Construct the menu, order, admin, and status view components."""
        self.root_frame = ttk.Frame(self, padding=18, style="Background.TFrame")
        self.root_frame.pack(fill=tk.BOTH, expand=True)

        self.menu_panel = MenuPanel(
            self.root_frame, self.settings, on_select=self.add_item_to_order)
        self.menu_panel.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 16))
        # Exposed for backward-compatible/test access; MenuPanel mutates
        # this same list in place on every refresh rather than replacing it.
        self.menu_buttons = self.menu_panel.buttons

        self.order_panel = OrderPanel(
            self.root_frame, self.settings,
            on_checkout=self.checkout,
            on_split_checkout=self.split_checkout,
            on_clear=self.clear_order,
            on_discount=self.apply_discount,
            on_export_csv=self.export_report,
            on_export_receipts=self.export_receipts,
        )
        self.order_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.payment_entry = self.order_panel.payment_entry
        self.customer_entry = self.order_panel.customer_entry
        self.split_cash_entry = self.order_panel.split_cash_entry
        self.split_card_entry = self.order_panel.split_card_entry
        self.checkout_button = self.order_panel.checkout_button
        self.discount_button = self.order_panel.discount_button
        self.clear_button = self.order_panel.clear_button

        self.admin_panel = AdminPanel(
            self.order_panel.controls, self.admin.role,
            on_set_tax=self.set_tax,
            on_add_item=self.add_menu_item,
            on_remove_item=self.remove_menu_item,
            on_view_history=self.view_order_history,
        )
        self.admin_panel.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.tax_button = self.admin_panel.tax_button
        self.add_item_button = self.admin_panel.add_item_button
        self.remove_item_button = self.admin_panel.remove_item_button
        self.role_var = self.admin_panel.role_var

        self.status_bar = StatusBar(self.root_frame, self.settings)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        self.status_var = self.status_bar.status_var
        self.order_summary_var = self.status_bar.order_summary_var
        self.sales_var = self.status_bar.sales_var

        self.refresh_menu_panel()

    def refresh_menu_panel(self) -> None:
        """Refresh menu buttons after administrator inventory changes."""
        self.menu_panel.refresh(self.menu.list_items())

    def refresh_order_panel(self) -> None:
        """Refresh displayed items, totals, and sales information."""
        totals = self.processor.calculate_order_total(self.order)
        summary = self.order_panel.refresh(self.order, totals)
        self.status_bar.order_summary_var.set(summary)
        self.status_bar.sales_var.set(
            f"Today's sales: ${self.sales_report.total_revenue():.2f}")

    # ------------------------------------------------------------------
    # Cashier actions
    # ------------------------------------------------------------------
    def add_item_to_order(self, sku: str) -> None:
        """Add a selected menu item to the active order."""
        try:
            menu_item = self.menu.get_item(sku)
            self.checkout_service.add_item(self.order, sku)
            self.status_bar.set_status(f"Added {menu_item.name} to the order.")
            self.refresh_order_panel()
        except ValueError as exc:
            self.dialogs.error("Order Error", str(exc))

    def apply_discount(self) -> None:
        """Apply the configured default order discount."""
        try:
            self.admin.apply_discount(self.order, self.admin.discount_percentage)
            self.status_bar.set_status(
                f"{self.admin.discount_percentage}% discount applied to the order.")
            self.refresh_order_panel()
        except ValueError as exc:
            self.dialogs.error("Discount Error", str(exc))

    def clear_order(self) -> None:
        """Discard the active order and refresh the display."""
        self.order.rollback()
        self.status_bar.set_status("Order cleared.")
        self.refresh_order_panel()

    def checkout(self) -> None:
        """Process the entered payment and display the resulting receipt."""
        try:
            self.order.customer = self.order_panel.customer_entry.get().strip()
            amount_text = self.order_panel.payment_entry.get().strip()
            if not amount_text:
                raise ValueError("Enter a cash amount before checking out.")
            try:
                amount = float(amount_text)
            except ValueError as exc:
                raise ValueError("Cash amount must be a valid number.") from exc
            payment_result = self.checkout_service.checkout(self.order, amount)
            receipt_text = payment_result["receipt"]

            self.status_bar.set_status(
                "Payment successful. Receipt generated. "
                f"Total: ${payment_result['total']:.2f}"
            )
            self.refresh_order_panel()
            self.refresh_menu_panel()
            self.dialogs.info("Receipt", receipt_text)
        except (ValueError, PaymentError) as exc:
            self.status_bar.set_status(str(exc))
            self.dialogs.error("Payment Error", str(exc))

    def split_checkout(self) -> None:
        """Checkout using cash and card partial tenders."""
        try:
            tenders: dict[str, float | Decimal] = {
                "cash": float(self.order_panel.split_cash_entry.get() or 0),
                "card": float(self.order_panel.split_card_entry.get() or 0),
            }
            result = self.checkout_service.checkout(self.order, 0, tenders=tenders)
            self.dialogs.info("Receipt", result["receipt"])
            self.refresh_order_panel()
            self.refresh_menu_panel()
        except (ValueError, PaymentError) as exc:
            self.dialogs.error("Payment Error", str(exc))

    def export_report(self) -> None:
        """Prompt for a destination and export sales data as CSV."""
        path = self.dialogs.ask_save_path(".csv")
        if path:
            self.sales_report.export_csv(path)

    def export_receipts(self) -> None:
        """Save the active receipt as PDF and display its kitchen ticket."""
        if not self.order.items:
            self.dialogs.info("Receipt", "Complete an order first.")
            return
        path = self.dialogs.ask_save_path(".pdf")
        if path:
            self.order.save_pdf(path)
        self.dialogs.info("Kitchen Ticket", self.order.kitchen_ticket())

    def view_order_history(self) -> None:
        """Open the order history screen for browsing and searching sales."""
        OrderHistoryWindow(self, self.sales_report)

    # ------------------------------------------------------------------
    # Administrator actions
    # ------------------------------------------------------------------
    def set_tax(self) -> None:
        """Prompt for and apply a new tax rate."""
        value = self.dialogs.ask_float(
            "Admin Tax", "Tax rate (e.g. 0.08):",
            initialvalue=float(self.processor.tax_rate))
        if value is not None:
            try:
                self.admin.set_tax_rate(value)
                self.refresh_order_panel()
                self.status_bar.set_status(f"Tax rate set to {value}.")
            except (PermissionError, ValueError) as exc:
                self.dialogs.error("Admin Error", str(exc))

    def add_menu_item(self) -> None:
        """Collect and add a menu item through the administrator controls."""
        sku = self.dialogs.ask_string("Admin Menu", "SKU:")
        name = self.dialogs.ask_string("Admin Menu", "Name:")
        category = self.dialogs.ask_string("Admin Menu", "Category:")
        price = self.dialogs.ask_float("Admin Menu", "Price:", minvalue=0)
        stock = self.dialogs.ask_int("Admin Menu", "Opening stock:", minvalue=0)
        if sku is None or name is None or category is None or price is None or stock is None:
            return
        try:
            self.admin.create_menu_item(MenuItem(sku, name, category, price, stock))
            self.refresh_menu_panel()
            self.status_bar.set_status(f"Added {name} to the menu.")
        except (PermissionError, ValueError) as exc:
            self.dialogs.error("Menu Error", str(exc))

    def remove_menu_item(self) -> None:
        """Remove a menu item by SKU through the administrator controls.

        Deleting a menu item is destructive and cannot be undone from the
        UI, so it is confirmed before the admin controls are called.
        """
        sku = self.dialogs.ask_string("Admin Menu", "SKU to remove:")
        if not sku:
            return
        if not self.dialogs.confirm(
            "Remove Menu Item",
            f"Remove '{sku}' from the menu? This cannot be undone.",
        ):
            self.status_bar.set_status("Menu item removal cancelled.")
            return
        try:
            self.admin.delete_menu_item(sku)
            self.refresh_menu_panel()
            self.status_bar.set_status(f"Removed {sku} from the menu.")
        except (KeyError, ValueError, PermissionError) as exc:
            self.dialogs.error("Menu Error", str(exc))


def main() -> None:
    """Launch the QuickServe POS desktop application."""
    app = RestaurantPOSApp()
    app.mainloop()


if __name__ == "__main__":
    main()
