import numpy as np

from portfolio_manager.engine import ArrayMarketData, Engine, SimulatedExecution
from portfolio_manager.portfolio import InMemoryPortfolio
from portfolio_manager.strategy import BaseStrategy, Order


class HoldOne(BaseStrategy):
    def on_bar(self, t, snapshot, portfolio):
        return [Order("x", 1.0)]


def test_engine_pnl_tracks_price_change():
    times = [0, 1, 2, 3]
    price = np.array([10.0, 11.0, 12.0, 13.0])
    market = ArrayMarketData(times, {"x": price})
    engine = Engine(market, SimulatedExecution(0.0, 0.0), InMemoryPortfolio(0.0))
    result = engine.run(HoldOne())
    # buy 1 @10 → equity = -10 + mark; with start cash 0 the curve is cumulative P&L
    assert np.allclose(result.equity, [0.0, 1.0, 2.0, 3.0])
