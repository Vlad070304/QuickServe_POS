from decimal import Decimal

import pytest

from restaurant_pos.menu import build_demo_menu
from restaurant_pos.payments import Order, PaymentError, PaymentProcessor


def test_order_total_calculations_and_tax_logic():
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
    order = Order()

    with pytest.raises(ValueError):
        order.apply_discount(-5)

    with pytest.raises(ValueError):
        order.apply_discount(101)


def test_payment_failure_rolls_back_order():
    menu = build_demo_menu()
    order = Order(tax_rate=0.08)
    order.add_item(menu.get_item("SODA"), 2)

    processor = PaymentProcessor(tax_rate=0.08)
    with pytest.raises(PaymentError):
        processor.process_payment(order, Decimal("5.00"), trigger_failure=True)

    assert order.items == []
    assert order.discount_percentage == Decimal("0")
    assert order.paid is False


def test_receipt_formatting_contains_totals_and_items():
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
