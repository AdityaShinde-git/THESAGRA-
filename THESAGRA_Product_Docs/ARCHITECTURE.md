# THESAGRA --- Proposed Architecture

## 1. Architecture summary

THESAGRA is proposed as a modular, relational-first database server. The
relational model is the primary foundation. Graph capabilities build on
shared identity, catalog, transaction, and storage services. Binary
objects use a dedicated subsystem with relational metadata.

The architecture below is a target direction. It should be simplified
during the first implementation rather than created all at once.

``` text
Applications
  |-- Python driver
  |-- Node.js / TypeScript driver
  |-- PHP driver
  `-- CLI
        |
        v
Client / Server Protocol
        |
        v
Server: listener, authentication, sessions, connection lifecycle
        |
        v
SQL / Graph Query Front End
  |-- Lexer and parser
  |-- Semantic validation
  |-- Query planner
  `-- Query executor
        |
        v
Shared database services
  |-- Catalog and schema manager
  |-- Transaction manager
  |-- Lock / concurrency manager
  |-- WAL and recovery
  |-- Type system
  `-- Buffer pool and page manager
        |
        +-------------------+-------------------+
        |                   |                   |
        v                   v                   v
Relational engine      Graph subsystem      Blob subsystem
tables / rows          nodes / edges        metadata / chunks
indexes / joins        traversal / paths    streaming / checksums
        |                   |                   |
        +-------------------+-------------------+
                            |
                            v
                    Persistent storage
                    data files / indexes / WAL
                            ^
                            |
                    Background task system
```

## 2. Main subsystem responsibilities

### 2.1 Client/server layer

Responsibilities:

-   Listen on a configurable TCP endpoint.
-   Authenticate clients.
-   Create and manage sessions.
-   Decode protocol messages and validate message sizes.
-   Route requests to the query front end.
-   Return structured results and errors.
-   Handle timeouts, cancellation, and disconnects.

The network layer must not directly manipulate storage pages. It should
call well-defined engine interfaces.

### 2.2 Protocol

Define a versioned binary or framed message protocol. It should specify:

-   Handshake and protocol version.
-   Authentication exchange.
-   Database/session selection.
-   Query submission and parameter encoding.
-   Result metadata and row encoding.
-   Transaction commands.
-   Blob streaming messages.
-   Error codes and diagnostics.
-   Cancellation and connection termination.

The connection URI is a client configuration format, not the wire
protocol itself.

Example target URI:

``` text
thesagra://username:password@localhost:5439/database_name
```

Credentials should be URL-encoded where required and should not be
logged. Production deployments should prefer secret injection or secure
configuration rather than embedding passwords in source code.

### 2.3 Query front end

Separate query handling into stages:

1.  Lexing/tokenization.
2.  Parsing into an abstract syntax tree (AST).
3.  Name and type resolution.
4.  Semantic validation.
5.  Logical plan construction.
6.  Physical plan selection.
7.  Execution.
8.  Result encoding.

Start with a deliberately small SQL subset. Expand the grammar only when
the executor and tests support the new feature.

Graph query syntax should be a separately documented language or a
clearly defined SQL extension. Do not call a graph pattern language
GraphQL.

### 2.4 Relational engine

Responsibilities:

-   Table and row representation.
-   Column types and null semantics.
-   Primary/unique/foreign-key constraints.
-   Scans, filters, projections, and joins.
-   Index access.
-   Aggregation and sorting.
-   Integration with transaction and catalog services.

The relational engine should use storage interfaces rather than depend
on raw file operations throughout the codebase.

### 2.5 Graph subsystem

A reasonable first representation is relationally managed node and edge
records:

-   Node: stable ID, label/type, properties.
-   Edge: stable ID, source node ID, target node ID, relationship type,
    properties.

Potential logical schema:

``` sql
nodes(
  node_id,
  label,
  properties
)

edges(
  edge_id,
  source_node_id,
  target_node_id,
  relationship_type,
  properties
)
```

This is a conceptual schema, not a final physical layout or supported
SQL syntax.

The graph subsystem should provide:

-   Node lookup by ID and selected properties.
-   Edge lookup by source, target, and relationship type.
-   Bounded traversal.
-   Path result representation.
-   Optional graph-pattern parser and planner in a later milestone.

Graph writes should use the same transaction and durability services as
relational writes wherever the product promises atomic cross-model
operations.

### 2.6 Blob subsystem

Use a hybrid logical model:

-   Relational metadata: object ID, name, MIME type, byte length,
    checksum, timestamps, ownership, and optional application metadata.
-   Blob storage: raw bytes, managed chunks, and storage references.

Required internal operations:

-   Create object / begin upload.
-   Append or write chunks.
-   Finalize and verify checksum.
-   Read a range or stream an object.
-   Mark for deletion.
-   Reconcile metadata and physical storage.
-   Garbage-collect safe orphans.

Blob metadata and bytes create a cross-subsystem consistency problem.
Define a transaction and recovery strategy before promising atomic
upload behavior.

### 2.7 Storage engine

The storage engine is the foundation and should be developed first.

Potential components:

-   Page format and page IDs.
-   File manager.
-   Page allocator.
-   Buffer pool.
-   Slotted-page or other row-page layout.
-   Record serialization.
-   Index pages and B+ Tree.
-   WAL.
-   Checkpointing and recovery.

Do not finalize page size, endianness, checksums, alignment, or on-disk
versioning casually. Document them and add compatibility tests.

### 2.8 Transaction and concurrency services

Responsibilities:

-   Transaction IDs and lifecycle.
-   Commit/rollback.
-   Logging and recovery.
-   Locking or another concurrency-control strategy.
-   Isolation semantics.
-   Deadlock handling if lock-based concurrency is used.
-   Visibility rules for readers and writers.

The initial engine may begin single-process and single-writer. This is a
deliberate simplification, not a production concurrency claim.

### 2.9 Worker system

Workers handle asynchronous maintenance and queued tasks. Start
in-process where possible. Separate processes only when isolation,
workload, or operational requirements justify it.

Every task needs:

-   Stable task ID.
-   Task type and payload schema.
-   State and timestamps.
-   Retry policy.
-   Idempotency strategy.
-   Error details.
-   Observability.

Workers must respect storage and transaction invariants. They must not
independently edit database files without coordination.

## 3. Suggested source layout

``` text
thesagra/
├── docs/
├── server/
│   ├── listener/
│   ├── protocol/
│   ├── auth/
│   └── sessions/
├── query/
│   ├── lexer/
│   ├── parser/
│   ├── ast/
│   ├── planner/
│   └── executor/
├── catalog/
├── relational/
├── graph/
├── blobs/
├── transactions/
├── concurrency/
├── storage/
│   ├── files/
│   ├── pages/
│   ├── allocator/
│   ├── buffer_pool/
│   ├── indexes/
│   └── wal/
├── workers/
├── drivers/
│   ├── python/
│   ├── node/
│   └── php/
├── cli/
├── tests/
└── benchmarks/
```

This is a conceptual module map. The first prototype may use a smaller
layout.

## 4. Data and request flow

### Relational query

1.  Client sends a parameterized query.
2.  Server authenticates and identifies the session.
3.  Parser creates an AST.
4.  Semantic validation resolves tables, columns, and types.
5.  Planner creates an execution plan.
6.  Executor requests records through storage/index interfaces.
7.  Transaction services enforce visibility and consistency.
8.  Protocol encodes the result for the client.

### Graph traversal

1.  Client submits a supported graph query or traversal API call.
2.  Graph front end validates labels, relationship types, and traversal
    bounds.
3.  Planner selects node/edge lookup strategies.
4.  Traversal uses graph indexes and storage interfaces.
5.  Transaction services enforce the defined visibility rules.
6.  Results are returned as node, edge, or path records.

### Blob upload

1.  Client requests an upload session.
2.  Server validates authorization, declared size, and limits.
3.  Blob subsystem receives chunks and calculates a checksum.
4.  Blob subsystem finalizes the object.
5.  Metadata is committed using the documented consistency protocol.
6.  Client receives an object identifier and metadata.

## 5. Architectural constraints

-   No subsystem should bypass the transaction manager for operations
    that promise transactional behavior.
-   Only storage components should own low-level page and file mutation.
-   The query executor should depend on storage interfaces, not
    hard-coded file layouts.
-   Background workers must coordinate with foreground transactions.
-   Blob data must not be exposed through arbitrary filesystem paths.
-   Network input must be treated as untrusted and size-limited.
-   On-disk and wire formats must be versioned independently.
-   Cross-model atomicity must be explicitly specified and tested.

## 6. Architecture evolution

Start with a single-process prototype. Add a network server after local
storage and query execution are reliable. Add workers only when there
are real background tasks. Add separate processes, replication,
sharding, and distributed coordination only when a demonstrated
requirement justifies their complexity.
