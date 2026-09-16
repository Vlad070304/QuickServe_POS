"""Order and payment logic for the POS system."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import List

CENT = Decimal("0.01")


def money(value: float | Decimal | str) -> Decimal:
    """Convert a value to currency precision using standard rounding."""
    decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    return decimal_value.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass
class OrderItem:
    """Represent one line item in a customer order."""

    sku: str
    name: str
    quantity: int
    unit_price: Decimal

    def line_total(self) -> Decimal:
        """Return the rounded total for this line item."""
        return (self.unit_price * Decimal(self.quantity)).quantize(CENT, rounding=ROUND_HALF_UP)


class PaymentError(RuntimeError):
    """Raised when a payment cannot be processed."""


class Order:
    """Represents the current customer order."""

    def __init__(self, tax_rate: float | Decimal = 0.08) -> None:
        """Create an empty order with the supplied tax rate."""
        self.items: List[OrderItem] = []
        self.discount_percentage = Decimal("0")
        self.tax_rate = money(tax_rate)
        self.paid = False

    def add_item(self, menu_item, quantity: int = 1) -> None:
        """Add a menu item quantity to the order."""
        if quantity <= 0:
            raise ValueError("Quantity must be greater than zero.")
        if menu_item.stock < quantity:
            raise ValueError(f"Not enough stock for {menu_item.name}.")
        for item in self.items:
            if item.sku == menu_item.sku:
                item.quantity += quantity
                return
        self.items.append(
            OrderItem(
                sku=menu_item.sku,
                name=menu_item.name,
                quantity=quantity,
                unit_price=money(menu_item.price),
            )
        )

    def subtotal(self) -> Decimal:
        """Return the rounded sum of all order line items."""
        return sum(
            (item.line_total() for item in self.items), Decimal("0")
        ).quantize(CENT, rounding=ROUND_HALF_UP)

    def apply_discount(self, percentage: float | Decimal) -> None:
        """Set the order discount percentage after validating its range."""
        discount = Decimal(str(percentage))
        if discount < 0 or discount > 100:
            raise ValueError("Discount percentage must be between 0 and 100.")
        self.discount_percentage = discount

    def calculate_totals(self) -> dict:
        """Calculate subtotal, discount, tax, and final order total."""
        subtotal = self.subtotal()
        discount_amount = (
            subtotal * (self.discount_percentage / Decimal("100"))
        ).quantize(CENT, rounding=ROUND_HALF_UP)
        discounted_subtotal = (subtotal - discount_amount).quantize(
            CENT, rounding=ROUND_HALF_UP
        )
        tax = (discounted_subtotal * self.tax_rate).quantize(CENT, rounding=ROUND_HALF_UP)
        total = (discounted_subtotal + tax).quantize(CENT, rounding=ROUND_HALF_UP)
        return {
            "subtotal": subtotal,
            "discount_amount": discount_amount,
            "discounted_subtotal": discounted_subtotal,
            "tax": tax,
            "total": total,
        }

    def receipt_lines(self) -> List[str]:
        """Build receipt content as a list of display lines."""
        totals = self.calculate_totals()
        lines = ["Restaurant POS", "================", ""]
        if not self.items:
            lines.append("No items in the order.")
            lines.extend(
                [
                    "",
                    f"Subtotal: ${totals['subtotal']:.2f}",
                    f"Tax: ${totals['tax']:.2f}",
                    f"Total: ${totals['total']:.2f}",
                ]
            )
            return lines

        for item in self.items:
            lines.append(f"{item.name} x{item.quantity} - ${item.line_total():.2f}")
        lines.extend(
            [
                "",
                f"Subtotal: ${totals['subtotal']:.2f}",
                f"Discount: -${totals['discount_amount']:.2f}",
                f"Tax: ${totals['tax']:.2f}",
                f"Total: ${totals['total']:.2f}",
            ]
        )
        return lines

    def receipt(self) -> str:
        """Return the formatted receipt text."""
        return "\n".join(self.receipt_lines())

    def rollback(self) -> None:
        """Clear the order and reset its payment state."""
        self.items.clear()
        self.discount_percentage = Decimal("0")
        self.paid = False


class PaymentProcessor:
    """Applies tax, discount logic, and payment settlement."""

    def __init__(self, tax_rate: float | Decimal = 0.08) -> None:
        """Create a payment processor with the supplied tax rate."""
        self.tax_rate = money(tax_rate)

    def calculate_order_total(self, order: Order) -> dict:
        """Apply the processor tax rate and calculate order totals."""
        order.tax_rate = self.tax_rate
        return order.calculate_totals()

    def process_payment(
        self,
        order: Order,
        tendered_amount: float | Decimal,
        *,
        trigger_failure: bool = False,
    ) -> dict:
        """Settle a payment or roll back the order when it cannot be completed."""
        try:
            totals = self.calculate_order_total(order)
            if not order.items:
                raise ValueError("Cannot process payment for an empty order.")
            payment = money(tendered_amount)
            total = totals["total"]

            if trigger_failure:
                raise PaymentError("Card declined. The transaction was rolled back.")
            if payment < total:
                raise ValueError("Insufficient payment to cover the order total.")

            change = (payment - total).quantize(CENT, rounding=ROUND_HALF_UP)
            order.paid = True
            return {
                "status": "paid",
                "total": total,
                "change": change,
                "receipt": order.receipt(),
            }
        except (PaymentError, ValueError):
            order.rollback()
            raise
