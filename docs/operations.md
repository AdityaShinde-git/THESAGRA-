# Phase 9 Operations

## Task queue

Tasks are persisted in a sibling SQLite queue:

```text
<database>.tasks.sqlite3
```

Each task has a stable ID, type, JSON payload, state, attempts, timestamps,
retry limit, idempotency key, and error details.

Supported maintenance task types:

- `blob_reconcile`
- `integrity_check`
- `graph_integrity_check`
- `checkpoint`

Duplicate execution can be prevented with an idempotency key.

## Worker

The initial worker is in-process. It:

- Recovers interrupted `running` tasks to `queued`
- Claims one task at a time
- Applies bounded retries
- Moves exhausted tasks to `dead`
- Exposes task counts and execution metrics

## CLI

```powershell
python -m thesagra.cli sample.db --worker
python -m thesagra.cli sample.db --integrity
python -m thesagra.cli sample.db --backup backup.zip
python -m thesagra.cli sample.db --restore backup.zip
```

## Backup contract

`--backup` creates a ZIP containing the database file, WAL, task queue, and
blob directory. `--restore` extracts that bundle to the selected database
path.

Backups are a prototype consistency mechanism, not a substitute for an atomic
online snapshot service. Stop the server or coordinate writes before taking
an operational backup.
