# 10 — Syntax subset

The journal grammar is a compatible subset of beancount v2. Files that this
engine accepts are also accepted by bean-check/fava, with one deliberate
semantic divergence for average-cost accounts (see 20-model-and-booking).
The compatibility gate is `tests/test_bean_compat.py`.

## Supported directives

| Directive | Form |
|---|---|
| open | `DATE open ACCOUNT [CUR[,CUR...]] ["BOOKING"]` |
| close | `DATE close ACCOUNT` |
| commodity | `DATE commodity CURRENCY` (+ metadata) |
| txn | `DATE FLAG ["payee"] ["narration"] [#tag ^link ...]` + postings |
| balance | `DATE balance ACCOUNT NUMBER [~ TOL] CURRENCY` |
| price | `DATE price CURRENCY NUMBER CURRENCY` |
| note | `DATE note ACCOUNT "comment"` |
| document | `DATE document ACCOUNT "path"` |
| option | `option "name" "value"` |
| include | `include "relative/path.beancount"` |

Flags: `*` (confirmed) and `!` (pending); the `txn` keyword equals `*`.
Metadata (`key: value`, indented) attaches to any directive or posting;
values may be strings, dates, numbers, amounts, `TRUE`/`FALSE`, or bare
currencies. Comments run from `;` to end of line. Lines starting with `*`
in column 0 are org-mode headings and are skipped.

## Postings

```
  [FLAG] ACCOUNT [NUMBER CURRENCY [COST] [@ NUMBER CURRENCY | @@ NUMBER CURRENCY]]
```

- At most one posting per transaction may omit its amount (interpolated).
- COST is `{...}` (per-unit) or `{{...}}` (total), containing any of
  `NUMBER CURRENCY`, `DATE`, `"label"` in any order, comma-separated.
  On an augmentation it defines the lot; on a reduction it matches lots.
- `@` is a per-unit price annotation, `@@` a total; they drive the posting's
  weight only when no cost is present (currency conversions).

## Not supported (deliberately)

- `pad` — auto-balancing hides real errors; migrations use explicit
  `Equity:Opening` entries instead.
- `event`, `query`, `custom`, `plugin`, `pushtag`/`poptag` — extensions go
  through metadata (ADR-3).
- Arithmetic expressions in numbers (`10 * 2.5`) — literals only.
- Elided amounts in transactions containing lot reductions — a reduction's
  weight is only known after booking, so interpolation around one would be
  silently wrong; the engine rejects the combination.

## Naming rules

- Accounts: `(Assets|Liabilities|Equity|Income|Expenses)(:Component)+`,
  components start with `[A-Z0-9]` (ASCII for now; unicode components are
  an open question).
- Currencies/commodities: `[A-Z]` then up to 23 of `[A-Z0-9'._-]`, ending
  alphanumeric — beancount's currency lexeme. This is why the securities
  encoding is `US.AAPL` / `HK.0700` (market first: `0700.HK` would start
  with a digit and be illegal).
- Tags/links: `#[A-Za-z0-9\-_/.]+` / `^[A-Za-z0-9\-_/.]+` (no colons —
  trade backlinks use `^t.IBKR-123` on the link and the exact id in
  `trade_id:` metadata).
