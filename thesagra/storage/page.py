import struct
import zlib
from typing import Iterable

PAGE_SIZE = 4096
FORMAT_VERSION = 1

MAGIC = b"TSG1"
PAGE_KIND_DATABASE = 1
PAGE_KIND_DATA = 2

HEADER = struct.Struct(">4sHHIII")
HEADER_SIZE = HEADER.size


class PageError(Exception):
    """Raised when an on-disk page is malformed or corrupt."""


def encode_value(value):
    if value is None:
        return b"\x00"
    if isinstance(value, bool):
        return b"\x01" + (b"\x01" if value else b"\x00")
    if isinstance(value, int) and not isinstance(value, bool):
        return b"\x02" + struct.pack(">q", value)
    if isinstance(value, float):
        return b"\x03" + struct.pack(">d", value)
    if isinstance(value, str):
        payload = value.encode("utf-8")
        return b"\x04" + struct.pack(">I", len(payload)) + payload
    if isinstance(value, bytes):
        return b"\x05" + struct.pack(">I", len(value)) + value
    raise TypeError(f"Unsupported value type: {type(value).__name__}")


def decode_value(payload: bytes):
    if not payload:
        raise PageError("Truncated value")

    kind = payload[0]
    body = payload[1:]
    if kind == 0:
        if body:
            raise PageError("Invalid null value")
        return None
    if kind == 1:
        if len(body) != 1 or body[0] not in (0, 1):
            raise PageError("Invalid boolean value")
        return body[0] == 1
    if kind == 2:
        if len(body) != 8:
            raise PageError("Invalid integer value")
        return struct.unpack(">q", body)[0]
    if kind == 3:
        if len(body) != 8:
            raise PageError("Invalid float value")
        return struct.unpack(">d", body)[0]
    if kind in (4, 5):
        if len(body) < 4:
            raise PageError("Truncated length-prefixed value")
        length = struct.unpack(">I", body[:4])[0]
        data = body[4:]
        if len(data) != length:
            raise PageError("Invalid length-prefixed value")
        if kind == 5:
            return data
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PageError("Invalid UTF-8 string") from exc
    raise PageError(f"Unknown value type: {kind}")


def encode_record(record: Iterable) -> bytes:
    values = list(record)
    payload = b"".join(
        struct.pack(">I", len(encoded)) + encoded
        for encoded in (encode_value(value) for value in values)
    )
    return struct.pack(">I", len(values)) + payload


def decode_record(payload: bytes):
    if len(payload) < 4:
        raise PageError("Truncated record")

    value_count = struct.unpack(">I", payload[:4])[0]
    offset = 4
    values = []
    for _ in range(value_count):
        if offset + 4 > len(payload):
            raise PageError("Truncated record value length")
        length = struct.unpack(">I", payload[offset:offset + 4])[0]
        offset += 4
        if offset + length > len(payload):
            raise PageError("Truncated record value")
        values.append(decode_value(payload[offset:offset + length]))
        offset += length
    if offset != len(payload):
        raise PageError("Trailing data in record")
    return tuple(values)


def encode_data_payload(records: Iterable[Iterable]) -> bytes:
    encoded_records = [encode_record(record) for record in records]
    payload = b"".join(
        struct.pack(">I", len(record)) + record
        for record in encoded_records
    )
    result = struct.pack(">I", len(encoded_records)) + payload
    if len(result) > PAGE_SIZE - HEADER_SIZE:
        raise ValueError("Records exceed one page")
    return result


def decode_data_payload(payload: bytes):
    if len(payload) < 4:
        raise PageError("Truncated data page")

    record_count = struct.unpack(">I", payload[:4])[0]
    offset = 4
    records = []
    for _ in range(record_count):
        if offset + 4 > len(payload):
            raise PageError("Truncated record length")
        length = struct.unpack(">I", payload[offset:offset + 4])[0]
        offset += 4
        if offset + length > len(payload):
            raise PageError("Truncated record")
        records.append(decode_record(payload[offset:offset + length]))
        offset += length
    if offset != len(payload):
        raise PageError("Trailing data in data page")
    return records


def encode_page(page_id: int, page_kind: int, payload: bytes) -> bytes:
    if len(payload) > PAGE_SIZE - HEADER_SIZE:
        raise ValueError("Payload exceeds page capacity")

    checksum = zlib.crc32(payload) & 0xffffffff
    header = HEADER.pack(
        MAGIC,
        FORMAT_VERSION,
        page_kind,
        page_id,
        len(payload),
        checksum,
    )
    page = header + payload
    return page + (b"\x00" * (PAGE_SIZE - len(page)))


def decode_page(page: bytes, expected_page_id: int):
    if len(page) != PAGE_SIZE:
        raise PageError(f"Page is {len(page)} bytes, expected {PAGE_SIZE}")

    magic, version, kind, page_id, payload_length, checksum = HEADER.unpack(
        page[:HEADER_SIZE]
    )
    if magic != MAGIC:
        raise PageError("Invalid page magic")
    if version != FORMAT_VERSION:
        raise PageError(f"Unsupported format version: {version}")
    if page_id != expected_page_id:
        raise PageError(
            f"Page ID mismatch: found {page_id}, expected {expected_page_id}"
        )
    if payload_length > PAGE_SIZE - HEADER_SIZE:
        raise PageError("Invalid payload length")

    payload = page[HEADER_SIZE:HEADER_SIZE + payload_length]
    if zlib.crc32(payload) & 0xffffffff != checksum:
        raise PageError("Page checksum mismatch")
    return kind, payload
