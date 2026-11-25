from dataclasses import dataclass
from urllib.parse import urlparse, unquote
import base64
from .streaming import iter_blob_chunks

from ...server.client import THESAGRAClient
from .errors import (
    AuthenticationError,
    BlobError,
    CancelledError,
    ConnectionError,
    GraphError,
    ProtocolError,
    QueryError,
)


@dataclass
class Cursor:
    columns: list
    rows: list
    rowcount: int
    request_id: str = ""
    ok: bool = True

    def __iter__(self):
        return iter(self.rows)

    def fetchall(self):
        return list(self.rows)

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def fetchmany(self, size=1):
        if size < 0:
            raise QueryError("Fetch size cannot be negative")
        selected = self.rows[:size]
        del self.rows[:size]
        return selected

    def __getitem__(self, key):
        if isinstance(key, str):
            return getattr(self, key, None)
        return self.rows[key]


class THESAGRAConnection:
    def __init__(self, uri=None, host="127.0.0.1", port=5439,
                 username=None, password=None, timeout=10,
                 tls=False, tls_ca=None, database=None):
        if uri:
            parsed = urlparse(uri)
            if parsed.scheme != "thesagra":
                raise ConnectionError("URI scheme must be thesagra")
            host = parsed.hostname or host
            port = parsed.port or port
            username = unquote(parsed.username) if parsed.username else username
            password = unquote(parsed.password) if parsed.password else password
            database = unquote(parsed.path.lstrip("/")) or database

        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.database = database
        self.timeout = timeout
        self.tls = tls
        self.tls_ca = tls_ca
        self.client = None
        self.is_admin = False
        self.multi_database = False

    def connect(self):
        try:
            self.client = THESAGRAClient(
                host=self.host,
                port=self.port,
                timeout=self.timeout,
                tls=self.tls,
                tls_ca=self.tls_ca,
            )
            response = self.client.handshake(
                self.username or "admin",
                self.password or "change-me",
                self.database,
            )
            self.database = response.get("database", self.database)
            self.is_admin = bool(response.get("is_admin", False))
            self.multi_database = bool(
                response.get("multi_database", False)
            )
        except RuntimeError as exc:
            self.client.close()
            self.client = None
            raise AuthenticationError(str(exc)) from exc
        except OSError as exc:
            if self.client is not None:
                self.client.close()
                self.client = None
            raise ConnectionError(str(exc)) from exc
        except Exception as exc:
            if self.client is not None:
                self.client.close()
                self.client = None
            raise ProtocolError(str(exc)) from exc
        return self

    def list_databases(self):
        return self._admin_operation("list_databases")

    def create_database(self, database, owner_role=None):
        return self._admin_operation(
            "create_database",
            database=database,
            owner_role=owner_role,
        )

    def create_user(self, username, password):
        return self._admin_operation(
            "create_user",
            username=username,
            password=password,
        )

    def reset_password(self, username, password):
        return self._admin_operation(
            "reset_password",
            username=username,
            password=password,
        )

    def create_role(self, role_name):
        return self._admin_operation("create_role", role_name=role_name)

    def grant_role(self, role_name, member_name, member_type="USER"):
        return self._admin_operation(
            "grant_role",
            role_name=role_name,
            member_name=member_name,
            member_type=member_type,
        )

    def revoke_role(self, role_name, member_name, member_type="USER"):
        return self._admin_operation(
            "revoke_role",
            role_name=role_name,
            member_name=member_name,
            member_type=member_type,
        )

    def grant_database(self, role_name, database, privilege):
        return self._admin_operation(
            "grant_database",
            role_name=role_name,
            database=database,
            privilege=privilege,
        )

    def revoke_database(self, role_name, database, privilege):
        return self._admin_operation(
            "revoke_database",
            role_name=role_name,
            database=database,
            privilege=privilege,
        )

    def _admin_operation(self, operation, **payload):
        if self.client is None:
            raise ConnectionError("Not connected")
        try:
            return self.client.operation(operation, **payload)
        except RuntimeError as exc:
            raise ProtocolError(str(exc)) from exc

    def __enter__(self):
        return self.connect()

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def execute(self, sql, parameters=None):
        if self.client is None:
            raise ConnectionError("Not connected")
        try:
            raw = self.client.query(sql, parameters)
        except RuntimeError as exc:
            message = str(exc)
            if message.startswith("CANCELLED"):
                raise CancelledError(message) from exc
            if message.startswith("AUTH_FAILED"):
                raise AuthenticationError(message) from exc
            raise QueryError(message) from exc
        except (OSError, EOFError) as exc:
            raise ConnectionError(str(exc)) from exc
        if "database" in raw:
            self.database = raw["database"]
        return Cursor(
            columns=raw.get("columns", []),
            rows=[tuple(row) for row in raw.get("rows", [])],
            rowcount=raw.get("rowcount", 0),
            request_id=raw.get("request_id", ""),
        )

    def query(self, sql, parameters=None):
        return self.execute(sql, parameters)

    def begin(self):
        return self.execute("BEGIN")

    def commit(self):
        return self.execute("COMMIT")

    def rollback(self):
        return self.execute("ROLLBACK")

    def create_node(self, label, properties=None, node_id=None):
        if self.client is None:
            raise ConnectionError("Not connected")
        try:
            response = self.client.operation(
                "graph_create_node",
                label=label,
                properties=properties,
                node_id=node_id,
            )
            return response["node"]
        except RuntimeError as exc:
            raise GraphError(str(exc)) from exc

    def create_edge(self, source_node_id, target_node_id,
                    relationship_type, properties=None, edge_id=None):
        if self.client is None:
            raise ConnectionError("Not connected")
        try:
            response = self.client.operation(
                "graph_create_edge",
                source_node_id=source_node_id,
                target_node_id=target_node_id,
                relationship_type=relationship_type,
                properties=properties,
                edge_id=edge_id,
            )
            return response["edge"]
        except RuntimeError as exc:
            raise GraphError(str(exc)) from exc

    def traverse(self, start_node_id, depth=1,
                 relationship_type=None, max_nodes=100):
        if self.client is None:
            raise ConnectionError("Not connected")
        try:
            response = self.client.operation(
                "graph_traverse",
                start_node_id=start_node_id,
                depth=depth,
                relationship_type=relationship_type,
                max_nodes=max_nodes,
            )
            return response["paths"]
        except RuntimeError as exc:
            raise GraphError(str(exc)) from exc

    def begin_blob_upload(self, name, mime_type="application/octet-stream",
                          application_metadata=None, max_size=None):
        if self.client is None:
            raise ConnectionError("Not connected")
        try:
            response = self.client.operation(
                "blob_begin",
                name=name,
                mime_type=mime_type,
                application_metadata=application_metadata,
                max_size=max_size,
            )
            return response["object_id"]
        except RuntimeError as exc:
            raise BlobError(str(exc)) from exc

    def append_blob(self, object_id, data):
        if self.client is None:
            raise ConnectionError("Not connected")
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise BlobError("Blob data must be bytes")
        try:
            response = self.client.operation(
                "blob_append",
                object_id=object_id,
                data=base64.b64encode(bytes(data)).decode("ascii"),
            )
            return response["written"]
        except RuntimeError as exc:
            raise BlobError(str(exc)) from exc

    def finalize_blob(self, object_id, declared_size=None):
        if self.client is None:
            raise ConnectionError("Not connected")
        try:
            response = self.client.operation(
                "blob_finalize",
                object_id=object_id,
                declared_size=declared_size,
            )
            return response["metadata"]
        except RuntimeError as exc:
            raise BlobError(str(exc)) from exc

    def read_blob(self, object_id, start=0, length=None):
        if self.client is None:
            raise ConnectionError("Not connected")
        try:
            response = self.client.operation(
                "blob_read",
                object_id=object_id,
                start=start,
                length=length,
            )
            return base64.b64decode(response["data"])
        except RuntimeError as exc:
            raise BlobError(str(exc)) from exc

    def stream_blob(self, object_id, chunk_size=64 * 1024):
        return iter_blob_chunks(self, object_id, chunk_size)

    def list_graph(self):
        if self.client is None:
            raise ConnectionError("Not connected")
        try:
            return self.client.operation("graph_list")
        except RuntimeError as exc:
            raise GraphError(str(exc)) from exc

    def list_catalog(self):
        if self.client is None:
            raise ConnectionError("Not connected")
        try:
            return self.client.operation("catalog_list")
        except RuntimeError as exc:
            raise ProtocolError(str(exc)) from exc

    def list_blobs(self):
        if self.client is None:
            raise ConnectionError("Not connected")
        try:
            return self.client.operation("blob_list")
        except RuntimeError as exc:
            raise BlobError(str(exc)) from exc

    def get_worker_status(self):
        if self.client is None:
            raise ConnectionError("Not connected")
        try:
            response = self.client.operation("task_status")
            return response["status"]
        except RuntimeError as exc:
            raise ProtocolError(str(exc)) from exc

    def enqueue_task(self, task_type, payload=None, max_attempts=3,
                     idempotency_key=None):
        if self.client is None:
            raise ConnectionError("Not connected")
        try:
            return self.client.operation(
                "task_enqueue",
                task_type=task_type,
                payload=payload or {},
                max_attempts=max_attempts,
                idempotency_key=idempotency_key,
            )
        except RuntimeError as exc:
            raise ProtocolError(str(exc)) from exc

    def delete_blob(self, object_id):
        if self.client is None:
            raise ConnectionError("Not connected")
        try:
            return self.client.operation(
                "blob_delete",
                object_id=object_id,
            )
        except RuntimeError as exc:
            raise BlobError(str(exc)) from exc

    def close(self):
        if self.client is not None:
            self.client.close()
            self.client = None
