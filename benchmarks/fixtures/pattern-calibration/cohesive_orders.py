"""A deliberately cohesive module that owns order-total calculation."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class OrderLine:
    quantity: int
    unit_price: Decimal

    @property
    def subtotal(self) -> Decimal:
        return self.unit_price * self.quantity


def order_total(lines: list[OrderLine]) -> Decimal:
    return sum((line.subtotal for line in lines), start=Decimal("0"))
