"""Order history screen: search and review past orders."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from ..reporting import SalesReport


def _order_row(record: Any) -> tuple[str, str, str, str]:
    """Normalize a persisted row or an in-memory Order into display columns."""
    if isinstance(record, dict) or hasattr(record, "keys"):
        return (
            str(record["order_number"]),
            str(record["customer"] or ""),
            str(record["created_at"])[:19],
            f"${float(record['total']):.2f}",
        )
    total = record.calculate_totals()["total"]
    return (
        record.order_number,
        record.customer or "",
        str(record.created_at)[:19],
        f"${total:.2f}",
    )


class OrderHistoryWindow(tk.Toplevel):
    """A standalone window for browsing and searching completed orders."""

    def __init__(self, parent: tk.Misc, sales_report: SalesReport) -> None:
        """Build the search box and results table, then load recent orders."""
        super().__init__(parent)
        self.title("Order History")
        self.geometry("640x420")
        self.transient(parent.winfo_toplevel())
        self._sales_report = sales_report

        search_bar = ttk.Frame(self)
        search_bar.pack(fill=tk.X, padx=12, pady=(12, 6))
        ttk.Label(search_bar, text="Search:").pack(side=tk.LEFT, padx=(0, 8))
        self.search_entry = ttk.Entry(search_bar)
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.search_entry.bind("<Return>", lambda _event: self.refresh())
        self.search_entry.focus_set()
        ttk.Button(search_bar, text="Search", command=self.refresh).pack(
            side=tk.LEFT, padx=(8, 0))

        columns = ("order", "customer", "created_at", "total")
        self.tree = ttk.Treeview(self, columns=columns, show="headings")
        for column, heading in zip(columns, ("Order #", "Customer", "Created", "Total")):
            self.tree.heading(column, text=heading)
        self.tree.column("order", width=110)
        self.tree.column("customer", width=140)
        self.tree.column("created_at", width=170)
        self.tree.column("total", width=90, anchor="e")
        self.tree.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))

        self.refresh()

    def refresh(self) -> None:
        """Reload results using the current search box contents."""
        query = self.search_entry.get().strip()
        for row_id in self.tree.get_children():
            self.tree.delete(row_id)
        for record in self._sales_report.search_history(query):
            self.tree.insert("", tk.END, values=_order_row(record))
