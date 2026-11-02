---
name: database
description: Database schema design, migrations, queries and ORMs (PostgreSQL, MySQL, SQLite, MongoDB; Prisma, SQLAlchemy, Django ORM, TypeORM, Drizzle).
when_to_use: schema changes, migrations, slow queries, ORM models, data integrity issues
---
# Database engineering

1. Find the source of truth for the schema (migration files, ORM models, schema.prisma) — never edit an applied migration; create a new one with the project's tool.
2. Migrations must be reversible where the tool supports it and safe on existing data: add nullable → backfill → add constraint; avoid long locks on big tables.
3. Model integrity in the database: primary keys, foreign keys, NOT NULL, unique constraints, check constraints; indexes for frequent filters/joins/sort columns.
4. Queries: parameterized only; avoid N+1 (eager loading/joins); select only needed columns; paginate.
5. Use transactions for multi-statement changes; pick the right isolation; handle unique-violation races.
6. Performance: read the query plan (`EXPLAIN ANALYZE`) before adding indexes.
7. Verify on a local/test database only — never run destructive statements against production data. Run the migration up and down, then the test suite.
