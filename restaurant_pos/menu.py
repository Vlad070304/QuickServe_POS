"""Menu management for the POS system."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class MenuItem:
    sku: str
    name: str
    category: str
    price: float
    stock: int = 0

    def __post_init__(self) -> None:
        if self.price < 0:
            raise ValueError("Price cannot be negative.")
        if self.stock < 0:
            raise ValueError("Stock cannot be negative.")


class Menu:
    """Simple in-memory menu registry."""

    def __init__(self) -> None:
        self._items: Dict[str, MenuItem] = {}

    def add_item(self, item: MenuItem) -> None:
        if item.sku in self._items:
            raise ValueError(f"Menu item with sku '{item.sku}' already exists.")
        self._items[item.sku] = item

    def get_item(self, sku: str) -> MenuItem:
        item = self._items.get(sku)
        if item is None:
            raise KeyError(f"Invalid menu item: {sku}")
        return item

    def list_items(self) -> List[MenuItem]:
        return sorted(self._items.values(), key=lambda item: item.name)

    def update_stock(self, sku: str, quantity: int) -> None:
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

    def remove_item(self, sku: str) -> None:
        self._items.pop(sku, None)

    def clear(self) -> None:
        self._items.clear()


def build_demo_menu() -> Menu:
    menu = Menu()
    menu.add_item(MenuItem("BURGER", "Classic Burger", "Main", 12.00, stock=25))
    menu.add_item(MenuItem("FRIES", "Sweet Potato Fries", "Sides", 4.50, stock=30))
    menu.add_item(MenuItem("SODA", "House Soda", "Drinks", 2.50, stock=50))
    menu.add_item(MenuItem("PASTA", "Chef Pasta", "Main", 15.00, stock=20))
    menu.add_item(MenuItem("SALAD", "Garden Salad", "Starter", 8.00, stock=18))
    return menu
