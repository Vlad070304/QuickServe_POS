"""Status bar: cart summary, sales total, and free-text status messages."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .settings import AppSettings


class StatusBar(ttk.Frame):
    """Bottom status strip, safe to update from background threads."""

    def __init__(self, parent: tk.Widget, settings: AppSettings) -> None:
        """Create the status, sales, and cart-summary display labels."""
        super().__init__(parent)
        self._root = parent.winfo_toplevel()
        self.settings = settings

        self.order_summary_var = tk.StringVar(value="Cart is empty")
        self.sales_var = tk.StringVar(value="Today's sales: $0.00")
        self.status_var = tk.StringVar(value="Ready for service.")

        ttk.Label(self, textvariable=self.order_summary_var, style="Body.TLabel",
                  anchor="w").pack(fill=tk.X, pady=(4, 0))
        ttk.Label(self, textvariable=self.sales_var, style="Muted.TLabel",
                  anchor="w", justify="left", wraplength=280).pack(
                      fill=tk.X, pady=(10, 0))
        ttk.Label(self, textvariable=self.status_var, style="Muted.TLabel",
                  anchor="w", justify="left", wraplength=280).pack(
                      fill=tk.X, pady=(4, 0))

    def set_status(self, message: str) -> None:
        """Set the status message. Safe to call from the Tk main thread only."""
        self.status_var.set(message)

    def report_error_threadsafe(self, message: str) -> None:
        """Update the status message from any thread via the Tk event loop.

        Tkinter variables are not thread-safe, so a background worker (for
        example the sales backup scheduler) must never touch ``status_var``
        directly. Scheduling the update through ``after`` hands it back to
        the main thread's event loop instead.
        """
        self._root.after(0, self.set_status, message)
