# THESAGRA --- Product Vision

## 1. Product statement

THESAGRA is a relational-first database management system that aims to
provide one coherent platform for structured relational records,
graph-shaped relationships, and binary assets such as images and
documents.

The product should be usable as the primary data layer for applications
built in different programming languages. A developer should be able to
run a THESAGRA server, create a database, connect using a connection
string, execute queries, and store or retrieve both records and files
through supported client libraries.

## 2. Problem and motivation

Application developers often combine several systems to handle
relational records, relationship traversal, and binary assets. THESAGRA
explores whether these capabilities can be presented through one
consistent database platform while retaining clear internal boundaries
and sound engineering principles.

The goal is not to claim that one engine is automatically better than
established specialized databases. The goal is to build a deeply
understood, extensible database system that can eventually serve real
projects after it has earned reliability through testing.

## 3. Product goals

-   Build a persistent storage engine that writes data to disk and can
    read it after restart.
-   Provide a relational model with tables, rows, schemas, constraints,
    indexes, and SQL-like queries.
-   Support transactions and crash recovery before claiming safe
    concurrent production use.
-   Represent graph entities and relationships and provide graph
    traversal/query capabilities.
-   Store large binary objects using a dedicated, database-managed
    subsystem.
-   Expose a stable client/server interface over a network connection.
-   Provide connection strings, authentication, session handling, and
    language drivers.
-   Add background workers for maintenance and other asynchronous
    database tasks.
-   Provide a CLI, diagnostics, metrics, backup and restore workflows,
    and documentation.
-   Keep the system modular enough to evolve without rewriting every
    subsystem.

## 4. Intended users and use cases

### Primary users

-   The project owner, as the database engineer and maintainer.
-   Developers building applications that need relational data, graph
    relationships, and binary assets.
-   Future contributors who need clear subsystem boundaries, tests, and
    documentation.

### Example application use cases

-   A knowledge or memory system with concepts, documents, tags, and
    relationships.
-   A project-management application with users, projects, tasks,
    permissions, and attachments.
-   A content platform that stores structured metadata and images or
    documents.
-   An application that needs relational queries and graph traversal
    over connected entities.

These are target use cases, not guarantees of current performance or
suitability.

## 5. Product principles

1.  **Correctness before performance.** A fast database that loses or
    corrupts data is not successful.
2.  **Relational foundation.** Graph and binary features must integrate
    without weakening relational semantics.
3.  **Explicit boundaries.** Query processing, storage, transactions,
    networking, and background work have distinct responsibilities.
4.  **Observable behavior.** Errors, query plans, resource usage, and
    worker activity should be inspectable.
5.  **Incremental delivery.** Every milestone should produce a runnable,
    testable artifact.
6.  **Documented compatibility.** Supported SQL, protocol versions, and
    driver behavior must be explicit.
7.  **Safe defaults.** Authentication, parameter binding, access
    control, and backup guidance must be designed rather than bolted on.

## 6. Product boundaries and non-goals

The first versions are not intended to:

-   Replace PostgreSQL, MySQL, or mature distributed databases on
    performance or feature breadth.
-   Promise horizontal sharding, multi-region replication, or
    distributed consensus in the initial release.
-   Claim full PostgreSQL or MySQL wire-protocol compatibility.
-   Implement every SQL standard feature.
-   Treat GraphQL as the graph query language. GraphQL is an API query
    language; graph traversal may use a Cypher-inspired syntax or
    another explicitly specified language.
-   Store arbitrary large files as ordinary inline table fields by
    default.
-   Claim production readiness before durability, recovery, security,
    concurrency, and backup tests pass.

## 7. Definition of success

A meaningful early success is a local database server that can:

1.  Create a database and tables.
2.  Insert, query, update, and delete records.
3.  Persist data across process restarts.
4.  Enforce basic constraints.
5.  Execute transactions with documented guarantees.
6.  Recover correctly from tested crash scenarios.
7.  Store and retrieve binary assets.
8.  represent and traverse graph relationships.
9.  Accept remote client connections through a documented protocol.
10. Be used by at least one external application through a supported
    driver.

A later release should add additional language drivers, operational
tooling, performance baselines, security hardening, backup/restore, and
a compatibility policy.
