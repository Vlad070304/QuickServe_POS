"""Small SQLite persistence layer used by the POS domain services."""
from __future__ import annotations

import sqlite3
import json
from pathlib import Path
from typing import Iterable


class SQLiteStore:
    """Persist menu inventory and completed orders in a local SQLite database."""

    def __init__(self, path: str | Path = "quickserve.db") -> None:
        self.path = str(path)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS menu_items (
              sku TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL,
              price REAL NOT NULL, stock INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS orders (
              id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
              order_number TEXT, customer TEXT,
              subtotal TEXT NOT NULL, tax TEXT NOT NULL, discount TEXT NOT NULL,
              total TEXT NOT NULL, payment_json TEXT NOT NULL, receipt TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS order_items (
              order_id INTEGER NOT NULL REFERENCES orders(id),
              sku TEXT NOT NULL, name TEXT NOT NULL, quantity INTEGER NOT NULL,
              unit_price TEXT NOT NULL
            );
            """
        )
        for column, definition in (("order_number", "TEXT"), ("customer", "TEXT")):
            try:
                self.connection.execute(f"ALTER TABLE orders ADD COLUMN {column} {definition}")
            except sqlite3.OperationalError:
                pass
        self.connection.commit()

    def save_menu_item(self, sku: str, name: str, category: str, price: float, stock: int) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO menu_items VALUES (?, ?, ?, ?, ?)",
            (sku, name, category, price, stock),
        )
        self.connection.commit()

    def load_menu_items(self) -> list[sqlite3.Row]:
        return list(self.connection.execute("SELECT * FROM menu_items ORDER BY name"))

    def delete_menu_item(self, sku: str) -> None:
        self.connection.execute("DELETE FROM menu_items WHERE sku = ?", (sku,))
        self.connection.commit()

    def save_order(self, order, payments: Iterable[dict] = ()) -> int:
        totals = order.calculate_totals()
        cursor = self.connection.execute(
            "INSERT INTO orders(subtotal,tax,discount,total,payment_json,receipt,order_number,customer,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (str(totals["subtotal"]), str(totals["tax"]), str(totals["discount_amount"]),
             str(totals["total"]), json.dumps(list(payments), default=str), order.receipt(),
             order.order_number, order.customer, order.created_at.isoformat()),
        )
        if cursor.lastrowid is None:
            raise RuntimeError("SQLite did not return an order ID.")
        order_id = cursor.lastrowid
        self.connection.executemany(
            "INSERT INTO order_items VALUES (?,?,?,?,?)",
            [(order_id, item.sku, item.name, item.quantity, str(item.unit_price))
             for item in order.items],
        )
        self.connection.commit()
        return order_id

    def search_orders(self, query: str = "", on_date: str | None = None) -> list[sqlite3.Row]:
        pattern = f"%{query}%"
        return list(self.connection.execute(
            """SELECT DISTINCT o.* FROM orders o JOIN order_items i ON i.order_id=o.id
               WHERE (? = '' OR i.name LIKE ? OR i.sku LIKE ?
                 OR o.order_number LIKE ? OR o.customer LIKE ?)
                 AND (? IS NULL OR date(o.created_at) = ?)
               ORDER BY o.id DESC""",
            (query, pattern, pattern, pattern, pattern, on_date, on_date),
        ))

    def close(self) -> None:
        self.connection.close()
