# Decisions

Running log, newest last. Same convention as instrument_manager /
portfolio_manager.

- **D1 — Component name `lexicon`, repo-level.** Noun-style sibling of
  `ledger`/`forecaster`; owns glossary + catalogs + pipeline + runtime for
  all apps. (Rename is cheap until code lands; flagged to owner.)
- **D2 — Text-canonical storage.** Glossary/catalogs/corrections as sorted
  JSONL in git; style rules as markdown; runtime bundles as committed
  generated JSON. No database. Consistent with ledger v2 stack.
- **D3 — Languages zh-Hans / ja / en, peer model.** No global source
  language; per-entry, per-language provenance (`human`/`ai`/`ai_verified`).
  Fallback for missing text: entry's human-source language → en → zh,
  resolved at build time.
- **D4 — Context annotation is mandatory** on every catalog entry, English,
  including UI constraints. `check` fails empty contexts.
- **D5 — Glossary is mechanically enforced** (canonical rendering must
  appear in translations of messages containing the term), `locked` entries
  only.
- **D6 — Corrections are append-only JSONL with required reasons.** Never
  edited or deleted; `distilled` flag moves them out of the retrieval pool
  but not out of history.
- **D7 — In-context learning only, no fine-tuning.** The feedback loop is
  glossary + size-capped style rules + retrieved corrections in the prompt.
  Portable across model generations, zero MLOps.
- **D8 — Distillation with hard size budget** (~1–2k tokens per style file)
  is the mechanism that keeps prompts light as corrections accumulate.
- **D9 — Vanilla-JS runtime, no build step, no i18n library.** ~80-line
  `i18n.js` + static per-language JSON bundles + `data-i18n` attributes.
  Fits the existing FastAPI/static setup; libraries (i18next etc.) bring
  plural/ICU machinery this project doesn't need and a dependency it
  doesn't want.
- **D10 — Draft (`proposed`) translations ship by default** in built
  bundles (personal tool; visible drafts aid review). `--locked-only`
  available.
- **D11 — No plural/gender machinery in v1**; explicit variant keys or
  phrasing that sidesteps it.
- **D12 — Docs about lexicon are English-only**, per repo-wide decision;
  the trilingual output of the system is data, not docs.
