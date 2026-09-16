"""Tests for the QuickServe POS business logic."""

from decimal import Decimal

import pytest

from restaurant_pos.menu import Menu, MenuItem, build_demo_menu
from restaurant_pos.payments import Order, PaymentError, PaymentProcessor
from restaurant_pos.reporting import SalesReport


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
