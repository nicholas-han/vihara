"""iv_rv_arb — implied-vs-realized variance statistical arbitrage (project layer).

Composes:
  - asset_pricer / discrete replication  -> model-free implied variance σ²(IV)
  - forecaster                           -> E[σ²(RV)] (HAR-RV baseline)
  - portfolio_manager                    -> backtest engine + accounting

The economic bet is the variance risk premium: short variance when implied is
rich vs the realized-variance forecast, long when cheap.

Decisions: see ../../portfolio_manager/docs (ADR-8, Q1-Q7).
"""
