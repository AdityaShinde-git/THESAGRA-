import json
import struct
from typing import Any, Dict


MAGIC = b"TSGP"
PROTOCOL_VERSION = 1
MAX_MESSAGE_SIZE = 1024 * 1024

REQUEST = 1
RESPONSE = 2
CANCEL = 3

HEADER = struct.Struct(">4sBBI")
HEADER_SIZE = HEADER.size


class ProtocolError(Exception):
    pass


def encode_message(message_type: int, payload: Dict[str, Any]) -> bytes:
    encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    if len(encoded) > MAX_MESSAGE_SIZE:
        raise ProtocolError("Message exceeds maximum size")
    return HEADER.pack(MAGIC, PROTOCOL_VERSION, message_type, len(encoded)) + encoded


def recv_exact(stream, length: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < length:
        chunk = stream.recv(length - len(chunks))
        if not chunk:
            raise ProtocolError("Connection closed during message")
        chunks.extend(chunk)
    return bytes(chunks)


def receive_message(stream):
    header = recv_exact(stream, HEADER_SIZE)
    magic, version, message_type, payload_length = HEADER.unpack(header)
    if magic != MAGIC:
        raise ProtocolError("Invalid protocol magic")
    if version != PROTOCOL_VERSION:
        raise ProtocolError(
            f"Unsupported protocol version: {version}"
        )
    if payload_length > MAX_MESSAGE_SIZE:
        raise ProtocolError("Message exceeds maximum size")
    payload_bytes = recv_exact(stream, payload_length)
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("Invalid JSON payload") from exc
    if not isinstance(payload, dict):
        raise ProtocolError("Payload must be a JSON object")
    return message_type, payload


def send_message(stream, message_type: int, payload: Dict[str, Any]):
    stream.sendall(encode_message(message_type, payload))


def sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if value is True:
        return "TRUE"
    if value is False:
        return "FALSE"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        if not value == value or value in (float("inf"), float("-inf")):
            raise ProtocolError("Non-finite numbers are not supported")
        return repr(value)
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    if isinstance(value, list):
        raise ProtocolError("List parameters are not supported")
    if isinstance(value, dict):
        raise ProtocolError("Object parameters are not supported")
    raise ProtocolError(
        f"Unsupported parameter type: {type(value).__name__}"
    )


def bind_parameters(sql: str, parameters) -> str:
    if parameters is None:
        parameters = []
    if not isinstance(parameters, list):
        raise ProtocolError("Parameters must be a JSON array")
    result = sql
    position = 0
    parameter_index = 0
    while True:
        marker = result.find("?", position)
        if marker < 0:
            break
        if parameter_index >= len(parameters):
            raise ProtocolError("Too few query parameters")
        replacement = sql_literal(parameters[parameter_index])
        result = result[:marker] + replacement + result[marker + 1:]
        position = marker + len(replacement)
        parameter_index += 1
    import re

    def replace_named(match):
        index = int(match.group(1))
        if index < 1 or index > len(parameters):
            raise ProtocolError("Parameter index out of range")
        return sql_literal(parameters[index - 1])

    result = re.sub(r"\$([1-9][0-9]*)", replace_named, result)
    return result
