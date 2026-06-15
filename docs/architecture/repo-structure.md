# Repository Structure

This monorepo will grow from one module (instrument manager) toward many
modules with heterogeneous storage and runtime needs (market data, vol surface,
backtest, order gateway, ledger, …). The layout below is designed so modules
stay self-contained now and can be extracted later with minimal churn.

## Core Principle

Separate **what a module persists** from **how environments are stood up**.

- *What a module persists* — schema, migrations, seeds, and the design of its
  storage — belongs to the module and is versioned alongside its logic.
- *How environments are stood up* — local dev orchestration and production
  infrastructure — is inherently cross-module and belongs to a repo-level
  `infra/`, organized by store/concern.

Infra **references** module-owned schema files; it never owns them. For example
`infra/local/compose.yaml` mounts `instrument_manager/db/schema.sql` rather than
holding its own copy.

## Layout

```
/docs/                         # system / company-level only
  architecture/                #   cross-cutting principles, repo structure, ADRs
  project-context/             #   founder context, business framing

/infra/                        # repo-level environment composition, by concern
  local/                       #   local dev orchestration (compose) + how-to
  <store>/                     #   (future) per-store production deploy definitions

/<module>/                     # e.g. instrument_manager/
  docs/                        #   module domain model, ERD, storage design
  db/                          #   schema.sql, seeds/, migrations/ (persistence contract)
  scripts/                     #   module tooling (generators, importers)
  <code>                       #   module implementation
```

## What Lives Where

- **Root `/docs`** — only documents that describe the whole system or business:
  architecture principles, this repo-structure doc, founder context,
  cross-cutting ADRs. Not module-specific design.
- **Module `<module>/docs`** — the module's domain model, ERD, and storage
  design. Owned by and changed with the module.
- **Module `<module>/db`** — the persistence contract: schema, seeds, and
  migrations. This is the source of truth for the module's data shape.
- **Root `/infra`** — local dev composition and (later) production IaC,
  namespaced by store. Kept central because local dev and prod topology span
  modules; namespacing keeps each store's definitions separable.

## Rationale

We start as a monorepo and a modular monolith (see
[architecture principles](principles.md)) and split into separately deployable
services later. Keeping each module's persistence contract and design docs under
the module — while keeping environment composition central but namespaced — means
a module and its infra subtree can be lifted out as a unit when that time comes,
without untangling a shared, undifferentiated infra folder.
