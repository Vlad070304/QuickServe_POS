"""Tkinter-based restaurant POS application."""

from __future__ import annotations

import tkinter as tk
import os
from tkinter import filedialog, messagebox, simpledialog, ttk
from decimal import Decimal
from pathlib import Path

from .menu import MenuItem, build_demo_menu
from .payments import Order, PaymentError, PaymentProcessor
from .reporting import SalesReport
from .services import CheckoutService
from .admin import AdminControls, StaffRole
from .operations import SalesBackupScheduler

COLORS = {
    "background": "#f4f7fb",
    "surface": "#ffffff",
    "primary": "#cfe8ff",
    "primary_text": "#143050",
    "text": "#183153",
    "muted": "#314f74",
    "success": "#d9f7e8",
    "danger": "#fbe8e8",
}


class RestaurantPOSApp(tk.Tk):
    """Provide the graphical user interface for the restaurant POS."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        staff_role: StaffRole | str = StaffRole.ADMIN,
    ) -> None:
        """Initialize the application state and widgets."""
        super().__init__()
        self.title("QuickServe POS")
        self.geometry("980x620")
        self.configure(bg=COLORS["background"])
        self._configure_theme()

        self.menu = build_demo_menu() if db_path is None else __import__(
            "restaurant_pos.menu", fromlist=["Menu"]).Menu(db_path)
        if db_path is not None and not self.menu.list_items():
            for item in build_demo_menu().list_items():
                self.menu.add_item(item)
        self.order = Order()
        self.processor = PaymentProcessor(tax_rate=0.08)
        self.sales_report = SalesReport(db_path)
        self.backup_scheduler = None
        backup_path = os.getenv("QUICKSERVE_BACKUP_PATH")
        if db_path is not None and backup_path:
            if self.sales_report.store is None:
                raise RuntimeError("Persistent sales storage is required for backups.")
            interval = float(os.getenv("QUICKSERVE_BACKUP_INTERVAL", "300"))
            if interval <= 0:
                raise ValueError("QUICKSERVE_BACKUP_INTERVAL must be greater than zero.")
            self.backup_scheduler = SalesBackupScheduler(
                self.sales_report.store, backup_path,
                interval,
                on_error=lambda exc: self.status_var.set(f"Backup error: {exc}"),
            )
            self.backup_scheduler.start()
        self.checkout_service = CheckoutService(
            self.menu,
            self.processor,
            self.sales_report,
        )
        self.admin = AdminControls(
            self.menu, self.processor, role=staff_role,
            store=self.sales_report.store,
        )
        self.order_panel: tk.Frame
        self.order_listbox: tk.Listbox
        self.summary_frame: tk.Frame
        self.subtotal_var: tk.StringVar
        self.tax_var: tk.StringVar
        self.total_var: tk.StringVar
        self.controls: tk.Frame
        self.payment_entry: tk.Entry
        self.discount_button: tk.Button
        self.clear_button: tk.Button
        self.checkout_button: tk.Button
        self.customer_entry: tk.Entry
        self.split_cash_entry: tk.Entry
        self.split_card_entry: tk.Entry
        self.tax_button: tk.Button
        self.add_item_button: tk.Button
        self.remove_item_button: tk.Button
        self.status_var: tk.StringVar
        self.order_summary_var: tk.StringVar
        self.sales_var: tk.StringVar
        self.role_var: tk.StringVar
        self.order_summary_var = tk.StringVar(value="Cart is empty")
        self.role_var = tk.StringVar(value=f"Role: {self.admin.role.value.title()}")

        self.build_ui()
        self._bind_shortcuts()
        self.refresh_order_panel()

    def _configure_theme(self) -> None:
        """Configure the standard ttk theme and shared application colors."""
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure(
            "POS.TLabel",
            background=COLORS["background"],
            foreground=COLORS["muted"],
        )

    def _bind_shortcuts(self) -> None:
        """Register keyboard shortcuts for frequent point-of-sale actions."""
        self.bind_all("<Control-Return>", lambda _event: self.checkout())
        self.bind_all("<Escape>", lambda _event: self.clear_order())
        self.bind_all("<Control-d>", lambda _event: self.apply_discount())

    def destroy(self) -> None:
        """Stop background work before closing the Tk application."""
        if self.backup_scheduler is not None:
            self.backup_scheduler.stop()
        if self.menu.store is not None:
            self.menu.store.close()
        if self.sales_report.store is not None and self.sales_report.store is not self.menu.store:
            self.sales_report.store.close()
        super().destroy()

    def build_ui(self) -> None:
        """Construct the menu, order, payment, and status controls."""
        self.root_frame = tk.Frame(self, padx=18, pady=18, bg=COLORS["background"])
        self.root_frame.pack(fill=tk.BOTH, expand=True)

        self.menu_panel = tk.Frame(self.root_frame, bg=COLORS["surface"], bd=1, relief=tk.SOLID)
        self.menu_panel.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 16))

        tk.Label(
            self.menu_panel,
            text="Menu",
            font=("Segoe UI", 18, "bold"),
            bg=COLORS["surface"],
        ).pack(pady=(12, 6))

        self.menu_buttons: list[tk.Button] = []
        self.refresh_menu_panel()

    def refresh_menu_panel(self) -> None:
        """Refresh menu buttons after administrator inventory changes."""
        for button in self.menu_buttons:
            button.destroy()
        self.menu_buttons.clear()
        for item in self.menu.list_items():
            def add_selected_item(sku: str = item.sku) -> None:
                """Add the selected menu item to the current order."""
                self.add_item_to_order(sku)

            button = tk.Button(
                self.menu_panel,
                text=f"{item.name} - ${item.price:.2f}",
                width=22,
                height=2,
                command=add_selected_item,
                bg=COLORS["primary"],
                fg=COLORS["text"],
                font=("Segoe UI", 10, "bold"),
            )
            button.pack(pady=4, padx=12, fill=tk.X)
            self.menu_buttons.append(button)

        self.order_panel = tk.Frame(self.root_frame, bg=COLORS["surface"], bd=1, relief=tk.SOLID)
        self.order_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        tk.Label(
            self.order_panel,
            text="Current Order",
            font=("Segoe UI", 18, "bold"),
            bg=COLORS["surface"],
        ).pack(pady=(12, 8))
        self.order_listbox = tk.Listbox(
            self.order_panel,
            width=48,
            height=14,
            font=("Segoe UI", 11),
        )
        self.order_listbox.pack(padx=12, fill=tk.BOTH, expand=True)

        self.summary_frame = tk.Frame(self.order_panel, bg=COLORS["surface"])
        self.summary_frame.pack(fill=tk.X, padx=12, pady=10)

        self.subtotal_var = tk.StringVar(value="Subtotal: $0.00")
        self.tax_var = tk.StringVar(value="Tax: $0.00")
        self.total_var = tk.StringVar(value="Total: $0.00")

        tk.Label(
            self.summary_frame,
            textvariable=self.subtotal_var,
            bg=COLORS["surface"],
            font=("Segoe UI", 11),
        ).pack(anchor="w")
        tk.Label(
            self.summary_frame,
            textvariable=self.tax_var,
            bg=COLORS["surface"],
            font=("Segoe UI", 11),
        ).pack(anchor="w")
        tk.Label(
            self.summary_frame,
            textvariable=self.total_var,
            bg=COLORS["surface"],
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w")

        self.controls = tk.Frame(self.order_panel, bg=COLORS["surface"])
        self.controls.pack(fill=tk.X, padx=12, pady=(8, 12))

        tk.Label(
            self.controls,
            text="Cash tendered",
            bg=COLORS["surface"],
            font=("Segoe UI", 10),
        ).grid(row=0, column=0, padx=(0, 8), sticky="w")
        self.payment_entry = tk.Entry(self.controls, width=18, font=("Segoe UI", 11))
        self.payment_entry.grid(row=0, column=1, sticky="ew")
        self.payment_entry.insert(0, "0.00")

        self.discount_button = tk.Button(
            self.controls,
            text="Apply 10% Discount",
            command=self.apply_discount,
            bg=COLORS["success"],
            fg="#113b2d",
        )
        self.discount_button.grid(row=1, column=0, pady=(10, 0), sticky="ew")

        self.clear_button = tk.Button(
            self.controls,
            text="Clear Order",
            command=self.clear_order,
            bg=COLORS["danger"],
            fg="#5d2323",
        )
        self.clear_button.grid(row=1, column=1, pady=(10, 0), sticky="ew")

        self.checkout_button = tk.Button(
            self.controls,
            text="Checkout",
            command=self.checkout,
            bg=COLORS["primary"],
            fg=COLORS["primary_text"],
            font=("Segoe UI", 10, "bold"),
        )
        self.checkout_button.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.customer_entry = tk.Entry(self.controls, width=18)
        self.customer_entry.insert(0, "")
        self.customer_entry.grid(row=3, column=0, columnspan=2, pady=(8, 0), sticky="ew")
        self.split_cash_entry = tk.Entry(self.controls, width=8)
        self.split_card_entry = tk.Entry(self.controls, width=8)
        self.split_cash_entry.insert(0, "0")
        self.split_card_entry.insert(0, "0")
        self.split_cash_entry.grid(row=4, column=0, sticky="ew")
        self.split_card_entry.grid(row=4, column=1, sticky="ew")
        tk.Button(self.controls, text="Split Cash + Card", command=self.split_checkout).grid(
            row=5, column=0, columnspan=2, sticky="ew")
        tk.Button(self.controls, text="Export CSV", command=self.export_report).grid(
            row=6, column=0, sticky="ew")
        tk.Button(
            self.controls,
            text="Receipt PDF / Kitchen Ticket",
            command=self.export_receipts,
        ).grid(row=6, column=1, sticky="ew")
        self.tax_button = tk.Button(self.controls, text="Admin: Set Tax", command=self.set_tax)
        self.tax_button.grid(
            row=7, column=0, columnspan=2, sticky="ew")
        self.add_item_button = tk.Button(
            self.controls, text="Admin: Add Item", command=self.add_menu_item)
        self.add_item_button.grid(
            row=8, column=0, sticky="ew")
        self.remove_item_button = tk.Button(
            self.controls, text="Admin: Remove Item", command=self.remove_menu_item)
        self.remove_item_button.grid(
            row=8, column=1, sticky="ew")
        ttk.Label(
            self.controls,
            textvariable=self.role_var,
            style="POS.TLabel",
        ).grid(row=9, column=0, columnspan=2, sticky="w")
        if self.admin.role == StaffRole.CASHIER:
            for button in (self.tax_button, self.add_item_button, self.remove_item_button):
                button.configure(state=tk.DISABLED)

        self.status_var = tk.StringVar(value="Ready for service.")
        self.sales_var = tk.StringVar(value="Today's sales: $0.00")
        ttk.Label(
            self.root_frame,
            textvariable=self.order_summary_var,
            style="POS.TLabel",
            anchor="w",
        ).pack(side=tk.BOTTOM, fill=tk.X, pady=(4, 0))
        tk.Label(
            self.root_frame,
            textvariable=self.sales_var,
            bg=COLORS["background"],
            fg=COLORS["muted"],
            anchor="w",
            justify="left",
            wraplength=260,
        ).pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))
        tk.Label(
            self.root_frame,
            textvariable=self.status_var,
            bg=COLORS["background"],
            fg=COLORS["muted"],
            anchor="w",
            justify="left",
            wraplength=260,
        ).pack(side=tk.BOTTOM, fill=tk.X, pady=(4, 0))

    def add_item_to_order(self, sku: str) -> None:
        """Add a selected menu item to the active order."""
        try:
            menu_item = self.menu.get_item(sku)
            self.checkout_service.add_item(self.order, sku)
            self.status_var.set(f"Added {menu_item.name} to the order.")
            self.refresh_order_panel()
        except ValueError as exc:
            messagebox.showerror("Order Error", str(exc))

    def apply_discount(self) -> None:
        """Apply the standard ten-percent order discount."""
        try:
            self.order.apply_discount(self.admin.discount_percentage)
            self.status_var.set("10% discount applied to the order.")
            self.refresh_order_panel()
        except ValueError as exc:
            messagebox.showerror("Discount Error", str(exc))

    def clear_order(self) -> None:
        """Discard the active order and refresh the display."""
        self.order.rollback()
        self.status_var.set("Order cleared.")
        self.refresh_order_panel()

    def refresh_order_panel(self) -> None:
        """Refresh displayed items, totals, and sales information."""
        self.order_listbox.delete(0, tk.END)
        if not self.order.items:
            self.order_listbox.insert(tk.END, "No items in the order.")
            self.checkout_button.configure(state=tk.DISABLED)
            self.order_summary_var.set("Cart is empty - add an item to begin")
        else:
            self.checkout_button.configure(state=tk.NORMAL)
            for item in self.order.items:
                line = f"{item.name} x{item.quantity} - ${item.line_total():.2f}"
                self.order_listbox.insert(tk.END, line)
            item_count = sum(item.quantity for item in self.order.items)
            self.order_summary_var.set(f"{item_count} item(s) in cart")

        totals = self.processor.calculate_order_total(self.order)
        self.subtotal_var.set(f"Subtotal: ${totals['subtotal']:.2f}")
        self.tax_var.set(f"Tax: ${totals['tax']:.2f}")
        self.total_var.set(f"Total: ${totals['total']:.2f}")
        self.sales_var.set(f"Today's sales: ${self.sales_report.total_revenue():.2f}")

    def checkout(self) -> None:
        """Process the entered payment and display the resulting receipt."""
        try:
            self.order.customer = self.customer_entry.get().strip()
            amount_text = self.payment_entry.get().strip()
            if not amount_text:
                raise ValueError("Enter a cash amount before checking out.")
            try:
                amount = float(amount_text)
            except ValueError as exc:
                raise ValueError("Cash amount must be a valid number.") from exc
            payment_result = self.checkout_service.checkout(self.order, amount)
            receipt_text = payment_result["receipt"]

            self.status_var.set(
                "Payment successful. Receipt generated. "
                f"Total: ${payment_result['total']:.2f}"
            )
            self.refresh_order_panel()
            messagebox.showinfo("Receipt", receipt_text)
        except (ValueError, PaymentError) as exc:
            self.status_var.set(str(exc))
            messagebox.showerror("Payment Error", str(exc))

    def set_tax(self) -> None:
        """Prompt for and apply a new tax rate."""
        value = simpledialog.askfloat("Admin Tax", "Tax rate (e.g. 0.08):",
                                      initialvalue=float(self.processor.tax_rate))
        if value is not None:
            self.admin.set_tax_rate(value)
            self.refresh_order_panel()

    def add_menu_item(self) -> None:
        """Collect and add a menu item through the administrator controls."""
        sku = simpledialog.askstring("Admin Menu", "SKU:")
        name = simpledialog.askstring("Admin Menu", "Name:")
        category = simpledialog.askstring("Admin Menu", "Category:")
        price = simpledialog.askfloat("Admin Menu", "Price:", minvalue=0)
        stock = simpledialog.askinteger("Admin Menu", "Opening stock:", minvalue=0)
        if sku is None or name is None or category is None or price is None or stock is None:
            return
        try:
            self.admin.create_menu_item(MenuItem(sku, name, category, price, stock))
            self.refresh_menu_panel()
            self.status_var.set(f"Added {name} to the menu.")
        except ValueError as exc:
            messagebox.showerror("Menu Error", str(exc))

    def remove_menu_item(self) -> None:
        """Remove a menu item by SKU through the administrator controls."""
        sku = simpledialog.askstring("Admin Menu", "SKU to remove:")
        if not sku:
            return
        try:
            self.admin.delete_menu_item(sku)
            self.refresh_menu_panel()
            self.status_var.set(f"Removed {sku} from the menu.")
        except (KeyError, ValueError) as exc:
            messagebox.showerror("Menu Error", str(exc))

    def split_checkout(self) -> None:
        """Checkout using cash and card partial tenders."""
        try:
            tenders: dict[str, float | Decimal] = {
                "cash": float(self.split_cash_entry.get() or 0),
                "card": float(self.split_card_entry.get() or 0),
            }
            result = self.checkout_service.checkout(
                self.order, 0, tenders=tenders)
            messagebox.showinfo("Receipt", result["receipt"])
            self.refresh_order_panel()
        except (ValueError, PaymentError) as exc:
            messagebox.showerror("Payment Error", str(exc))

    def export_report(self) -> None:
        """Prompt for a destination and export sales data as CSV."""
        path = filedialog.asksaveasfilename(defaultextension=".csv")
        if path:
            self.sales_report.export_csv(path)

    def export_receipts(self) -> None:
        """Save the active receipt as PDF and display its kitchen ticket."""
        if not self.order.items:
            messagebox.showinfo("Receipt", "Complete an order first.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".pdf")
        if path:
            self.order.save_pdf(path)
        messagebox.showinfo("Kitchen Ticket", self.order.kitchen_ticket())


def main() -> None:
    """Launch the QuickServe POS desktop application."""
    app = RestaurantPOSApp()
    app.mainloop()


if __name__ == "__main__":
    main()
