# THESAGRA --- Engineering Decisions and Open Questions

This document is the source of truth for technical decisions. Update it
when a decision is made; do not silently turn a proposal into a
requirement.

## 1. Product decisions already established

  -----------------------------------------------------------------------
  Topic                               Current direction
  ----------------------------------- -----------------------------------
  Product name                        THESAGRA

  Product designation                 THESAGRA DBMS

  Product category                    Unified Database System

  Tagline                             Relational storage. Graph
                                      intelligence. Binary persistence.

  Primary data model                  Relational-first

  Graph capability                    Native graph model/traversal
                                      integrated with relational data

  Graph terminology                   Graph query/traversal; not GraphQL

  Binary capability                   Store and retrieve images, PDFs,
                                      and other binary assets

  Binary design direction             Dedicated blob subsystem with
                                      relational metadata

  Background work                     Distinct worker responsibilities,
                                      initially in-process where
                                      practical

  Connectivity goal                   Server, network protocol,
                                      connection strings, and language
                                      drivers

  Intended clients                    Python, Node.js/TypeScript, and PHP

  Intended use                        Reusable data layer for future
                                      applications
  -----------------------------------------------------------------------

## 2. Proposals, not final decisions

  -----------------------------------------------------------------------
  Topic                   Candidate direction     Why it remains open
  ----------------------- ----------------------- -----------------------
  Initial implementation  Python prototype; Rust  Must balance learning,
  language                for later               implementation speed,
                          performance-critical    and systems-level
                          components              goals.

  Storage page size       Fixed-size pages        Exact size and layout
                                                  need benchmarking and
                                                  format design.

  Index structure         B+ Tree                 Alternatives and
                                                  workload requirements
                                                  should be evaluated.

  Graph physical model    Nodes and edges backed  A separate graph store
                          by relational storage   may be justified only
                          initially               by measured needs.

  Blob layout             Metadata in relational  Cross-subsystem
                          tables; bytes in        atomicity and recovery
                          dedicated chunk storage must be designed.

  Network transport       TCP with a versioned    Message format,
                          framed protocol         security, and
                                                  compatibility need
                                                  specification.

  SQL scope               Deliberate SQL subset   Full SQL compatibility
                          first                   is out of scope
                                                  initially.

  Graph query syntax      Bounded traversal API   Syntax should follow
                          first; Cypher-inspired  stable graph semantics.
                          patterns later          

  Worker deployment       In-process tasks first  Separate processes add
                                                  coordination and
                                                  failure complexity.

  Concurrency             Begin with a simple     Multi-writer support
                          documented model        must follow transaction
                                                  and recovery design.
  -----------------------------------------------------------------------

## 3. Decisions to make before implementation expands

### Initial implementation selections

**D-001 selected: Python**

- Status: Accepted
- Date: 2026-11-25
- Rationale: Python provides fast iteration for the first storage and query
  prototypes while database internals are being validated.
- Consequence: Systems-level components may be replaced or extended later.
  On-disk and wire formats will remain versioned and independently specified.

**D-002 selected: first format**

- Status: Accepted
- Date: 2026-11-25
- Rationale: The smallest milestone needs fixed-size pages, a format marker,
  page IDs, payload lengths, and payload checksums.
- Selected format: 4096-byte pages, big-endian fields, `TSG1` magic,
  format version 1, and CRC32 payload checksums.
- Consequence: The format is not production-ready. Future decisions for
  free-space management, allocation reuse, compaction, and upgrade behavior
  remain open.

### D-001 --- Implementation language

Questions: - Is the first goal learning database internals with fast
iteration? - Is systems-level memory control required from the first
milestone? - Will a later Rust implementation preserve the same on-disk
and protocol contracts?

Possible approach: prototype core concepts in Python, then use Rust for
components where profiling and correctness justify it. Avoid rewriting
prematurely.

### D-002 --- On-disk format

Specify: - Page size. - Page header fields. - Database format version. -
Byte order and integer encoding. - Checksums. - Page allocation and
free-space tracking. - Record layout. - Upgrade and compatibility
policy.

### D-003 --- Transaction model

Specify: - Single-writer or multi-writer behavior. - Isolation levels. -
Locking or alternative concurrency control. - WAL record types. - Commit
durability. - Recovery ordering. - Checkpoint behavior.

### D-004 --- Graph semantics

Specify: - Node and edge identity. - Labels and relationship types. -
Property types and null behavior. - Directionality. - Multiple edges
between the same nodes. - Traversal depth and result limits. -
Transaction behavior across relational and graph records. - Query
language and result shape.

### D-005 --- Blob consistency

Specify: - Maximum object size. - Chunk size. - Upload/finalization
protocol. - Checksums. - Atomicity between blob bytes and metadata. -
Interrupted upload cleanup. - Object deletion and garbage collection. -
Backup/restore behavior.

### D-006 --- Client protocol and URI

Specify: - URI grammar and escaping. - Authentication method. - Protocol
handshake and versioning. - Parameter and type encoding. - Result
framing. - Error codes. - Timeouts and cancellation. - TLS and
remote-access defaults.

### D-007 --- Driver contract

Specify common behavior for: - Connect and disconnect. - Query and
parameter binding. - Transactions. - Result iteration. - Error types. -
Blob upload/download. - Graph operations. - Connection pooling.

## 4. Architecture decision record template

Use one file per significant decision, for example
`docs/decisions/ADR-0001-storage-language.md`.

``` text
# ADR-XXXX: Decision title

Status: Proposed | Accepted | Superseded
Date:
Owners:

## Context
What problem or constraint requires a decision?

## Options considered
1.
2.
3.

## Decision
What was selected?

## Consequences
Benefits, costs, risks, and migration implications.

## Validation
What experiment or test will confirm the decision?
```

## 5. Rules for changing decisions

-   Record the reason, not just the chosen technology.
-   Separate measured evidence from assumptions.
-   Record rejected alternatives when they were seriously considered.
-   Revisit a decision when new requirements or measurements invalidate
    its assumptions.
-   Version any change that affects on-disk data, wire protocol, SQL
    semantics, or driver behavior.
