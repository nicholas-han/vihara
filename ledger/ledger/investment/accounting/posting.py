"""Pure journal values. The caller owns precision and the database transaction."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Line:
    ledger_account_code: str
    side: str
    book_amount: Decimal
    financial_account_id: int | None = None
    native_currency: str | None = None
    native_amount: Decimal | None = None
    position_id: int | None = None

    def inverse(self):
        from dataclasses import replace

        return replace(self, side="CREDIT" if self.side == "DEBIT" else "DEBIT")


def cash(side, book, account, currency, amount):
    return Line("CASH", side, book, account, currency, amount)


def balance_difference(lines, account):
    difference = sum(
        (l.book_amount if l.side == "DEBIT" else -l.book_amount for l in lines),
        Decimal(0),
    )
    if difference:
        lines.append(
            Line(account, "CREDIT" if difference > 0 else "DEBIT", abs(difference))
        )
    return lines
