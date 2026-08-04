# Roadmap and Phasing

## P0 — Foundations + first real screen (MVP)

Goal: the portfolio web page runs in all three languages, driven by files
that follow the final schemas. No review tooling yet; AI use is manual/basic.

1. Package scaffold: `lexicon/` with `pyproject.toml`, models
   (glossary entry, catalog entry, correction event as dataclasses +
   (de)serialization + validation), pytest wiring into root `pytest.ini`.
2. Glossary seed: ~50–80 terms from records/models.py, current web UI,
   trades import template, ledger vocabulary (zh/en human, ja AI-drafted
   and hand-reviewed once).
3. Catalog `portfolio_web.jsonl` + `ui_common.jsonl`: convert
   `web/index.html` + `app.js` fully to keys, writing real context
   annotations along the way.
4. `lexicon check` (schema, sort, placeholders, glossary enforcement,
   context non-empty) and `lexicon build` (fallback resolution → committed
   `web/lang/*.json`).
5. `runtime/i18n.js` + language switcher in the toolbar; `Intl` formatting
   keyed to active language.
6. `lexicon translate` v1: batch prompt with glossary constraints + context;
   no retrieval, no verify pass yet.

Exit criteria: switching 中文/日本語/English live on the holdings page;
`lexicon check` green in pytest; all shipped ja text at least `proposed`.

## P1 — Correction loop

1. `lexicon review` CLI (approve / edit+reason / reject); correction events
   appended; statuses and provenance updated.
2. Staleness propagation in `check` (glossary/context edits → `stale`).
3. Retrieval-augmented `translate` (top-k undistilled corrections) and
   `--verify` adversarial pass.
4. `lexicon extract`: grep `t("…")` / `data-i18n` usage vs catalog for
   missing/orphan keys.

Exit criteria: a full cycle — edit UI, extract, translate, review with at
least one override, rebuild — takes minutes and leaves an audit trail.

## P2 — Self-improvement

1. `lexicon distill`: corrections → style-rule diffs + glossary candidates,
   size-capped `style/<lang>.md`, `distilled` marking.
2. `lexicon stats`: override rate, locked ratio, rule-file size trend.
3. Per-namespace `auto_lock: checks_passed` policy + `review --sample`
   spot-checking.

Exit criteria: measured override rate on a new batch under ~10% before
enabling auto-lock anywhere.

## P3 — Later, when justified

- Web editing UI for glossary/catalog/review (FastAPI + the same vanilla
  stack), replacing CLI review for comfort.
- Server-emitted message keys (FastAPI errors as `{key, params}`).
- Additional namespaces as GUIs appear (pricer, ledger, forecaster).
- Embedding-based retrieval only if lexical retrieval demonstrably fails.
- Additional languages if life demands them (schema already permits).
