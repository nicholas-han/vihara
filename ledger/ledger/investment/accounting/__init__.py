"""Investment accounting contracts; no dependency on legacy ledger CRUD."""

ACCOUNT_DEFINITIONS = (
    ("CASH", "ASSET", "DEBIT"),
    ("INVESTMENT", "ASSET", "DEBIT"),
    ("REALIZED_TRADE_PNL", "INCOME", "CREDIT"),
    ("DIVIDEND_INCOME", "INCOME", "CREDIT"),
    ("FX_ADJUSTMENT_RESERVE", "EQUITY", "CREDIT"),
    ("EXTERNAL_CAPITAL_FLOW", "EQUITY", "CREDIT"),
)
