# Named Databases and Hosted Connections

## Status

Named-database mode is an experimental, single-server deployment mode. It
provides separate database files and per-database access grants; it is not
yet a production multi-tenant service. Use loopback or a trusted network
while evaluating it. Configure TLS before remote use.

## Start a multi-database server

Choose a strong bootstrap administrator password. The first launch stores a
PBKDF2 password hash in the system catalog. Changing the environment variable
later does not rotate that stored password.

```powershell
$env:THESAGRA_USERNAME = "db_admin"
$env:THESAGRA_PASSWORD = "<strong-secret>"
python -m thesagra.cli --serve `
  --data-dir .\thesagra-data `
  --host 127.0.0.1 --port 5439
```

Named files are stored under `thesagra-data\databases\`; account, role, grant,
and database-name metadata is stored in `thesagra-data\system.sqlite3`.
The positional database argument is ignored in `--data-dir` mode. Existing
single-file mode remains available when `--data-dir` is omitted.

In Studio, leave the Database picker empty and click **Connect** to open a
server-level session. **Refresh** lists databases the account can access;
**Create DB** is available to the system administrator. Select a database
from the picker and click **Connect** again to open its workbench.

## Provision projects and roles

Connect as the system administrator without selecting a database, then create
databases, users, and roles (roles can act as groups):

```python
from thesagra import THESAGRAConnection

with THESAGRAConnection(
    host="127.0.0.1",
    port=5439,
    username="db_admin",
    password="<strong-secret>",
) as admin:
    admin.create_database("orders")
    admin.create_role("orders_app_role")
    admin.create_user("orders_app", "<app-secret>")
    admin.grant_role("orders_app_role", "orders_app")
    for privilege in ("CONNECT", "READ", "WRITE"):
        admin.grant_database(
            "orders_app_role",
            "orders",
            privilege,
        )
```

Supported database privileges are `CONNECT`, `READ`, `WRITE`, and `ADMIN`.
`ADMIN` includes the other database privileges. Only the bootstrap
administrator can provision users, roles, databases, and grants in this
initial implementation. It can also revoke role memberships and database
grants, and reset a user's password:

```python
admin.revoke_database("project_readers", "project_db", "WRITE")
admin.revoke_role("project_readers", "reporting_app")
admin.reset_password("reporting_app", "<replacement-secret>")
```

## Connect to a project database

The database name is the single path segment after the host and port:

```python
from thesagra import THESAGRAConnection

with THESAGRAConnection(
    uri="thesagra://orders_app:<url-encoded-secret>@127.0.0.1:5439/orders"
) as connection:
    rows = connection.execute("SELECT * FROM orders;").fetchall()
```

The server checks the account, its role memberships, and the `CONNECT` grant
before binding the session to that database. Queries and graph/blob operations
then run against that database's own catalog, database file, WAL, blob files,
and task queue. One connection uses one selected database; open another
connection to use another project database.

TLS can be enabled by the Python client with `tls=True` and the server's
`--tls-cert` / `--tls-key` options. Keep real passwords out of source code;
percent-encode reserved characters in URI credentials or pass credentials
through the individual client options.

## Isolation and current limits

- Database names are validated and cannot contain filesystem path segments.
- Database files are isolated from one another; the same table name can exist
  in different databases.
- The bootstrap administrator has access to every database.
- Users require explicit `CONNECT` plus `READ` or `WRITE` grants for the
  corresponding operations.
- Per-database transactions are serialized while active so one session cannot
  accidentally commit or roll back another session's transaction.
- `CREATE DATABASE name` and `USE name` are available in SQL on named-mode
  servers. Creating databases requires the system administrator; `USE`
  requires `CONNECT`. There is no schema namespace, quota system, online
  backup, replication, or production high-availability support yet.
- Keep the server process as the only process accessing its database files.
  Do not point multiple server processes at the same data directory.
- For a consistent backup, stop writes and archive the complete data
  directory, including `system.sqlite3`, `databases\`, and their sidecar files.
