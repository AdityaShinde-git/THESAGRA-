# Phase 7 Network Protocol

## Transport

THESAGRA uses TCP with length-framed JSON payloads. Each frame is:

```text
4-byte magic: "TSGP"
1-byte protocol version
1-byte message type
4-byte big-endian JSON payload length
JSON payload
```

Maximum payload size: 1 MiB.

## Message types

- `1` request
- `2` response
- `3` cancellation

## Operations

The first operation is `handshake` with `username`, `password`, and an
optional `database`. In named-database mode, the server verifies the
credentials and the user's `CONNECT` grant before binding the session to that
database. A client may omit `database` to open a control-plane session and
list only databases it can access; database creation and user/role
administration require the system administrator. Legacy single-file mode
uses the logical name `main`. Successful handshake returns a session ID and
selected database.

The `query` operation accepts `sql`, a JSON `parameters` array, and a unique
`request_id`. Positional `?` and `$1`, `$2`, ... parameter forms are supported.

The `disconnect` operation closes and removes the session.

## Security boundary

Environment variables or server constructor arguments provide first-stage
credentials. The initial release is intended for local or explicitly trusted
network use. TLS, authorization policies, rate limits, and secure password
storage remain later work.
