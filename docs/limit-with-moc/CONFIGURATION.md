# Private trading configuration

The repository contains schemas/examples only. Actual broker/exchange accounts
and connection selection belong to `~/.config/vihara/trading.toml`, or the external
path selected by `--config` / `VIHARA_TRADING_CONFIG`. Precedence: CLI, environment,
default. There is no module-local fallback and no account auto-discovery/default
account selection.

A profile is addressed by a local alias, e.g. `paper` or `hk_primary`. The
application resolves `[accounts.<alias>].connection` to an external
`[connections.<name>]` with `host`, `port`, `account_id` and optional `unlock_env`.
`plumber` receives that object in memory. The actual account ID is never stored
in the order database, custom logs, test artifacts or code. Passwords are read
only from the named environment variable and are never written into TOML or
SQLite. The SDK may retain an in-memory unlock credential for reconnects.

Only localhost OpenD is supported. The SDK/OpenD's own external configuration and
OpenD-owned logging are outside this application's storage controls; keep those
outside Git as well. Application-side SDK diagnostic loggers are disabled before
account access. We preserve safe normalized evidence, not raw account responses.

Controls enforced by the application:

- Configuration/calendar files must be regular non-symlink files, owned by the
  current user, mode 0600 (or stricter), outside any Git checkout/worktree.
- State defaults to `~/.local/state/vihara/orders/<alias>/<mode>/`, outside Git.
  Mode-specific storage prevents paper/live cross-contamination. Directories use
  0700, database/paper journal/lock use 0600; the CLI sets umask 077.
- An HMAC account binding detects accidental alias remapping without storing the
  account ID. Its random key remains in private runtime storage. Duplicate LIVE
  aliases for the same account in one configuration are rejected. A second LIVE
  worker for the same broker account is also blocked across configuration files,
  aliases, OpenD ports and state directories using a shared HMAC-named lock in
  `~/.local/state/vihara/account-locks/`. The directory/key/locks are private and
  outside Git; actual account IDs do not appear in filenames or contents. This
  scope is one host and OS user, not distributed multi-host coordination. Do not
  delete or relocate these files while workers are running.
- SQLite stores only the alias, intended security/order data, broker order/deal
  IDs, safe evidence and user notes. It is an execution journal, not a secret store.
- LIVE is off by default. Each startup and each order require explicit confirmation.
- Known raw SDK/config exception text is suppressed; inspect safe reason codes.

Repository `.gitignore` additionally excludes local config naming conventions,
`.env.*`, state, logs, database journals/WAL/SHM, and credential/key files. Templates
ending in `.example.toml`/`.example.json` remain trackable. Automated tests use
`git check-ignore` to check both exclusions and example visibility. Existing
tracked files are not made private by `.gitignore`, and `git add -f` can bypass
it; do not force-add runtime data. The primary boundary is external storage.

The calendar explicitly lists each date as FULL_DAY, HALF_DAY, CLOSED or disabled.
Executable dates need `source`, timezone-aware `verified_at`, and `valid_until`.
Instrument allowlists need dated CAS verification, lot size, the tick band for the
submitted price, and a conservative auction risk price. These are controlled
inputs, not fabricated automatic exchange data. Futu also checks current market
state, suspension and lot size before trading; cash-only buying power and
non-short sellable quantity are rechecked before conversion.
