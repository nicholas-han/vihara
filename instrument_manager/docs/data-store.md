# Instrument Manager — Data Store

This document fixes the storage form and production deployment shape of the
instrument manager. It is the basis for how the persistence contract in
`instrument_manager/db/` is deployed and consumed.

## Nature of the Data

Instrument manager data is **slowly-changing reference / control-plane data**:

- Low write frequency — new listings, expiries, status and lifecycle changes.
- Read-heavy but low QPS relative to market data.
- Small volume — thousands to low millions of rows, orders of magnitude smaller
  than market data, vol surfaces, or tick history.
- Not latency-critical at the database layer.

## Production Form

The authoritative store is a **small PostgreSQL instance** (or a logical database
within a shared cluster) acting as the **system of record**. It does not need to
be a large or specialized deployment.

The critical distinction is between the system of record and how hot-path
services consume it:

- **System of record (Postgres)** — durable, transactional, the single place
  instrument definitions are written and audited. Does not need to be memory-resident.
- **Hot-path consumers** (order gateway, risk checks, pricing engine) — must
  **not** query Postgres on the critical path. They load an instrument snapshot
  into an **in-process immutable cache at startup**, and refresh via change
  events or periodic reload.

The data's small size is a **feature here**: the entire instrument universe fits
comfortably in each consumer's memory. This is the opposite of market data,
which cannot be held in full and requires specialized stores.

So: the database itself need not be in memory, but the **served view is
effectively in-memory** inside each latency-sensitive consumer.

## Contrast With Other Stores

Instrument data must not share storage design or infra with high-volume,
latency-sensitive data:

| Concern        | Instrument manager            | Market data / vol surface         |
| -------------- | ----------------------------- | --------------------------------- |
| Change rate    | Low (reference/control-plane) | High (streaming/continuous)       |
| Volume         | Small                         | Very large                        |
| Storage tech   | Postgres (system of record)   | Time-series / columnar / object / in-memory |
| Hot-path use   | Snapshot to in-process cache  | Specialized readers / feed handlers |

These are designed and deployed separately, each as its own store under
`infra/` (see [repo structure](../../docs/architecture/repo-structure.md)).

## Implications

- The persistence contract — `schema.sql`, `seeds/`, and `migrations/` — is owned
  by this module under `db/`.
- Local development brings the store up via `infra/local/compose.yaml`, which
  references the module-owned schema and seeds.
- Production IaC for this store is a repo-level concern, added under `infra/`
  when needed, namespaced separately from market-data and other stores.
