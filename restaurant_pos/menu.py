"""Menu management for the POS system."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
from pathlib import Path
from .storage import SQLiteStore


@dataclass(frozen=True)
class MenuItem:
    """Describe a menu item and its available stock."""

    sku: str
    name: str
    category: str
    price: float
    stock: int = 0

    def __post_init__(self) -> None:
        """Validate the item's price and stock values."""
        if self.price < 0:
            raise ValueError("Price cannot be negative.")
        if self.stock < 0:
            raise ValueError("Stock cannot be negative.")


class Menu:
    """Simple in-memory menu registry."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        """Create an empty menu registry."""
        self._items: Dict[str, MenuItem] = {}
        self.store = SQLiteStore(db_path) if db_path else None
        if self.store:
            for row in self.store.load_menu_items():
                self._items[row["sku"]] = MenuItem(
                    row["sku"], row["name"], row["category"], row["price"], row["stock"]
                )

    def add_item(self, item: MenuItem) -> None:
        """Add a menu item, rejecting duplicate SKUs."""
        if item.sku in self._items:
            raise ValueError(f"Menu item with sku '{item.sku}' already exists.")
        self._items[item.sku] = item
        if self.store:
            self.store.save_menu_item(item.sku, item.name, item.category, item.price, item.stock)

    def get_item(self, sku: str) -> MenuItem:
        """Return the menu item for a SKU or raise an error."""
        item = self._items.get(sku)
        if item is None:
            raise KeyError(f"Invalid menu item: {sku}")
        return item

    def list_items(self) -> List[MenuItem]:
        """Return menu items sorted alphabetically by name."""
        return sorted(self._items.values(), key=lambda item: item.name)

    def update_stock(self, sku: str, quantity: int) -> None:
        """Adjust stock for a menu item by the requested quantity."""
        item = self.get_item(sku)
        new_stock = item.stock + quantity
        if new_stock < 0:
            raise ValueError(f"Not enough stock for menu item: {sku}")
        self._items[sku] = MenuItem(
            sku=item.sku,
            name=item.name,
            category=item.category,
            price=item.price,
            stock=new_stock,
        )
        if self.store:
            updated = self._items[sku]
            self.store.save_menu_item(updated.sku, updated.name, updated.category,
                                      updated.price, updated.stock)

    def update_item(self, sku: str, **changes) -> MenuItem:
        """Update administrator-controlled menu fields and persist them."""
        item = self.get_item(sku)
        updated = MenuItem(sku, changes.get("name", item.name),
                           changes.get("category", item.category),
                           changes.get("price", item.price),
                           changes.get("stock", item.stock))
        self._items[sku] = updated
        if self.store:
            self.store.save_menu_item(updated.sku, updated.name, updated.category,
                                      updated.price, updated.stock)
        return updated

    def remove_item(self, sku: str) -> None:
        """Remove a menu item if it exists."""
        self._items.pop(sku, None)
        if self.store:
            self.store.delete_menu_item(sku)

    def clear(self) -> None:
        """Remove all menu items."""
        self._items.clear()
        if self.store:
            self.store.clear_menu()


def build_demo_menu() -> Menu:
    """Build the sample menu used by the desktop application."""
    menu = Menu()
    menu.add_item(MenuItem("BURGER", "Classic Burger", "Main", 12.00, stock=25))
    menu.add_item(MenuItem("FRIES", "Sweet Potato Fries", "Sides", 4.50, stock=30))
    menu.add_item(MenuItem("SODA", "House Soda", "Drinks", 2.50, stock=50))
    menu.add_item(MenuItem("PASTA", "Chef Pasta", "Main", 15.00, stock=20))
    menu.add_item(MenuItem("SALAD", "Garden Salad", "Starter", 8.00, stock=18))
    return menu
