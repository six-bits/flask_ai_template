"""Money and currency utility functions."""

from decimal import Decimal, ROUND_HALF_UP
from typing import Union


def to_decimal(val: Union[int, float, str, Decimal]) -> Decimal:
    """Convert a value to Decimal safely."""
    if isinstance(val, Decimal):
        return val
    return Decimal(str(val))


def quantize_amount(amount: Decimal, decimals: int = 4) -> Decimal:
    """Quantize decimal amount to standard precision."""
    exp = Decimal("10") ** -decimals
    return amount.quantize(exp, rounding=ROUND_HALF_UP)


def round_currency(amount: Union[Decimal, float], currency: str = "USD") -> Decimal:
    """Round currency amount to appropriate standard decimals (2 for fiat, 0/2 for JPY)."""
    dec_amount = to_decimal(amount)
    decimals = 0 if currency.upper() == "JPY" else 2
    exp = Decimal("10") ** -decimals
    return dec_amount.quantize(exp, rounding=ROUND_HALF_UP)


def to_float(val: Union[Decimal, float]) -> float:
    """Convert Decimal or float to float for JSON responses."""
    return float(val)
