> 2026-09-12 范围提示：费用及 canonical 纠错以 [新 PRD](../design/INVESTMENT_CHARGE_PRD.md) 为准。本文的历史草稿重建是旧工作流设想，不代表本轮已授权实施；已创建 canonical 不随 mapping 修订而重解释。

# Historical data entry working scope

Status: user-confirmed scope, 2026-09-11; fee-expensing direction confirmed; detailed contracts pending review and not implemented.

- Reconstruct from Day 1 using actual events. No opening cash/position transactions or balancing plugs.
- This branch covers daily statements, stock transactions and related cash events. Funds and options are excluded, including their trades, positions and lifecycle implementation. Monthly statements do not supply transactions.
- Broker subaccount numbers identify source evidence/deduplication namespaces; they do not automatically create internal FinancialAccounts or PositionScopes.
- Actual broker statements and all derived personal data stay under VIHARA_DATA_DIR. PDF password lives only in the gitignored root .env as FUTU_STATEMENT_PDF_PASSWORD; never put its value in code, examples, logs or reports.
- Snapshot balances, valuations, daily accrual displays and cumulative amounts are reconciliation observations, not cash events. Actual debits/credits require semantic classification.
- Before history is finalized, edit normalized source events and rebuild a dedicated historical working database, preserving account/reference configuration. Do not use REVERSAL for draft corrections; do not directly patch derived journals/lots. The rebuild tool is not implemented yet.
- Once history is frozen, genuine recording errors use the existing correction/reversal workflow. Actual refunds and business cancellations must remain real historical events even during draft processing; they are not draft data corrections.
- Excluding funds/options prevents full-account cash/holding reconciliation where their effects are present. Keep excluded-source markers and report the resulting coverage gaps; do not fabricate deposits or opening balances.

## Confirmed fee direction; detailed design pending

All fees are separate expense transactions. BUY basis and SELL proceeds use consideration only; no capitalization and no fee subtraction inside TRADE. Links preserve available evidence but never force allocation across trades. Detailed type/schema/import/reporting contracts are under review in [FEE_EXPENSING_DESIGN.md](FEE_EXPENSING_DESIGN.md), not implemented.
