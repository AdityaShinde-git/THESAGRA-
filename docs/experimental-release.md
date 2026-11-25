# THESAGRA Experimental Release Limits

THESAGRA is an experimental database prototype. It is not a production
replacement for mature database systems.

## Supported for experimental use

- Fixed-size page persistence
- Small relational SQL subset
- Inner joins and basic aggregates
- BEGIN, COMMIT, and ROLLBACK
- WAL restart recovery for the supported page model
- Persistent graph records and bounded traversal
- Chunked blob metadata and local storage
- TCP protocol with authentication and parameter binding
- Experimental named-database mode with user, role, and per-database grants
- Python SDK, plus experimental Node.js and PHP clients
- Tkinter desktop workbench and browser workbench
- In-process maintenance tasks
- Backup and restore bundles
- TLS transport support, password-hash verification, authentication
  throttling, and audit events

## Known limitations

- Transaction coordination is not a production multi-process locking model.
- Named-database mode is not production-ready: account/role administration,
  quotas, online backup, and high availability remain limited.
- Authentication does not provide mature role-based authorization.
- TLS, credentials, and audit logs still require deployment-specific review.
- Blob metadata and chunk consistency is not a fully atomic crash protocol.
- Query optimization is intentionally limited.
- Backups are prototype snapshot bundles; stop writes or coordinate them
  externally during backup.
- Node.js and PHP drivers have not completed shared conformance testing.
- Browser transfers and server operations have prototype resource limits.
- No production multi-region, sharding, replication, or consensus support exists.

## Security boundary

Run on loopback or an explicitly trusted network. Do not expose the listener
to an untrusted network until TLS certificates, credential configuration,
authorization, throttling, and audit logging have been reviewed for the
workload.

## Upgrade policy

On-disk page and wire formats are versioned. A format or protocol change must
record migration and compatibility behavior before it is released.
