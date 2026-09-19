"""Menu panel: renders one button per menu item with stock indicators."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, List

from ..menu import MenuItem
from .settings import AppSettings


class MenuPanel(ttk.Frame):
    """Display menu items as buttons and report selections to the caller."""

    def __init__(
        self,
        parent: tk.Widget,
        settings: AppSettings,
        on_select: Callable[[str], None],
    ) -> None:
        """Create the panel; ``on_select`` is called with the chosen SKU."""
        super().__init__(parent, style="Surface.TFrame")
        self._settings = settings
        self._on_select = on_select
        self.buttons: List[ttk.Button] = []

        ttk.Label(self, text="Menu", style="Heading.TLabel").pack(pady=(12, 6))

        self._button_area = ttk.Frame(self, style="Surface.TFrame")
        self._button_area.pack(fill=tk.BOTH, expand=True)

    def refresh(self, items: List[MenuItem]) -> None:
        """Rebuild the button list from the current menu state."""
        for button in self.buttons:
            button.destroy()
        self.buttons.clear()

        for item in items:
            button = self._build_button(item)
            button.pack(pady=4, padx=12, fill=tk.X)
            self.buttons.append(button)

        if self.buttons:
            # Keyboard users land on a sensible first control instead of
            # having focus stuck on whatever widget built last.
            self.buttons[0].focus_set()

    def _build_button(self, item: MenuItem) -> ttk.Button:
        """Build a single menu button, applying stock-aware styling."""
        def add_selected_item(sku: str = item.sku) -> None:
            self._on_select(sku)

        style, label = self._stock_presentation(item)
        button = ttk.Button(
            self._button_area,
            text=label,
            width=26,
            style=style,
            command=add_selected_item,
        )
        if item.stock <= 0:
            button.configure(state=tk.DISABLED)
        return button

    def _stock_presentation(self, item: MenuItem) -> tuple[str, str]:
        """Return the ttk style and label text reflecting current stock."""
        base = f"{item.name} - ${item.price:.2f}"
        if item.stock <= 0:
            return "OutOfStock.Menu.TButton", f"{base} (Out of stock)"
        if item.stock <= self._settings.low_stock_threshold:
            return "LowStock.Menu.TButton", f"{base}  \u26a0 Only {item.stock} left"
        return "Menu.TButton", base
