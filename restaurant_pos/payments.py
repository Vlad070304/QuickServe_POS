"""Order and payment logic for the POS system."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from enum import Enum
from typing import List, Mapping
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4

CENT = Decimal("0.01")
PAYMENT_METHODS = frozenset({"cash", "card", "gift_card", "mobile"})


class PaymentStatus(str, Enum):
    """Supported states in the payment lifecycle."""

    PENDING = "pending"
    PAID = "paid"
    PARTIALLY_PAID = "partially_paid"
    FAILED = "failed"
    REFUNDED = "refunded"


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
    category: str = "Uncategorized"

    def line_total(self) -> Decimal:
        """Return the rounded total for this line item."""
        return (self.unit_price * Decimal(self.quantity)).quantize(CENT, rounding=ROUND_HALF_UP)


class PaymentError(RuntimeError):
    """Raised when a payment cannot be processed."""


class Order:
    """Represents the current customer order."""

    def __init__(self, tax_rate: float | Decimal = 0.08, *, customer: str = "",
                 order_number: str | None = None, created_at: datetime | None = None,
                 employee: str = "") -> None:
        """Create an empty order with the supplied tax rate."""
        self.items: List[OrderItem] = []
        self.discount_percentage = Decimal("0")
        self.tax_rate = money(tax_rate)
        self.paid = False
        self.order_number = order_number or uuid4().hex[:10].upper()
        self.customer = customer
        self.employee = employee
        self.created_at = created_at or datetime.now(timezone.utc)

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
                category=getattr(menu_item, "category", "Uncategorized"),
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

    def kitchen_ticket(self) -> str:
        """Return a compact ticket containing only preparation details."""
        lines = ["KITCHEN TICKET", "==============="]
        lines.extend(f"{item.quantity} x {item.name}" for item in self.items)
        return "\n".join(lines)

    def save_pdf(self, path: str | Path) -> None:
        """Save a dependency-free, printable PDF receipt."""
        text = self.receipt().replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        commands = "BT /F1 11 Tf 40 760 Td " + " ".join(
            f"({line}) Tj 0 -16 Td" for line in text.splitlines()
        ) + " ET"
        stream = commands.encode("latin-1", "replace")
        objects = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 800] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        ]
        pdf = bytearray(b"%PDF-1.4\n")
        offsets = []
        for index, obj in enumerate(objects, 1):
            offsets.append(len(pdf))
            pdf.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
        xref = len(pdf)
        pdf.extend(f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode())
        pdf.extend(b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets))
        trailer = (
            f"trailer << /Size {len(objects)+1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF"
        )
        pdf.extend(trailer.encode())
        Path(path).write_bytes(pdf)

    def print_thermal(self, printer=None) -> str:
        """Return receipt text for a thermal printer callback or spooler."""
        receipt = self.receipt()
        if printer:
            printer(receipt)
        return receipt

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
        self._idempotent_results: dict[str, dict] = {}

    def calculate_order_total(self, order: Order) -> dict:
        """Apply the processor tax rate and calculate order totals."""
        order.tax_rate = self.tax_rate
        return order.calculate_totals()

    def validate_payment(self, order: Order, tendered_amount: float | Decimal) -> Decimal:
        """Validate payment input before any payment can be accepted."""
        if not order.items:
            raise ValueError("Cannot process payment for an empty order.")
        try:
            amount = money(tendered_amount)
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ValueError("Payment amount must be a valid number.") from exc
        if amount < 0:
            raise ValueError("Payment amount cannot be negative.")
        if amount < self.calculate_order_total(order)["total"]:
            raise ValueError("Insufficient payment to cover the order total.")
        return amount

    def process_payment(
        self,
        order: Order,
        tendered_amount: float | Decimal,
        *,
        trigger_failure: bool = False,
        method: str = "cash",
        authorization_reference: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict:
        """Settle a payment or roll back the order when it cannot be completed."""
        try:
            self._validate_method(method)
        except ValueError:
            order.rollback()
            raise
        if idempotency_key and idempotency_key in self._idempotent_results:
            return self._idempotent_results[idempotency_key]
        try:
            totals = self.calculate_order_total(order)
            if trigger_failure:
                raise PaymentError("Card declined. The transaction was rolled back.")
            payment = self.validate_payment(order, tendered_amount)
            total = totals["total"]
            change = (payment - total).quantize(CENT, rounding=ROUND_HALF_UP)
            order.paid = True
            result = {
                "status": PaymentStatus.PAID.value,
                "total": total,
                "change": change,
                "payments": [{"method": method, "amount": payment,
                              "authorization_reference": authorization_reference}],
                "receipt": order.receipt(),
            }
            if idempotency_key:
                self._idempotent_results[idempotency_key] = result
            return result
        except (PaymentError, ValueError):
            order.rollback()
            raise

    def process_split_payment(self, order: Order,
                              tenders: Mapping[str, float | Decimal],
                              *,
                              authorization_references: Mapping[str, str] | None = None,
                              idempotency_key: str | None = None,
                              allow_partial: bool = False) -> dict:
        """Accept multiple partial tenders (for example cash plus card)."""
        if idempotency_key and idempotency_key in self._idempotent_results:
            return self._idempotent_results[idempotency_key]
        try:
            totals = self.calculate_order_total(order)
            if not order.items:
                raise ValueError("Cannot process payment for an empty order.")
            for name in tenders:
                self._validate_method(name)
            normalized = {name: money(value) for name, value in tenders.items()}
            if any(amount < 0 for amount in normalized.values()):
                raise ValueError("Payment amounts cannot be negative.")
            paid = sum(normalized.values(), Decimal("0"))
            if paid < totals["total"] and not allow_partial:
                raise ValueError("Insufficient payment to cover the order total.")
            order.paid = paid >= totals["total"]
            result = {
                "status": (PaymentStatus.PAID.value if order.paid
                           else PaymentStatus.PARTIALLY_PAID.value),
                "total": totals["total"],
                "change": money(paid - totals["total"]),
                "payments": [{"method": name, "amount": amount}
                             for name, amount in normalized.items() if amount],
                "receipt": order.receipt(),
            }
            for payment in result["payments"]:
                payment["authorization_reference"] = (
                    (authorization_references or {}).get(payment["method"])
                )
            if idempotency_key:
                self._idempotent_results[idempotency_key] = result
            return result
        except (InvalidOperation, TypeError, ValueError):
            order.rollback()
            raise

    @staticmethod
    def _validate_method(method: str) -> None:
        """Reject payment methods outside the supported provider set."""
        if method not in PAYMENT_METHODS:
            raise ValueError(f"Unsupported payment method: {method}")
