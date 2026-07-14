"""Portfolio records application layer (v2).

Historical holdings tracking: trades are the single source of truth for
positions; 'opening' snapshots anchor accounts whose earlier history is
unavailable and 'checkpoint' snapshots are reconciled against (never override
trades). Cost basis + realized P&L support average/FIFO/LIFO/lowest-cost-first,
dividend cash flows are recorded per account, and summaries convert across
currencies via the manually maintained fx_rates table.

Swap seams for v3 (see docs/portfolio-records-v2_zh-Hans.md):
- providers.RecordsStore — replace instrument methods with an
  instrument_manager adapter (id mapping via identity.py + instrument_aliases).
- fx.FxProvider — replace the manual fx_rates table with a live source.
- A future PriceProvider seam adds marks / market value / unrealized P&L.
"""

from .cost_basis import calculate_position
from .import_service import import_dividends_csv, import_trades_csv, import_trades_text
from .models import CostMethod, HoldingRow, PortfolioSummary, SnapshotKind, Trade
from .service import PortfolioRecordsService

__all__ = [
    "CostMethod",
    "HoldingRow",
    "PortfolioRecordsService",
    "PortfolioSummary",
    "SnapshotKind",
    "Trade",
    "calculate_position",
    "import_dividends_csv",
    "import_trades_csv",
    "import_trades_text",
]
