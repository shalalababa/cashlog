"""Exact money arithmetic.

Rules (see docs/PLAN.md, sql-code-review decision):
  - Original amounts are stored as INTEGER minor units (e.g. cents).
  - CNY conversion is cached as INTEGER micro-units (CNY * 1_000_000).
  - Exchange rates are decimal strings, parsed to Decimal.
  - Never use binary float for a value that gets summed or settled.

All rounding is ROUND_HALF_UP, matching spreadsheet behaviour.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Optional, Union

from .config import CNY_MICRO_SCALE

Number = Union[str, int, float, Decimal]

_MICRO = Decimal(CNY_MICRO_SCALE)


def parse_decimal(value: Optional[Number]) -> Optional[Decimal]:
    """Best-effort parse to Decimal. Returns None for empty/garbage input.

    Floats are routed through str() so that 5.51 -> Decimal('5.51'), not the
    binary-float tail. Junk such as '100.。' (seen in the workbook) -> None.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):  # guard: bool is an int subclass
        return None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    text = str(value).strip()
    if not text:
        return None
    try:
        dec = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    # NaN / Infinity are not amounts; refusing them here keeps them from
    # reaching quantize() (InvalidOperation -> HTTP 500) or the database.
    return dec if dec.is_finite() else None


# Largest magnitude we store: SQLite INTEGER is signed 64-bit. Anything near it
# is a typo, not a real amount, and must fail as a clean ValueError (-> 400)
# instead of an OverflowError / InvalidOperation (-> 500).
_INT_LIMIT = 2 ** 63 - 1
_MAX_MAJOR = Decimal(10) ** 12


def _bounded(dec: Decimal, raw) -> Decimal:
    if abs(dec) > _MAX_MAJOR:
        raise ValueError(f"amount out of range: {raw!r}")
    return dec


def _checked_int(value: Decimal, raw) -> int:
    n = int(value)
    if abs(n) > _INT_LIMIT:
        raise ValueError(f"amount out of range: {raw!r}")
    return n


def _quantum(minor_unit: int) -> Decimal:
    return Decimal(1).scaleb(-minor_unit)  # 2 -> Decimal('0.01'), 0 -> Decimal('1')


def to_minor(amount_major: Number, minor_unit: int) -> int:
    """Major amount -> integer minor units. Raises on unparseable input."""
    dec = parse_decimal(amount_major)
    if dec is None:
        raise ValueError(f"cannot parse amount: {amount_major!r}")
    dec = _bounded(dec, amount_major)
    scaled = (dec * (Decimal(10) ** minor_unit)).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return _checked_int(scaled, amount_major)


def from_minor(amount_minor: int, minor_unit: int) -> Decimal:
    """Integer minor units -> major Decimal."""
    return (Decimal(amount_minor) / (Decimal(10) ** minor_unit)).quantize(
        _quantum(minor_unit)
    )


def to_base_micro(amount_minor: int, minor_unit: int, rate_to_base: Number) -> int:
    """Convert an original amount to base-currency (CNY) micro-units.

    base_cny = amount_major * rate ; stored as round(base_cny * 1_000_000).
    """
    rate = parse_decimal(rate_to_base)
    if rate is None:
        raise ValueError(f"cannot parse rate: {rate_to_base!r}")
    amount_major = Decimal(amount_minor) / (Decimal(10) ** minor_unit)
    base_cny = amount_major * rate
    micro = (base_cny * _MICRO).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return _checked_int(micro, amount_minor)


def cny_to_base_micro(amount_cny: Number) -> int:
    """CNY major amount -> integer micro-units (CNY * 1_000_000).

    The inverse of base_micro_to_cny, for values already denominated in CNY
    (e.g. budgets) that need to be compared against the cached base_amount_micro.
    """
    dec = parse_decimal(amount_cny)
    if dec is None:
        raise ValueError(f"cannot parse amount: {amount_cny!r}")
    dec = _bounded(dec, amount_cny)
    micro = (dec * _MICRO).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return _checked_int(micro, amount_cny)


def base_micro_to_cny(base_micro: int) -> Decimal:
    """Micro-units -> CNY Decimal rounded to 2 dp (display / reconcile)."""
    return (Decimal(base_micro) / _MICRO).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def rate_to_str(rate: Number) -> str:
    """Normalise a rate to a canonical decimal string for storage."""
    dec = parse_decimal(rate)
    if dec is None:
        raise ValueError(f"cannot parse rate: {rate!r}")
    return format(dec.normalize(), "f")
