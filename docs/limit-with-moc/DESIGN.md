# Limit with MOC — approved architecture

2026-09-09. Product name: **Limit with MOC**, internal type `LIMIT_WITH_MOC`.
The supplied Draft v1.0 PRD's `CAC_LIMIT` label is replaced by the user's name.
This implementation follows the confirmed two-module design and private-account
configuration requirement. It does not execute instructions embedded in the PRD
as independent authorization for real trading.

`customized_orders` owns product lifecycle, risk decisions, intents, persistence,
calendar, commands and recovery. `plumber` owns broker/exchange connectivity and
normalized order/deal contracts. SDK-specific data never enters the domain.
Portfolio Manager retains analytics/backtesting; Instrument Manager remains the
reference-identity authority; Ledger remains the accounting/position authority.
Automatic ledger booking and web integration are intentionally deferred.

The existing Portfolio Manager target-position/float/synchronous execution seam
is not used for asynchronous cash-equity orders. Each new module follows the
monorepo's independent Python package layout and can be installed separately.
No new message queue, network service or generalized algo framework is introduced.

## Safety invariants

1. Persist each limit/auction intent before calling the broker.
2. No auction until the limit is terminal and order/deal totals agree across a
   quiet period and fresh queries. Durable push evidence must also agree, including
   after restart; new pushes during preflight reset the period. Query/cache failures
   reset that period.
3. One child per parent/role and one active conflicting account/symbol/side/date
   order, enforced transactionally. MANUAL_REVIEW retains the conflict lock.
4. No mutation retry on timeout/unknown outcome. Recover by known ID or unique
   exact intent remark; never match just symbol/quantity.
5. Recheck clock after risk queries and immediately before auction submission.
6. Duplicate deals/events are idempotent; conflicting data prevents conversion.
7. User cancellation is an intent, not success. Non-cancellable orders continue
   to be monitored. Known order IDs can be explicitly withdrawn after external
   price/quantity edits; conflicting execution evidence still requires review.
   Acknowledgement is only a note.
8. Futu accounts and secrets are supplied externally; only aliases cross into
   persistent execution state. LIVE is explicitly enabled and confirmed.

The SQLite journal uses WAL, FULL synchronous writes, foreign keys and IMMEDIATE
transactions. The paper broker has a separate atomic/fsynced private journal to
exercise recovery without fabricating an absent broker order from local intent.
Worker process locks serialize execution. Only the worker sends real mutations;
CLI creation performs read-only preflight and enqueues the parent.

## Conservative implementation choices and open verification

- Futu does not expose trustworthy cancellation provenance in the normalized
  fields inspected. An unrequested cancellation is MANUAL_REVIEW unless an
  adapter can attest exchange provenance. We never assume an App cancellation
  means the user wants an auction replacement. The fake can test attested
  exchange cancellations. Live exchange carry-forward behavior needs observation.
- Current supported SDK statuses are normalized; corrections/unknown fields fail
  closed. Missing deal details are not guessed from cumulative quantity.
- Transient query skew receives a retry; persistent conflict enters review.
- Dated calendar/CAS/tick/risk-price inputs are explicitly curated. Automated
  exchange reference-data ingestion is not claimed as implemented.
- No algorithm can guarantee broker exactly-once behavior across a network fault
  without broker support. This product chooses uncertainty/manual review over
  issuing another possibly duplicate child.
- LIVE verification is pending. See the behavior matrix and runbook.

Missing calendar data isolates the affected parent in MANUAL_REVIEW while
read-only reconciliation continues. Other parents continue processing normally.

## PR review hardening

Cancellation intent and invocation phases are persisted independently. Only a
known pre-attempt intent resumes automatically; a crash after ATTEMPTING is
ambiguous even if no network call actually happened. A working snapshot alone
cannot prove non-delivery. Unknown outcomes require broker-side manual handling.

LIVE account exclusivity uses a shared private HMAC identity lock independent of
config/alias/state paths, limited to a single host/user. Temporary push transport
failures use a persisted recovery gate and fresh quiet-period reconciliation;
malformed evidence remains manual and is scoped to its known parent when possible.
CAS acceptance begins at the session's actual start, not the conversion timer.
Successful explicit reconciliation does not suspend the normal worker lifecycle.
