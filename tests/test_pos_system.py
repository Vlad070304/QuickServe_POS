"""Tests for the QuickServe POS business logic."""

from datetime import datetime, timezone
from decimal import Decimal
import time

import tkinter as tk
from hypothesis import given, strategies as st
import pytest

from restaurant_pos.app import RestaurantPOSApp
from restaurant_pos.menu import Menu, MenuItem, build_demo_menu
from restaurant_pos.payments import Order, PaymentError, PaymentProcessor, money
from restaurant_pos.reporting import SalesReport
from restaurant_pos.services import CheckoutService
from restaurant_pos.operations import (
    export_menu, export_sales, import_menu, import_sales, seed_demo_data,
)
from restaurant_pos.admin import AdminControls, StaffRole
from restaurant_pos.operations import SalesBackupScheduler
from restaurant_pos.storage import SQLiteStore


@pytest.fixture(name="pos_app")
def _pos_app():
    """Create a UI instance when a display is available."""
    try:
        instance = RestaurantPOSApp()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter display is unavailable: {exc}")
    try:
        yield instance
    finally:
        instance.destroy()


def test_order_total_calculations_and_tax_logic():
    """Calculate subtotal, discount, tax, and total correctly."""
    menu = build_demo_menu()
    order = Order(tax_rate=0.08)

    order.add_item(menu.get_item("BURGER"), 2)
    order.add_item(menu.get_item("FRIES"), 1)
    order.apply_discount(10)

    totals = order.calculate_totals()

    assert totals["subtotal"] == Decimal("28.50")
    assert totals["discount_amount"] == Decimal("2.85")
    assert totals["discounted_subtotal"] == Decimal("25.65")
    assert totals["tax"] == Decimal("2.05")
    assert totals["total"] == Decimal("27.70")


def test_invalid_discount_range_raises_value_error():
    """Reject discounts outside the inclusive zero-to-one-hundred range."""
    order = Order()

    with pytest.raises(ValueError):
        order.apply_discount(-5)

    with pytest.raises(ValueError):
        order.apply_discount(101)


def test_payment_failure_rolls_back_order():
    """Roll back the order when payment processing fails."""
    menu = build_demo_menu()
    order = Order(tax_rate=0.08)
    order.add_item(menu.get_item("SODA"), 2)

    processor = PaymentProcessor(tax_rate=0.08)
    with pytest.raises(PaymentError):
        processor.process_payment(order, Decimal("5.00"), trigger_failure=True)

    assert not order.items
    assert order.discount_percentage == Decimal("0")
    assert order.paid is False


def test_payment_accepts_exact_amount_and_returns_zero_change():
    """Mark an order paid when tendered cash exactly matches the total."""
    menu = build_demo_menu()
    order = Order()
    order.add_item(menu.get_item("SODA"))
    processor = PaymentProcessor()

    result = processor.process_payment(order, Decimal("2.70"))

    assert result["status"] == "paid"
    assert result["change"] == Decimal("0.00")
    assert order.paid is True


def test_payment_returns_change_for_overpayment():
    """Return the correct change for cash above the order total."""
    menu = build_demo_menu()
    order = Order()
    order.add_item(menu.get_item("SODA"))
    processor = PaymentProcessor()

    result = processor.process_payment(order, Decimal("5.00"))

    assert result["change"] == Decimal("2.30")
    assert order.paid is True


def test_payment_rejects_empty_order():
    """Do not settle a payment when there are no order items."""
    order = Order()

    with pytest.raises(ValueError, match="empty order"):
        PaymentProcessor().process_payment(order, Decimal("10.00"))

    assert order.paid is False


def test_receipt_formatting_contains_totals_and_items():
    """Include item names and totals in the generated receipt."""
    menu = build_demo_menu()
    order = Order(tax_rate=0.08)
    order.add_item(menu.get_item("PASTA"), 1)
    order.add_item(menu.get_item("SODA"), 1)

    receipt = order.receipt()

    assert "Restaurant POS" in receipt
    assert "Chef Pasta" in receipt
    assert "House Soda" in receipt
    assert "Total:" in receipt
    assert "$17.50" in receipt


def test_order_merges_duplicate_items_and_resets_discount_when_cleared():
    """Merge repeated menu selections and reset all order state on clear."""
    menu = build_demo_menu()
    order = Order()
    order.add_item(menu.get_item("SODA"))
    order.add_item(menu.get_item("SODA"), 2)
    order.apply_discount(10)

    assert len(order.items) == 1
    assert order.items[0].quantity == 3

    order.rollback()
    assert not order.items
    assert order.discount_percentage == Decimal("0")
    assert order.paid is False


def test_empty_order_receipt_is_explicit():
    """Explain that an empty order has no items while retaining totals."""
    receipt = Order().receipt()

    assert "No items in the order." in receipt
    assert "Total: $0.00" in receipt


def test_menu_rejects_invalid_items_and_duplicate_skus():
    """Reject invalid menu data and duplicate registrations."""
    with pytest.raises(ValueError):
        MenuItem("BAD", "Invalid", "Main", -1)
    with pytest.raises(ValueError):
        MenuItem("BAD", "Invalid", "Main", 1, stock=-1)

    menu = Menu()
    item = MenuItem("ITEM", "Item", "Main", 1, stock=2)
    menu.add_item(item)
    with pytest.raises(ValueError):
        menu.add_item(item)
    with pytest.raises(KeyError):
        menu.get_item("MISSING")


def test_menu_updates_and_removes_stock():
    """Adjust inventory and reject changes that would create negative stock."""
    menu = Menu()
    menu.add_item(MenuItem("ITEM", "Item", "Main", 1, stock=2))

    menu.update_stock("ITEM", 3)
    assert menu.get_item("ITEM").stock == 5
    with pytest.raises(ValueError):
        menu.update_stock("ITEM", -6)

    menu.remove_item("ITEM")
    menu.clear()
    assert menu.list_items() == []


def test_sales_report_summarizes_revenue_and_items():
    """Aggregate revenue and item quantities across completed orders."""
    menu = build_demo_menu()
    report = SalesReport()
    first_order = Order()
    first_order.add_item(menu.get_item("SODA"), 2)
    second_order = Order()
    second_order.add_item(menu.get_item("PASTA"))

    report.add_order(first_order)
    report.add_order(second_order)

    assert report.total_revenue() == Decimal("21.60")
    assert report.items_sold() == {"House Soda": 2, "Chef Pasta": 1}
    assert "Daily Sales Summary" in report.summary_text()


def test_sales_report_rejects_empty_orders():
    """Do not include empty orders in sales reporting."""
    with pytest.raises(ValueError):
        SalesReport().add_order(Order())


def test_checkout_service_validates_stock_and_records_sale():
    """Coordinate inventory, payment, and sales reporting outside the UI."""
    menu = Menu()
    menu.add_item(MenuItem("ITEM", "Test item", "Test", 1.00, stock=2))
    report = SalesReport()
    service = CheckoutService(menu, PaymentProcessor(tax_rate=0), report)
    order = Order(tax_rate=0)

    service.add_item(order, "ITEM", 2)
    result = service.checkout(order, Decimal("2.00"))

    assert result["status"] == "paid"
    assert menu.get_item("ITEM").stock == 0
    assert report.items_sold() == {"Test item": 2}
    assert not order.items


def test_checkout_service_rejects_order_above_available_stock():
    """Reject an order before payment when inventory is insufficient."""
    menu = Menu()
    menu.add_item(MenuItem("ITEM", "Test item", "Test", 1.00, stock=1))
    service = CheckoutService(menu, PaymentProcessor(tax_rate=0), SalesReport())
    order = Order(tax_rate=0)

    with pytest.raises(ValueError, match="Not enough stock"):
        service.add_item(order, "ITEM", 2)


def test_split_payment_and_order_metadata_are_recorded():
    """Accept partial tenders and retain searchable customer metadata."""
    order = Order(tax_rate=0, customer="Ada", order_number="ORD-1",
                  created_at=datetime(2026, 1, 2, 12, tzinfo=timezone.utc))
    order.add_item(MenuItem("ITEM", "Test item", "Main", 10, stock=1))
    result = PaymentProcessor(tax_rate=0).process_split_payment(
        order, {"cash": Decimal("4"), "card": Decimal("6")})
    report = SalesReport()
    report.add_order(order)
    assert result["change"] == Decimal("0.00")
    assert report.search_orders("ord-1") == [order]
    assert report.daily_totals(datetime(2026, 1, 2).date())["revenue"] == Decimal("10.00")


def test_sqlite_menu_and_order_persistence(tmp_path):
    """Persist inventory and completed orders in SQLite."""
    path = tmp_path / "pos.db"
    menu = Menu(path)
    menu.add_item(MenuItem("ITEM", "Test item", "Main", 2, stock=3))
    menu.update_stock("ITEM", -1)
    reopened = Menu(path)
    assert reopened.get_item("ITEM").stock == 2
    report = SalesReport(path)
    order = Order(tax_rate=0, customer="Sam", order_number="ORD-2")
    order.add_item(reopened.get_item("ITEM"))
    report.add_order(order)
    assert report.search_history("Sam")[0]["order_number"] == "ORD-2"


def test_reporting_refund_best_sellers_and_receipt_exports(tmp_path):
    """Expose operational reporting and receipt output formats."""
    report = SalesReport()
    order = Order(tax_rate=0, order_number="ORD-3")
    order.add_item(MenuItem("ITEM", "Test item", "Main", 2, stock=1))
    report.add_order(order)
    assert report.best_sellers() == {"Test item": 1}
    assert report.category_sales() == {"Main": Decimal("2.00")}
    assert report.refund("ORD-3") == Decimal("2.00")
    pdf = tmp_path / "receipt.pdf"
    order.save_pdf(pdf)
    assert pdf.read_bytes().startswith(b"%PDF")


@given(
    st.decimals(min_value="0", max_value="10000", places=4, allow_nan=False, allow_infinity=False)
)
def test_money_is_idempotent_for_finite_nonnegative_values(value):
    """Rounding an already rounded monetary value does not change it."""
    rounded = money(value)

    assert money(rounded) == rounded


@given(st.decimals(min_value="0", max_value="100", places=4, allow_nan=False))
def test_discount_math_never_exceeds_subtotal(percentage):
    """Discount calculations remain bounded for every valid percentage."""
    order = Order(tax_rate=0)
    order.add_item(MenuItem("TEST", "Test item", "Test", 10.00, stock=1))
    order.apply_discount(percentage)

    totals = order.calculate_totals()

    assert Decimal("0.00") <= totals["discount_amount"] <= totals["subtotal"]
    assert totals["discounted_subtotal"] + totals["discount_amount"] == totals["subtotal"]


def test_app_starts_without_crashing(pos_app):
    """Initialize the complete desktop application successfully."""
    assert pos_app.title() == "QuickServe POS"


def test_clicking_menu_button_adds_item(pos_app):
    """Connect a rendered menu button to order state."""
    pos_app.menu_buttons[0].invoke()

    assert len(pos_app.order.items) == 1
    assert pos_app.order.items[0].quantity == 1


def test_checkout_with_valid_cash_updates_status(pos_app, monkeypatch):
    """Complete a cash checkout and update the status message."""
    pos_app.menu_buttons[0].invoke()
    pos_app.payment_entry.delete(0, tk.END)
    pos_app.payment_entry.insert(0, "20.00")
    monkeypatch.setattr("restaurant_pos.app.messagebox.showinfo", lambda *args: None)

    pos_app.checkout()

    assert pos_app.status_var.get().startswith("Payment successful.")
    assert not pos_app.order.items


def test_invalid_numeric_input_shows_payment_error(pos_app, monkeypatch):
    """Show a payment error instead of raising for invalid cash input."""
    errors: list[str] = []
    monkeypatch.setattr(
        "restaurant_pos.app.messagebox.showerror",
        lambda _title, message: errors.append(message),
    )
    pos_app.payment_entry.delete(0, tk.END)
    pos_app.payment_entry.insert(0, "not-a-number")

    pos_app.checkout()

    assert errors == ["Cash amount must be a valid number."]
    assert "Cash amount must be a valid number." in pos_app.status_var.get()


def test_demo_seed_and_menu_sales_exports(tmp_path):
    """Seed a new database and transfer menu and sales data through CSV."""
    db_path = tmp_path / "demo.db"
    assert seed_demo_data(db_path) == 5
    assert seed_demo_data(db_path) == 0
    menu_csv = tmp_path / "menu.csv"
    export_menu(db_path, menu_csv)
    imported_db = tmp_path / "imported.db"
    assert import_menu(imported_db, menu_csv) == 5
    imported_menu = Menu(imported_db)
    assert len(imported_menu.list_items()) == 5
    assert imported_menu.store is not None
    imported_menu.store.close()

    report = SalesReport(db_path)
    order = Order(tax_rate=0)
    source_menu = Menu(db_path)
    order.add_item(source_menu.get_item("SODA"))
    assert source_menu.store is not None
    source_menu.store.close()
    report.add_order(order)
    sales_csv = tmp_path / "sales.csv"
    export_sales(db_path, sales_csv)
    assert "order_number" in sales_csv.read_text(encoding="utf-8")
    assert report.store is not None
    report.store.close()
    restored_db = tmp_path / "restored.db"
    assert import_sales(restored_db, sales_csv) == 1


def test_payment_validation_rejects_negative_tender_without_accepting_order():
    """Reject invalid tender before marking the order paid."""
    order = Order(tax_rate=0)
    order.add_item(MenuItem("ITEM", "Item", "Main", 1, stock=1))
    with pytest.raises(ValueError, match="negative"):
        PaymentProcessor(tax_rate=0).process_payment(order, -1)
    assert not order.paid
    assert not order.items


def test_staff_roles_protect_administration_controls():
    """Prevent cashiers from changing tax or menu configuration."""
    menu = Menu()
    processor = PaymentProcessor()
    cashier = AdminControls(menu, processor, role=StaffRole.CASHIER)

    with pytest.raises(PermissionError, match="Manager or administrator"):
        cashier.set_tax_rate(0.05)
    with pytest.raises(PermissionError, match="Manager or administrator"):
        cashier.create_menu_item(MenuItem("ITEM", "Item", "Main", 1, stock=1))

    manager = AdminControls(menu, processor, role="manager")
    assert manager.set_tax_rate(0.05) == Decimal("0.05")


def test_admin_controls_persist_settings_and_manage_menu(tmp_path):
    """Persist protected administration changes and staff audit events."""
    path = tmp_path / "admin.db"
    store = SQLiteStore(path)
    store.create_staff_account("admin", "secret", "admin")
    menu = Menu(path)
    controls = AdminControls(menu, PaymentProcessor(), store=store)

    session = controls.login("admin", "secret")
    assert session.role is StaffRole.ADMIN
    assert controls.set_tax_rate("0.07") == Decimal("0.07")
    assert controls.set_discount_percentage(15) == Decimal("15")
    controls.create_menu_item(MenuItem("NEW", "New item", "Main", 3, stock=2))
    assert controls.update_menu_item("NEW", price=4).price == 4
    controls.adjust_stock("NEW", 1)
    controls.apply_discount(Order(), 5)
    controls.delete_menu_item("NEW")
    controls.logout()

    assert store.get_setting("tax_rate") == "0.07"
    assert store.get_setting("missing", "fallback") == "fallback"
    assert store.connection.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] >= 7
    store.close()


def test_admin_controls_require_authenticated_manager(tmp_path):
    """Reject missing, mismatched, and expired persistent staff sessions."""
    store = SQLiteStore(tmp_path / "staff.db")
    store.create_staff_account("manager", "secret", "manager")
    controls = AdminControls(Menu(), PaymentProcessor(), store=store)

    with pytest.raises(PermissionError, match="Log in"):
        controls.set_tax_rate(0.05)
    session = controls.login("manager", "secret")
    store.connection.execute("UPDATE staff_sessions SET expires_at = 0")
    with pytest.raises(PermissionError, match="valid staff session"):
        controls.set_tax_rate(0.05)
    controls.session = session
    with pytest.raises(PermissionError, match="valid staff session"):
        controls.require_manager()
    with pytest.raises(PermissionError):
        store.authenticate_staff("manager", "wrong")
    with pytest.raises(ValueError):
        AdminControls(Menu(), PaymentProcessor(), role="unknown")
    with pytest.raises(ValueError):
        AdminControls.validate_discount(101)
    store.close()


def test_storage_payment_lifecycle_and_csv_validation(tmp_path):
    """Exercise payment persistence, reversal, backup, and CSV validation."""
    path = tmp_path / "lifecycle.db"
    store = SQLiteStore(path)
    store.save_menu_item("ITEM", "Item", "Main", 2, 3)
    order = Order(tax_rate=0, order_number="LIFE-1")
    order.add_item(MenuItem("ITEM", "Item", "Main", 2, stock=1))
    payment = {"method": "cash", "amount": Decimal("2"), "authorization_reference": "a"}
    store.save_order(order, [payment], idempotency_key="key")
    assert store.get_order_receipt("LIFE-1").startswith("Restaurant POS")
    assert store.get_idempotent_payment("key")["status"] == "paid"
    payment_id = store.connection.execute("SELECT id FROM payments").fetchone()[0]
    store.reverse_payment(payment_id)
    with pytest.raises(ValueError, match="already"):
        store.reverse_payment(payment_id)
    store.set_setting("mode", "test")
    assert store.get_setting("mode") == "test"
    backup = tmp_path / "backup" / "copy.db"
    store.backup_to(backup)
    with pytest.raises(ValueError, match="differ"):
        store.backup_to(path)
    menu_csv = tmp_path / "menu.csv"
    store.export_menu_csv(menu_csv)
    assert store.import_menu_csv(menu_csv, replace=True) == 1
    with pytest.raises(FileNotFoundError):
        store.import_menu_csv(tmp_path / "missing.csv")
    store.close()


def test_reporting_search_time_windows_and_csv(tmp_path):
    """Cover report filtering, time discounts, exports, and persistent search."""
    report = SalesReport()
    order = Order(tax_rate=0, order_number="REPORT-1",
                  created_at=datetime(2026, 1, 2, 23, tzinfo=timezone.utc))
    order.add_item(MenuItem("ITEM", "Report item", "Main", 10, stock=1))
    report.add_order(order)
    assert report.search("ITEM") == [order]
    assert report.search_orders(on_date=datetime(2026, 1, 2).date()) == [order]
    assert report.daily_totals(datetime(2026, 1, 2).date())["orders"] == Decimal("1")
    assert report.hourly_sales() == {23: Decimal("10.00")}
    assert report.apply_time_discount(order, 10, 22, 2)
    assert report.best_sellers(1) == {"Report item": 1}
    assert "Report item" in report.export_csv()
    with pytest.raises(ValueError):
        report.apply_time_discount(order, 10, -1, 2)
    with pytest.raises(ValueError):
        report.refund("REPORT-1", 100)

    persisted = SalesReport(tmp_path / "report.db")
    persisted.add_order(order)
    assert persisted.search_history("Report")[0]["order_number"] == "REPORT-1"
    persisted.store.close()


def test_payment_methods_idempotency_and_partial_tenders():
    """Handle payment method validation, idempotency, and partial settlement."""
    item = MenuItem("ITEM", "Item", "Main", 10, stock=2)
    order = Order(tax_rate=0)
    order.add_item(item)
    processor = PaymentProcessor(tax_rate=0)
    first = processor.process_payment(order, 10, method="card", idempotency_key="same")
    assert processor.process_payment(order, 1, idempotency_key="same") is first
    order.rollback()
    order.add_item(item)
    partial = processor.process_split_payment(
        order, {"cash": 3}, allow_partial=True, authorization_references={"cash": "ref"}
    )
    assert partial["status"] == "partially_paid"
    assert partial["payments"][0]["authorization_reference"] == "ref"
    with pytest.raises(ValueError, match="Unsupported"):
        processor.process_payment(order, 10, method="bitcoin")
    order.add_item(item)
    with pytest.raises(ValueError, match="Insufficient"):
        processor.process_split_payment(order, {"cash": 1})


def test_backup_scheduler_creates_backup_and_rejects_duplicate_start(tmp_path):
    """Run a scheduled backup worker and stop it cleanly."""
    store = SQLiteStore(tmp_path / "source.db")
    destination = tmp_path / "scheduled.db"
    scheduler = SalesBackupScheduler(store, destination, 0.01)
    scheduler.start()
    with pytest.raises(RuntimeError, match="already"):
        scheduler.start()
    for _ in range(100):
        if destination.exists():
            break
        time.sleep(0.01)
    scheduler.stop()
    assert destination.exists()
    store.close()
