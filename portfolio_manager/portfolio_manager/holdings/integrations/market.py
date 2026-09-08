"""Controlled daily market observations. Never a source of historical book FX."""

from datetime import date
from decimal import Decimal, localcontext
from ledger.investment.numbers import decimal_text, decimal_value
from ledger.investment.errors import LedgerError


def import_rows(store, kind, rows):
    if kind not in ("prices", "fx"):
        raise LedgerError("VALIDATION_ERROR", "Invalid market quote type.")
    with store.transaction() as conn:
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
                    oid not in store.catalog.observables
                    or currency not in store.catalog.currencies
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
                    or base not in store.catalog.currencies
                    or quote not in store.catalog.currencies
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


def fx(conn, currency, functional, day):
    if currency == functional:
        return {"rate": "1", "as_of": day, "source": "identity"}
    row = conn.execute(
        "SELECT * FROM market_fx WHERE base_currency=? AND quote_currency=? AND as_of<=? ORDER BY as_of DESC,observation_id DESC LIMIT 1",
        (currency, functional, day),
    ).fetchone()
    return dict(row) if row else None


def value(conn, result, catalog):
    day = result["as_of"] or date.today().isoformat()
    functional = conn.execute(
        "SELECT functional_currency FROM accounting_config"
    ).fetchone()[0]
    subtotal = Decimal(0)
    unrealized = Decimal(0)
    unvalued = 0
    investment_unvalued = 0
    with localcontext() as context:
        context.prec = 120
        for kind in ("cash", "investments"):
            for row in result[kind]:
                row["market_value"] = None
                row["unrealized_difference"] = None
                row["price_as_of"] = None
                row["fx_as_of"] = None
                if kind == "investments":
                    quote = conn.execute(
                        "SELECT * FROM market_prices WHERE observable_id=? AND as_of<=? ORDER BY as_of DESC,observation_id DESC LIMIT 1",
                        (row["observable_id"], day),
                    ).fetchone()
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
                    row["asset_class"] = catalog.observables[
                        catalog.currencies[row["currency"]]
                    ].asset_class
                    native = Decimal(row["quantity"])
                rate = fx(conn, row["valuation_currency"], functional, day)
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
    return result
