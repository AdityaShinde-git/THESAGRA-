from dataclasses import dataclass
from typing import List

from ..catalog.catalog import Catalog, CatalogError, Column
from ..catalog.catalog import ForeignKey
from ..storage.database import DatabaseFile
from ..storage.page import PageError
from .parser import (
    CreateTable,
    Delete,
    Insert,
    Select,
    Update,
    Explain,
    SelectedColumn,
    CreateIndex,
    ArithmeticExpression,
    DropTable,
    AlterTable,
)
from ..relational.types import normalize_type, coerce_value, TypeErrorValue
from ..transactions.wal import WAL
from ..storage.page import encode_page, encode_data_payload, PAGE_KIND_DATA
from .parser import Begin, Commit, Rollback
from .parser import GraphMatch
import json
from ..graph.model import GraphNode, GraphEdge, GraphError
from ..blobs.model import BlobError, BlobMetadata
import hashlib
import os
import re
import datetime


class QueryError(Exception):
    pass


@dataclass
class QueryResult:
    columns: List[str]
    rows: List[tuple]
    rowcount: int = 0


class RelationalEngine:
    def __init__(self, database: DatabaseFile):
        self.database = database
        self.wal = WAL(database.path)
        self.active_transaction = None
        self.pending_pages = {}
        self.next_transaction_id = 1
        self.recover()
        self.catalog = Catalog(database)
        self.primary_indexes = {}
        self.ensure_graph_tables()
        self.ensure_blob_tables()
        self._build_primary_indexes()

    def ensure_graph_tables(self):
        if "__thesagra_nodes" not in self.catalog.tables:
            self.catalog.create_table(
                "__thesagra_nodes",
                [
                    Column("node_id", "INTEGER", False, True),
                    Column("label", "TEXT", False, False),
                    Column("properties", "TEXT", False, False),
                ],
            )
        if "__thesagra_edges" not in self.catalog.tables:
            self.catalog.create_table(
                "__thesagra_edges",
                [
                    Column("edge_id", "INTEGER", False, True),
                    Column("source_node_id", "INTEGER", False, False),
                    Column("target_node_id", "INTEGER", False, False),
                    Column("relationship_type", "TEXT", False, False),
                    Column("properties", "TEXT", False, False),
                ],
            )

    def ensure_blob_tables(self):
        if "__thesagra_blobs" not in self.catalog.tables:
            self.catalog.create_table(
                "__thesagra_blobs",
                [
                    Column("object_id", "INTEGER", False, True),
                    Column("name", "TEXT", False, False),
                    Column("mime_type", "TEXT", False, False),
                    Column("byte_length", "INTEGER", False, False),
                    Column("checksum", "TEXT", False, False),
                    Column("state", "TEXT", False, False),
                    Column("created_at", "TEXT", False, False),
                    Column("application_metadata", "TEXT", False, False),
                ],
            )
        if "__thesagra_blob_chunks" not in self.catalog.tables:
            self.catalog.create_table(
                "__thesagra_blob_chunks",
                [
                    Column("object_id", "INTEGER", False, False),
                    Column("chunk_index", "INTEGER", False, False),
                    Column("byte_offset", "INTEGER", False, False),
                    Column("byte_length", "INTEGER", False, False),
                    Column("checksum", "TEXT", False, False),
                ],
            )

    def recover(self):
        _, snapshots = self.wal.committed_page_snapshots()
        for snapshot in snapshots:
            page_id = snapshot["page_id"]
            page = __import__("base64").b64decode(snapshot["page"])
            self.database._write_page(page_id, page)

    def _build_primary_indexes(self):
        for table_name, table in self.catalog.tables.items():
            primary_columns = [
                index
                for index, column in enumerate(table.columns)
                if column.primary_key
            ]
            if len(primary_columns) == 1:
                primary = primary_columns[0]
                index = {}
                for row_number, row in enumerate(
                    self.read_records(table.page_id)
                ):
                    index[row[primary]] = row_number
                self.primary_indexes[table_name] = index

    def execute(self, statement):
        if isinstance(statement, GraphMatch):
            return self.graph_match(statement)
        if isinstance(statement, Begin):
            return self.begin()
        if isinstance(statement, Commit):
            return self.commit()
        if isinstance(statement, Rollback):
            return self.rollback()
        if isinstance(statement, Explain):
            return self.explain(statement)
        if isinstance(statement, CreateTable):
            return self.create_table(statement)
        if isinstance(statement, CreateIndex):
            return self.create_index(statement)
        if isinstance(statement, DropTable):
            return self.drop_table(statement)
        if isinstance(statement, AlterTable):
            return self.alter_table(statement)
        if isinstance(statement, Insert):
            return self.insert(statement)
        if isinstance(statement, Select):
            return self.select(statement)
        if isinstance(statement, Update):
            return self.update(statement)
        if isinstance(statement, Delete):
            return self.delete(statement)
        raise QueryError("Unsupported statement")

    def graph_match(self, statement):
        node_table = self.catalog.get_table("__thesagra_nodes")
        edge_table = self.catalog.get_table("__thesagra_edges")
        nodes = {
            row[0]: GraphNode(row[0], row[1], json.loads(row[2]))
            for row in self.read_records(node_table.page_id)
        }
        edges = self.read_records(edge_table.page_id)
        rows = []
        for edge in edges:
            if edge[3] != statement.relationship_type:
                continue
            source = nodes.get(edge[1])
            target = nodes.get(edge[2])
            if source is None or target is None:
                continue
            if statement.left_label != "*" and source.label != statement.left_label:
                continue
            if statement.right_label != "*" and target.label != statement.right_label:
                continue
            rows.append((
                source.node_id,
                source.label,
                target.node_id,
                target.label,
            ))
        return QueryResult(
            ["source_id", "source_label", "target_id", "target_label"],
            rows,
            len(rows),
        )

    def begin(self):
        if self.active_transaction is not None:
            raise QueryError("Transaction already active")
        self.active_transaction = self.next_transaction_id
        self.next_transaction_id += 1
        self.pending_pages = {}
        self.wal.begin(self.active_transaction)
        return QueryResult([], [], 0)

    def commit(self):
        if self.active_transaction is None:
            raise QueryError("No active transaction")
        transaction_id = self.active_transaction
        for page_id, records in self.pending_pages.items():
            payload = encode_data_payload(records)
            page = encode_page(page_id, PAGE_KIND_DATA, payload)
            self.wal.append_page(transaction_id, page_id, page)
        self.wal.commit(transaction_id)
        for page_id, records in self.pending_pages.items():
            payload = encode_data_payload(records)
            page = encode_page(page_id, PAGE_KIND_DATA, payload)
            self.database._write_page(page_id, page)
        self.pending_pages = {}
        self.active_transaction = None
        self._build_primary_indexes()
        return QueryResult([], [], 0)

    def rollback(self):
        if self.active_transaction is None:
            raise QueryError("No active transaction")
        transaction_id = self.active_transaction
        self.wal.rollback(transaction_id)
        self.pending_pages = {}
        self.active_transaction = None
        self._build_primary_indexes()
        return QueryResult([], [], 0)

    def read_records(self, page_id):
        if page_id in self.pending_pages:
            return list(self.pending_pages[page_id])
        return self.database.read_records(page_id)

    def write_records(self, page_id, records):
        records = [tuple(record) for record in records]
        if self.active_transaction is not None:
            self.pending_pages[page_id] = records
            return
        payload = encode_data_payload(records)
        page = encode_page(page_id, PAGE_KIND_DATA, payload)
        transaction_id = self.next_transaction_id
        self.next_transaction_id += 1
        self.wal.begin(transaction_id)
        self.wal.append_page(transaction_id, page_id, page)
        self.wal.commit(transaction_id)
        self.database._write_page(page_id, page)

    def _blob_directory(self):
        path = os.path.splitext(self.database.path)[0] + ".blobs"
        os.makedirs(path, exist_ok=True)
        return path

    def _sync_blob_directory(self, path):
        if os.name == "nt":
            return
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def begin_blob_upload(
        self,
        name,
        mime_type="application/octet-stream",
        application_metadata=None,
        max_size=None,
    ):
        if not isinstance(name, str) or not name:
            raise BlobError("Blob name must be a non-empty string")
        if not isinstance(mime_type, str) or not mime_type:
            raise BlobError("MIME type must be a non-empty string")
        if application_metadata is None:
            application_metadata = {}
        if not isinstance(application_metadata, dict):
            raise BlobError("Blob application metadata must be a dictionary")
        if max_size is not None:
            if not isinstance(max_size, int) or isinstance(max_size, bool) or max_size < 0:
                raise BlobError("max_size must be a non-negative integer")

        table = self.catalog.get_table("__thesagra_blobs")
        rows = self.read_records(table.page_id)
        object_id = 1
        existing_ids = {row[0] for row in rows}
        while object_id in existing_ids:
            object_id += 1
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        try:
            metadata_json = json.dumps(application_metadata, sort_keys=True)
        except (TypeError, ValueError) as exc:
            raise BlobError("Blob metadata must be JSON-compatible") from exc
        rows.append(
            (
                object_id,
                name,
                mime_type,
                0,
                "",
                "uploading",
                now,
                metadata_json,
            )
        )
        self.write_records(table.page_id, rows)
        os.makedirs(os.path.join(self._blob_directory(), str(object_id)), exist_ok=True)
        setattr(self, f"_blob_max_size_{object_id}", max_size)
        return object_id

    def append_blob_chunk(self, object_id, data):
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise BlobError("Blob chunk must be bytes")
        data = bytes(data)

        metadata = self.get_blob_metadata(object_id)
        if metadata is None:
            raise BlobError(f"Blob {object_id} does not exist")
        if metadata.state != "uploading":
            raise BlobError(f"Blob {object_id} is not accepting chunks")

        max_size = getattr(self, f"_blob_max_size_{object_id}", None)
        if max_size is not None and metadata.byte_length + len(data) > max_size:
            raise BlobError("Blob exceeds configured maximum size")
        if not data:
            return 0

        chunk_size = 64 * 1024
        chunk_table = self.catalog.get_table("__thesagra_blob_chunks")
        chunk_rows = self.read_records(chunk_table.page_id)
        object_chunks = [row for row in chunk_rows if row[0] == object_id]
        next_index = max((row[1] for row in object_chunks), default=-1) + 1
        offset = metadata.byte_length

        object_directory = os.path.join(self._blob_directory(), str(object_id))
        os.makedirs(object_directory, exist_ok=True)
        appended_rows = []
        for index, start in enumerate(range(0, len(data), chunk_size)):
            chunk = data[start:start + chunk_size]
            if not chunk:
                break
            chunk_index = next_index + index
            chunk_path = os.path.join(object_directory, f"{chunk_index}.chunk")
            temporary_path = chunk_path + ".tmp"
            with open(temporary_path, "wb") as chunk_file:
                chunk_file.write(chunk)
                chunk_file.flush()
                os.fsync(chunk_file.fileno())
            os.replace(temporary_path, chunk_path)
            appended_rows.append(
                (
                    object_id,
                    chunk_index,
                    offset,
                    len(chunk),
                    hashlib.sha256(chunk).hexdigest(),
                )
            )
            offset += len(chunk)

        self._sync_blob_directory(object_directory)
        chunk_rows.extend(appended_rows)
        blob_table = self.catalog.get_table("__thesagra_blobs")
        blob_rows = self.read_records(blob_table.page_id)
        for index, row in enumerate(blob_rows):
            if row[0] == object_id:
                blob_rows[index] = (
                    row[0],
                    row[1],
                    row[2],
                    offset,
                    row[4],
                    row[5],
                    row[6],
                    row[7],
                )
                break
        owns_transaction = self.active_transaction is None
        if owns_transaction:
            self.begin()
        try:
            self.write_records(chunk_table.page_id, chunk_rows)
            self.write_records(blob_table.page_id, blob_rows)
        except Exception:
            if owns_transaction and self.active_transaction is not None:
                self.rollback()
            raise
        if owns_transaction:
            self.commit()
        return len(data)

    def finalize_blob(self, object_id, declared_size=None):
        metadata = self.get_blob_metadata(object_id)
        if metadata is None:
            raise BlobError(f"Blob {object_id} does not exist")
        if metadata.state != "uploading":
            raise BlobError(f"Blob {object_id} is not uploading")
        if declared_size is not None:
            if not isinstance(declared_size, int) or isinstance(declared_size, bool):
                raise BlobError("Declared size must be an integer")
            if declared_size != metadata.byte_length:
                raise BlobError(
                    f"Declared size {declared_size} does not match "
                    f"uploaded size {metadata.byte_length}"
                )

        object_directory = os.path.join(self._blob_directory(), str(object_id))
        overall = hashlib.sha256()
        chunk_table = self.catalog.get_table("__thesagra_blob_chunks")
        chunk_rows = [
            row
            for row in self.read_records(chunk_table.page_id)
            if row[0] == object_id
        ]
        actual_length = 0
        ordered_chunks = sorted(chunk_rows, key=lambda row: row[1])
        for expected_index, chunk_row in enumerate(ordered_chunks):
            if chunk_row[1] != expected_index or chunk_row[2] != actual_length:
                raise BlobError(
                    f"Blob {object_id} has an inconsistent chunk layout"
                )
            chunk_path = os.path.join(object_directory, f"{chunk_row[1]}.chunk")
            if not os.path.isfile(chunk_path):
                raise BlobError(
                    f"Chunk {chunk_row[1]} missing for blob {object_id}"
                )
            with open(chunk_path, "rb") as chunk_file:
                chunk = chunk_file.read()
            if len(chunk) != chunk_row[3]:
                raise BlobError(
                    f"Chunk {chunk_row[1]} for blob {object_id} is truncated"
                )
            if hashlib.sha256(chunk).hexdigest() != chunk_row[4]:
                raise BlobError(
                    f"Chunk {chunk_row[1]} checksum mismatch"
                )
            overall.update(chunk)
            actual_length += len(chunk)

        if actual_length != metadata.byte_length:
            raise BlobError(
                f"Blob size mismatch: found {actual_length}, "
                f"expected {metadata.byte_length}"
            )
        checksum = overall.hexdigest()
        blob_table = self.catalog.get_table("__thesagra_blobs")
        blob_rows = self.read_records(blob_table.page_id)
        for index, row in enumerate(blob_rows):
            if row[0] == object_id:
                blob_rows[index] = (
                    row[0], row[1], row[2], actual_length,
                    checksum, "ready", row[6], row[7],
                )
                break
        self.write_records(blob_table.page_id, blob_rows)
        return BlobMetadata(
            object_id,
            metadata.name,
            metadata.mime_type,
            actual_length,
            checksum,
            "ready",
            metadata.created_at,
            metadata.application_metadata,
        )

    def get_blob_metadata(self, object_id):
        table = self.catalog.get_table("__thesagra_blobs")
        for row in self.read_records(table.page_id):
            if row[0] == object_id:
                try:
                    application_metadata = json.loads(row[7])
                except json.JSONDecodeError as exc:
                    raise BlobError("Stored blob metadata is invalid") from exc
                return BlobMetadata(
                    row[0],
                    row[1],
                    row[2],
                    row[3],
                    row[4],
                    row[5],
                    row[6],
                    application_metadata,
                )
        return None

    def read_blob_range(self, object_id, start=0, length=None):
        metadata = self.get_blob_metadata(object_id)
        if metadata is None:
            raise BlobError(f"Blob {object_id} does not exist")
        if metadata.state != "ready":
            raise BlobError(f"Blob {object_id} is not finalized")
        if not isinstance(start, int) or isinstance(start, bool) or start < 0:
            raise BlobError("Blob range start must be a non-negative integer")
        if length is not None:
            if not isinstance(length, int) or isinstance(length, bool) or length < 0:
                raise BlobError("Blob range length must be a non-negative integer")
            end = min(start + length, metadata.byte_length)
        else:
            end = metadata.byte_length
        if start >= metadata.byte_length:
            return b""

        output = bytearray()
        chunk_table = self.catalog.get_table("__thesagra_blob_chunks")
        chunk_rows = sorted(
            (
                row
                for row in self.read_records(chunk_table.page_id)
                if row[0] == object_id
            ),
            key=lambda row: row[2],
        )
        object_directory = os.path.join(self._blob_directory(), str(object_id))
        for chunk_row in chunk_rows:
            chunk_offset = chunk_row[2]
            chunk_length = chunk_row[3]
            chunk_end = chunk_offset + chunk_length
            if chunk_end <= start:
                continue
            if chunk_offset >= end:
                break
            chunk_path = os.path.join(
                object_directory, f"{chunk_row[1]}.chunk"
            )
            if not os.path.isfile(chunk_path):
                raise BlobError(
                    f"Chunk {chunk_row[1]} missing for blob {object_id}"
                )
            with open(chunk_path, "rb") as chunk_file:
                chunk = chunk_file.read()
            if len(chunk) != chunk_length:
                raise BlobError(
                    f"Chunk {chunk_row[1]} for blob {object_id} is truncated"
                )
            if hashlib.sha256(chunk).hexdigest() != chunk_row[4]:
                raise BlobError(
                    f"Chunk {chunk_row[1]} checksum mismatch"
                )
            slice_start = max(start - chunk_offset, 0)
            slice_end = min(end - chunk_offset, chunk_length)
            output.extend(chunk[slice_start:slice_end])
        if len(output) != end - start:
            raise BlobError(f"Blob {object_id} has an incomplete chunk layout")
        return bytes(output)

    def stream_blob(self, object_id, chunk_size=64 * 1024):
        metadata = self.get_blob_metadata(object_id)
        if metadata is None:
            raise BlobError(f"Blob {object_id} does not exist")
        if metadata.state != "ready":
            raise BlobError(f"Blob {object_id} is not finalized")
        if not isinstance(chunk_size, int) or isinstance(chunk_size, bool) or chunk_size < 1:
            raise BlobError("Stream chunk size must be positive")
        for offset in range(0, metadata.byte_length, chunk_size):
            yield self.read_blob_range(
                object_id,
                offset,
                min(chunk_size, metadata.byte_length - offset),
            )

    def delete_blob(self, object_id):
        metadata = self.get_blob_metadata(object_id)
        if metadata is None:
            raise BlobError(f"Blob {object_id} does not exist")
        if metadata.state == "deleted":
            return
        table = self.catalog.get_table("__thesagra_blobs")
        rows = self.read_records(table.page_id)
        for index, row in enumerate(rows):
            if row[0] == object_id:
                rows[index] = (
                    row[0], row[1], row[2], row[3],
                    row[4], "deleted", row[6], row[7],
                )
                break
        self.write_records(table.page_id, rows)

    def reconcile_blobs(self):
        if self.active_transaction is not None:
            raise BlobError(
                "Blob reconciliation cannot run during an active transaction"
            )
        blob_table = self.catalog.get_table("__thesagra_blobs")
        blob_rows = self.read_records(blob_table.page_id)
        metadata_by_id = {row[0]: row for row in blob_rows}
        live_ids = {
            row[0] for row in blob_rows
            if row[5] in ("ready", "uploading")
        }
        chunk_table = self.catalog.get_table("__thesagra_blob_chunks")
        chunk_rows = self.read_records(chunk_table.page_id)
        retained_rows = [
            row
            for row in chunk_rows
            if not (
                metadata_by_id.get(row[0])
                and metadata_by_id[row[0]][5] == "uploading"
                and row[2] >= metadata_by_id[row[0]][3]
            )
        ]
        if len(retained_rows) != len(chunk_rows):
            self.write_records(chunk_table.page_id, retained_rows)
        chunk_rows = retained_rows
        referenced_chunks = {}
        for row in chunk_rows:
            referenced_chunks.setdefault(row[0], set()).add(
                f"{row[1]}.chunk"
            )
        cleaned = []
        root = self._blob_directory()
        if not os.path.isdir(root):
            return cleaned
        for entry in os.listdir(root):
            object_directory = os.path.join(root, entry)
            if not os.path.isdir(object_directory):
                continue
            try:
                object_id = int(entry)
            except ValueError:
                continue
            if object_id in live_ids:
                keep = referenced_chunks.get(object_id, set())
                for name in os.listdir(object_directory):
                    path = os.path.join(object_directory, name)
                    if (
                        os.path.isfile(path)
                        and name not in keep
                        and (name.endswith(".chunk") or name.endswith(".chunk.tmp"))
                    ):
                        os.remove(path)
                continue
            for name in os.listdir(object_directory):
                os.remove(os.path.join(object_directory, name))
            os.rmdir(object_directory)
            cleaned.append(object_id)
        return cleaned

    def create_node(self, label: str, properties=None, node_id=None):
        if not isinstance(label, str) or not label:
            raise GraphError("Node label must be a non-empty string")
        properties = properties or {}
        if not isinstance(properties, dict):
            raise GraphError("Node properties must be a dictionary")
        table = self.catalog.get_table("__thesagra_nodes")
        rows = self.read_records(table.page_id)
        existing_ids = {row[0] for row in rows}
        if node_id is None:
            node_id = 1
            while node_id in existing_ids:
                node_id += 1
        if not isinstance(node_id, int) or isinstance(node_id, bool):
            raise GraphError("Node ID must be an integer")
        if node_id in existing_ids:
            raise GraphError(f"Node {node_id} already exists")
        try:
            encoded_properties = json.dumps(properties, sort_keys=True)
        except (TypeError, ValueError) as exc:
            raise GraphError("Node properties must be JSON-compatible") from exc
        rows.append((node_id, label, encoded_properties))
        self.write_records(table.page_id, rows)
        return GraphNode(node_id, label, dict(properties))

    def create_edge(
        self,
        source_node_id: int,
        target_node_id: int,
        relationship_type: str,
        properties=None,
        edge_id=None,
    ):
        if not isinstance(relationship_type, str) or not relationship_type:
            raise GraphError("Relationship type must be a non-empty string")
        properties = properties or {}
        if not isinstance(properties, dict):
            raise GraphError("Edge properties must be a dictionary")

        node_table = self.catalog.get_table("__thesagra_nodes")
        node_ids = {row[0] for row in self.read_records(node_table.page_id)}
        if source_node_id not in node_ids:
            raise GraphError(f"Source node {source_node_id} does not exist")
        if target_node_id not in node_ids:
            raise GraphError(f"Target node {target_node_id} does not exist")

        edge_table = self.catalog.get_table("__thesagra_edges")
        edges = self.read_records(edge_table.page_id)
        existing_ids = {row[0] for row in edges}
        if edge_id is None:
            edge_id = 1
            while edge_id in existing_ids:
                edge_id += 1
        if not isinstance(edge_id, int) or isinstance(edge_id, bool):
            raise GraphError("Edge ID must be an integer")
        if edge_id in existing_ids:
            raise GraphError(f"Edge {edge_id} already exists")
        try:
            encoded_properties = json.dumps(properties, sort_keys=True)
        except (TypeError, ValueError) as exc:
            raise GraphError("Edge properties must be JSON-compatible") from exc
        edges.append(
            (
                edge_id,
                source_node_id,
                target_node_id,
                relationship_type,
                encoded_properties,
            )
        )
        self.write_records(edge_table.page_id, edges)
        return GraphEdge(
            edge_id,
            source_node_id,
            target_node_id,
            relationship_type,
            dict(properties),
        )

    def get_node(self, node_id):
        table = self.catalog.get_table("__thesagra_nodes")
        for row in self.read_records(table.page_id):
            if row[0] == node_id:
                try:
                    properties = json.loads(row[2])
                except json.JSONDecodeError as exc:
                    raise GraphError("Stored node properties are invalid") from exc
                return GraphNode(row[0], row[1], properties)
        return None

    def delete_edge(self, edge_id):
        table = self.catalog.get_table("__thesagra_edges")
        rows = self.read_records(table.page_id)
        kept = [row for row in rows if row[0] != edge_id]
        if len(kept) == len(rows):
            raise GraphError(f"Edge {edge_id} does not exist")
        self.write_records(table.page_id, kept)

    def delete_node(self, node_id):
        edge_table = self.catalog.get_table("__thesagra_edges")
        edge_rows = self.read_records(edge_table.page_id)
        if any(row[1] == node_id or row[2] == node_id for row in edge_rows):
            raise GraphError(
                f"Node {node_id} has incident edges; delete them first"
            )
        node_table = self.catalog.get_table("__thesagra_nodes")
        rows = self.read_records(node_table.page_id)
        kept = [row for row in rows if row[0] != node_id]
        if len(kept) == len(rows):
            raise GraphError(f"Node {node_id} does not exist")
        self.write_records(node_table.page_id, kept)

    def traverse(self, start_node_id, depth=1, relationship_type=None,
                 max_nodes=100):
        if not isinstance(depth, int) or isinstance(depth, bool) or depth < 0:
            raise GraphError("Traversal depth must be a non-negative integer")
        if not isinstance(max_nodes, int) or isinstance(max_nodes, bool) or max_nodes < 1:
            raise GraphError("max_nodes must be a positive integer")
        start = self.get_node(start_node_id)
        if start is None:
            raise GraphError(f"Node {start_node_id} does not exist")

        edge_table = self.catalog.get_table("__thesagra_edges")
        edges = self.read_records(edge_table.page_id)
        paths = [[start]]
        visited = {start_node_id}

        for _ in range(depth):
            next_paths = []
            for path in paths:
                current_id = path[-1].node_id
                for edge_row in edges:
                    edge_source = edge_row[1]
                    edge_target = edge_row[2]
                    edge_type = edge_row[3]
                    if edge_source != current_id:
                        continue
                    if relationship_type is not None and edge_type != relationship_type:
                        continue
                    if edge_target in visited:
                        continue
                    node = self.get_node(edge_target)
                    if node is None:
                        raise GraphError(
                            f"Edge endpoint {edge_target} does not exist"
                        )
                    if len(visited) >= max_nodes:
                        break
                    visited.add(edge_target)
                    next_paths.append(path + [node])
                    if len(visited) >= max_nodes:
                        break
                if len(visited) >= max_nodes:
                    break
            if not next_paths:
                break
            paths.extend(next_paths)
        return [tuple(path) for path in paths]

    def explain(self, statement: Explain):
        inner = statement.statement
        if not isinstance(inner, Select):
            return QueryResult(
                ["plan"],
                [("Execute: " + inner.__class__.__name__,)],
                1,
            )

        table = self.catalog.get_table(inner.table)
        plan = [f"Table Scan: {table.name}"]
        if inner.where is not None:
            column = table.column(inner.where.column)
            if column is not None and column.primary_key and inner.where.operator == "=":
                plan.append(f"Primary Key Lookup: {table.name}.{column.name}")
            else:
                plan.append(f"Filter: {table.name}.{inner.where.column}")
        if inner.join is not None:
            join_name = {
                "INNER": "Inner Join",
                "LEFT": "Left Join",
                "RIGHT": "Right Join",
                "FULL": "Full Outer Join",
                "CROSS": "Cross Join",
            }[inner.join.join_type]
            plan.append(f"{join_name}: {inner.join.table}")
        if inner.group_by is not None:
            plan.append(f"Group By: {inner.group_by}")
        if inner.order_by is not None:
            plan.append(
                f"Sort: {inner.order_by} "
                f"{'DESC' if inner.descending else 'ASC'}"
            )
        if inner.limit is not None:
            plan.append(f"Limit: {inner.limit}")
        return QueryResult(["plan"], [(step,) for step in plan], len(plan))

    def create_table(self, statement: CreateTable):
        columns = []
        try:
            for definition in statement.columns:
                columns.append(self.column_from_definition(definition))
            foreign_keys = [
                ForeignKey(
                    tuple(key.columns),
                    key.referenced_table,
                    tuple(key.referenced_columns),
                )
                for key in (statement.foreign_keys or [])
            ]
            self.catalog.create_table(
                statement.name,
                columns,
                foreign_keys,
            )
        except (CatalogError, TypeErrorValue) as exc:
            raise QueryError(str(exc)) from exc
        self._build_primary_indexes()
        return QueryResult([], [], 0)

    def column_from_definition(self, definition):
        type_name = normalize_type(definition.type_name)
        if (
            definition.type_length is not None
            and definition.type_name.upper()
            not in (
                "VARCHAR", "CHAR", "CHARACTER",
                "DECIMAL", "NUMERIC",
            )
        ):
            raise QueryError(
                f"Length is not supported for type "
                f"'{definition.type_name}'"
            )
        if definition.auto_increment and (
            type_name != "INTEGER" or not definition.primary_key
        ):
            raise QueryError(
                "AUTO_INCREMENT requires an INTEGER PRIMARY KEY"
            )
        if definition.default_current_timestamp and type_name != "TEXT":
            raise QueryError(
                "CURRENT_TIMESTAMP defaults require a text-compatible column"
            )
        return Column(
            definition.name,
            type_name,
            definition.nullable,
            definition.primary_key,
            definition.unique,
            definition.auto_increment,
            definition.default_value,
            definition.default_current_timestamp,
            definition.type_length,
        )

    def alter_table(self, statement: AlterTable):
        if self.active_transaction is not None:
            raise QueryError(
                "ALTER TABLE is not supported inside an active transaction"
            )
        try:
            table = self.catalog.get_table(statement.table)
            rows = self.read_records(table.page_id)
            added_rows = None
            column = None
            if statement.action == "add_column":
                if table.column(statement.definition.name) is not None:
                    if statement.if_exists:
                        return QueryResult([], [], 0)
                    raise QueryError(
                        f"Column '{statement.definition.name}' already exists"
                    )
                column = self.column_from_definition(statement.definition)
                if (
                    rows
                    and not column.nullable
                    and column.default_value is None
                    and not column.default_current_timestamp
                    and not column.auto_increment
                ):
                    raise QueryError(
                        "Cannot add a NOT NULL column to a populated table "
                        "without a default"
                    )
                default_timestamp = (
                    datetime.datetime.now(datetime.timezone.utc).isoformat()
                    if column.default_current_timestamp
                    else None
                )
                added_rows = []
                values = []
                for row_index, row in enumerate(rows):
                    if column.auto_increment:
                        value = row_index + 1
                    elif column.default_current_timestamp:
                        value = default_timestamp
                    else:
                        value = column.default_value
                    value = coerce_value(value, column)
                    values.append(value)
                    added_rows.append(tuple(row) + (value,))
                if column.primary_key or column.unique:
                    seen = set()
                    for value in values:
                        if value is None and column.unique:
                            continue
                        if value in seen:
                            raise QueryError(
                                f"Cannot add unique column '{column.name}' "
                                "with duplicate values"
                            )
                        seen.add(value)
            elif statement.action == "drop_column":
                column = table.column(statement.old_name)
                if column is None and not statement.if_exists:
                    raise QueryError(
                        f"Unknown column '{statement.old_name}' in "
                        f"table '{table.name}'"
                    )
            elif statement.action == "rename_column":
                if table.column(statement.old_name) is None:
                    raise QueryError(
                        f"Unknown column '{statement.old_name}' in "
                        f"table '{table.name}'"
                    )
            elif statement.action != "rename_table":
                raise QueryError(
                    f"Unsupported ALTER TABLE action '{statement.action}'"
                )

            self.begin()
            if statement.action == "add_column":
                self.catalog.add_column(
                    table.name,
                    column,
                    write_records=self.write_records,
                )
                self.write_records(table.page_id, added_rows)
            elif statement.action == "drop_column":
                column_index = self.catalog.drop_column(
                    table.name,
                    statement.old_name,
                    cascade=statement.cascade,
                    if_exists=statement.if_exists,
                    write_records=self.write_records,
                )
                if column_index is None:
                    self.rollback()
                    return QueryResult([], [], 0)
                self.write_records(
                    table.page_id,
                    [
                        tuple(row[:column_index]) + tuple(row[column_index + 1:])
                        for row in rows
                    ],
                )
            elif statement.action == "rename_column":
                self.catalog.rename_column(
                    table.name,
                    statement.old_name,
                    statement.new_name,
                    write_records=self.write_records,
                )
            else:
                self.catalog.rename_table(
                    table.name,
                    statement.new_name,
                    write_records=self.write_records,
                )
            self.commit()
        except (CatalogError, PageError, TypeErrorValue, ValueError, OSError) as exc:
            if self.active_transaction is not None:
                self.rollback()
            self.catalog.load()
            self._build_primary_indexes()
            raise QueryError(str(exc)) from exc
        except Exception:
            if self.active_transaction is not None:
                self.rollback()
            self.catalog.load()
            self._build_primary_indexes()
            raise
        self._build_primary_indexes()
        return QueryResult([], [], 0)

    def create_index(self, statement: CreateIndex):
        try:
            table = self.catalog.get_table(statement.table)
            columns = [table.column(name) for name in statement.columns]
            if any(column is None for column in columns):
                raise QueryError("Index refers to an unknown column")
            indexes = [
                table.columns.index(column)
                for column in columns
            ]
            if statement.unique:
                rows = self.read_records(table.page_id)
                seen = set()
                for row in rows:
                    key = tuple(row[index] for index in indexes)
                    if any(value is None for value in key):
                        continue
                    if key in seen:
                        raise QueryError(
                            "Cannot create a unique index with duplicate values"
                        )
                    seen.add(key)
            self.catalog.create_index(
                statement.name,
                statement.table,
                statement.columns,
                statement.unique,
            )
        except (CatalogError, PageError, ValueError, OSError) as exc:
            raise QueryError(str(exc)) from exc
        return QueryResult([], [], 0)

    def drop_table(self, statement: DropTable):
        if self.active_transaction is not None:
            raise QueryError(
                "DROP TABLE is not supported inside an active transaction"
            )
        try:
            table = self.catalog.drop_table(
                statement.name,
                cascade=statement.cascade,
                if_exists=statement.if_exists,
            )
            if table is None:
                return QueryResult([], [], 0)
            self.write_records(table.page_id, [])
        except (CatalogError, PageError, ValueError, OSError) as exc:
            raise QueryError(str(exc)) from exc
        self._build_primary_indexes()
        return QueryResult([], [], 0)

    def insert(self, statement: Insert):
        try:
            table = self.catalog.get_table(statement.table)
            existing = self.read_records(table.page_id)
            values_rows = statement.rows or [statement.values]
            indexes = self.insert_column_indexes(table, statement)
            for values in values_rows:
                if len(values) != len(indexes):
                    raise QueryError(
                        f"Expected {len(indexes)} values, got {len(values)}"
                    )
                row = [None] * len(table.columns)
                for index, value in zip(indexes, values):
                    row[index] = coerce_value(value, table.columns[index])
                for index, column in enumerate(table.columns):
                    if column.auto_increment and (
                        index not in indexes or row[index] is None
                    ):
                        row[index] = max(
                            (existing_row[index] for existing_row in existing),
                            default=0,
                        ) + 1
                    elif index not in indexes:
                        if column.default_current_timestamp:
                            row[index] = datetime.datetime.now(
                                datetime.timezone.utc
                            ).isoformat()
                        elif column.default_value is not None:
                            row[index] = column.default_value
                    row[index] = coerce_value(row[index], column)
                candidate = tuple(row)
                if not self.row_constraints_are_unique(
                    table,
                    candidate,
                    existing,
                ):
                    raise QueryError(
                        "Duplicate primary key or unique value"
                    )
                self.require_foreign_keys(
                    table,
                    candidate,
                    existing,
                )
                existing.append(candidate)
            self.write_records(table.page_id, existing)
            self._build_primary_indexes()
            return QueryResult([], [], len(values_rows))
        except (CatalogError, TypeErrorValue, PageError, ValueError) as exc:
            raise QueryError(str(exc)) from exc

    def insert_column_indexes(self, table, statement):
        if statement.columns is None:
            indexes = list(range(len(table.columns)))
        else:
            indexes = []
            for name in statement.columns:
                column = table.column(name)
                if column is None:
                    raise QueryError(
                        f"Unknown column '{name}' in table '{table.name}'"
                    )
                indexes.append(table.columns.index(column))
            if len(set(indexes)) != len(indexes):
                raise QueryError("Duplicate column in INSERT")
        return indexes

    def require_foreign_keys(self, table, candidate, current_rows=None):
        for foreign_key in table.foreign_keys:
            values = tuple(
                candidate[
                    table.columns.index(table.column(column_name))
                ]
                for column_name in foreign_key.columns
            )
            if any(value is None for value in values):
                continue
            if foreign_key.referenced_table.lower() == table.name.lower():
                target_rows = current_rows or self.read_records(table.page_id)
                target = table
            else:
                target = self.catalog.get_table(
                    foreign_key.referenced_table
                )
                target_rows = self.read_records(target.page_id)
            target_indexes = [
                target.columns.index(target.column(column_name))
                for column_name in foreign_key.referenced_columns
            ]
            if not any(
                tuple(row[index] for index in target_indexes) == values
                for row in target_rows
            ):
                raise QueryError(
                    f"Foreign key on '{table.name}' does not reference "
                    f"a row in '{target.name}'"
                )

    def select(self, statement: Select):
        try:
            table = self.catalog.get_table(statement.table)
            rows = self.read_records(table.page_id)
        except (CatalogError, PageError) as exc:
            raise QueryError(str(exc)) from exc

        if (
            statement.join is None
            and not statement.additional_joins
            and statement.where is not None
            and statement.where.conditions is None
            and statement.where.operator == "="
        ):
            column = table.column(statement.where.column)
            if (
                column is not None
                and column.primary_key
                and not isinstance(statement.where.value, Select)
            ):
                try:
                    key = coerce_value(statement.where.value, column)
                    row_number = self.primary_indexes[table.name.lower()].get(key)
                    rows = [] if row_number is None else [rows[row_number]]
                except (KeyError, TypeErrorValue):
                    raise QueryError(
                        f"Invalid value for primary key '{column.name}'"
                    )

        sources = [(statement.table_alias or table.name, table, rows)]
        combined_rows = [(row,) for row in rows]
        joins = ([statement.join] if statement.join is not None else []) + (
            statement.additional_joins or []
        )
        for join in joins:
            try:
                right_table = self.catalog.get_table(join.table)
                right_rows = self.read_records(right_table.page_id)
            except (CatalogError, PageError) as exc:
                raise QueryError(str(exc)) from exc
            sources.append((
                join.alias or right_table.name,
                right_table,
                right_rows,
            ))
            prior_sources = sources[:-1]
            prior_rows = combined_rows
            combined_rows = []
            join_type = join.join_type
            unmatched_left = tuple(None for _ in table.columns)
            unmatched_right = tuple(None for _ in right_table.columns)
            matched_right = set()
            for left_rows in prior_rows:
                matched = False
                for right_index, right_row in enumerate(right_rows):
                    source_rows = left_rows + (right_row,)
                    if (
                        join_type == "CROSS"
                        or self.matches_join(
                            sources, source_rows, join
                        )
                    ):
                        combined_rows.append(source_rows)
                        matched = True
                        matched_right.add(right_index)
                if not matched and join_type in ("LEFT", "FULL"):
                    combined_rows.append(left_rows + (unmatched_right,))
            if join_type in ("RIGHT", "FULL"):
                for right_index, right_row in enumerate(right_rows):
                    if right_index not in matched_right:
                        combined_rows.append(
                            tuple(
                                tuple(None for _ in source[1].columns)
                                for source in prior_sources
                            )
                            + (right_row,)
                        )

        filtered = []
        for source_rows in combined_rows:
            if statement.where is not None:
                if not self.matches_joined_where(
                    sources, source_rows, statement.where
                ):
                    continue
            filtered.append(source_rows)

        has_aggregates = statement.columns is not None and any(
            isinstance(column, SelectedColumn) and column.aggregate is not None
            for column in statement.columns
        )
        if has_aggregates:
            groups = self.aggregate_groups(
                sources, filtered, statement.group_by
            )
            selected_names = []
            result_rows = []
            for column in statement.columns:
                if isinstance(column, SelectedColumn) and column.aggregate:
                    selected_names.append(
                        column.alias or f"{column.aggregate}({column.name})"
                    )
                else:
                    selected_names.append(
                        getattr(column, "alias", None)
                        or getattr(column, "name", str(column))
                    )
            for group_values, group_rows in groups:
                if statement.having is not None:
                    having_value = self.aggregate_value(
                        sources,
                        group_rows,
                        SelectedColumn(
                            name=statement.having.column,
                            aggregate=statement.having.aggregate,
                        ),
                    )
                    if not self.compare_values(
                        having_value,
                        statement.having.operator,
                        statement.having.value,
                    ):
                        continue
                aggregate_row = []
                for column in statement.columns:
                    if not isinstance(column, SelectedColumn) or column.aggregate is None:
                        aggregate_row.append(
                            self.resolve_joined_value(
                                sources,
                                group_rows[0],
                                getattr(column, "name", str(column)),
                            )
                        )
                    else:
                        aggregate_row.append(
                            self.aggregate_value(
                                sources,
                                group_rows,
                                column,
                            )
                        )
                result_rows.append(tuple(aggregate_row))
            if statement.distinct:
                result_rows = list(dict.fromkeys(result_rows))
            if statement.limit is not None:
                result_rows = result_rows[:statement.limit]
            return QueryResult(selected_names, result_rows, len(result_rows))

        if statement.columns is None:
            selected_names = []
            selected_specs = []
            for source_name, source_table, _ in sources:
                for column in source_table.columns:
                    selected_names.append(
                        f"{source_name}.{column.name}"
                        if statement.join is not None
                        else column.name
                    )
                    selected_specs.append((source_name, column.name))
        else:
            selected_names = []
            selected_specs = []
            for column in statement.columns:
                name = getattr(column, "name", str(column))
                selected_names.append(
                    getattr(column, "alias", None) or name
                )
                selected_specs.append((None, name))

        result_rows = []
        for source_rows in filtered:
            selected_row = []
            for qualifier, name in selected_specs:
                selected_row.append(
                    self.resolve_joined_value(
                        sources, source_rows, name, qualifier
                    )
                )
            result_rows.append(tuple(selected_row))

        if statement.distinct:
            result_rows = list(dict.fromkeys(result_rows))

        if statement.order_by is not None:
            order_index = None
            for index, (qualifier, name) in enumerate(selected_specs):
                if name.lower() == statement.order_by.lower():
                    order_index = index
                    break
            if order_index is not None:
                result_rows.sort(
                    key=lambda row: row[order_index],
                    reverse=statement.descending,
                )
            else:
                paired_rows = [
                    (
                        self.resolve_joined_value(
                            sources,
                            source_rows,
                            statement.order_by,
                        ),
                        result_row,
                    )
                    for source_rows, result_row in zip(filtered, result_rows)
                ]
                paired_rows.sort(
                    key=lambda item: item[0],
                    reverse=statement.descending,
                )
                result_rows = [item[1] for item in paired_rows]

        if statement.limit is not None:
            result_rows = result_rows[:statement.limit]
        return QueryResult(selected_names, result_rows, len(result_rows))

    def resolve_joined_value(self, sources, source_rows, name, qualifier=None):
        if "." in name:
            name_qualifier, name = name.split(".", 1)
            if qualifier is None:
                qualifier = name_qualifier
        for source_index, (table_name, table, _) in enumerate(sources):
            if qualifier is not None and table_name.lower() != str(qualifier).lower():
                continue
            column = table.column(name)
            if column is not None:
                row = source_rows[source_index]
                return row[table.columns.index(column)]
        raise QueryError(f"Unknown column '{name}'")

    def matches_join(self, sources, source_rows, join):
        def split_name(value):
            if "." in value:
                qualifier, column = value.split(".", 1)
                return qualifier, column
            return None, value

        left_qualifier, left_column = split_name(join.left_column)
        right_qualifier, right_column = split_name(join.right_column)
        left = self.resolve_joined_value(
            sources, source_rows, left_column, left_qualifier
        )
        right = self.resolve_joined_value(
            sources, source_rows, right_column, right_qualifier
        )
        return left == right

    def matches_joined_where(self, sources, source_rows, where):
        if where.conditions is not None:
            return all(
                self.matches_joined_where(sources, source_rows, condition)
                for condition in where.conditions
            )
        actual = self.resolve_joined_value(
            sources, source_rows, where.column, where.qualifier
        )
        if where.operator == "IS NULL":
            return actual is None
        if where.operator == "IS NOT NULL":
            return actual is not None
        value = where.value
        if where.operator not in ("IN", "BETWEEN") and not isinstance(
            value,
            Select,
        ):
            for source_name, table, _ in sources:
                if (
                    where.qualifier is not None
                    and source_name.lower() != where.qualifier.lower()
                ):
                    continue
                column = table.column(where.column)
                if column is not None:
                    value = coerce_value(value, column)
                    break

        if where.operator == "IN":
            if isinstance(value, Select):
                result = self.select(value)
                candidates = [row[0] for row in result.rows if row]
            else:
                candidates = value
            for source_name, table, _ in sources:
                if (
                    where.qualifier is not None
                    and source_name.lower() != where.qualifier.lower()
                ):
                    continue
                column = table.column(where.column)
                if column is not None:
                    candidates = [
                        coerce_value(candidate, column)
                        for candidate in candidates
                    ]
                    break
            return actual in candidates
        if isinstance(value, Select):
            result = self.select(value)
            if not result.rows or not result.rows[0]:
                value = None
            else:
                value = result.rows[0][0]
                for source_name, table, _ in sources:
                    if (
                        where.qualifier is not None
                        and source_name.lower() != where.qualifier.lower()
                    ):
                        continue
                    column = table.column(where.column)
                    if column is not None:
                        value = coerce_value(value, column)
                        break

        if where.operator == "BETWEEN":
            lower, upper = where.value
            for source_name, table, _ in sources:
                if (
                    where.qualifier is not None
                    and source_name.lower() != where.qualifier.lower()
                ):
                    continue
                column = table.column(where.column)
                if column is not None:
                    lower = coerce_value(lower, column)
                    upper = coerce_value(upper, column)
                    break
            return actual is not None and lower <= actual <= upper
        if where.operator == "LIKE":
            if actual is None:
                return False
            pattern = re.escape(str(value))
            pattern = pattern.replace("%", ".*").replace("_", ".")
            return re.fullmatch(pattern, str(actual), re.DOTALL) is not None

        if where.operator == "=":
            return actual == value
        if where.operator == "!=":
            return actual != value
        if where.operator == "<":
            return actual is not None and actual < value
        if where.operator == "<=":
            return actual is not None and actual <= value
        if where.operator == ">":
            return actual is not None and actual > value
        if where.operator == ">=":
            return actual is not None and actual >= value
        raise QueryError(f"Unsupported operator '{where.operator}'")

    @staticmethod
    def compare_values(actual, operator, value):
        if operator == "=":
            return actual == value
        if operator == "!=":
            return actual != value
        if actual is None or value is None:
            return False
        if operator == "<":
            return actual < value
        if operator == "<=":
            return actual <= value
        if operator == ">":
            return actual > value
        if operator == ">=":
            return actual >= value
        raise QueryError(f"Unsupported operator '{operator}'")

    def aggregate_groups(self, sources, filtered, group_by):
        if group_by is None:
            return [(None, filtered)]
        groups = {}
        for source_rows in filtered:
            key = self.resolve_joined_value(sources, source_rows, group_by)
            groups.setdefault(key, []).append(source_rows)
        return list(groups.items())

    def aggregate_value(self, sources, group_rows, column):
        if column.aggregate == "COUNT":
            if column.name == "*":
                return len(group_rows)
            return sum(
                1
                for source_rows in group_rows
                if self.resolve_joined_value(
                    sources, source_rows, column.name
                ) is not None
            )

        values = [
            self.resolve_joined_value(sources, source_rows, column.name)
            for source_rows in group_rows
        ]
        values = [value for value in values if value is not None]
        if not values:
            return None
        if column.aggregate == "SUM":
            return sum(values)
        if column.aggregate == "AVG":
            return sum(values) / len(values)
        if column.aggregate == "MIN":
            return min(values)
        if column.aggregate == "MAX":
            return max(values)
        raise QueryError(f"Unsupported aggregate '{column.aggregate}'")

    def update(self, statement: Update):
        try:
            table = self.catalog.get_table(statement.table)
            rows = self.read_records(table.page_id)
        except (CatalogError, PageError) as exc:
            raise QueryError(str(exc)) from exc

        assignments = {}
        for assignment in statement.assignments:
            column = table.column(assignment.column)
            if column is None:
                raise QueryError(
                    f"Unknown column '{assignment.column}' "
                    f"in table '{table.name}'"
                )
            value = assignment.value
            if isinstance(value, ArithmeticExpression):
                value = ArithmeticExpression(
                    value.column,
                    value.operator,
                    coerce_value(value.value, column),
                )
            else:
                value = coerce_value(value, column)
            assignments[table.columns.index(column)] = (column, value)

        new_rows = []
        affected = 0
        for row in rows:
            if statement.where is not None and not self.matches_where(
                table, row, statement.where
            ):
                new_rows.append(row)
                continue
            updated = list(row)
            for index, (column, value) in assignments.items():
                if isinstance(value, ArithmeticExpression):
                    source_column = table.column(value.column)
                    if source_column is None:
                        raise QueryError(
                            f"Unknown column '{value.column}' "
                            f"in table '{table.name}'"
                        )
                    left = updated[
                        table.columns.index(source_column)
                    ]
                    right = value.value
                    if left is None or right is None:
                        updated[index] = None
                    else:
                        try:
                            if value.operator == "+":
                                calculated = left + right
                            elif value.operator == "-":
                                calculated = left - right
                            elif value.operator == "*":
                                calculated = left * right
                            elif value.operator == "/":
                                calculated = left / right
                            else:
                                raise QueryError(
                                    "Unsupported arithmetic operator"
                                )
                        except (TypeError, ZeroDivisionError) as exc:
                            raise QueryError(
                                f"Invalid arithmetic expression for "
                                f"'{column.name}'"
                            ) from exc
                        updated[index] = coerce_value(
                            calculated,
                            column,
                        )
                else:
                    updated[index] = value
            for index, column in enumerate(table.columns):
                updated[index] = coerce_value(updated[index], column)
            if not self.row_constraints_are_unique(
                table,
                tuple(updated),
                new_rows,
            ):
                raise QueryError("Duplicate primary key or unique value")
            new_rows.append(tuple(updated))
            affected += 1

        for updated_row in new_rows:
            self.require_foreign_keys(table, updated_row, new_rows)
        self.require_no_referenced_rows(table, new_rows)

        try:
            self.write_records(table.page_id, new_rows)
        except (PageError, ValueError) as exc:
            raise QueryError(str(exc)) from exc
        self._build_primary_indexes()
        return QueryResult([], [], affected)

    def row_constraints_are_unique(self, table, candidate, existing_rows):
        primary_indexes = [
            index
            for index, column in enumerate(table.columns)
            if column.primary_key
        ]
        if primary_indexes:
            primary_key = tuple(candidate[index] for index in primary_indexes)
            if any(value is None for value in primary_key):
                return False
            if any(
                tuple(row[index] for index in primary_indexes) == primary_key
                for row in existing_rows
            ):
                return False

        for column_index, column in enumerate(table.columns):
            if not column.unique or column.primary_key:
                continue
            value = candidate[column_index]
            if value is not None and any(
                row[column_index] == value for row in existing_rows
            ):
                return False
        for index in table.indexes:
            if not index.unique:
                continue
            indexes = [
                table.columns.index(table.column(name))
                for name in index.columns
            ]
            key = tuple(candidate[index] for index in indexes)
            if any(value is None for value in key):
                continue
            if any(
                tuple(row[index] for index in indexes) == key
                for row in existing_rows
            ):
                return False
        return True

    def require_no_referenced_rows(self, table, target_rows):
        for child_table in self.catalog.tables.values():
            child_rows = (
                target_rows
                if child_table.name.lower() == table.name.lower()
                else self.read_records(child_table.page_id)
            )
            for foreign_key in child_table.foreign_keys:
                if (
                    foreign_key.referenced_table.lower()
                    != table.name.lower()
                ):
                    continue
                target_indexes = [
                    table.columns.index(table.column(name))
                    for name in foreign_key.referenced_columns
                ]
                child_indexes = [
                    child_table.columns.index(
                        child_table.column(name)
                    )
                    for name in foreign_key.columns
                ]
                target_keys = {
                    tuple(row[index] for index in target_indexes)
                    for row in target_rows
                }
                for child_row in child_rows:
                    child_key = tuple(
                        child_row[index] for index in child_indexes
                    )
                    if (
                        not any(value is None for value in child_key)
                        and child_key not in target_keys
                    ):
                        raise QueryError(
                            f"Cannot change '{table.name}': rows in "
                            f"'{child_table.name}' reference it"
                        )

    def delete(self, statement: Delete):
        try:
            table = self.catalog.get_table(statement.table)
            rows = self.read_records(table.page_id)
        except (CatalogError, PageError) as exc:
            raise QueryError(str(exc)) from exc

        kept = []
        affected = 0
        for row in rows:
            if statement.where is not None and not self.matches_where(
                table, row, statement.where
            ):
                kept.append(row)
            else:
                affected += 1
        self.require_no_referenced_rows(table, kept)
        try:
            self.write_records(table.page_id, kept)
        except (PageError, ValueError) as exc:
            raise QueryError(str(exc)) from exc
        self._build_primary_indexes()
        return QueryResult([], [], affected)

    def matches_where(self, table, row, where):
        return self.matches_joined_where(
            [(table.name, table, [])],
            (row,),
            where,
        )

