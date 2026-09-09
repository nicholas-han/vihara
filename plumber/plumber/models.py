"""SDK-independent, exact value types. Raw account IDs never cross this API."""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol


def decimal(value) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("Invalid decimal value") from None
    if not result.is_finite():
        raise ValueError("Non-finite decimal value")
    return result


class Unavailable(RuntimeError):
    """Authoritative evidence unavailable; messages contain only safe reason codes."""


class UnknownResult(Unavailable):
    """A mutation may have reached the broker. Never blindly retry."""


@dataclass(frozen=True)
class Request:
    intent: str
    symbol: str
    side: str
    kind: str
    quantity: Decimal
    price: Decimal | None


@dataclass(frozen=True)
class Order:
    id: str
    intent: str
    symbol: str
    side: str
    kind: str
    quantity: Decimal
    price: Decimal | None
    filled: Decimal
    status: str
    terminal: bool
    cancellation_source: str = "UNKNOWN"


@dataclass(frozen=True)
class Deal:
    id: str
    order_id: str
    quantity: Decimal
    price: Decimal
    at: str


@dataclass(frozen=True)
class Snapshot:
    orders: tuple[Order, ...]
    deals: tuple[Deal, ...]


class BrokerGateway(Protocol):
    def submit(self, request: Request) -> Order: ...
    def cancel(self, order_id: str) -> None: ...
    def snapshot(self, day: str) -> Snapshot: ...
    def capacity(self, symbol: str, side: str, kind: str, price: Decimal) -> Decimal: ...
    def healthy(self, symbol: str, now: datetime) -> bool: ...
    def drain(self) -> Snapshot: ...
    def close(self) -> None: ...
