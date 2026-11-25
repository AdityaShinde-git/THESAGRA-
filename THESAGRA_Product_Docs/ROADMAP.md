# THESAGRA --- Development Roadmap

## Delivery philosophy

Build a sequence of working database capabilities. Each phase must have
tests and a demonstrable outcome. Do not create empty modules for every
planned feature before the first storage engine works.

## Phase 0 --- Specification and project skeleton

### Work

-   Create repository and documentation.
-   Choose implementation language and development environment.
-   Define coding conventions and test strategy.
-   Write initial architecture decision records.
-   Define a minimal binary page format proposal.

### Exit criteria

-   Project builds/runs.
-   Test runner is configured.
-   Documentation and decisions are version-controlled.
-   First milestone is narrowly defined.

## Phase 1 --- Persistent storage prototype

### Work

-   Create/open a database file.
-   Define page IDs and page headers.
-   Read and write fixed-size pages.
-   Serialize and deserialize simple records.
-   Allocate and reuse pages safely.
-   Add basic corruption checks.

### Demonstration

Write records, terminate the process, restart, and read the same
records.

### Exit criteria

-   Unit tests cover page encoding/decoding.
-   Integration tests cover persistence across restart.
-   Invalid or truncated pages fail safely.
-   On-disk format has a version marker.

## Phase 2 --- Basic relational engine

### Work

-   Catalog for databases, tables, and columns.
-   Type system.
-   Row format and table scans.
-   SQL lexer and parser for a small subset.
-   INSERT, SELECT, UPDATE, DELETE.
-   WHERE, ORDER BY, LIMIT.
-   Primary-key lookup.
-   Initial index implementation.

### Demonstration

Create tables and run basic SQL from a local CLI.

### Exit criteria

-   SQL behavior is documented.
-   Query results are deterministic.
-   Constraints and type errors are tested.
-   Data persists across restart.

## Phase 3 --- Query planning and relational features

### Work

-   AST and semantic validation.
-   Logical and physical query plans.
-   Filters and projections.
-   Joins and aggregations.
-   B+ Tree index operations if selected.
-   Explain-plan output.
-   Query regression tests.

### Demonstration

Run a multi-table join and compare indexed and non-indexed query plans.

### Exit criteria

-   Join correctness tests pass.
-   Index consistency is verified.
-   Explain output identifies chosen operations.

## Phase 4 --- Transactions and recovery

### Work

-   Transaction lifecycle.
-   WAL record format.
-   Commit and rollback.
-   Recovery procedure.
-   Locking/concurrency strategy.
-   Isolation contract.
-   Checkpoints.

### Demonstration

Run concurrent transactions, terminate the server at controlled points,
restart, and verify committed and rolled-back outcomes.

### Exit criteria

-   Crash tests pass for documented failure cases.
-   No acknowledged committed transaction is lost within the durability
    contract.
-   Isolation behavior is documented and tested.
-   Recovery is repeatable and observable.

## Phase 5 --- Graph model and traversal

### Work

-   Node and edge identity.
-   Labels/types and properties.
-   Edge endpoint integrity.
-   Adjacency indexes.
-   Bounded traversal API.
-   Graph result model.
-   Graph query syntax only after traversal semantics are stable.

### Demonstration

Create a graph of people, projects, technologies, or concepts and
traverse relationships to a specified depth.

### Exit criteria

-   Node and edge integrity tests pass.
-   Traversal depth and result limits work.
-   Graph changes obey documented transaction semantics.
-   Query language behavior is documented.

## Phase 6 --- Binary object storage

### Work

-   Blob metadata catalog.
-   Chunked object writes.
-   Streaming reads.
-   Checksums and size validation.
-   Object lifecycle and deletion.
-   Recovery/reconciliation behavior.
-   Garbage collection.

### Demonstration

Upload an image and a large test file, restart the server, retrieve
both, and verify checksums.

### Exit criteria

-   Large files do not require loading the entire object into memory.
-   Integrity checks detect altered/truncated data.
-   Metadata and object lifecycle behavior is tested.
-   Orphan cleanup cannot delete live objects.

## Phase 7 --- Server and client protocol

### Work

-   TCP listener and framing.
-   Handshake and protocol version.
-   Authentication.
-   Sessions and connection lifecycle.
-   Parameterized query messages.
-   Result and error messages.
-   Timeouts and cancellation.
-   Configurable host and port.

### Demonstration

Connect from a separate process using a THESAGRA connection URI and run
a parameterized query.

### Exit criteria

-   Protocol tests cover malformed and oversized messages.
-   Multiple sessions behave correctly within the supported concurrency
    model.
-   Credentials are not logged.
-   Connection failures return documented errors.

## Phase 8 --- Drivers and developer experience

### Work

-   Python driver.
-   Node.js/TypeScript driver.
-   PHP driver.
-   Consistent error and result APIs.
-   Transaction API.
-   Blob APIs.
-   Graph APIs.
-   Connection pooling where justified.
-   CLI administration and examples.

### Demonstration

Use the same database from Python and Node.js applications. Add PHP
connectivity after the core driver contract stabilizes.

### Exit criteria

-   Driver conformance tests pass.
-   Connection string behavior is documented.
-   Parameter binding is supported.
-   Examples work against a clean server installation.

## Phase 9 --- Workers and operations

### Work

-   Task queue and task state model.
-   Retry and idempotency.
-   Index maintenance tasks.
-   Blob cleanup.
-   Checkpoint and compaction tasks.
-   Structured logs and metrics.
-   Backup, restore, and integrity check.
-   Operational documentation.

### Demonstration

Schedule maintenance tasks, inspect worker status, stop/restart the
server, and verify safe task recovery.

### Exit criteria

-   Duplicate task execution does not cause corruption.
-   Worker failures are visible.
-   Backup/restore is tested.
-   Basic operational metrics are available.

## Phase 10 --- Hardening and experimental release

### Work

-   Security review.
-   Fuzzing of parsers and protocol boundaries.
-   Load and concurrency testing.
-   Storage corruption testing.
-   Performance benchmarks.
-   Upgrade and migration tests.
-   Documentation of limitations.

### Release gate

Call the result an experimental release until the durability, recovery,
security, backup, and compatibility requirements are demonstrated.
Production use should be limited to workloads that fit the documented
guarantees.

## Original first milestone (completed)

The initial storage milestone is complete. It created a database file,
wrote typed records to a page, reopened the file, and verified persistence.

The first milestone was:

**A program that creates a database file, writes a page containing a few
typed records, closes the file, reopens it, and reads the records back
correctly.**

It established the byte serialization, page boundaries, file I/O, and
persistence foundation used by the later phases.

## Post-Phase-10 engineering plan

Phases 0–10 describe the experimental prototype. The work below is future
hardening; it is not included in the Phase 10 completion claim.

### Phase 11 --- Blob crash consistency

**Status: in progress**

- Define metadata and byte-storage commit ordering for uploads, finalization,
  deletion, and reconciliation.
- Make interrupted operations recoverable without exposing partial objects or
  deleting live data.
- Add fault-injection tests at each persistent write boundary.

**Exit criteria:** restart recovery is repeatable and leaves metadata and blob
bytes consistent after each tested interruption point.

### Phase 12 --- Transaction coordination

- Define the supported isolation and writer model.
- Add database-scoped locking for concurrent clients and processes.
- Test transaction ordering, crash recovery, and lock cleanup.

**Exit criteria:** concurrent writes follow the documented model and do not
lose or interleave committed state.

### Phase 13 --- Authorization and deployment security

- Define roles and per-operation permissions.
- Review credential storage, TLS certificate configuration, throttling, and
  audit behavior together.
- Document secure local and network deployment profiles.

**Exit criteria:** permission boundaries and deployment controls have
  negative tests and documented operational requirements.

### Phase 14 --- Client and transport conformance

- Build a shared protocol conformance suite for Python, Node.js, and PHP.
- Verify streaming and error behavior across drivers.
- Add bounded HTTP streaming for the browser workbench.

**Exit criteria:** all supported drivers pass the same contract tests and large
  object transfers remain bounded in memory.

### Phase 15 --- Backup, restore, and format migration

- Define consistent backup snapshots while the server is active.
- Validate restore behavior for database pages, WAL, task state, and blobs.
- Add explicit on-disk and protocol migration procedures.

**Exit criteria:** repeatable backup/restore and migration tests cover every
  persistent component.

### Phase 16 --- Release qualification

- Run repeatable performance baselines, concurrency tests, parser/protocol
  fuzzing, and storage-corruption tests.
- Track failures and resource limits against documented release targets.

**Exit criteria:** release claims are backed by reproducible results; otherwise
  the limitations remain explicit and the release stays experimental.
