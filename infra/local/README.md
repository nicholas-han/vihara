# Local Development Stack

Repo-level orchestration for the local development environment. Container
definitions live here; the schema and seed files they mount are owned by their
modules (e.g. `instrument_manager/db/`) and only referenced from here.

## PostgreSQL

Run local Postgres with:

```bash
docker compose -f infra/local/compose.yaml up -d
```

The database initializes from the instrument manager's persistence contract:

- `instrument_manager/db/schema.sql`
- `instrument_manager/db/seeds/seed_v0.sql`
- `instrument_manager/db/seeds/seed_examples.sql`

Connection string:

```text
postgresql://vihara:vihara_dev@localhost:5432/vihara
```
