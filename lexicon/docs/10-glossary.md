# L0 — Glossary

The glossary is the single source of truth for domain terminology in
zh-Hans / ja / en. It is small, human-governed, and load-bearing: catalog
translations are mechanically checked against it, and it is the strongest
constraint injected into AI prompts.

## 1. What belongs in the glossary

A term earns a glossary entry when **getting it wrong would be costly or
embarrassing** and the correct rendering is not obvious:

- Financial concepts with a fixed professional rendering per language
  (已实现盈亏 / 実現損益 / realized P&L).
- Terms where the natural literal translation is wrong in at least one
  language (均价 → *not* 平均価格 in ja brokerage context but 平均取得単価).
- Vihara-specific coinages (cost method names, ledger concepts).
- Terms that must NOT be translated (FIFO, LIFO, EPS, CSV, ticker symbols).

What does *not* belong: ordinary UI vocabulary ("save", "cancel", "loading")
— that lives in catalogs under the `ui-common` namespace and needs no
per-term governance.

## 2. Entry schema

One JSON object per line (JSONL), sorted by `id`, one file per domain.
Files: `glossary/portfolio.jsonl`, `accounting.jsonl`, `derivatives.jsonl`,
`market.jsonl`, `ui-common.jsonl` (split further as domains grow).

```json
{
  "id": "realized_pnl",
  "domain": "portfolio",
  "en": "realized P&L",
  "zh": "已实现盈亏",
  "ja": "実現損益",
  "definition": "P&L crystallized by closing trades, per the active cost method; excludes dividends.",
  "aliases": {
    "en": ["realized profit and loss", "realized gains/losses"],
    "zh": ["已实现损益"],
    "ja": ["実現済み損益"]
  },
  "do_not_translate": false,
  "notes": "ja: standard brokerage register; avoid 実現された利益.",
  "source": {"en": "human", "zh": "human", "ja": "ai_verified"},
  "status": "locked",
  "created": "2026-07-18",
  "updated": "2026-07-18"
}
```

Field notes:

- `id` — stable snake_case slug, referenced by catalog entries and checks.
  Never renamed once referenced (add an alias entry instead).
- `definition` — **English only**, one or two sentences. This is the context
  the AI reads when translating any message containing the term; write it for
  a translator, not a textbook.
- `aliases` — accepted-but-non-canonical surface forms per language. Used by
  the checker to *detect* term occurrences in source text and by the AI as
  "recognize these, but emit the canonical form".
- `do_not_translate: true` — the `en` form is used verbatim in all languages
  (FIFO, EPS, CSV). `zh`/`ja` fields may still hold an explanatory gloss for
  tooltips but are not substituted into UI text.
- `source` — per-language provenance: `human` | `ai` | `ai_verified`
  (AI-proposed, human-approved).
- `status` — `draft` | `locked`. Only `locked` entries are enforced by the
  checker; `draft` entries are advisory. Locking is a human action.

## 3. Governance rules

1. **zh and en are seeded by hand** (the author is fluent; existing UI and
   model code already carry both). **ja is AI-proposed, human-reviewed** —
   review promotes `source.ja` from `ai` to `ai_verified`.
2. Editing a `locked` term's rendering is allowed (git records history) but
   the CLI (`lexicon check`) must then flag every catalog entry that used the
   old rendering as `stale`, forcing a re-translation pass. A glossary change
   is a repo-wide event, which is exactly why the glossary stays small.
3. New AI-proposed glossary candidates arrive only through `lexicon distill`
   (see 30-ai-pipeline) or manual entry — the translate step may *suggest*
   "this looks like it wants a glossary entry" but never writes one.

## 4. Seeding plan (P0)

Initial ~50–80 terms harvested from existing artifacts:

- `portfolio_manager/portfolio_manager/records/models.py` — CostMethod
  values, TradeSide, snapshot kinds, HoldingRow fields (average cost,
  realized P&L, dividends received, dividend per share, EPS, position
  source, reconciliation…).
- The current web UI strings (账户 / 市场 / 代码 / 名称 / 持仓数量 / 均价 /
  已实现盈亏 / 实收分红 / 每股分红 / 来源 / 对账不一致…).
- `trades_import_v1.csv` header vocabulary (commission, tax, settle date,
  fx rate, net amount…).
- Ledger v2 vocabulary (double-entry: account, posting, journal, debit/
  credit, balance…).
- Derivatives vocabulary from asset_pricer (option, strike, expiry, implied
  volatility, variance swap…) — seeded thin, grows when pricer GUIs appear.

Seeding is a one-time human+AI pass: AI drafts the table from these sources,
the author reviews zh/en and corrects ja, entries get locked.
