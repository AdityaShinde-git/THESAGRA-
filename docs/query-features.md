# THESAGRA SQL Feature Status

THESAGRA runs its own SQL parser and storage engine. The SQL below is a
practical, growing subset; it does not install PostgreSQL and does not speak
the PostgreSQL wire protocol. PostgreSQL applications and drivers therefore
cannot connect unchanged.

## Supported today

### Database and schema commands

- `CREATE TABLE` with `INTEGER`/`INT`, `REAL`, `TEXT`, `BOOLEAN`, and `BLOB`
  columns
- `VARCHAR(n)` and `CHAR(n)` as length-limited text; `DATE` and `TIMESTAMP`
  as text; `DECIMAL(p,s)` and `NUMERIC(p,s)` as floating-point `REAL`
- Column `PRIMARY KEY`, `UNIQUE`, `NOT NULL`, `DEFAULT`, and
  `AUTO_INCREMENT` (integer primary keys); table-level composite primary and
  foreign keys
- `CREATE [UNIQUE] INDEX`
- `ALTER TABLE`:
  - `ADD [COLUMN] [IF NOT EXISTS]` with supported column types/defaults
  - `DROP [COLUMN] [IF EXISTS]`, with `RESTRICT` by default and `CASCADE`
    to remove dependent foreign keys/indexes
  - `RENAME COLUMN old TO new` and `RENAME TO new_table`
- `DROP TABLE [IF EXISTS] [RESTRICT|CASCADE]`; cascade removes dependent
  foreign-key constraints, not the referencing tables
- `CREATE DATABASE name` and `USE name` in named-database server mode only

### Data and queries

- Multi-row `INSERT`, `UPDATE`, and `DELETE`
- `SELECT` projections, aliases, `DISTINCT`, and chained `INNER`, `LEFT`,
  `RIGHT`, `FULL`, and `CROSS` joins; non-cross joins use equality conditions
- `WHERE` comparisons, `AND`, `IS [NOT] NULL`, `BETWEEN`, `LIKE`, `IN`
  lists, and supported scalar/`IN` subqueries
- `COUNT`, `SUM`, `AVG`, `MIN`, `MAX`, `GROUP BY`, aggregate `HAVING`,
  `ORDER BY`, and `LIMIT`
- `BEGIN`/`START TRANSACTION`, `COMMIT`, and `ROLLBACK`

See [transactions.md](./transactions.md) for the transaction and recovery
limits.

## Important semantic limits

- `DECIMAL`/`NUMERIC` do not provide exact fixed-scale arithmetic; they map to
  floating-point `REAL`.
- `DATE`/`TIMESTAMP` are text, not validated temporal values.
- Index metadata is persisted, but the current query path only uses
  in-memory primary-key indexes for equality lookups; most other filters scan
  table rows.
- `ALTER TABLE` is not allowed inside an explicit transaction. Column additions
  to populated tables need a compatible default if `NOT NULL`; unique values
  are checked against existing rows.
- Transactions are serialized per database in hosted mode and do not provide
  a mature multi-process locking/isolation model.
- The engine remains experimental and is not yet a production-ready database
  service. See [experimental-release.md](./experimental-release.md).

## Not implemented yet

Common application and migration features still missing include:

- `INSERT ... RETURNING`, `UPDATE ... RETURNING`, `DELETE ... RETURNING`
- `INSERT ... ON CONFLICT`
- `ALTER COLUMN` type/nullability/default changes and constraint management
- `DROP INDEX`, `CHECK` constraints, `SERIAL`/sequences, JSON/JSONB
- `OR`, `NOT`, `CASE`, common table expressions, `UNION`, window functions,
  views, and stored procedures
- PostgreSQL schemas, extensions, COPY, and PostgreSQL wire-protocol
  compatibility

These are tracked as incremental SQL-engine work, not as a plan to replace
THESAGRA with PostgreSQL.

## SQL work sequence

1. **Core relational SQL — implemented:** tables, constraints, CRUD, joins,
   filters, aggregates, indexes, and basic transactions.
2. **Schema migrations — implemented incrementally:** `ALTER TABLE` add/drop/
   rename operations are available with explicit dependency behavior.
3. **Application CRUD ergonomics — next:** prioritize `RETURNING` and
   `ON CONFLICT`, each with atomicity and constraint tests.
4. **Broader query language — later:** richer expressions, CTEs, views, and
   additional data types.
5. **Production readiness — separate work:** concurrency control, crash
   consistency, operational tooling, backup/restore guarantees, authorization,
   and compatibility testing must be addressed before a production claim.
