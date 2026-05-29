# Local PostgreSQL

Run local Postgres with:

```bash
docker compose -f infra/postgres/compose.yaml up -d
```

The database initializes from:

- `instrument_manager/schema.sql`
- `instrument_manager/seed_v0.sql`
- `instrument_manager/seed_initial_universe.sql`

Connection string:

```text
postgresql://vihara:vihara_dev@localhost:5432/vihara
```
