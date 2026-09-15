"""Tkinter-based restaurant POS application."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox

from .menu import build_demo_menu
from .payments import Order, OrderItem, PaymentError, PaymentProcessor
from .reporting import SalesReport


class RestaurantPOSApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("QuickServe POS")
        self.geometry("980x620")
        self.configure(bg="#f4f7fb")

        self.menu = build_demo_menu()
        self.order = Order()
        self.processor = PaymentProcessor(tax_rate=0.08)
        self.sales_report = SalesReport()

        self.build_ui()
        self.refresh_order_panel()

    def build_ui(self) -> None:
        self.frame = tk.Frame(self, padx=18, pady=18, bg="#f4f7fb")
        self.frame.pack(fill=tk.BOTH, expand=True)

        self.menu_panel = tk.Frame(self.frame, bg="#ffffff", bd=1, relief=tk.SOLID)
        self.menu_panel.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 16))

        tk.Label(self.menu_panel, text="Menu", font=("Segoe UI", 18, "bold"), bg="#ffffff").pack(pady=(12, 6))

        self.menu_buttons = []
        for item in self.menu.list_items():
            button = tk.Button(
                self.menu_panel,
                text=f"{item.name} - ${item.price:.2f}",
                width=22,
                height=2,
                command=lambda sku=item.sku: self.add_item_to_order(sku),
                bg="#dfeaff",
                fg="#183153",
                font=("Segoe UI", 10, "bold"),
            )
            button.pack(pady=4, padx=12, fill=tk.X)
            self.menu_buttons.append(button)

        self.order_panel = tk.Frame(self.frame, bg="#ffffff", bd=1, relief=tk.SOLID)
        self.order_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        tk.Label(self.order_panel, text="Current Order", font=("Segoe UI", 18, "bold"), bg="#ffffff").pack(pady=(12, 8))
        self.order_listbox = tk.Listbox(self.order_panel, width=48, height=14, font=("Segoe UI", 11))
        self.order_listbox.pack(padx=12, fill=tk.BOTH, expand=True)

        self.summary_frame = tk.Frame(self.order_panel, bg="#ffffff")
        self.summary_frame.pack(fill=tk.X, padx=12, pady=10)

        self.subtotal_var = tk.StringVar(value="Subtotal: $0.00")
        self.tax_var = tk.StringVar(value="Tax: $0.00")
        self.total_var = tk.StringVar(value="Total: $0.00")

        tk.Label(self.summary_frame, textvariable=self.subtotal_var, bg="#ffffff", font=("Segoe UI", 11)).pack(anchor="w")
        tk.Label(self.summary_frame, textvariable=self.tax_var, bg="#ffffff", font=("Segoe UI", 11)).pack(anchor="w")
        tk.Label(self.summary_frame, textvariable=self.total_var, bg="#ffffff", font=("Segoe UI", 11, "bold")).pack(anchor="w")

        self.controls = tk.Frame(self.order_panel, bg="#ffffff")
        self.controls.pack(fill=tk.X, padx=12, pady=(8, 12))

        tk.Label(self.controls, text="Cash tendered", bg="#ffffff", font=("Segoe UI", 10)).grid(row=0, column=0, padx=(0, 8), sticky="w")
        self.payment_entry = tk.Entry(self.controls, width=18, font=("Segoe UI", 11))
        self.payment_entry.grid(row=0, column=1, sticky="ew")
        self.payment_entry.insert(0, "0.00")

        self.discount_button = tk.Button(self.controls, text="Apply 10% Discount", command=self.apply_discount, bg="#d9f7e8", fg="#113b2d")
        self.discount_button.grid(row=1, column=0, pady=(10, 0), sticky="ew")

        self.clear_button = tk.Button(self.controls, text="Clear Order", command=self.clear_order, bg="#fbe8e8", fg="#5d2323")
        self.clear_button.grid(row=1, column=1, pady=(10, 0), sticky="ew")

        self.checkout_button = tk.Button(self.controls, text="Checkout", command=self.checkout, bg="#cfe8ff", fg="#143050", font=("Segoe UI", 10, "bold"))
        self.checkout_button.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))

        self.status_var = tk.StringVar(value="Ready for service.")
        self.sales_var = tk.StringVar(value="Today's sales: $0.00")
        tk.Label(self.frame, textvariable=self.sales_var, bg="#f4f7fb", fg="#314f74", anchor="w", justify="left", wraplength=260).pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))
        tk.Label(self.frame, textvariable=self.status_var, bg="#f4f7fb", fg="#314f74", anchor="w", justify="left", wraplength=260).pack(side=tk.BOTTOM, fill=tk.X, pady=(4, 0))

    def add_item_to_order(self, sku: str) -> None:
        try:
            menu_item = self.menu.get_item(sku)
            self.order.add_item(menu_item, quantity=1)
            self.status_var.set(f"Added {menu_item.name} to the order.")
            self.refresh_order_panel()
        except ValueError as exc:
            messagebox.showerror("Order Error", str(exc))

    def apply_discount(self) -> None:
        try:
            self.order.apply_discount(10)
            self.status_var.set("10% discount applied to the order.")
            self.refresh_order_panel()
        except ValueError as exc:
            messagebox.showerror("Discount Error", str(exc))

    def clear_order(self) -> None:
        self.order.rollback()
        self.status_var.set("Order cleared.")
        self.refresh_order_panel()

    def refresh_order_panel(self) -> None:
        self.order_listbox.delete(0, tk.END)
        if not self.order.items:
            self.order_listbox.insert(tk.END, "No items in the order.")
        else:
            for item in self.order.items:
                self.order_listbox.insert(tk.END, f"{item.name} x{item.quantity} - ${item.line_total():.2f}")

        totals = self.processor.calculate_order_total(self.order)
        self.subtotal_var.set(f"Subtotal: ${totals['subtotal']:.2f}")
        self.tax_var.set(f"Tax: ${totals['tax']:.2f}")
        self.total_var.set(f"Total: ${totals['total']:.2f}")
        self.sales_var.set(f"Today's sales: ${self.sales_report.total_revenue():.2f}")

    def checkout(self) -> None:
        try:
            amount = float(self.payment_entry.get())
            payment_result = self.processor.process_payment(self.order, amount)
            receipt_text = payment_result["receipt"]

            report_order = Order(tax_rate=self.order.tax_rate)
            for item in self.order.items:
                report_order.items.append(
                    OrderItem(
                        sku=item.sku,
                        name=item.name,
                        quantity=item.quantity,
                        unit_price=item.unit_price,
                    )
                )
            self.sales_report.add_order(report_order)

            self.status_var.set(f"Payment successful. Receipt generated. Total: ${payment_result['total']:.2f}")
            self.order.rollback()
            self.refresh_order_panel()
            messagebox.showinfo("Receipt", receipt_text)
        except (ValueError, PaymentError) as exc:
            self.status_var.set(str(exc))
            messagebox.showerror("Payment Error", str(exc))


def main() -> None:
    app = RestaurantPOSApp()
    app.mainloop()


if __name__ == "__main__":
    main()
