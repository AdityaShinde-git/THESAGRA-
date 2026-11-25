# Python Driver Contract

## Connection

```python
from thesagra import THESAGRAConnection

with THESAGRAConnection(
    uri="thesagra://username:password@127.0.0.1:5439/project_db"
) as connection:
    cursor = connection.execute(
        "INSERT INTO users VALUES (?, ?);",
        [1, "Ada"],
    )
```

Credentials and the URI password are decoded from URL escaping. Passwords
must not be logged or stored in source code.

In named-database server mode, the URI path selects the database and is
authorized during the handshake. A system administrator can connect without
a database to provision it:

```python
with THESAGRAConnection(
    host="127.0.0.1",
    port=5439,
    username="db_admin",
    password="...",
) as admin:
    admin.create_database("project_db")
    admin.create_role("project_readers")
    admin.create_user("reporting_app", "...")
    admin.grant_role("project_readers", "reporting_app")
    admin.grant_database("project_readers", "project_db", "CONNECT")
    admin.grant_database("project_readers", "project_db", "READ")
```

See [multi-database-hosting.md](multi-database-hosting.md) for the setup
command and current limitations. The administrator API also exposes
`revoke_role`, `revoke_database`, and `reset_password`. Legacy single-file
server mode exposes the logical database name `main`.

## Cursor

`execute` and `query` return a cursor with:

- `columns`
- `rows`
- `rowcount`
- `fetchall()`
- `fetchone()`
- `fetchmany(size)`
- Python iteration

## Transactions

```python
connection.begin()
try:
    connection.execute("INSERT INTO items VALUES (1);")
    connection.commit()
except Exception:
    connection.rollback()
    raise
```

## Graph and blob APIs

The Python connection exposes:

- `list_catalog`
- `create_node`
- `create_edge`
- `list_graph`
- `traverse`
- `begin_blob_upload`
- `append_blob`
- `finalize_blob`
- `read_blob`
- `stream_blob`
- `list_blobs`
- `delete_blob`
- `get_worker_status`
- `enqueue_task`

## Error types

- `THESAGRAError`
- `ConnectionError`
- `AuthenticationError`
- `ProtocolError`
- `QueryError`
- `CancelledError`
- `BlobError`
- `GraphError`
