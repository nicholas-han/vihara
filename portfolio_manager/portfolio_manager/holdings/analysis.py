"""Portfolio analysis consumes the Investment Ledger's reconciled balances."""

from ledger.investment.application.service import Service as InvestmentLedger
from .integrations.market import value


class HoldingsService:
    def __init__(self, store):
        self.store = store
        self.ledger = InvestmentLedger(store)

    def holdings(self, as_of=None, include_zero=False):
        result = self.ledger.balances(as_of, include_zero)
        with self.store.read() as conn:
            return value(conn, result, self.store.catalog)
