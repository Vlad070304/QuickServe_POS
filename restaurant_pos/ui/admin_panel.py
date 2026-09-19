"""Admin panel: tax and menu administration, role display, order history."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Iterable

from ..admin import StaffRole


class AdminPanel(ttk.Frame):
    """Administrator controls, gated by the active staff role."""

    def __init__(
        self,
        parent: tk.Widget,
        role: StaffRole,
        *,
        on_set_tax: Callable[[], None],
        on_add_item: Callable[[], None],
        on_remove_item: Callable[[], None],
        on_view_history: Callable[[], None],
    ) -> None:
        """Build the admin controls and disable restricted ones for cashiers."""
        super().__init__(parent, style="Surface.TFrame")
        self.role_var = tk.StringVar(value=f"Role: {role.value.title()}")

        self.tax_button = ttk.Button(self, text="Admin: Set Tax", command=on_set_tax)
        self.tax_button.grid(row=0, column=0, columnspan=2, sticky="ew")

        self.add_item_button = ttk.Button(self, text="Admin: Add Item", command=on_add_item)
        self.add_item_button.grid(row=1, column=0, sticky="ew")

        self.remove_item_button = ttk.Button(
            self, text="Admin: Remove Item", command=on_remove_item)
        self.remove_item_button.grid(row=1, column=1, sticky="ew")

        self.history_button = ttk.Button(
            self, text="View Order History", command=on_view_history)
        self.history_button.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 0))

        ttk.Label(self, textvariable=self.role_var, style="Small.TLabel").grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))

        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)

        self._restricted_buttons: Iterable[ttk.Button] = (
            self.tax_button, self.add_item_button, self.remove_item_button,
        )
        if role == StaffRole.CASHIER:
            self.set_admin_controls_enabled(False)

    def set_admin_controls_enabled(self, enabled: bool) -> None:
        """Enable or disable the tax/menu-maintenance controls."""
        state = tk.NORMAL if enabled else tk.DISABLED
        for button in self._restricted_buttons:
            button.configure(state=state)

    def set_role(self, role: StaffRole) -> None:
        """Update the displayed role and refresh restricted-control state."""
        self.role_var.set(f"Role: {role.value.title()}")
        self.set_admin_controls_enabled(role != StaffRole.CASHIER)
