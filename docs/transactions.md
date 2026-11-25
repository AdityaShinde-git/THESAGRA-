# Initial Transaction and Recovery Model

## Durability contract

THESAGRA Phase 4 supports:

- `BEGIN`
- `COMMIT`
- `ROLLBACK`
- Write-ahead logging for changed data pages
- Recovery of committed page snapshots after restart
- Rejection of uncommitted and rolled-back WAL changes

An acknowledged commit is durable after the WAL commit record and affected page
writes are fsynced. The initial implementation does not yet promise checkpoint
truncation, standby replication, or distributed commit guarantees.

## Isolation

The first prototype is single-writer and process-local:

- Only one transaction can be active on an engine.
- Transaction changes are staged in memory.
- `SELECT` can observe staged changes.
- `ROLLBACK` discards staged pages.
- Other processes and engines are not a supported concurrent transaction
  coordination mechanism.
- A later lock or concurrency-control implementation must replace this
  documented limitation.

## WAL format

The WAL is a separate length-framed file with a `TSGWAL1` magic header.
Each record contains a transaction ID, record type, and JSON payload.
Page snapshots use base64 encoding in the JSON payload.

Committed recovery replays only page snapshots belonging to transactions with
a `COMMIT` record. `ROLLBACK` and interrupted transactions are ignored.
