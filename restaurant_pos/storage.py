"""Small SQLite persistence layer used by the POS domain services."""
from __future__ import annotations

import csv
import hashlib
import hmac
import json
import secrets
import sqlite3
import time
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
              payment_id INTEGER,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS payments (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              order_number TEXT NOT NULL REFERENCES orders(order_number),
              method TEXT NOT NULL, amount TEXT NOT NULL,
              status TEXT NOT NULL, authorization_reference TEXT,
              idempotency_key TEXT UNIQUE,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS settings (
              key TEXT PRIMARY KEY, value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS staff_users (
              username TEXT PRIMARY KEY, password_hash TEXT NOT NULL,
              role TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS staff_sessions (
              token_hash TEXT PRIMARY KEY, username TEXT NOT NULL
                REFERENCES staff_users(username) ON DELETE CASCADE,
              expires_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit_log (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              username TEXT NOT NULL, action TEXT NOT NULL,
              details TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS ix_audit_log_created_at ON audit_log(created_at);
            """
        )
        self._run_migrations()
        self._ensure_order_lifecycle_columns()
        self._ensure_refund_columns()
        self.connection.commit()

    def _ensure_order_lifecycle_columns(self) -> None:
        """Add payment lifecycle columns to databases created by older versions."""
        columns = {
            row["name"] for row in self.connection.execute("PRAGMA table_info(orders)")
        }
        if "payment_status" not in columns:
            self.connection.execute(
                "ALTER TABLE orders ADD COLUMN payment_status TEXT NOT NULL DEFAULT 'paid'"
            )
        if "idempotency_key" not in columns:
            self.connection.execute("ALTER TABLE orders ADD COLUMN idempotency_key TEXT")
            self.connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_orders_idempotency "
                "ON orders(idempotency_key) WHERE idempotency_key IS NOT NULL"
            )

    def _ensure_refund_columns(self) -> None:
        """Add payment linkage to refund records created by older versions."""
        columns = {
            row["name"] for row in self.connection.execute("PRAGMA table_info(refunds)")
        }
        if "payment_id" not in columns:
            self.connection.execute("ALTER TABLE refunds ADD COLUMN payment_id INTEGER")

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

    def save_order(
        self, order, payments: Iterable[dict] = (), *, idempotency_key: str | None = None,
        status: str = "paid",
    ) -> int:
        """Persist an order and its line items, returning the database ID."""
        totals = order.calculate_totals()
        payment_records = list(payments)
        with self.connection:
            cursor = self.connection.execute(
                "INSERT INTO orders("
                "subtotal,tax,discount,total,payment_json,receipt,"
                "order_number,customer,created_at,payment_status,idempotency_key) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (str(totals["subtotal"]), str(totals["tax"]), str(totals["discount_amount"]),
                 str(totals["total"]), json.dumps(payment_records, default=str), order.receipt(),
                 order.order_number, order.customer, order.created_at.isoformat(),
                 status, idempotency_key),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("SQLite did not return an order ID.")
            order_id = cursor.lastrowid
            self.connection.executemany(
                "INSERT INTO order_items VALUES (?,?,?,?,?)",
                [(order_id, item.sku, item.name, item.quantity, str(item.unit_price))
                 for item in order.items],
            )
            self._save_payments(order.order_number, payment_records, status, idempotency_key)
        return order_id

    def complete_checkout(
        self, order, payments: Iterable[dict] = (), *,
        idempotency_key: str | None = None, status: str = "paid",
    ) -> None:
        """Atomically decrement inventory and persist a paid order."""
        totals = order.calculate_totals()
        payment_records = list(payments)
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
                "order_number,customer,created_at,payment_status,idempotency_key) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (str(totals["subtotal"]), str(totals["tax"]), str(totals["discount_amount"]),
                 str(totals["total"]), json.dumps(payment_records, default=str), order.receipt(),
                 order.order_number, order.customer, order.created_at.isoformat(),
                 status, idempotency_key),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("SQLite did not return an order ID.")
            self.connection.executemany(
                "INSERT INTO order_items VALUES (?,?,?,?,?)",
                [(cursor.lastrowid, item.sku, item.name, item.quantity, str(item.unit_price))
                 for item in order.items],
            )
            self._save_payments(order.order_number, payment_records, status, idempotency_key)

    def _save_payments(
        self, order_number: str, payments: Iterable[dict], status: str,
        idempotency_key: str | None,
    ) -> None:
        """Persist each tender as an individual payment record."""
        for payment in payments:
            self.connection.execute(
                """INSERT INTO payments(
                   order_number,method,amount,status,authorization_reference,idempotency_key)
                   VALUES (?,?,?,?,?,?)""",
                (order_number, payment["method"], str(payment["amount"]), status,
                 payment.get("authorization_reference"), idempotency_key),
            )

    def get_order_receipt(self, order_number: str) -> str:
        """Return the stored receipt for an order number."""
        row = self.connection.execute(
            "SELECT receipt FROM orders WHERE order_number = ?", (order_number,)
        ).fetchone()
        if row is None:
            raise KeyError(order_number)
        return row["receipt"]

    def get_idempotent_payment(self, idempotency_key: str) -> dict | None:
        """Return a previously persisted checkout result for an idempotency key."""
        order = self.connection.execute(
            "SELECT order_number, payment_status, total, receipt "
            "FROM orders WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if order is None:
            return None
        payments = self.connection.execute(
            """SELECT method, amount, authorization_reference
               FROM payments WHERE idempotency_key = ? ORDER BY id""",
            (idempotency_key,),
        ).fetchall()
        return {
            "status": order["payment_status"],
            "total": order["total"],
            "change": "0.00",
            "payments": [dict(payment) for payment in payments],
            "receipt": order["receipt"],
        }

    def reverse_payment(self, payment_id: int) -> None:
        """Mark a payment as reversed and create a refund record."""
        with self.connection:
            payment = self.connection.execute(
                "SELECT order_number, amount, status FROM payments WHERE id = ?",
                (payment_id,),
            ).fetchone()
            if payment is None:
                raise KeyError(payment_id)
            if payment["status"] in {"refunded", "reversed"}:
                raise ValueError("Payment has already been reversed.")
            self.connection.execute(
                "UPDATE payments SET status = 'refunded' WHERE id = ?", (payment_id,)
            )
            self.connection.execute(
                "INSERT INTO refunds(order_number, amount, payment_id) VALUES (?, ?, ?)",
                (payment["order_number"], payment["amount"], payment_id),
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

    def create_staff_account(
        self,
        username: str,
        password: str,
        role: str,
        *,
        session_token: str | None = None,
    ) -> None:
        """Create a staff account, requiring admin approval after bootstrap."""
        username = username.strip()
        if not username or not password:
            raise ValueError("Username and password are required.")
        if role not in {"cashier", "manager", "admin"}:
            raise ValueError(f"Unknown staff role: {role}")
        account_count = self.connection.execute(
            "SELECT COUNT(*) AS count FROM staff_users"
        ).fetchone()["count"]
        if account_count:
            if session_token is None:
                raise PermissionError("An administrator session is required.")
            _, actor_role = self.get_session_role(session_token)
            if actor_role != "admin":
                raise PermissionError("Administrator approval is required.")
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
        encoded = f"pbkdf2_sha256$200000${salt.hex()}${digest.hex()}"
        with self.connection:
            self.connection.execute(
                "INSERT INTO staff_users(username, password_hash, role) VALUES (?, ?, ?)",
                (username, encoded, role),
            )

    def authenticate_staff(self, username: str, password: str, *, ttl: int = 28800) -> str:
        """Verify credentials and create a time-limited opaque session token."""
        row = self.connection.execute(
            "SELECT password_hash, role FROM staff_users "
            "WHERE username = ? AND active = 1", (username.strip(),)
        ).fetchone()
        if row is None:
            raise PermissionError("Invalid username or password.")
        scheme, iterations, salt_hex, digest_hex = row["password_hash"].split("$")
        if scheme != "pbkdf2_sha256":
            raise PermissionError("Unsupported password hash.")
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations)
        )
        if not hmac.compare_digest(candidate.hex(), digest_hex):
            raise PermissionError("Invalid username or password.")
        token = secrets.token_urlsafe(32)
        with self.connection:
            self.connection.execute(
                "INSERT INTO staff_sessions(token_hash, username, expires_at) VALUES (?, ?, ?)",
                (hashlib.sha256(token.encode()).hexdigest(), username.strip(),
                 time.time() + ttl),
            )
        return token

    def get_session_role(self, token: str) -> tuple[str, str]:
        """Return the username and role for a valid, unexpired session."""
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        row = self.connection.execute(
            """SELECT s.username, u.role FROM staff_sessions s
               JOIN staff_users u ON u.username = s.username
               WHERE s.token_hash = ? AND s.expires_at > ? AND u.active = 1""",
            (token_hash, time.time()),
        ).fetchone()
        if row is None:
            raise PermissionError("A valid staff session is required.")
        return row["username"], row["role"]

    def revoke_session(self, token: str) -> None:
        """Revoke a staff session token."""
        with self.connection:
            self.connection.execute(
                "DELETE FROM staff_sessions WHERE token_hash = ?",
                (hashlib.sha256(token.encode()).hexdigest(),),
            )

    def audit(self, username: str, action: str, details: str = "") -> None:
        """Record a security-relevant staff action."""
        with self.connection:
            self.connection.execute(
                "INSERT INTO audit_log(username, action, details) VALUES (?, ?, ?)",
                (username, action, details),
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
