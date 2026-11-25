import math
from typing import Any

from ..catalog.catalog import Column


SUPPORTED_TYPES = {"INTEGER", "TEXT", "REAL", "BOOLEAN", "BLOB"}


class TypeErrorValue(Exception):
    pass


def normalize_type(type_name: str) -> str:
    normalized = type_name.upper()
    if normalized in ("INT", "SMALLINT", "BIGINT"):
        normalized = "INTEGER"
    elif normalized in (
        "VARCHAR", "CHAR", "CHARACTER", "TIMESTAMP", "DATE",
        "DECIMAL", "NUMERIC",
    ):
        normalized = (
            "REAL"
            if normalized in ("DECIMAL", "NUMERIC")
            else "TEXT"
        )
    if normalized not in SUPPORTED_TYPES:
        raise TypeErrorValue(f"Unsupported type '{type_name}'")
    return normalized


def coerce_value(value: Any, column: Column):
    type_name = column.type_name
    if value is None:
        if not column.nullable:
            raise TypeErrorValue(
                f"Column '{column.name}' does not allow NULL"
            )
        return None

    if type_name == "INTEGER":
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeErrorValue(
                f"Column '{column.name}' requires INTEGER"
            )
        return value
    if type_name == "REAL":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeErrorValue(
                f"Column '{column.name}' requires REAL"
            )
        result = float(value)
        if not math.isfinite(result):
            raise TypeErrorValue(
                f"Column '{column.name}' requires a finite REAL"
            )
        return result
    if type_name == "TEXT":
        if not isinstance(value, str):
            raise TypeErrorValue(
                f"Column '{column.name}' requires TEXT"
            )
        if column.max_length is not None and len(value) > column.max_length:
            raise TypeErrorValue(
                f"Column '{column.name}' exceeds maximum length "
                f"of {column.max_length}"
            )
        return value
    if type_name == "BOOLEAN":
        if not isinstance(value, bool):
            raise TypeErrorValue(
                f"Column '{column.name}' requires BOOLEAN"
            )
        return value
    if type_name == "BLOB":
        if not isinstance(value, bytes):
            raise TypeErrorValue(
                f"Column '{column.name}' requires BLOB"
            )
        return value
    raise TypeErrorValue(f"Unsupported type '{type_name}'")
