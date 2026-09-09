# L1 — Message Catalogs and Runtime

## 1. Message catalog schema

One JSONL file per app namespace: `catalogs/portfolio_web.jsonl` (later
`catalogs/pricer_web.jsonl`, `catalogs/ledger_web.jsonl`, …), plus
`catalogs/ui_common.jsonl` shared by all apps. One object per line, sorted
by `key`.

```json
{
  "key": "holdings.table.avg_cost",
  "context": "Column header in the holdings table; per-share average cost under the selected cost method. Keep short (<= 10 chars zh/ja).",
  "terms": ["average_cost"],
  "params": [],
  "text": {
    "zh": {"value": "均价", "source": "human", "status": "locked"},
    "en": {"value": "Avg Cost", "source": "human", "status": "locked"},
    "ja": {"value": "平均取得単価", "source": "ai", "status": "proposed"}
  },
  "updated": "2026-07-18"
}
```

Field notes:

- `key` — `area.section.slug`, semantic English snake/dot case. The
  namespace (= filename) is not repeated inside the key. Keys are stable
  identifiers; renaming is a scripted refactor across catalog + app code.
- `context` — **mandatory, English.** Where the string appears, what it
  means, plus UI constraints (length budget, capitalization, tone). This is
  the single highest-leverage field in the whole system: it is what
  generic i18n lacks and what makes AI translation accurate. `lexicon check`
  fails any entry with an empty context.
- `terms` — glossary ids known to occur in this message. Populated
  automatically by alias matching, hand-correctable. Drives glossary
  enforcement.
- `params` — placeholder names, e.g. `["file_name"]` for
  `"正在导入 {file_name}..."`. Checker verifies every language's text uses
  exactly these placeholders.
- `text.<lang>.source` — `human` | `ai` | `ai_verified`.
- `text.<lang>.status` — lifecycle: `missing` → `proposed` (AI wrote it) →
  `locked` (human approved or human wrote it) | `stale` (source text,
  context, or a referenced glossary term changed after locking).

Per-entry, the human typically authors one language first (usually zh, the
author's native register, or en). That language is the entry's *source text*;
the other two are AI-filled and reviewed. There is no global source language
— provenance is tracked per language per entry.

### Variants instead of grammar machinery

No plural/gender engine in v1. Where en needs singular/plural, use explicit
keys (`import.result.row_one`, `import.result.row_other`) or phrasing that
avoids the problem ("Rows: 3"). zh/ja don't inflect. Revisit if this ever
gets painful.

## 2. Build output

`lexicon build` compiles catalogs into flat runtime bundles, one per
language per app, written into the app's static dir:

```
portfolio_manager/portfolio_manager/web/lang/
  zh.json      {"holdings.table.avg_cost": "均价", ...}
  ja.json
  en.json
  meta.json    {"languages": ["zh","ja","en"], "default": "zh", "version": "<git-sha-or-hash>"}
```

Build rules:

- Bundles merge the app namespace over `ui_common` (app wins on collision —
  collision is also a check warning).
- **Fallback is resolved at build time**, not runtime: a `missing`/`proposed`
  value falls back to the entry's human-source text, else en, else zh. The
  runtime therefore never sees a missing key at bundle level; `proposed`
  (unreviewed AI) text *is* shipped — this is a personal tool, seeing draft
  ja in the UI is acceptable and even useful for review. A build flag
  `--locked-only` exists for stricter moods.
- Bundles are generated artifacts but **committed** (text-canonical repo,
  no CI build step; same spirit as committed projections elsewhere).

## 3. Vanilla-JS runtime (`runtime/i18n.js`)

A single ~80-line ES module, no dependencies, served like any other static
file. API surface:

```js
await initI18n({ base: "/static/lang", fallback: "zh" });  // reads localStorage, then meta.default
t("holdings.table.avg_cost")                 // -> "均价"
t("import.progress", { file_name: f.name })  // "{file_name}" interpolation
setLanguage("ja")                            // persists to localStorage, re-applies DOM, updates <html lang>
currentLanguage()
```

Static HTML is translated declaratively — markup carries keys, `applyDom()`
walks them on init and on language switch:

```html
<span data-i18n="holdings.table.avg_cost"></span>
<input data-i18n-attr="placeholder:import.file_placeholder" />
```

Dynamic JS strings call `t()` directly (the current `app.js` template
literals like `` `导入失败: ${...}` `` become
`t("import.failed", { detail })`).

Language switcher: a small `<select>` in the toolbar (语言/言語/Language),
wired to `setLanguage`. Numbers and dates switch to
`Intl.NumberFormat`/`Intl.DateTimeFormat` keyed off `currentLanguage()`
(the existing `toLocaleString(undefined, …)` calls gain an explicit locale).

## 4. Backend integration

None required for v1. FastAPI already mounts the static dir; bundles are
static JSON. No translation API, no server-side rendering concerns. A future
editing web UI (P3) would add endpoints, and server-generated messages
(FastAPI error details) can later adopt catalog keys returned as
`{"key": "...", "params": {...}}` for client-side rendering — noted in
open-questions, not designed here.

## 5. Migration of the current page

P0 includes converting `web/index.html` + `app.js` to keys — it is the
proving ground. The page currently mixes languages ("Holdings" heading,
"账户" labels, "Excluding selected accounts" checkbox); every visible string
becomes a catalog entry with real context annotations written during the
conversion. This exercise also produces the first ~40 catalog entries and
stress-tests the schema before any AI is involved.
