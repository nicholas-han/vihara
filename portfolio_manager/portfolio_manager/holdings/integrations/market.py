"""Portfolio-owned market storage and valuation over public ledger/reference data."""

from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext
from types import MappingProxyType
from typing import Mapping

from instrument_manager.references import ReferencePort
from ledger.investment.numbers import decimal_text, decimal_value
from ledger.investment.api import LedgerError


@dataclass(frozen=True)
class MarketSnapshot:
    """Daily quotes from one read transaction, independent of database connections."""

    day: str
    functional_currency: str
    prices: Mapping[str, Mapping]
    rates: Mapping[str, Mapping]


class MarketRepository:
    """Owns market SQL in the shared database; never reads accounting tables.

    The application composition layer injects the existing transaction provider.
    Its schema validation and locking remain in effect for market operations.
    """

    def __init__(self, store):
        self._store = store
        self._catalog: ReferencePort = store.catalog

    def import_rows(self, kind, rows):
        if kind not in ("prices", "fx"):
            raise LedgerError("VALIDATION_ERROR", "Invalid market quote type.")
        with self._store.transaction() as conn:
            ids = []
            for row in rows:
                try:
                    day = date.fromisoformat(row["as_of"]).isoformat()
                except (ValueError, KeyError, TypeError):
                    raise LedgerError(
                        "VALIDATION_ERROR", "Invalid market quote date format."
                    ) from None
                source = (row.get("source") or "").strip()
                if not source:
                    raise LedgerError("VALIDATION_ERROR", "Market quotes require a source.")
                if kind == "prices":
                    oid = row.get("observable_id")
                    currency = row.get("currency")
                    price = decimal_value(row.get("price"))
                    if price < 0:
                        raise LedgerError(
                            "VALIDATION_ERROR", "Market price must not be negative."
                        )
                    if (
                        self._catalog.observable(oid) is None
                        or self._catalog.currency_observable(currency) is None
                    ):
                        raise LedgerError(
                            "REFERENCE_NOT_FOUND",
                            "Market quote Observable or Currency not found.",
                        )
                    ids.append(
                        conn.execute(
                            "INSERT INTO market_prices(observable_id,price,currency,as_of,source) VALUES (?,?,?,?,?)",
                            (oid, decimal_text(price), currency, day, source),
                        ).lastrowid
                    )
                else:
                    base, quote = row.get("base_currency"), row.get("quote_currency")
                    rate = decimal_text(row.get("rate"), positive=True)
                    if (
                        base == quote
                        or self._catalog.currency_observable(base) is None
                        or self._catalog.currency_observable(quote) is None
                    ):
                        raise LedgerError(
                            "VALIDATION_ERROR", "Invalid Market FX currency pair."
                        )
                    ids.append(
                        conn.execute(
                            "INSERT INTO market_fx(base_currency,quote_currency,rate,as_of,source) VALUES (?,?,?,?,?)",
                            (base, quote, rate, day, source),
                        ).lastrowid
                    )
            return list(map(str, ids))

    def snapshot(self, day, functional_currency, observable_ids, currencies):
        prices = {}
        rates = {}
        needed_currencies = set(currencies)
        with self._store.read() as conn:
            for observable_id in sorted(set(observable_ids)):
                row = conn.execute(
                    "SELECT * FROM market_prices WHERE observable_id=? AND as_of<=? "
                    "ORDER BY as_of DESC,observation_id DESC LIMIT 1",
                    (observable_id, day),
                ).fetchone()
                if row is not None:
                    prices[observable_id] = MappingProxyType(dict(row))
                    needed_currencies.add(row["currency"])
            for currency in sorted(needed_currencies):
                if currency == functional_currency:
                    rates[currency] = MappingProxyType(
                        {"rate": "1", "as_of": day, "source": "identity"}
                    )
                    continue
                row = conn.execute(
                    "SELECT * FROM market_fx WHERE base_currency=? AND quote_currency=? "
                    "AND as_of<=? ORDER BY as_of DESC,observation_id DESC LIMIT 1",
                    (currency, functional_currency, day),
                ).fetchone()
                if row is not None:
                    rates[currency] = MappingProxyType(dict(row))
        return MarketSnapshot(
            day, functional_currency, MappingProxyType(prices), MappingProxyType(rates)
        )


def import_rows(store, kind, rows):
    """Compatibility entry point; new callers construct MarketRepository."""
    return MarketRepository(store).import_rows(kind, rows)


def value(result, market: MarketSnapshot, catalog: ReferencePort):
    """Enrich a copy of ledger balances using a detached market snapshot."""
    result = deepcopy(result)
    day = market.day
    functional = market.functional_currency
    subtotal = Decimal(0)
    unrealized = Decimal(0)
    unvalued = 0
    investment_unvalued = 0
    with localcontext() as context:
        context.prec = 120
        for kind in ("cash", "investments"):
            for row in result[kind]:
                row["market_value"] = None
                row["native_market_value"] = None
                row["market_fx_rate"] = None
                row["unrealized_difference"] = None
                row["price_as_of"] = None
                row["fx_as_of"] = None
                if kind == "investments":
                    quantity = Decimal(row["quantity"])
                    row["average_historical_cost"] = (
                        format(Decimal(row["book_value"]) / quantity, "f")
                        if quantity
                        else None
                    )
                    quote = market.prices.get(row["observable_id"])
                    row["valuation_currency"] = quote["currency"] if quote else None
                    row["market_price"] = quote["price"] if quote else None
                    if quote is None:
                        row["valuation_status"] = "MISSING_PRICE"
                        unvalued += 1
                        investment_unvalued += 1
                        continue
                    row["price_as_of"] = quote["as_of"]
                    row["price_source"] = quote["source"]
                    native = Decimal(row["quantity"]) * Decimal(quote["price"])
                else:
                    row["valuation_currency"] = row["currency"]
                    row["asset_class"] = catalog.observable(
                        catalog.currency_observable(row["currency"])
                    ).asset_class
                    native = Decimal(row["quantity"])
                row["native_market_value"] = format(native, "f")
                rate = market.rates.get(row["valuation_currency"])
                if rate is None:
                    row["valuation_status"] = "MISSING_FX"
                    unvalued += 1
                    investment_unvalued += kind == "investments"
                    continue
                row["fx_as_of"] = rate["as_of"]
                row["fx_source"] = rate["source"]
                row["market_fx_rate"] = rate["rate"]
                amount = native * Decimal(rate["rate"])
                # Valuation is derived, may have more fractional digits than canonical storage.
                row["market_value"] = format(amount, "f")
                row["valuation_status"] = "AVAILABLE"
                subtotal += amount
                if kind == "investments":
                    difference = amount - Decimal(row["book_value"])
                    row["unrealized_difference"] = format(difference, "f")
                    unrealized += difference
        result["valuation"] = {
            "as_of": day,
            "functional_currency": functional,
            "valued_subtotal": format(subtotal, "f"),
            "unvalued_count": unvalued,
            "complete": unvalued == 0,
            "investment_unrealized_subtotal": format(unrealized, "f"),
            "investment_unrealized_complete": investment_unvalued == 0,
        }
    # Scope values inherit the exact parent quote; totals above count parent rows only.
    with localcontext() as context:
        context.prec = 120
        for row in result["investments"]:
            for scope in row.get("scopes", []):
                q, cost = Decimal(scope["quantity"]), Decimal(scope["book_value"])
                for field in (
                    "market_price",
                    "valuation_currency",
                    "market_fx_rate",
                    "price_as_of",
                    "fx_as_of",
                    "valuation_status",
                ):
                    scope[field] = row.get(field)
                scope["average_historical_cost"] = format(cost / q, "f") if q else None
                native = (
                    q * Decimal(row["market_price"])
                    if row["market_price"] is not None
                    else None
                )
                amount = (
                    native * Decimal(row["market_fx_rate"])
                    if native is not None and row["market_fx_rate"] is not None
                    else None
                )
                scope["native_market_value"] = (
                    format(native, "f") if native is not None else None
                )
                scope["market_value"] = (
                    format(amount, "f") if amount is not None else None
                )
                scope["unrealized_difference"] = (
                    format(amount - cost, "f") if amount is not None else None
                )
    return result
