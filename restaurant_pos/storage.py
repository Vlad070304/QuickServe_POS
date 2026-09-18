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
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA busy_timeout = 5000")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
              version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS menu_items (
              sku TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL,
              price REAL NOT NULL, stock INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS orders (
              id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
              order_number TEXT UNIQUE, customer TEXT,
              subtotal TEXT NOT NULL, tax TEXT NOT NULL, discount TEXT NOT NULL,
              total TEXT NOT NULL, payment_json TEXT NOT NULL, receipt TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS order_items (
              order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
              sku TEXT NOT NULL, name TEXT NOT NULL, quantity INTEGER NOT NULL,
              unit_price TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS refunds (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              order_number TEXT NOT NULL REFERENCES orders(order_number),
              amount TEXT NOT NULL,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS settings (
              key TEXT PRIMARY KEY, value TEXT NOT NULL
            );
            """
        )
        self._run_migrations()
        self.connection.commit()

    def _run_migrations(self) -> None:
        """Apply schema changes in order so upgrades are explicit and repeatable."""
        applied = {
            row["version"]
            for row in self.connection.execute("SELECT version FROM schema_migrations")
        }
        if 1 not in applied:
            columns = {
                row["name"]
                for row in self.connection.execute("PRAGMA table_info(orders)")
            }
            for column in ("order_number", "customer"):
                if column not in columns:
                    self.connection.execute(f"ALTER TABLE orders ADD COLUMN {column} TEXT")
            duplicates = self.connection.execute(
                """SELECT order_number FROM orders
                   WHERE order_number IS NOT NULL
                   GROUP BY order_number HAVING COUNT(*) > 1"""
            ).fetchall()
            for duplicate in duplicates:
                rows = self.connection.execute(
                    "SELECT id FROM orders WHERE order_number = ? ORDER BY id",
                    (duplicate["order_number"],),
                ).fetchall()
                for row in rows[1:]:
                    self.connection.execute(
                        "UPDATE orders SET order_number = ? WHERE id = ?",
                        (f"{duplicate['order_number']}-{row['id']}", row["id"]),
                    )
            self.connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_orders_order_number "
                "ON orders(order_number)"
            )
            self.connection.execute(
                "CREATE INDEX IF NOT EXISTS ix_orders_created_at ON orders(created_at)"
            )
            self.connection.execute(
                "CREATE INDEX IF NOT EXISTS ix_orders_customer ON orders(customer)"
            )
            self.connection.execute(
                "CREATE INDEX IF NOT EXISTS ix_order_items_sku ON order_items(sku)"
            )
            self.connection.execute(
                "INSERT INTO schema_migrations(version) VALUES (1)"
            )

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
        with self.connection:
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
        return order_id

    def complete_checkout(self, order, payments: Iterable[dict] = ()) -> None:
        """Atomically decrement inventory and persist a paid order."""
        totals = order.calculate_totals()
        with self.connection:
            for item in order.items:
                updated = self.connection.execute(
                    "UPDATE menu_items SET stock = stock - ? "
                    "WHERE sku = ? AND stock >= ?",
                    (item.quantity, item.sku, item.quantity),
                )
                if updated.rowcount != 1:
                    raise ValueError(f"Not enough stock for menu item: {item.sku}")
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
            self.connection.executemany(
                "INSERT INTO order_items VALUES (?,?,?,?,?)",
                [(cursor.lastrowid, item.sku, item.name, item.quantity, str(item.unit_price))
                 for item in order.items],
            )

    def set_setting(self, key: str, value: str) -> None:
        """Persist an application setting."""
        with self.connection:
            self.connection.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        """Return a persisted setting or its supplied default."""
        row = self.connection.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def save_refund(self, order_number: str, amount) -> None:
        """Persist a refund against an existing order."""
        with self.connection:
            self.connection.execute(
                "INSERT INTO refunds(order_number, amount) VALUES (?, ?)",
                (order_number, str(amount)),
            )

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
