from portfolio_manager.portfolio import InMemoryPortfolio
from portfolio_manager.strategy import Fill, MarketSnapshot


def test_apply_fills_cash_positions_equity():
    pf = InMemoryPortfolio(0.0)
    pf.apply_fills([Fill("a", 2.0, 10.0, 1.0)])
    assert pf.position("a") == 2.0
    assert pf.cash == -21.0           # -(2*10) - 1 fee
    assert pf.fees_paid == 1.0
    snap = MarketSnapshot(t=0, marks={"a": 12.0})
    assert pf.equity(snap) == 3.0     # -21 + 2*12
