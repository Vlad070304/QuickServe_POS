"""Small SQLite persistence layer used by the POS domain services."""
from __future__ import annotations

import sqlite3
import json
import csv
from pathlib import Path
from typing import Iterable


class SQLiteStore:
    """Persist menu inventory and completed orders in a local SQLite database."""

    def __init__(self, path: str | Path = "quickserve.db") -> None:
        """Open or create a SQLite database and initialize its schema."""
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
        """Insert or replace one menu item."""
        self.connection.execute(
            "INSERT OR REPLACE INTO menu_items VALUES (?, ?, ?, ?, ?)",
            (sku, name, category, price, stock),
        )
        self.connection.commit()

    def load_menu_items(self) -> list[sqlite3.Row]:
        """Return all menu items ordered by display name."""
        return list(self.connection.execute("SELECT * FROM menu_items ORDER BY name"))

    def delete_menu_item(self, sku: str) -> None:
        """Delete a menu item by SKU."""
        self.connection.execute("DELETE FROM menu_items WHERE sku = ?", (sku,))
        self.connection.commit()

    def clear_menu(self) -> None:
        """Remove all menu rows from persistent storage."""
        self.connection.execute("DELETE FROM menu_items")
        self.connection.commit()

    def save_order(self, order, payments: Iterable[dict] = ()) -> int:
        """Persist an order and its line items, returning the database ID."""
        totals = order.calculate_totals()
        cursor = self.connection.execute(
            "INSERT INTO orders("
            "subtotal,tax,discount,total,payment_json,receipt,"
            "order_number,customer,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
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
        """Search persisted orders by text and optional calendar date."""
        pattern = f"%{query}%"
        return list(self.connection.execute(
            """SELECT DISTINCT o.* FROM orders o JOIN order_items i ON i.order_id=o.id
               WHERE (? = '' OR i.name LIKE ? OR i.sku LIKE ?
                 OR o.order_number LIKE ? OR o.customer LIKE ?)
                 AND (? IS NULL OR date(o.created_at) = ?)
               ORDER BY o.id DESC""",
            (query, pattern, pattern, pattern, pattern, on_date, on_date),
        ))

    def export_menu_csv(self, path: str | Path) -> None:
        """Write the current menu to a portable CSV file."""
        rows = self.load_menu_items()
        target = Path(path)
        with target.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["sku", "name", "category", "price", "stock"])
            writer.writerows((row["sku"], row["name"], row["category"], row["price"], row["stock"])
                            for row in rows)

    def import_menu_csv(self, path: str | Path, *, replace: bool = False) -> int:
        """Import validated menu rows, returning the number of rows applied."""
        with Path(path).open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            required = {"sku", "name", "category", "price", "stock"}
            if reader.fieldnames is None or not required.issubset(reader.fieldnames):
                raise ValueError(
                    "Menu CSV must contain sku, name, category, price, and stock columns."
                )
            rows = list(reader)
        parsed = []
        for row in rows:
            try:
                sku, name, category = (row[key].strip() for key in ("sku", "name", "category"))
                price, stock = float(row["price"]), int(row["stock"])
            except (AttributeError, TypeError, ValueError, KeyError) as exc:
                raise ValueError("Menu CSV contains an invalid row.") from exc
            if not sku or not name or not category or price < 0 or stock < 0:
                raise ValueError("Menu CSV contains an invalid row.")
            parsed.append((sku, name, category, price, stock))
        with self.connection:
            if replace:
                self.connection.execute("DELETE FROM menu_items")
            self.connection.executemany(
                "INSERT OR REPLACE INTO menu_items("
                "sku,name,category,price,stock) VALUES (?,?,?,?,?)",
                parsed,
            )
        return len(parsed)

    def export_sales_csv(self, path: str | Path) -> None:
        """Export completed sales and their line items as a portable CSV file."""
        rows = self.connection.execute(
            """SELECT o.order_number, o.created_at, o.customer, i.sku, i.name,
                      i.quantity, i.unit_price, o.subtotal, o.tax, o.discount, o.total
               FROM orders o JOIN order_items i ON i.order_id=o.id ORDER BY o.id, i.rowid"""
        )
        with Path(path).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["order_number", "created_at", "customer", "sku", "name",
                             "quantity", "unit_price", "subtotal", "tax", "discount", "total"])
            writer.writerows(tuple(row) for row in rows)

    def import_sales_csv(self, path: str | Path) -> int:
        """Import sales CSV rows and return the number of orders restored."""
        with Path(path).open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            required = {"order_number", "created_at", "customer", "sku", "name",
                        "quantity", "unit_price", "subtotal", "tax", "discount", "total"}
            if reader.fieldnames is None or not required.issubset(reader.fieldnames):
                raise ValueError("Sales CSV is missing required columns.")
            rows = list(reader)
        grouped: dict[str, list[dict[str, str]]] = {}
        for row in rows:
            try:
                if not row["order_number"].strip() or int(row["quantity"]) <= 0:
                    raise ValueError
                float(row["unit_price"])
                for key in ("subtotal", "tax", "discount", "total"):
                    float(row[key])
            except (AttributeError, TypeError, ValueError, KeyError) as exc:
                raise ValueError("Sales CSV contains an invalid row.") from exc
            grouped.setdefault(row["order_number"], []).append(row)
        with self.connection:
            for order_number, order_rows in grouped.items():
                first = order_rows[0]
                cursor = self.connection.execute(
                    """INSERT INTO orders(order_number,customer,subtotal,tax,discount,total,
                       payment_json,receipt,created_at) VALUES (?,?,?,?,?,?,?,?,?)""",
                    (order_number, first["customer"], first["subtotal"], first["tax"],
                     first["discount"], first["total"], "[]", "Imported sale",
                     first["created_at"]),
                )
                order_id = cursor.lastrowid
                if order_id is None:
                    raise RuntimeError("SQLite did not return an order ID.")
                self.connection.executemany(
                    "INSERT INTO order_items VALUES (?,?,?,?,?)",
                    [(order_id, row["sku"], row["name"], int(row["quantity"]), row["unit_price"])
                     for row in order_rows],
                )
        return len(grouped)

    def backup_to(self, path: str | Path) -> None:
        """Create a consistent SQLite backup without copying a live file."""
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.resolve() == Path(self.path).resolve():
            raise ValueError("Backup destination must differ from the active database.")
        backup = sqlite3.connect(destination)
        try:
            self.connection.backup(backup)
        finally:
            backup.close()

    def close(self) -> None:
        """Close the database connection."""
        self.connection.close()
