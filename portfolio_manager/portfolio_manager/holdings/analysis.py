"""Portfolio analysis consumes the Investment Ledger's reconciled balances."""

from datetime import date

from ledger.investment.api import Queries
from .integrations.market import MarketRepository, value


class HoldingsService:
    def __init__(self, store=None, *, queries=None, market=None, catalog=None):
        # Keep the previous constructor for callers outside the Web composition.
        if store is not None:
            queries = queries if queries is not None else Queries(store)
            market = market if market is not None else MarketRepository(store)
            catalog = catalog if catalog is not None else store.catalog
        if queries is None or market is None or catalog is None:
            raise TypeError("HoldingsService requires queries, market and catalog")
        self.ledger = queries
        self.market = market
        self.catalog = catalog

    def holdings(self, as_of=None, include_zero=False):
        result = self.ledger.balances(as_of, include_zero)
        functional = self.ledger.configuration()["functional_currency"]
        quotes = self.market.snapshot(
            result["as_of"] or date.today().isoformat(),
            functional,
            [r["observable_id"] for r in result["investments"]],
            [r["currency"] for r in result["cash"]],
        )
        return value(result, quotes, self.catalog)
