# THESAGRA

#### UNIFIED DATABASE SYSTEM

**THESAGRA DBMS**

*Relational storage. Graph intelligence. Binary persistence.*

THESAGRA is an ambitious, relational-first database management system
intended to become a reusable data platform for future applications. Its
long-term goal is to combine relational data management, graph
relationships, and binary-object persistence behind one database server
and a consistent developer experience.

This repository contains the initial product-development documentation.
It describes the product vision, requirements, architecture direction,
roadmap, and unresolved engineering decisions. It is a product
specification---not a claim that these capabilities have already been
implemented.

## Documentation

-   [Product vision](PRODUCT_VISION.md) --- purpose, users, principles,
    scope, and success criteria.
-   [Product requirements](PRODUCT_REQUIREMENTS.md) --- functional and
    non-functional requirements.
-   [Architecture](ARCHITECTURE.md) --- proposed subsystems and how they
    fit together.
-   [Development roadmap](ROADMAP.md) --- staged implementation plan and
    acceptance criteria.
-   [Engineering decisions](ENGINEERING_DECISIONS.md) --- decisions
    made, assumptions, and questions still open.

## Product direction

THESAGRA should be:

1.  **Relational-first:** tables, constraints, indexes, joins,
    transactions, and SQL form the foundation.
2.  **Graph-capable:** nodes, edges, properties, and traversal are
    supported as first-class database concepts, not confused with
    GraphQL.
3.  **Binary-capable:** images, PDFs, and other files can be stored and
    retrieved through database-managed blob facilities.
4.  **Multi-client:** applications can connect over a documented network
    protocol using connection strings and language-specific drivers.
5.  **Reliable:** persistence, transaction safety, recovery,
    concurrency, backups, and observability are designed deliberately.
6.  **Extensible:** the architecture allows new data types, indexes,
    query features, and client drivers over time.

## Current status

**Status: Product definition / pre-implementation.**

The initial implementation language, wire protocol, exact SQL
compatibility target, on-disk format, and production-readiness criteria
remain to be decided and validated. The roadmap deliberately starts with
a small, testable storage engine rather than attempting every feature at
once.

## Naming

-   Product: **THESAGRA**
-   Product category: Unified Database System
-   Technical designation: **THESAGRA DBMS**
-   Tagline: **Relational storage. Graph intelligence. Binary
    persistence.**
