"""ledger_bridge — the pm -> ledger projection (ADR-4 realized, ADR-10).

Trades, dividends and cashflows (canonical CSVs in vihara-data) are the
single source of truth; this package deterministically generates their
double-entry journal under ``<data>/ledger/generated/`` and reconciles the
two sides. The ledger stays generic — everything broker-specific
(accounts mapping, commodity encoding, fee conventions) lives here.

Dependency direction: portfolio_manager -> ledger, never the reverse
(mirrors instrument_manager -> asset_pricer).
"""
