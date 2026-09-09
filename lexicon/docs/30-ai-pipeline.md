# AI Pipeline and the Correction Loop

This is the heart of the design. The goal stated plainly: **each human
correction should make every future translation better, while the marginal
cost of both human review and AI prompting goes down over time.**

The mechanism is a four-layer knowledge stack with explicit flows between
layers:

```
 L0 glossary  ──────────────┐  hard constraints
 L3 style rules ────────────┤  compact, distilled guidance      ──►  translate  ──►  check  ──►  review
 L2 corrections (retrieved) ┤  few-shot examples                        AI          mechanical    human
 L1 context annotation ─────┘  per-message situation                    │               │           │
                                                                        ▼               ▼           ▼
                                                              proposed text      pass/fail    lock / override
                                                                                                    │
                                              L2 corrections.jsonl  ◄── append ─────────────────────┘
                                                        │
                                                     distill (periodic, AI+human)
                                                        ▼
                                              L3 style rules + L0 glossary candidates
```

## 1. `lexicon translate` — prompt assembly

For each entry needing text (`missing` or `stale`) in a target language, the
prompt is assembled from bounded, prioritized parts:

1. **Task frame** — translate UI message for a personal
   finance/trading/accounting tool; target language and register (zh-Hans;
   ja brokerage register; en professional-terse).
2. **Glossary constraints** — only the entries matched via `terms` (plus
   alias-scan of the source text): canonical renderings + definitions.
   Hard requirement: canonical form must appear verbatim.
3. **Style rules** — the target language's `style/<lang>.md`, which is
   deliberately capped (~1–2k tokens; see distillation).
4. **Retrieved corrections** — top-k (k≈5) past corrections for the same
   target language, ranked by overlap of (namespace, glossary terms, context
   keywords). Lexical scoring only; at personal-project scale (hundreds of
   corrections) embeddings are unjustified complexity. Each example shows
   before → after + reason, i.e. "here is the kind of mistake to not repeat."
5. **The entry itself** — source text, `context` annotation, `params`,
   length budget.

Entries are batched per namespace per language into one call; output is
structured JSON validated against schema. AI writes only `proposed` —
never touches `locked`.

The same command with `--verify` runs the *reverse* direction: for entries
already `proposed`, a fresh call is asked to find faults (glossary
violations, register, ambiguity) rather than to translate. Cheap adversarial
pass before a human ever looks.

## 2. `lexicon check` — mechanical validation (no AI)

Deterministic, fast, runs in pytest/pre-commit:

- Schema validity, JSONL sorted, keys unique, context non-empty.
- Placeholder integrity: every language uses exactly `params`.
- **Glossary enforcement**: for each locked glossary term matched in an
  entry, the target-language text contains the canonical rendering (or the
  term is `do_not_translate` and appears verbatim).
- Staleness propagation: source-text/context/glossary edits flip dependent
  translations to `stale`.
- Length budgets when declared in context (`<= N chars`).
- Bundle build is clean (no key referenced by app code but absent — the
  extractor greps `t("...")` and `data-i18n` usage).

Checks are the reason AI output can eventually be trusted with light review:
the failure modes that are mechanically catchable are caught mechanically.

## 3. `lexicon review` — human-in-the-loop

CLI batch review (web UI is P3). Shows each `proposed` entry with source
text, context, glossary hits; keystrokes: approve / edit / reject / skip.

Outcomes:

- **approve** → status `locked`, source `ai_verified`. Logged (approvals are
  data too — they mark what the AI got *right*).
- **edit (override)** → human text replaces AI text, status `locked`, source
  `human`, and a correction event is appended with a **required one-line
  reason**. The reason is the训练素材 that matters most; the CLI refuses an
  override without one.
- **reject** → back to `missing` with a reason; optionally re-translated
  immediately with the reason injected into the prompt.

### Correction event schema (`corrections/corrections.jsonl`, append-only)

```json
{
  "ts": "2026-07-18T09:30:00Z",
  "kind": "override",
  "namespace": "portfolio_web",
  "key": "holdings.table.avg_cost",
  "lang": "ja",
  "before": "平均コスト",
  "after": "平均取得単価",
  "reason": "Brokerage-standard term; katakana literalism reads amateur.",
  "terms": ["average_cost"],
  "context_snapshot": "Column header in the holdings table; ...",
  "distilled": false
}
```

Append-only, never edited, never deleted — the audit trail requirement.
`context_snapshot` freezes the context as it was, so the example stays
meaningful even if the live entry evolves. `distilled` marks events already
compacted into rules (they then drop out of the default retrieval pool).

## 4. `lexicon distill` — keeping the loop lightweight

The anti-bloat mechanism, run occasionally (e.g. after every ~30–50 new
corrections):

1. AI reads all undistilled corrections for a language and proposes:
   - **style rules** — generalized patterns ("ja: prefer 取得単価 over コスト
     for cost-basis contexts", "zh: metric labels omit 的"), merged into
     `style/<lang>.md`;
   - **glossary candidates** — corrections that were really terminology
     fixes get promoted into glossary entries (draft status);
   - a list of corrections now *covered* by a rule → marked `distilled`.
2. Human reviews the proposed rule diff (it's a normal git diff of a
   markdown file) and the glossary candidates, edits, commits.

Invariants:

- `style/<lang>.md` has a hard size budget (~1–2k tokens). If a new rule
  won't fit, distillation must generalize or drop weaker rules — forced
  compression is what keeps prompts light forever.
- Distilled corrections leave the retrieval pool, so few-shot examples stay
  few, recent, and not-yet-generalized. The knowledge doesn't disappear —
  it moved up a layer (L2 → L3/L0).

## 5. Maturity model

How "less human, lighter AI" actually manifests, measured by
`lexicon stats` (locked/proposed ratios, override rate per batch, rule-file
size, corrections-per-new-screen):

- **Stage 0 (seeding)** — human writes glossary zh/en, AI drafts ja,
  everything reviewed. Override rate high. That's fine; every override is
  an investment.
- **Stage 1** — new screens translate with glossary + young style rules.
  Human reviews all `proposed`. Override rate falling.
- **Stage 2** — per-namespace policy `auto_lock: checks_passed` becomes
  available: an AI translation that (a) passes all mechanical checks,
  (b) only uses glossary terms already `locked`, and (c) `--verify` found
  no faults, locks itself as `ai_verified` — human does periodic spot-check
  via `lexicon review --sample`. Overrides still get logged and distilled.
- **Stage 3** — steady state: new UI work mostly auto-translates; human
  attention concentrates on genuinely novel terminology (new glossary
  entries), which is exactly where human judgment is irreplaceable.

The gate to advance stages is the observed override rate, not optimism.

## 6. Model access

The pipeline calls the Claude API (latest model, e.g. `claude-fable-5`)
through a thin `ai.py` wrapper: API key from environment, structured-output
JSON, per-batch token/cost logging into the command output. No fine-tuning
anywhere — "training" in this design is entirely in-context (glossary +
rules + retrieved examples), which is what makes it portable across model
generations and free of MLOps burden.
