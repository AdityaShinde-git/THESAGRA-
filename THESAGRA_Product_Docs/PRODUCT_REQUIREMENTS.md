# THESAGRA --- Product Requirements

This document lists desired product capabilities. Requirements are
grouped by priority:

-   **P0 --- Foundation:** required before the first useful database
    milestone.
-   **P1 --- Core product:** required for the intended integrated
    database.
-   **P2 --- Advanced:** valuable capabilities for later iterations.
-   **Future:** deliberately outside the initial implementation.

Priority does not imply that a feature is already implemented.

## 1. Database and catalog management

  -----------------------------------------------------------------------
  ID                      Priority                Requirement
  ----------------------- ----------------------- -----------------------
  DB-001                  P0                      Create, list, open, and
                                                  drop databases through
                                                  an administrative
                                                  interface.

  DB-002                  P0                      Persist database
                                                  metadata and schemas.

  DB-003                  P0                      Create, alter, rename,
                                                  and drop tables.

  DB-004                  P0                      Support defined column
                                                  types, nullability, and
                                                  defaults.

  DB-005                  P1                      Support
                                                  schemas/namespaces and
                                                  catalog inspection.

  DB-006                  P1                      Provide explicit
                                                  database and schema
                                                  versioning/migration
                                                  behavior.
  -----------------------------------------------------------------------

## 2. Relational engine

  -----------------------------------------------------------------------
  ID                      Priority                Requirement
  ----------------------- ----------------------- -----------------------
  REL-001                 P0                      Store and retrieve
                                                  typed rows.

  REL-002                 P0                      Support INSERT, SELECT,
                                                  UPDATE, and DELETE.

  REL-003                 P0                      Support filtering,
                                                  projection, ordering,
                                                  and limits.

  REL-004                 P1                      Support primary keys
                                                  and unique constraints.

  REL-005                 P1                      Support foreign keys
                                                  and referential
                                                  integrity.

  REL-006                 P1                      Support inner joins and
                                                  common aggregate
                                                  operations.

  REL-007                 P1                      Support indexes,
                                                  initially with a B+
                                                  Tree or a justified
                                                  alternative.

  REL-008                 P1                      Provide a query planner
                                                  and executor with
                                                  inspectable plans.

  REL-009                 P2                      Add additional join
                                                  algorithms, statistics,
                                                  and cost-based
                                                  optimization.

  REL-010                 P2                      Expand SQL syntax in
                                                  documented, versioned
                                                  increments.
  -----------------------------------------------------------------------

## 3. Transactions and durability

  -----------------------------------------------------------------------
  ID                      Priority                Requirement
  ----------------------- ----------------------- -----------------------
  TX-001                  P0                      Define the durability
                                                  contract for
                                                  acknowledged writes.

  TX-002                  P1                      Implement transaction
                                                  boundaries: BEGIN,
                                                  COMMIT, and ROLLBACK.

  TX-003                  P1                      Implement write-ahead
                                                  logging (WAL) before
                                                  claiming crash-safe
                                                  transactions.

  TX-004                  P1                      Recover committed data
                                                  after process restart
                                                  and tested crash
                                                  scenarios.

  TX-005                  P1                      Define and test
                                                  isolation and
                                                  concurrency behavior.

  TX-006                  P1                      Implement locking or
                                                  another documented
                                                  concurrency-control
                                                  mechanism.

  TX-007                  P2                      Add checkpoints, log
                                                  truncation, and
                                                  recovery diagnostics.

  TX-008                  P2                      Add backup and restore,
                                                  including consistency
                                                  checks.
  -----------------------------------------------------------------------

## 4. Graph capabilities

Graph functionality is a graph data model and query capability. It is
not GraphQL.

  -----------------------------------------------------------------------
  ID                      Priority                Requirement
  ----------------------- ----------------------- -----------------------
  GR-001                  P1                      Represent nodes with
                                                  stable identifiers,
                                                  labels/types, and
                                                  properties.

  GR-002                  P1                      Represent directed
                                                  edges with source,
                                                  target, relationship
                                                  type, and properties.

  GR-003                  P1                      Enforce valid
                                                  references between
                                                  edges and nodes.

  GR-004                  P1                      Support graph traversal
                                                  and bounded path
                                                  exploration.

  GR-005                  P1                      Support useful indexes
                                                  for node lookup and
                                                  edge adjacency.

  GR-006                  P1                      Define how graph data
                                                  participates in
                                                  relational
                                                  transactions.

  GR-007                  P2                      Provide a documented
                                                  graph query syntax,
                                                  potentially
                                                  Cypher-inspired MATCH
                                                  patterns.

  GR-008                  P2                      Support variable-length
                                                  paths, filters, and
                                                  graph projections with
                                                  defined limits.

  GR-009                  P2                      Provide
                                                  explain/diagnostic
                                                  output for graph
                                                  queries.
  -----------------------------------------------------------------------

### Graph consistency requirements

-   Graph entities must have stable identity.
-   Edge endpoints must reference existing nodes unless an explicitly
    documented deferred-validation mode exists.
-   Node, edge, and relational changes should share transaction
    semantics where supported.
-   Traversal must have configurable depth/row limits to avoid unbounded
    work.
-   The product must distinguish graph traversal syntax from GraphQL API
    operations.

## 5. Binary and file storage

  -----------------------------------------------------------------------
  ID                      Priority                Requirement
  ----------------------- ----------------------- -----------------------
  BIN-001                 P1                      Store binary objects
                                                  through a dedicated
                                                  blob subsystem.

  BIN-002                 P1                      Store metadata such as
                                                  object ID, filename,
                                                  MIME type, byte length,
                                                  checksum, and
                                                  timestamps.

  BIN-003                 P1                      Upload and retrieve
                                                  binary data through
                                                  client APIs.

  BIN-004                 P1                      Support streaming or
                                                  chunked transfer for
                                                  large objects.

  BIN-005                 P1                      Verify object integrity
                                                  using checksums.

  BIN-006                 P1                      Define transactional
                                                  behavior between blob
                                                  metadata and blob
                                                  contents.

  BIN-007                 P2                      Support deduplication
                                                  only if its correctness
                                                  and lifecycle semantics
                                                  are clearly defined.

  BIN-008                 P2                      Support safe deletion,
                                                  orphan detection, and
                                                  garbage collection.

  BIN-009                 P2                      Support configurable
                                                  object-size limits and
                                                  storage quotas.
  -----------------------------------------------------------------------

The initial design preference is a hybrid model: metadata is queryable
through relational tables, while bytes are managed by a dedicated blob
subsystem. The actual physical layout remains an engineering decision.

## 6. Server, protocol, and connectivity

  ------------------------------------------------------------------------------------------------
  ID                      Priority                Requirement
  ----------------------- ----------------------- ------------------------------------------------
  NET-001                 P1                      Run as a server process listening on a
                                                  configurable host and port.

  NET-002                 P1                      Define a versioned client/server wire protocol.

  NET-003                 P1                      Support multiple client sessions.

  NET-004                 P1                      Support authentication and secure credential
                                                  handling.

  NET-005                 P1                      Provide a documented connection-string format,
                                                  for example
                                                  `thesagra://user:password@host:port/database`.

  NET-006                 P1                      Support parameterized queries/prepared
                                                  statements.

  NET-007                 P1                      Define error codes, timeouts, cancellation, and
                                                  connection lifecycle behavior.

  NET-008                 P2                      Support TLS for remote connections.

  NET-009                 P2                      Support connection pooling in client drivers.

  NET-010                 P2                      Define protocol negotiation and
                                                  backward-compatibility policy.
  ------------------------------------------------------------------------------------------------

A custom `thesagra://` URI does not imply compatibility with PostgreSQL
or MySQL drivers. Such compatibility would require implementing the
relevant wire protocol separately.

## 7. Client drivers and developer experience

  -----------------------------------------------------------------------
  ID                      Priority                Requirement
  ----------------------- ----------------------- -----------------------
  SDK-001                 P1                      Provide a Python
                                                  driver.

  SDK-002                 P1                      Provide a
                                                  Node.js/TypeScript
                                                  driver.

  SDK-003                 P2                      Provide a PHP driver.

  SDK-004                 P1                      Expose query execution,
                                                  parameter binding,
                                                  transactions, and
                                                  errors consistently.

  SDK-005                 P1                      Expose blob
                                                  upload/download APIs.

  SDK-006                 P2                      Expose graph query and
                                                  traversal APIs.

  SDK-007                 P2                      Publish versioning,
                                                  installation, and
                                                  compatibility
                                                  documentation.
  -----------------------------------------------------------------------

## 8. Worker system

Workers perform asynchronous or maintenance tasks. They must not bypass
transaction, locking, or storage invariants.

  -----------------------------------------------------------------------
  ID                      Priority                Requirement
  ----------------------- ----------------------- -----------------------
  WRK-001                 P1                      Define a task queue and
                                                  worker lifecycle.

  WRK-002                 P1                      Support retry policies
                                                  and bounded retry
                                                  counts.

  WRK-003                 P1                      Make retryable tasks
                                                  idempotent or protect
                                                  them against duplicate
                                                  effects.

  WRK-004                 P1                      Expose worker health,
                                                  task status, and
                                                  failures.

  WRK-005                 P2                      Add index-maintenance
                                                  tasks.

  WRK-006                 P2                      Add blob cleanup and
                                                  garbage-collection
                                                  tasks.

  WRK-007                 P2                      Add compaction,
                                                  checkpoint, and
                                                  maintenance tasks.

  WRK-008                 P2                      Allow selected workers
                                                  to move from in-process
                                                  execution to separate
                                                  processes when
                                                  justified.
  -----------------------------------------------------------------------

Potential worker roles include index maintenance, blob maintenance,
compaction/cleanup, checkpointing, and recovery support. Query execution
should not automatically be split into separate processes; execution
placement must be justified by measurements and consistency
requirements.

## 9. Administration and observability

  ------------------------------------------------------------------------------
  ID                      Priority                Requirement
  ----------------------- ----------------------- ------------------------------
  OPS-001                 P1                      Provide a CLI to start, stop,
                                                  inspect, and administer the
                                                  server.

  OPS-002                 P1                      Provide structured logs and
                                                  useful error messages.

  OPS-003                 P1                      Expose basic metrics:
                                                  connections, queries, latency,
                                                  storage, and worker state.

  OPS-004                 P1                      Provide
                                                  database/table/index/catalog
                                                  inspection commands.

  OPS-005                 P2                      Provide query-plan inspection
                                                  and slow-query diagnostics.

  OPS-006                 P2                      Provide backup, restore,
                                                  integrity-check, and
                                                  maintenance commands.

  OPS-007                 P2                      Provide an optional
                                                  administrative UI only after
                                                  the core server interface is
                                                  stable.
  ------------------------------------------------------------------------------

## 10. Security

-   Authenticate clients before allowing database access.
-   Never store plaintext passwords.
-   Use parameter binding rather than string-concatenated SQL.
-   Define database-level and object-level authorization.
-   Restrict administrative operations.
-   Avoid exposing filesystem paths or arbitrary file access through
    blob APIs.
-   Define safe network defaults and TLS requirements for remote
    deployment.
-   Audit security-sensitive operations.
-   Document threat assumptions and known limitations.

## 11. Quality attributes

-   **Correctness:** deterministic, testable semantics for types,
    constraints, transactions, and queries.
-   **Durability:** acknowledged committed writes survive the failures
    covered by the documented contract.
-   **Consistency:** integrity constraints remain true after normal
    operations and recovery.
-   **Concurrency:** simultaneous clients cannot silently corrupt shared
    state.
-   **Performance:** benchmarked against published test workloads; no
    unsupported performance claims.
-   **Maintainability:** modular source code, subsystem contracts, and
    architecture decision records.
-   **Portability:** document supported operating systems and filesystem
    assumptions.
-   **Operability:** provide logs, metrics, backup/restore, and
    diagnostic commands.
-   **Compatibility:** version the protocol, drivers, catalog, and
    on-disk format deliberately.

## 12. Release gates

A release must not be called production-ready merely because basic
queries work. At minimum, release gates should include:

-   Automated unit, integration, and regression tests.
-   Persistence and crash-recovery tests.
-   Concurrency and transaction tests.
-   Corruption and integrity checks.
-   Authentication and authorization tests.
-   Backup/restore validation.
-   Resource and load benchmarks.
-   Documented limitations and upgrade procedures.
