from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


VAT_RATE = Decimal("0.25")
VAT_MULTIPLIER = Decimal("1.25")


def parse_money(value) -> Decimal:
    try:
        decimal_value = Decimal(str(value or "0"))
    except (InvalidOperation, TypeError, ValueError):
        decimal_value = Decimal("0")
    return decimal_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def apply_vat(value, *, enabled: bool):
    if value is None:
        return None
    decimal_value = parse_money(value)
    if not enabled:
        return decimal_value
    return (decimal_value * VAT_MULTIPLIER).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )
