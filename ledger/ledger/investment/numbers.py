"""Exact decimals at all persistence/API boundaries."""

from decimal import Decimal, InvalidOperation, localcontext, ROUND_HALF_EVEN
from .errors import LedgerError


def decimal_value(value: str | Decimal, *, positive: bool = False) -> Decimal:
    if not isinstance(value, (str, Decimal)):
        raise LedgerError(
            "VALIDATION_ERROR", "Amounts must be decimal strings.", "DECIMAL_REQUIRED"
        )
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise LedgerError("VALIDATION_ERROR", "Invalid decimal amount.") from None
    if not result.is_finite():
        raise LedgerError("VALIDATION_ERROR", "Amount must be finite.")
    # Ignore trailing zeroes without applying the ambient Decimal precision.
    sign, digits, exponent = result.as_tuple()
    digits = list(digits)
    while len(digits) > 1 and digits[-1] == 0:
        digits.pop()
        exponent += 1
    if result == 0:
        digits, exponent = [0], 0
    integer_digits = max(len(digits) + exponent, 0)
    scale = max(-exponent, 0)
    if scale > 18 or max(integer_digits + scale, len(digits)) > 38:
        raise LedgerError(
            "VALIDATION_ERROR",
            "Amount exceeds supported precision (38 digits, up to 18 decimal places).",
            "PRECISION_LIMIT",
        )
    if positive and result <= 0:
        raise LedgerError("VALIDATION_ERROR", "Amount must be positive.")
    return result


def decimal_text(value: str | Decimal, *, positive: bool = False) -> str:
    number = decimal_value(value, positive=positive)
    if number == 0:
        return "0"
    text = format(number, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if number == 0 else text


def book_amount(value: Decimal) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise LedgerError("VALIDATION_ERROR", "Book amount must be a finite Decimal.")
    with localcontext() as ctx:
        ctx.prec = 80
        try:
            rounded = value.quantize(Decimal("1e-18"), rounding=ROUND_HALF_EVEN)
        except InvalidOperation:
            raise LedgerError(
                "VALIDATION_ERROR",
                "Book amount exceeds supported precision.",
                "PRECISION_LIMIT",
            ) from None
    if value > 0 and rounded == 0:
        raise LedgerError(
            "VALIDATION_ERROR",
            "Positive book amount rounds to zero at supported precision.",
            "PRECISION_LIMIT",
        )
    return decimal_value(rounded, positive=True)
