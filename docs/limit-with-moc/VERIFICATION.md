# Implementation verification — 2026-09-09

Branch: `feat/limit-with-moc`.

Full repository regression: **405 passed**, no skips. One existing
Starlette/httpx deprecation warning. Command (use your checkout's absolute path):

```sh
PYTHONDONTWRITEBYTECODE=1 IM_PYBIND_DIR="$PWD/build/holdings-im" \
  python3 -m pytest -p no:cacheprovider --tb=short
```

The Instrument Manager extension was already compiled in `build/holdings-im`.
Without this environment setting the pre-existing Ledger boundary subprocess
cannot import it. No existing module implementation was changed.

Both new Python distributions built successfully with `pip wheel --no-deps
--no-build-isolation` in temporary storage. CLI create/worker/status/cancel was
exercised end to end using private temporary configuration and a durable paper
broker. The suite verifies each external-effect restart boundary, cancellation
races, submission ambiguity, duplicate data, deadline crossing during risk
queries, auction outcomes, and configuration/privacy boundaries.

The 23 additional regression cases cover durable push/query disagreements,
restart recovery, pushes arriving during submission preflight, SDK boolean login
state and intraday query boundaries, optional submission remarks, transient
health failures after transition, explicit cancellation after external edits or
overfill, and isolation/monitoring of orders with missing historical calendars.
The two new modules' tests report **79 passed**.

`git diff --check` passed. Repository `git check-ignore --no-index` tests confirm
private configuration, .env variants, credentials, logs, database sidecars and
runtime state are excluded, while example configurations remain trackable.
Account binding tests confirm real identifiers do not enter SQLite and accidental
alias remapping fails closed. No real account configuration was created, and no
real OpenD connection, shadow trading session or live trade was performed.

Release state remains **IMPLEMENTED_NOT_LIVE_VERIFIED**. Real environment
verification requirements are tracked in `futu-live-behavior.md`.
