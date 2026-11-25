import os
import json
import socket
import socketserver
import threading
import uuid
import base64
import hmac
import re
import ssl
from ..security import (
    AuditLog,
    FailureThrottle,
    hash_password,
    verify_password,
)
from ..workers.worker import Worker

from ..query.engine import QueryError, QueryResult, RelationalEngine
from ..query.parser import ParseError, parse
from ..storage.database import DatabaseFile
from .registry import DatabaseRegistry, RegistryError
from .protocol import (
    CANCEL,
    REQUEST,
    ProtocolError,
    bind_parameters,
    receive_message,
    send_message,
)


class THESAGRAServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        database_path,
        host="127.0.0.1",
        port=5439,
        username=None,
        password=None,
        password_hash=None,
        max_sessions=64,
        tls_cert=None,
        tls_key=None,
        database_directory=None,
    ):
        self.username = username or os.environ.get(
            "THESAGRA_USERNAME",
            "admin",
        )
        self.password = password or os.environ.get(
            "THESAGRA_PASSWORD",
            "change-me",
        )
        self.password_hash = password_hash or os.environ.get(
            "THESAGRA_PASSWORD_HASH"
        )
        self.multi_database = database_directory is not None
        self.engines = {}
        self.engine_locks = {}
        self.workers = {}
        self.engine_lock = threading.RLock()
        if self.multi_database:
            if not self.password_hash and self.password == "change-me":
                raise ValueError(
                    "Multi-database mode requires a non-default "
                    "administrator password or password hash"
                )
            administrator_hash = self.password_hash or hash_password(
                self.password
            )
            self.registry = DatabaseRegistry(
                database_directory,
                self.username,
                administrator_hash,
            )
            self.database_path = self.registry.path
            self.engine = None
            self.worker = None
        else:
            self.registry = None
            self.database_path = os.fspath(database_path)
            exists = os.path.isfile(self.database_path)
            database = (
                DatabaseFile.open(self.database_path)
                if exists
                else DatabaseFile.create(self.database_path)
            )
            self.engine = RelationalEngine(database)
            self.engines["main"] = self.engine
            self.engine_locks["main"] = self.engine_lock
            self.worker = Worker(
                self.engine,
                engine_lock=self.engine_lock,
            )
            self.worker.start()
        self.sessions = {}
        self.sessions_lock = threading.Lock()
        self.cancelled_requests = set()
        self.max_sessions = max_sessions
        self.failure_throttle = FailureThrottle()
        self.audit = AuditLog(self.database_path)
        self.tls_context = None
        if tls_cert or tls_key:
            if not tls_cert or not tls_key:
                raise ValueError("Both TLS certificate and key are required")
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(tls_cert, tls_key)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            self.tls_context = context
        super().__init__((host, port), _THESAGRAHandler)

    def get_request(self):
        socket, address = super().get_request()
        if self.tls_context is not None:
            try:
                socket = self.tls_context.wrap_socket(
                    socket,
                    server_side=True,
                )
            except ssl.SSLError:
                socket.close()
                raise
        return socket, address

    def engine_for(self, database_name):
        if not self.multi_database:
            if database_name not in (None, "main"):
                raise RegistryError("Single-file mode exposes database 'main'")
            return self.engine
        path = self.registry.database_path(database_name)
        with self.engine_lock:
            engine = self.engines.get(database_name.lower())
            if engine is None:
                engine = RelationalEngine(DatabaseFile.open(path))
                self.engines[database_name.lower()] = engine
                self.engine_locks[database_name.lower()] = threading.RLock()
            return engine

    def lock_for(self, database_name):
        if not self.multi_database:
            return self.engine_lock
        key = database_name.lower()
        with self.engine_lock:
            if key not in self.engine_locks:
                self.engine_for(database_name)
            return self.engine_locks[key]

    def worker_for(self, database_name):
        if not self.multi_database:
            return self.worker
        key = database_name.lower()
        with self.engine_lock:
            if key not in self.workers:
                worker = Worker(
                    self.engine_for(database_name),
                    engine_lock=self.engine_locks[key],
                )
                worker.start()
                self.workers[key] = worker
            return self.workers[key]

    def server_close(self):
        if self.worker is not None:
            self.worker.stop()
        for worker in self.workers.values():
            worker.stop()
        super().server_close()


class _THESAGRAHandler(socketserver.StreamRequestHandler):
    def _end_transaction(self):
        if not self.transaction_lock_held:
            return
        try:
            if self.engine is not None and self.engine.active_transaction is not None:
                self.engine.rollback()
        finally:
            self.transaction_lock_held = False
            self.engine_lock.release()

    def handle(self):
        self.request.settimeout(30)
        authenticated = False
        session_id = None
        self.session_id = None
        self.database_name = None
        self.principal = None
        self.engine = self.server.engine
        self.engine_lock = self.server.engine_lock
        self.worker = self.server.worker
        self.transaction_lock_held = False
        while True:
            try:
                message_type, payload = receive_message(self.request)
            except (ProtocolError, ConnectionError, OSError):
                return
            if message_type == CANCEL:
                request_id = payload.get("request_id")
                if request_id is not None:
                    self.server.cancelled_requests.add(str(request_id))
                send_message(
                    self.request,
                    2,
                    {"ok": True, "status": "cancelled", "request_id": request_id},
                )
                continue
            if message_type != REQUEST:
                send_message(
                    self.request,
                    2,
                    {"ok": False, "error": {"code": "BAD_MESSAGE", "message": "Expected request"}},
                )
                continue

            operation = payload.get("operation")
            if operation == "handshake":
                identity = str(self.client_address[0])
                if self.server.failure_throttle.blocked(identity):
                    self.server.audit.write(
                        "auth_blocked",
                        peer=self.client_address,
                    )
                    send_message(
                        self.request,
                        2,
                        {"ok": False, "error": {"code": "AUTH_BLOCKED", "message": "Too many authentication failures"}},
                    )
                    continue
                if authenticated:
                    send_message(
                        self.request,
                        2,
                        {"ok": False, "error": {"code": "ALREADY_AUTHENTICATED", "message": "Session is already authenticated"}},
                    )
                    continue
                supplied_username = payload.get("username")
                supplied_password = payload.get("password")
                requested_database = payload.get("database")
                if self.server.multi_database:
                    self.principal = self.server.registry.authenticate(
                        supplied_username,
                        supplied_password,
                    )
                    authenticated_user = self.principal is not None
                else:
                    username_matches = (
                        isinstance(supplied_username, str)
                        and hmac.compare_digest(
                            supplied_username.encode("utf-8"),
                            self.server.username.encode("utf-8"),
                        )
                    )
                    password_matches = isinstance(supplied_password, str) and (
                        verify_password(
                            supplied_password,
                            self.server.password_hash,
                        )
                        if self.server.password_hash
                        else hmac.compare_digest(
                            supplied_password.encode("utf-8"),
                            self.server.password.encode("utf-8"),
                        )
                    )
                    authenticated_user = (
                        username_matches and password_matches
                    )
                if not authenticated_user:
                    blocked = self.server.failure_throttle.record_failure(identity)
                    self.server.audit.write(
                        "auth_failed",
                        peer=self.client_address,
                        detail="account locked" if blocked else None,
                    )
                    send_message(
                        self.request,
                        2,
                        {"ok": False, "error": {"code": "AUTH_FAILED", "message": "Authentication failed"}},
                    )
                    continue
                if self.server.multi_database:
                    try:
                        if requested_database is not None:
                            self.database_name = (
                                self.server.registry.validate_database_name(
                                    requested_database
                                )
                            )
                            self.server.registry.require(
                                self.principal,
                                self.database_name,
                                "CONNECT",
                            )
                            self.engine = self.server.engine_for(
                                self.database_name
                            )
                            self.engine_lock = self.server.lock_for(
                                self.database_name
                            )
                            self.worker = self.server.worker_for(
                                self.database_name
                            )
                    except RegistryError as exc:
                        send_message(
                            self.request,
                            2,
                            {
                                "ok": False,
                                "error": {
                                    "code": "DATABASE_ACCESS_DENIED",
                                    "message": str(exc),
                                },
                            },
                        )
                        continue
                else:
                    self.database_name = (
                        requested_database or "main"
                    )
                    if self.database_name != "main":
                        send_message(
                            self.request,
                            2,
                            {
                                "ok": False,
                                "error": {
                                    "code": "DATABASE_NOT_FOUND",
                                    "message": (
                                        "Single-file mode exposes database "
                                        "'main'"
                                    ),
                                },
                            },
                        )
                        continue
                with self.server.sessions_lock:
                    if len(self.server.sessions) >= self.server.max_sessions:
                        send_message(
                            self.request,
                            2,
                            {
                                "ok": False,
                                "error": {
                                    "code": "TOO_MANY_SESSIONS",
                                    "message": "Maximum session count reached",
                                },
                            },
                        )
                        continue
                    authenticated = True
                    session_id = str(uuid.uuid4())
                    self.session_id = session_id
                    self.server.sessions[session_id] = {
                        "peer": self.client_address,
                        "username": supplied_username,
                        "database": self.database_name,
                    }
                self.server.failure_throttle.record_success(identity)
                self.server.audit.write(
                    "auth_success",
                    peer=self.client_address,
                )
                send_message(
                    self.request,
                    2,
                    {
                        "ok": True,
                        "session_id": session_id,
                        "protocol_version": 1,
                        "database": self.database_name,
                        "is_admin": bool(
                            self.principal
                            and self.principal["is_superuser"]
                        ),
                        "multi_database": self.server.multi_database,
                    },
                )
                continue

            if operation == "disconnect":
                if session_id:
                    self._end_transaction()
                    with self.server.sessions_lock:
                        self.server.sessions.pop(session_id, None)
                    self.server.audit.write(
                        "session_disconnected",
                        peer=self.client_address,
                        detail=session_id,
                    )
                send_message(
                    self.request,
                    2,
                    {"ok": True, "status": "disconnected"},
                )
                return

            if not authenticated:
                send_message(
                    self.request,
                    2,
                    {"ok": False, "error": {"code": "NOT_AUTHENTICATED", "message": "Handshake required"}},
                )
                continue

            if operation in {
                "list_databases",
                "create_database",
                "create_user",
                "reset_password",
                "create_role",
                "grant_role",
                "revoke_role",
                "grant_database",
                "revoke_database",
            }:
                try:
                    if not self.server.multi_database:
                        raise RegistryError(
                            "Database administration requires multi-database mode"
                        )
                    if operation == "list_databases":
                        result = {
                            "databases": self.server.registry.list_databases(
                                self.principal
                            )
                        }
                    elif not self.principal["is_superuser"]:
                        raise RegistryError(
                            "System administrator permission required"
                        )
                    elif operation == "create_database":
                        self.server.registry.create_database(
                            payload.get("database"),
                            payload.get("owner_role"),
                        )
                        self.server.engine_for(payload.get("database"))
                        result = {
                            "database": payload.get("database"),
                        }
                    elif operation == "create_user":
                        self.server.registry.create_user(
                            payload.get("username"),
                            payload.get("password"),
                        )
                        result = {"username": payload.get("username")}
                    elif operation == "reset_password":
                        self.server.registry.reset_password(
                            payload.get("username"),
                            payload.get("password"),
                        )
                        result = {"username": payload.get("username")}
                    elif operation == "create_role":
                        self.server.registry.create_role(
                            payload.get("role_name")
                        )
                        result = {"role_name": payload.get("role_name")}
                    elif operation == "grant_role":
                        self.server.registry.grant_role(
                            payload.get("role_name"),
                            payload.get("member_name"),
                            payload.get("member_type", "USER"),
                        )
                        result = {"status": "granted"}
                    elif operation == "revoke_role":
                        self.server.registry.revoke_role(
                            payload.get("role_name"),
                            payload.get("member_name"),
                            payload.get("member_type", "USER"),
                        )
                        result = {"status": "revoked"}
                    elif operation == "grant_database":
                        self.server.registry.grant_database(
                            payload.get("role_name"),
                            payload.get("database"),
                            payload.get("privilege"),
                        )
                        result = {"status": "granted"}
                    else:
                        self.server.registry.revoke_database(
                            payload.get("role_name"),
                            payload.get("database"),
                            payload.get("privilege"),
                        )
                        result = {"status": "revoked"}
                    send_message(
                        self.request,
                        2,
                        {"ok": True, **result},
                    )
                except Exception as exc:
                    send_message(
                        self.request,
                        2,
                        {
                            "ok": False,
                            "error": {
                                "code": "ADMIN_ERROR",
                                "message": str(exc),
                            },
                        },
                    )
                continue

            if self.server.multi_database and operation != "query":
                required = {
                    "catalog_list": "READ",
                    "graph_traverse": "READ",
                    "graph_list": "READ",
                    "blob_list": "READ",
                    "blob_read": "READ",
                    "task_status": "READ",
                }.get(operation, "WRITE")
                try:
                    self.server.registry.require(
                        self.principal,
                        self.database_name,
                        required,
                    )
                except RegistryError as exc:
                    send_message(
                        self.request,
                        2,
                        {
                            "ok": False,
                            "error": {
                                "code": "PERMISSION_DENIED",
                                "message": str(exc),
                            },
                        },
                    )
                    continue

            if operation == "task_enqueue":
                try:
                    task_id = self.worker.queue.enqueue(
                        payload.get("task_type"),
                        payload.get("payload"),
                        payload.get("max_attempts", 3),
                        payload.get("idempotency_key"),
                    )
                    send_message(
                        self.request,
                        2,
                        {"ok": True, "task_id": task_id},
                    )
                except Exception as exc:
                    send_message(
                        self.request,
                        2,
                        {"ok": False, "error": {"code": "TASK_ERROR",
                                                "message": str(exc)}},
                    )
                continue

            if operation == "task_status":
                task_id = payload.get("task_id")
                if task_id:
                    task = self.worker.queue.get(task_id)
                else:
                    task = self.worker.status()
                send_message(
                    self.request,
                    2,
                    {"ok": True, "task": task} if task_id else
                    {"ok": True, "status": task},
                )
                continue

            if operation == "catalog_list":
                try:
                    with self.engine_lock:
                        tables = [
                            {
                                "name": table.name,
                                "page_id": table.page_id,
                                "columns": [
                                    {
                                        "name": column.name,
                                        "type": column.type_name,
                                        "nullable": column.nullable,
                                        "primary_key": column.primary_key,
                                        "unique": column.unique,
                                        "auto_increment": column.auto_increment,
                                        "default": (
                                            "CURRENT_TIMESTAMP"
                                            if column.default_current_timestamp
                                            else column.default_value
                                        ),
                                        "max_length": column.max_length,
                                    }
                                    for column in table.columns
                                ],
                            }
                            for table in sorted(
                                self.engine.catalog.tables.values(),
                                key=lambda item: item.name.lower(),
                            )
                            if not table.name.lower().startswith("__thesagra_")
                        ]
                    send_message(
                        self.request,
                        2,
                        {"ok": True, "tables": tables},
                    )
                except Exception as exc:
                    send_message(
                        self.request,
                        2,
                        {"ok": False, "error": {"code": "CATALOG_ERROR",
                                                "message": str(exc)}},
                    )
                continue

            if operation == "query":
                request_id = str(payload.get("request_id", uuid.uuid4()))
                sql = payload.get("sql")
                if not isinstance(sql, str):
                    send_message(
                        self.request,
                        2,
                        {"ok": False, "request_id": request_id, "error": {"code": "BAD_REQUEST", "message": "SQL must be a string"}},
                    )
                    continue
                is_begin = False
                try:
                    sql = bind_parameters(sql, payload.get("parameters", []))
                    create_database = re.fullmatch(
                        r"CREATE\s+DATABASE\s+([A-Za-z][A-Za-z0-9_]{0,62})\s*;?",
                        sql.strip(),
                        re.IGNORECASE,
                    )
                    use_database = re.fullmatch(
                        r"USE\s+([A-Za-z][A-Za-z0-9_]{0,62})\s*;?",
                        sql.strip(),
                        re.IGNORECASE,
                    )
                    if create_database:
                        if not self.server.multi_database:
                            raise QueryError(
                                "CREATE DATABASE requires named-database "
                                "server mode (--data-dir)"
                            )
                        if not self.principal["is_superuser"]:
                            raise RegistryError(
                                "System administrator permission required "
                                "to create a database"
                            )
                        if self.transaction_lock_held:
                            raise QueryError(
                                "CREATE DATABASE is not allowed inside a "
                                "transaction"
                            )
                        database_name = create_database.group(1)
                        self.server.registry.create_database(database_name)
                        self.server.engine_for(database_name)
                        result = QueryResult([], [], 0)
                    elif use_database:
                        if not self.server.multi_database:
                            requested = use_database.group(1)
                            if requested.lower() != "main":
                                raise QueryError(
                                    "Single-file mode exposes database "
                                    "'main'"
                                )
                        if self.transaction_lock_held:
                            raise QueryError(
                                "USE is not allowed inside a transaction"
                            )
                        database_name = use_database.group(1)
                        if self.server.multi_database:
                            self.server.registry.require(
                                self.principal,
                                database_name,
                                "CONNECT",
                            )
                            engine = self.server.engine_for(database_name)
                            engine_lock = self.server.lock_for(database_name)
                            worker = self.server.worker_for(database_name)
                            self.database_name = database_name
                            self.engine = engine
                            self.engine_lock = engine_lock
                            self.worker = worker
                            with self.server.sessions_lock:
                                self.server.sessions[session_id][
                                    "database"
                                ] = database_name
                        else:
                            self.database_name = "main"
                        result = QueryResult([], [], 0)
                    else:
                        result = None
                    if result is not None:
                        self.server.cancelled_requests.discard(request_id)
                        send_message(
                            self.request,
                            2,
                            {
                                "ok": True,
                                "request_id": request_id,
                                "columns": result.columns,
                                "rows": [],
                                "rowcount": result.rowcount,
                                "database": self.database_name,
                            },
                        )
                        continue
                    statement = parse(sql)
                    statement_type = (
                        statement.statement.__class__.__name__
                        if statement.__class__.__name__ == "Explain"
                        else statement.__class__.__name__
                    )
                    is_begin = statement_type == "Begin"
                    is_end_transaction = statement_type in (
                        "Commit",
                        "Rollback",
                    )
                    if is_begin and not self.transaction_lock_held:
                        self.engine_lock.acquire()
                        self.transaction_lock_held = True
                    with self.engine_lock:
                        if request_id in self.server.cancelled_requests:
                            raise QueryError("Query cancelled")
                        if self.server.multi_database:
                            privilege = (
                                "READ"
                                if statement_type in ("Select", "GraphMatch", "Explain")
                                else "WRITE"
                            )
                            self.server.registry.require(
                                self.principal,
                                self.database_name,
                                privilege,
                            )
                        result = self.engine.execute(statement)
                    if is_end_transaction and self.transaction_lock_held:
                        self.transaction_lock_held = False
                        self.engine_lock.release()
                    self.server.cancelled_requests.discard(request_id)
                    send_message(
                        self.request,
                        2,
                        {
                            "ok": True,
                            "request_id": request_id,
                            "columns": result.columns,
                            "rows": [list(row) for row in result.rows],
                            "rowcount": result.rowcount,
                            "database": self.database_name,
                        },
                    )
                except (
                    ProtocolError,
                    ParseError,
                    QueryError,
                    RegistryError,
                ) as exc:
                    if (
                        is_begin
                        and self.transaction_lock_held
                        and (
                            self.engine is None
                            or self.engine.active_transaction is None
                        )
                    ):
                        self.transaction_lock_held = False
                        self.engine_lock.release()
                    if str(exc) == "Query cancelled":
                        code = "CANCELLED"
                    elif isinstance(exc, RegistryError):
                        code = "PERMISSION_DENIED"
                    else:
                        code = "QUERY_ERROR"
                    send_message(
                        self.request,
                        2,
                        {"ok": False, "request_id": request_id, "error": {"code": code, "message": str(exc)}},
                    )
                continue

            if operation == "graph_create_node":
                try:
                    with self.engine_lock:
                        node = self.engine.create_node(
                            payload.get("label"),
                            payload.get("properties"),
                            payload.get("node_id"),
                        )
                    send_message(
                        self.request,
                        2,
                        {"ok": True, "node": {"node_id": node.node_id,
                                             "label": node.label,
                                             "properties": node.properties}},
                    )
                except Exception as exc:
                    send_message(
                        self.request,
                        2,
                        {"ok": False, "error": {"code": "GRAPH_ERROR",
                                                "message": str(exc)}},
                    )
                continue

            if operation == "graph_create_edge":
                try:
                    with self.engine_lock:
                        edge = self.engine.create_edge(
                            payload.get("source_node_id"),
                            payload.get("target_node_id"),
                            payload.get("relationship_type"),
                            payload.get("properties"),
                            payload.get("edge_id"),
                        )
                    send_message(
                        self.request,
                        2,
                        {"ok": True, "edge": {"edge_id": edge.edge_id,
                                              "source_node_id": edge.source_node_id,
                                              "target_node_id": edge.target_node_id,
                                              "relationship_type": edge.relationship_type,
                                              "properties": edge.properties}},
                    )
                except Exception as exc:
                    send_message(
                        self.request,
                        2,
                        {"ok": False, "error": {"code": "GRAPH_ERROR",
                                                "message": str(exc)}},
                    )
                continue

            if operation == "graph_traverse":
                try:
                    with self.engine_lock:
                        paths = self.engine.traverse(
                            payload.get("start_node_id"),
                            payload.get("depth", 1),
                            payload.get("relationship_type"),
                            payload.get("max_nodes", 100),
                        )
                    serialized = [
                        [{"node_id": node.node_id,
                          "label": node.label,
                          "properties": node.properties} for node in path]
                        for path in paths
                    ]
                    send_message(
                        self.request,
                        2,
                        {"ok": True, "paths": serialized},
                    )
                except Exception as exc:
                    send_message(
                        self.request,
                        2,
                        {"ok": False, "error": {"code": "GRAPH_ERROR",
                                                "message": str(exc)}},
                    )
                continue

            if operation == "graph_list":
                try:
                    with self.engine_lock:
                        node_table = self.engine.catalog.get_table("__thesagra_nodes")
                        edge_table = self.engine.catalog.get_table("__thesagra_edges")
                        nodes = [
                            {
                                "node_id": row[0],
                                "label": row[1],
                                "properties": json.loads(row[2]),
                            }
                            for row in self.engine.read_records(node_table.page_id)
                        ]
                        edges = [
                            {
                                "edge_id": row[0],
                                "source_node_id": row[1],
                                "target_node_id": row[2],
                                "relationship_type": row[3],
                                "properties": json.loads(row[4]),
                            }
                            for row in self.engine.read_records(edge_table.page_id)
                        ]
                    send_message(
                        self.request,
                        2,
                        {"ok": True, "nodes": nodes, "edges": edges},
                    )
                except Exception as exc:
                    send_message(
                        self.request,
                        2,
                        {"ok": False, "error": {"code": "GRAPH_ERROR", "message": str(exc)}},
                    )
                continue

            if operation == "blob_list":
                try:
                    with self.engine_lock:
                        table = self.engine.catalog.get_table("__thesagra_blobs")
                        blobs = []
                        for row in self.engine.read_records(table.page_id):
                            blobs.append({
                                "object_id": row[0],
                                "name": row[1],
                                "mime_type": row[2],
                                "byte_length": row[3],
                                "checksum": row[4],
                                "state": row[5],
                                "created_at": row[6],
                            })
                    send_message(
                        self.request,
                        2,
                        {"ok": True, "blobs": blobs},
                    )
                except Exception as exc:
                    send_message(
                        self.request,
                        2,
                        {"ok": False, "error": {"code": "BLOB_ERROR", "message": str(exc)}},
                    )
                continue

            if operation == "blob_delete":
                try:
                    with self.engine_lock:
                        self.engine.delete_blob(payload.get("object_id"))
                    send_message(
                        self.request,
                        2,
                        {"ok": True, "object_id": payload.get("object_id")},
                    )
                except Exception as exc:
                    send_message(
                        self.request,
                        2,
                        {"ok": False, "error": {"code": "BLOB_ERROR", "message": str(exc)}},
                    )
                continue

            if operation == "blob_begin":
                try:
                    with self.engine_lock:
                        object_id = self.engine.begin_blob_upload(
                            payload.get("name"),
                            payload.get("mime_type",
                                         "application/octet-stream"),
                            payload.get("application_metadata"),
                            payload.get("max_size"),
                        )
                    send_message(
                        self.request,
                        2,
                        {"ok": True, "object_id": object_id},
                    )
                except Exception as exc:
                    send_message(
                        self.request,
                        2,
                        {"ok": False, "error": {"code": "BLOB_ERROR",
                                                "message": str(exc)}},
                    )
                continue

            if operation == "blob_append":
                try:
                    data = base64.b64decode(payload.get("data", ""), validate=True)
                    with self.engine_lock:
                        written = self.engine.append_blob_chunk(
                            payload.get("object_id"),
                            data,
                        )
                    send_message(
                        self.request,
                        2,
                        {"ok": True, "written": written},
                    )
                except Exception as exc:
                    send_message(
                        self.request,
                        2,
                        {"ok": False, "error": {"code": "BLOB_ERROR",
                                                "message": str(exc)}},
                    )
                continue

            if operation == "blob_finalize":
                try:
                    with self.engine_lock:
                        metadata = self.engine.finalize_blob(
                            payload.get("object_id"),
                            payload.get("declared_size"),
                        )
                    send_message(
                        self.request,
                        2,
                        {"ok": True, "metadata": {
                            "object_id": metadata.object_id,
                            "name": metadata.name,
                            "mime_type": metadata.mime_type,
                            "byte_length": metadata.byte_length,
                            "checksum": metadata.checksum,
                            "state": metadata.state,
                        }},
                    )
                except Exception as exc:
                    send_message(
                        self.request,
                        2,
                        {"ok": False, "error": {"code": "BLOB_ERROR",
                                                "message": str(exc)}},
                    )
                continue

            if operation == "blob_read":
                try:
                    with self.engine_lock:
                        data = self.engine.read_blob_range(
                            payload.get("object_id"),
                            payload.get("start", 0),
                            payload.get("length"),
                        )
                    send_message(
                        self.request,
                        2,
                        {"ok": True, "data": base64.b64encode(data).decode("ascii")},
                    )
                except Exception as exc:
                    send_message(
                        self.request,
                        2,
                        {"ok": False, "error": {"code": "BLOB_ERROR",
                                                "message": str(exc)}},
                    )
                continue

            send_message(
                self.request,
                2,
                {"ok": False, "error": {"code": "UNKNOWN_OPERATION", "message": "Unknown operation"}},
            )

    def finish(self):
        self._end_transaction()
        if getattr(self, "session_id", None):
            with self.server.sessions_lock:
                self.server.sessions.pop(self.session_id, None)
            self.server.audit.write(
                "session_disconnected",
                peer=self.client_address,
                detail=self.session_id,
            )
        return super().finish()
