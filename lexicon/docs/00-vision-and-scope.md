# Lexicon — Vision and Scope

Status: design v1 (branch `trilingual-v1`)

## 1. What this is

`lexicon` is Vihara's trilingual (Simplified Chinese / Japanese / English) language
system. It is a repo-level component, sibling to `portfolio_manager`,
`instrument_manager`, `ledger`, etc., and serves every present and future GUI
in the monorepo.

It has four responsibilities:

1. **Glossary** — a human-curated, single-source-of-truth table of financial
   terminology in zh/ja/en. The canonical rendering of every important domain
   term lives here and nowhere else.
2. **Message catalogs** — per-app UI string tables (keys → zh/ja/en text),
   each entry carrying a *context annotation* describing where and how the
   string appears.
3. **AI translation pipeline** — generate and verify catalog entries with an
   LLM, constrained by the glossary, style rules, and past corrections.
4. **Correction loop** — every human override is captured in an append-only
   log; the log is periodically distilled into style rules and glossary
   additions so that the system needs progressively less human review *and*
   progressively lighter AI prompting.

## 2. Why (problem statement)

- The current web UI (`portfolio_manager/portfolio_manager/web/`) hardcodes a
  mix of Chinese and English strings in HTML/JS — no locale switching, no
  consistency guarantee (e.g. "Holdings" heading next to "持仓数量" column).
- Vihara is a lifelong personal system that will grow many GUIs. Retrofitting
  i18n later gets more expensive with every screen added.
- Financial terminology is precision-critical and context-sensitive.
  Generic i18n tooling and generic LLM translation both fail here for the
  same reason: **no context**. "均价" is "Avg Cost" as a column header but
  "average cost method" when naming the cost algorithm; "実現損益" is the
  correct Japanese brokerage register while a literal "実現された利益と損失"
  is wrong.
- Therefore the design centers on *context capture* and a *self-improving
  feedback loop*, not just string tables.

## 3. Non-negotiable principles

- **Text-canonical.** All data (glossary, catalogs, corrections, style rules)
  lives as line-oriented text files in git, consistent with the ledger v2 /
  pm-records v3 stack. Git is the versioning, diffing, and backup layer.
  Databases, if ever needed, are disposable projections.
- **Glossary is law.** When a message contains a glossary term, its
  translation must use the glossary rendering. This is mechanically checked,
  not left to model goodwill.
- **Human override is terminal.** A human-`locked` entry is never rewritten
  by AI. AI proposes; humans dispose.
- **Every correction is training data.** Overrides are logged append-only
  with before/after/reason. Nothing about a correction is ever lost.
- **Prompts must not grow unboundedly.** Raw corrections are periodically
  *distilled* into compact style rules; the prompt uses rules + a small
  retrieved sample of corrections, not the whole history.
- **Zero build-step frontend.** The runtime is a tiny vanilla-JS loader over
  compiled static JSON bundles; it must work with the current no-bundler
  FastAPI + static-files setup.

## 4. In scope (v1)

- zh-Hans / ja / en. Schema reserves room for more languages but v1 tooling
  targets exactly these three.
- UI strings for `portfolio_manager` web app (first consumer).
- Glossary seeded from existing domain models and UI (~50–100 terms).
- CLI-driven pipeline (extract / translate / check / review / distill /
  build / stats).

## 5. Out of scope (v1)

- Translating markdown documentation (docs remain English-only per the
  repo-wide decision; the historical `*_zh-Hans.md` pattern is frozen).
- Translating user *data* (account names, instrument names, notes). Data is
  displayed as stored. Instrument display names may later join via
  `instrument_manager`, not via lexicon.
- A web-based editing UI (P3; CLI review comes first).
- Pluralization/gender grammar machinery (CLDR plural rules). zh/ja have no
  plural forms and en usage in this app is simple; a `{n}` placeholder plus
  explicit variant keys covers v1. Revisit only if a real case appears.

## 6. Component layout

```
lexicon/
  docs/                      # this design
  glossary/                  # L0: term SSOT, one JSONL per domain
    portfolio.jsonl
    accounting.jsonl
    derivatives.jsonl
    ui-common.jsonl
  catalogs/                  # L1: per-app message catalogs
    portfolio_web.jsonl
  corrections/               # L2: append-only override log
    corrections.jsonl
  style/                     # L3: distilled per-language style rules
    zh.md  ja.md  en.md
  lexicon/                   # Python package (pipeline + build)
  runtime/                   # i18n.js (vanilla JS runtime, copied/served per app)
  pyproject.toml
```

Layer numbering mirrors the instrument_manager habit: lower layers are more
canonical. L0 (glossary) constrains L1 (catalogs); L2 (corrections) feeds
L3 (style rules) which feed back into how L1 gets generated.

## 7. Document map

- `10-glossary.md` — term schema, domains, seeding, governance
- `20-catalogs-and-runtime.md` — message schema, key naming, fallback,
  build output, vanilla-JS runtime, FastAPI integration
- `30-ai-pipeline.md` — prompt assembly, mechanical checks, review workflow,
  correction log, distillation, maturity model
- `90-roadmap-and-phasing.md` — P0–P3
- `decisions.md` / `open-questions.md` — running logs, same convention as
  other components
