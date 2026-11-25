import base64
import json
import os
import struct


class WALError(Exception):
    pass


class WAL:
    MAGIC = b"TSGWAL1"
    HEADER = struct.Struct(">I")

    def __init__(self, database_path: str):
        self.path = os.path.splitext(os.fspath(database_path))[0] + ".wal"
        if not os.path.exists(self.path):
            with open(self.path, "wb") as file:
                file.write(self.MAGIC)
                file.flush()
                os.fsync(file.fileno())

    def append(self, transaction_id: int, record_type: str, payload=None):
        record = {
            "transaction_id": transaction_id,
            "type": record_type,
            "payload": payload,
        }
        encoded = json.dumps(record, separators=(",", ":")).encode("utf-8")
        framed = self.HEADER.pack(len(encoded)) + encoded
        with open(self.path, "ab") as file:
            file.write(framed)
            file.flush()
            os.fsync(file.fileno())

    def append_page(self, transaction_id: int, page_id: int, page: bytes):
        payload = {
            "page_id": page_id,
            "page": base64.b64encode(page).decode("ascii"),
        }
        self.append(transaction_id, "SET_PAGE", payload)

    def begin(self, transaction_id: int):
        self.append(transaction_id, "BEGIN")

    def commit(self, transaction_id: int):
        self.append(transaction_id, "COMMIT")

    def rollback(self, transaction_id: int):
        self.append(transaction_id, "ROLLBACK")

    def records(self):
        with open(self.path, "rb") as file:
            magic = file.read(len(self.MAGIC))
            if magic != self.MAGIC:
                raise WALError("Invalid WAL magic")
            while True:
                header = file.read(self.HEADER.size)
                if not header:
                    break
                if len(header) != self.HEADER.size:
                    raise WALError("Truncated WAL record length")
                length = self.HEADER.unpack(header)[0]
                encoded = file.read(length)
                if len(encoded) != length:
                    raise WALError("Truncated WAL record")
                try:
                    yield json.loads(encoded.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise WALError("Malformed WAL record") from exc

    def committed_page_snapshots(self):
        committed = set()
        pending = {}
        snapshots = []
        for record in self.records():
            transaction_id = record["transaction_id"]
            record_type = record["type"]
            if record_type == "BEGIN":
                pending[transaction_id] = []
            elif record_type == "SET_PAGE":
                pending.setdefault(transaction_id, []).append(record["payload"])
            elif record_type == "COMMIT":
                committed.add(transaction_id)
                snapshots.extend(pending.pop(transaction_id, []))
            elif record_type == "ROLLBACK":
                pending.pop(transaction_id, None)
        return committed, snapshots
