# Open Questions

- **Q1 — Component name.** `lexicon` is the working name (D1). Owner may
  prefer `trilingual`, `langsys`, or other. Decide before P0 code lands.
- **Q2 — Japanese register.** Assumed: brokerage/securities-industry
  standard (証券会社の標準用語, e.g. 平均取得単価, 実現損益, 保有銘柄).
  Alternative would be casual/app-style Japanese. Owner confirmation wanted
  before seeding the glossary's ja column.
- **Q3 — Default language on first load.** Currently assumed zh (matches
  `meta.default: "zh"`). Could instead follow `navigator.language`.
- **Q4 — Server-emitted strings.** FastAPI error `detail` strings reach the
  UI verbatim today (e.g. import failures). P3 sketch is `{key, params}`
  responses; until then these remain untranslated. Acceptable for v1?
- **Q5 — Do instrument/account display names ever get localized?** Current
  answer: no, data is data (out of scope, 00 §5). But e.g. market names
  (東証/NYSE) sit on the boundary. Revisit when it hurts.
- **Q6 — Distillation cadence.** "Every ~30–50 corrections" is a guess;
  tune with real usage.
- **Q7 — Should `ui-common` glossary domain exist at all**, or is
  ui-common vocabulary purely catalog-level? Leaning: catalog-only unless a
  common word turns out to need enforcement.
