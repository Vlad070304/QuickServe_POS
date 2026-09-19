"""Order panel: the current cart, running totals, and checkout controls."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from ..payments import Order
from .settings import AppSettings


class OrderPanel(ttk.Frame):
    """Render the active order and expose the checkout-facing controls."""

    def __init__(
        self,
        parent: tk.Widget,
        settings: AppSettings,
        *,
        on_checkout: Callable[[], None],
        on_split_checkout: Callable[[], None],
        on_clear: Callable[[], None],
        on_discount: Callable[[], None],
        on_export_csv: Callable[[], None],
        on_export_receipts: Callable[[], None],
    ) -> None:
        """Build the cart list, summary labels, and payment controls."""
        super().__init__(parent, style="Surface.TFrame")
        self._settings = settings

        ttk.Label(self, text="Current Order", style="Heading.TLabel").pack(pady=(12, 8))

        self.order_listbox = tk.Listbox(
            self, width=48, height=14, font=settings.font("body"),
            exportselection=False,
        )
        self.order_listbox.pack(padx=12, fill=tk.BOTH, expand=True)

        self._build_summary()
        self._build_controls(
            on_checkout=on_checkout,
            on_split_checkout=on_split_checkout,
            on_clear=on_clear,
            on_discount=on_discount,
            on_export_csv=on_export_csv,
            on_export_receipts=on_export_receipts,
        )

    def _build_summary(self) -> None:
        """Create the subtotal/tax/total summary labels."""
        summary_frame = ttk.Frame(self, style="Surface.TFrame")
        summary_frame.pack(fill=tk.X, padx=12, pady=10)

        self.subtotal_var = tk.StringVar(value="Subtotal: $0.00")
        self.tax_var = tk.StringVar(value="Tax: $0.00")
        self.total_var = tk.StringVar(value="Total: $0.00")

        ttk.Label(summary_frame, textvariable=self.subtotal_var,
                  style="Body.TLabel").pack(anchor="w")
        ttk.Label(summary_frame, textvariable=self.tax_var,
                  style="Body.TLabel").pack(anchor="w")
        ttk.Label(summary_frame, textvariable=self.total_var,
                  style="Total.TLabel").pack(anchor="w")

    def _build_controls(
        self, *, on_checkout, on_split_checkout, on_clear, on_discount,
        on_export_csv, on_export_receipts,
    ) -> None:
        """Create the payment entry, customer entry, and action buttons."""
        controls = ttk.Frame(self, style="Surface.TFrame")
        controls.pack(fill=tk.X, padx=12, pady=(8, 12))
        controls.columnconfigure(0, weight=1)
        controls.columnconfigure(1, weight=1)
        self.controls = controls

        ttk.Label(controls, text="Cash tendered", style="Small.TLabel").grid(
            row=0, column=0, padx=(0, 8), sticky="w")
        self.payment_entry = ttk.Entry(controls, width=18)
        self.payment_entry.grid(row=0, column=1, sticky="ew")
        self.payment_entry.insert(0, "0.00")
        # Enter on the payment field is the fast path to checkout: cashiers
        # should not have to reach for the mouse for the most common action.
        self.payment_entry.bind("<Return>", lambda _event: on_checkout())

        self.discount_button = ttk.Button(
            controls, text="Apply Discount", command=on_discount,
            style="Success.TButton")
        self.discount_button.grid(row=1, column=0, pady=(10, 0), sticky="ew")

        self.clear_button = ttk.Button(
            controls, text="Clear Order", command=on_clear, style="Danger.TButton")
        self.clear_button.grid(row=1, column=1, pady=(10, 0), sticky="ew")

        self.checkout_button = ttk.Button(
            controls, text="Checkout", command=on_checkout, style="Primary.TButton")
        self.checkout_button.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))

        ttk.Label(controls, text="Customer name", style="Small.TLabel").grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.customer_entry = ttk.Entry(controls, width=18)
        self.customer_entry.grid(row=4, column=0, columnspan=2, sticky="ew")

        ttk.Label(controls, text="Split cash / card", style="Small.TLabel").grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.split_cash_entry = ttk.Entry(controls, width=8)
        self.split_card_entry = ttk.Entry(controls, width=8)
        self.split_cash_entry.insert(0, "0")
        self.split_card_entry.insert(0, "0")
        self.split_cash_entry.grid(row=6, column=0, sticky="ew")
        self.split_card_entry.grid(row=6, column=1, sticky="ew")

        ttk.Button(controls, text="Split Cash + Card", command=on_split_checkout).grid(
            row=7, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        ttk.Button(controls, text="Export CSV", command=on_export_csv).grid(
            row=8, column=0, sticky="ew", pady=(4, 0))
        ttk.Button(controls, text="Receipt PDF / Kitchen Ticket",
                   command=on_export_receipts).grid(row=8, column=1, sticky="ew", pady=(4, 0))

    def refresh(self, order: Order, totals: dict) -> str:
        """Redraw the cart and totals; return a one-line order summary."""
        self.order_listbox.delete(0, tk.END)
        if not order.items:
            self.order_listbox.insert(tk.END, "No items in the order.")
            self.checkout_button.configure(state=tk.DISABLED)
            summary = "Cart is empty - add an item to begin"
        else:
            self.checkout_button.configure(state=tk.NORMAL)
            for item in order.items:
                line = f"{item.name} x{item.quantity} - ${item.line_total():.2f}"
                self.order_listbox.insert(tk.END, line)
            item_count = sum(item.quantity for item in order.items)
            summary = f"{item_count} item(s) in cart"

        self.subtotal_var.set(f"Subtotal: ${totals['subtotal']:.2f}")
        self.tax_var.set(f"Tax: ${totals['tax']:.2f}")
        self.total_var.set(f"Total: ${totals['total']:.2f}")
        return summary
