"""Operational helpers for demo data, transfers, and scheduled backups."""

from __future__ import annotations

import threading
import sqlite3
from pathlib import Path
from typing import Callable

from .menu import Menu, build_demo_menu
from .storage import SQLiteStore


def seed_demo_data(db_path: str | Path, *, force: bool = False) -> int:
    """Seed a database with the standard demo menu, returning rows created."""
    menu = Menu(db_path)
    try:
        if menu.list_items() and not force:
            return 0
        if force:
            menu.clear()
        for item in build_demo_menu().list_items():
            menu.add_item(item)
        return len(menu.list_items())
    finally:
        if menu.store:
            menu.store.close()


def export_menu(db_path: str | Path, path: str | Path) -> None:
    """Export menu data from a database."""
    store = SQLiteStore(db_path)
    try:
        store.export_menu_csv(path)
    finally:
        store.close()


def import_menu(db_path: str | Path, path: str | Path, *, replace: bool = False) -> int:
    """Import menu data into a database."""
    store = SQLiteStore(db_path)
    try:
        return store.import_menu_csv(path, replace=replace)
    finally:
        store.close()


def export_sales(db_path: str | Path, path: str | Path) -> None:
    """Export completed sales from a database."""
    store = SQLiteStore(db_path)
    try:
        store.export_sales_csv(path)
    finally:
        store.close()


def import_sales(db_path: str | Path, path: str | Path) -> int:
    """Import completed sales into a database, returning orders restored."""
    store = SQLiteStore(db_path)
    try:
        return store.import_sales_csv(path)
    finally:
        store.close()


class SalesBackupScheduler:
    """Run consistent database backups on a daemon thread at a fixed interval."""

    def __init__(self, store: SQLiteStore, destination: str | Path, interval_seconds: float,
                 *, on_error: Callable[[Exception], None] | None = None) -> None:
        """Configure a periodic backup worker for a SQLite store."""
        if interval_seconds <= 0:
            raise ValueError("Backup interval must be greater than zero.")
        self.store = store
        self.destination = Path(destination)
        self.interval_seconds = interval_seconds
        self.on_error = on_error
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start scheduled backups; calling start twice is an error."""
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("Backup scheduler is already running.")
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="sales-backup", daemon=True)
        self._thread.start()

    def stop(self, timeout: float | None = 5) -> None:
        """Stop scheduled backups and wait for the worker to finish."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)

    def _run(self) -> None:
        """Create backups until the scheduler stop event is signaled."""
        while not self._stop.wait(self.interval_seconds):
            try:
                # SQLite connections are thread-bound; open a worker-local connection.
                worker_store = SQLiteStore(self.store.path)
                try:
                    worker_store.backup_to(self.destination)
                finally:
                    worker_store.close()
            except (OSError, sqlite3.Error, ValueError) as exc:
                if self.on_error is not None:
                    self.on_error(exc)
