"""THESAGRA database system prototype."""

from .storage.database import DatabaseFile
from .query.engine import RelationalEngine, QueryResult
from .query.parser import parse
from .graph.model import GraphEdge, GraphError, GraphNode
from .blobs.model import BlobError, BlobMetadata
from .server.server import THESAGRAServer
from .server.client import THESAGRAClient
from .drivers.python.client import Cursor, THESAGRAConnection
from .drivers.python.errors import (
    THESAGRAError,
    ConnectionError,
    AuthenticationError,
    QueryError,
    ProtocolError,
    CancelledError,
    BlobError,
    GraphError,
)
from .operations import (
    OperationsError,
    backup_database,
    integrity_check,
    restore_database,
)
from .security import AuditLog, FailureThrottle, hash_password, verify_password

__all__ = [
    "DatabaseFile",
    "RelationalEngine",
    "QueryResult",
    "parse",
    "GraphEdge",
    "GraphError",
    "GraphNode",
    "BlobError",
    "BlobMetadata",
    "THESAGRAServer",
    "THESAGRAClient",
    "THESAGRAConnection",
    "Cursor",
    "THESAGRAError",
    "ConnectionError",
    "AuthenticationError",
    "QueryError",
    "ProtocolError",
    "CancelledError",
    "BlobError",
    "GraphError",
    "OperationsError",
    "backup_database",
    "integrity_check",
    "restore_database",
    "AuditLog",
    "FailureThrottle",
    "hash_password",
    "verify_password",
]
