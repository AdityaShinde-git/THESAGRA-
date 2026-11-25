from copy import deepcopy
from dataclasses import dataclass, field, replace
import base64
import json
import zlib
from typing import Any, Dict, List, Optional

from ..storage.database import DatabaseFile
from ..storage.page import PageError


@dataclass(frozen=True)
class Column:
    name: str
    type_name: str
    nullable: bool = True
    primary_key: bool = False
    unique: bool = False
    auto_increment: bool = False
    default_value: Any = None
    default_current_timestamp: bool = False
    max_length: Optional[int] = None


@dataclass(frozen=True)
class ForeignKey:
    columns: tuple
    referenced_table: str
    referenced_columns: tuple


@dataclass(frozen=True)
class Index:
    name: str
    columns: tuple
    unique: bool = False


@dataclass
class Table:
    name: str
    columns: List[Column]
    page_id: int
    foreign_keys: List[ForeignKey] = field(default_factory=list)
    indexes: List[Index] = field(default_factory=list)

    def column(self, name: str):
        for column in self.columns:
            if column.name.lower() == name.lower():
                return column
        return None


class CatalogError(Exception):
    pass


class Catalog:
    def __init__(self, database: DatabaseFile):
        self.database = database
        self.tables: Dict[str, Table] = {}
        self.load()

    def load(self):
        rows = self.database.read_records(1)
        if rows and rows[0][0] == "schema":
            if len(rows) != 1 or len(rows[0]) != 2:
                raise PageError("Invalid compact catalog schema")
            try:
                payload = json.loads(zlib.decompress(rows[0][1]))
                tables = {}
                for table_data in payload:
                    columns = []
                    for column_data in table_data["columns"]:
                        default = column_data["default"]
                        default_value = (
                            base64.b64decode(default["value"])
                            if default["kind"] == "bytes"
                            else default["value"]
                        )
                        columns.append(
                            Column(
                                column_data["name"],
                                column_data["type_name"],
                                column_data["nullable"],
                                column_data["primary_key"],
                                column_data["unique"],
                                column_data["auto_increment"],
                                default_value,
                                column_data["default_current_timestamp"],
                                column_data["max_length"],
                            )
                        )
                    table = Table(
                        table_data["name"],
                        columns,
                        table_data["page_id"],
                        [
                            ForeignKey(
                                tuple(item["columns"]),
                                item["referenced_table"],
                                tuple(item["referenced_columns"]),
                            )
                            for item in table_data["foreign_keys"]
                        ],
                        [
                            Index(
                                item["name"],
                                tuple(item["columns"]),
                                item["unique"],
                            )
                            for item in table_data["indexes"]
                        ],
                    )
                    tables[table.name.lower()] = table
                self.tables = tables
            except (
                KeyError,
                TypeError,
                ValueError,
                zlib.error,
                json.JSONDecodeError,
            ) as exc:
                raise PageError("Invalid compact catalog schema") from exc
            return
        tables = {}
        for row in rows:
            if not row:
                continue
            if row[0] == "table":
                if len(row) != 3:
                    raise PageError("Invalid catalog table row")
                tables[str(row[1]).lower()] = Table(str(row[1]), [], int(row[2]))
            elif row[0] == "column":
                if len(row) not in (6, 10, 11):
                    raise PageError("Invalid catalog column row")
                _, table_name, name, type_name, nullable, primary_key = row[:6]
                if len(row) >= 10:
                    (
                        unique,
                        auto_increment,
                        default_value,
                        default_current_timestamp,
                    ) = row[6:10]
                else:
                    unique = False
                    auto_increment = False
                    default_value = None
                    default_current_timestamp = False
                max_length = row[10] if len(row) == 11 else None
                table = tables.get(str(table_name).lower())
                if table is None:
                    raise PageError("Catalog column has no table")
                table.columns.append(
                    Column(
                        str(name),
                        str(type_name),
                        bool(nullable),
                        bool(primary_key),
                        bool(unique),
                        bool(auto_increment),
                        default_value,
                        bool(default_current_timestamp),
                        max_length,
                    )
                )
            elif row[0] == "foreign_key":
                if len(row) != 5:
                    raise PageError("Invalid catalog foreign key row")
                table = tables.get(str(row[1]).lower())
                if table is None:
                    raise PageError("Catalog foreign key has no table")
                table.foreign_keys.append(
                    ForeignKey(
                        tuple(json.loads(row[2])),
                        str(row[3]),
                        tuple(json.loads(row[4])),
                    )
                )
            elif row[0] == "index":
                if len(row) != 5:
                    raise PageError("Invalid catalog index row")
                table = tables.get(str(row[1]).lower())
                if table is None:
                    raise PageError("Catalog index has no table")
                table.indexes.append(
                    Index(
                        str(row[2]),
                        tuple(json.loads(row[3])),
                        bool(row[4]),
                    )
                )
            else:
                raise PageError("Unknown catalog record")
        self.tables = tables

    def save(self, write_records=None):
        schema = []
        for table_name in sorted(self.tables):
            table = self.tables[table_name]
            columns = []
            for column in table.columns:
                default = (
                    {
                        "kind": "bytes",
                        "value": base64.b64encode(
                            column.default_value
                        ).decode("ascii"),
                    }
                    if isinstance(column.default_value, bytes)
                    else {
                        "kind": "value",
                        "value": column.default_value,
                    }
                )
                columns.append(
                    {
                        "name": column.name,
                        "type_name": column.type_name,
                        "nullable": column.nullable,
                        "primary_key": column.primary_key,
                        "unique": column.unique,
                        "auto_increment": column.auto_increment,
                        "default": default,
                        "default_current_timestamp":
                            column.default_current_timestamp,
                        "max_length": column.max_length,
                    }
                )
            schema.append(
                {
                    "name": table.name,
                    "page_id": table.page_id,
                    "columns": columns,
                    "foreign_keys": [
                        {
                            "columns": foreign_key.columns,
                            "referenced_table":
                                foreign_key.referenced_table,
                            "referenced_columns":
                                foreign_key.referenced_columns,
                        }
                        for foreign_key in table.foreign_keys
                    ],
                    "indexes": [
                        {
                            "name": index.name,
                            "columns": index.columns,
                            "unique": index.unique,
                        }
                        for index in table.indexes
                    ],
                }
            )
        payload = json.dumps(
            schema,
            separators=(",", ":"),
        ).encode("utf-8")
        writer = write_records or self.database.write_records
        writer(1, [("schema", zlib.compress(payload))])

    def create_table(
        self,
        name: str,
        columns: List[Column],
        foreign_keys=None,
    ) -> Table:
        key = name.lower()
        if key in self.tables:
            raise CatalogError(f"Table '{name}' already exists")
        if not columns:
            raise CatalogError("A table must have at least one column")

        names = set()
        for column in columns:
            lower_name = column.name.lower()
            if lower_name in names:
                raise CatalogError(f"Duplicate column '{column.name}'")
            names.add(lower_name)

        foreign_keys = list(foreign_keys or [])
        for foreign_key in foreign_keys:
            local = [
                next(
                    (
                        column for column in columns
                        if column.name.lower() == local_name.lower()
                    ),
                    None,
                )
                for local_name in foreign_key.columns
            ]
            if any(column is None for column in local):
                raise CatalogError("Foreign key refers to an unknown column")
            if len(foreign_key.columns) != len(
                foreign_key.referenced_columns
            ):
                raise CatalogError(
                    "Foreign key column counts do not match"
                )
            target = (
                Table(name, columns, 0)
                if foreign_key.referenced_table.lower() == key
                else self.tables.get(foreign_key.referenced_table.lower())
            )
            if target is None:
                raise CatalogError(
                    f"Referenced table '{foreign_key.referenced_table}' "
                    "does not exist"
                )
            target_columns = [
                target.column(column_name)
                for column_name in foreign_key.referenced_columns
            ]
            if any(column is None for column in target_columns):
                raise CatalogError(
                    "Foreign key refers to an unknown referenced column"
                )
            if len(target_columns) == 1:
                if not (
                    target_columns[0].primary_key
                    or target_columns[0].unique
                ):
                    raise CatalogError(
                        "Foreign keys must reference a primary or unique key"
                    )
            elif not all(column.primary_key for column in target_columns):
                raise CatalogError(
                    "Composite foreign keys must reference a primary key"
                )
        page_id = self.database.allocate_page()
        table = Table(name, columns, page_id)
        table.foreign_keys = foreign_keys
        self.tables[key] = table
        self.database.write_records(page_id, [])
        self.save()
        return table

    def create_index(self, name: str, table_name: str, columns, unique=False):
        if any(
            index.name.lower() == name.lower()
            for table in self.tables.values()
            for index in table.indexes
        ):
            raise CatalogError(f"Index '{name}' already exists")
        table = self.get_table(table_name)
        if not columns:
            raise CatalogError("An index must include at least one column")
        if any(table.column(column) is None for column in columns):
            raise CatalogError("Index refers to an unknown column")
        table.indexes.append(Index(name, tuple(columns), bool(unique)))
        self.save()
        return table.indexes[-1]

    def drop_table(self, name: str, cascade=False, if_exists=False):
        key = name.lower()
        table = self.tables.get(key)
        if table is None:
            if if_exists:
                return None
            raise CatalogError(f"Unknown table '{name}'")

        dependent_tables = sorted(
            {
                child.name
                for child in self.tables.values()
                if child.name.lower() != key
                and any(
                    foreign_key.referenced_table.lower() == key
                    for foreign_key in child.foreign_keys
                )
            },
            key=str.lower,
        )
        if dependent_tables and not cascade:
            names = ", ".join(dependent_tables)
            raise CatalogError(
                f"Cannot drop table '{table.name}': referenced by "
                f"foreign key(s) in {names}; use CASCADE to remove "
                "those constraints"
            )

        dependent_foreign_keys = {
            child.name.lower(): list(child.foreign_keys)
            for child in self.tables.values()
            if child.name.lower() != key
            and any(
                foreign_key.referenced_table.lower() == key
                for foreign_key in child.foreign_keys
            )
        }
        for child_key in dependent_foreign_keys:
            child = self.tables[child_key]
            child.foreign_keys = [
                foreign_key
                for foreign_key in child.foreign_keys
                if foreign_key.referenced_table.lower() != key
            ]
        del self.tables[key]
        try:
            self.save()
        except Exception:
            self.tables[key] = table
            for child_key, foreign_keys in dependent_foreign_keys.items():
                self.tables[child_key].foreign_keys = foreign_keys
            raise
        return table

    def add_column(self, table_name, column, write_records=None):
        table = self.get_table(table_name)
        if table.column(column.name) is not None:
            raise CatalogError(f"Column '{column.name}' already exists")
        table.columns.append(column)
        try:
            self.save(write_records)
        except Exception:
            table.columns.pop()
            raise

    def drop_column(
        self,
        table_name,
        column_name,
        cascade=False,
        if_exists=False,
        write_records=None,
    ):
        table = self.get_table(table_name)
        column = table.column(column_name)
        if column is None:
            if if_exists:
                return None
            raise CatalogError(
                f"Unknown column '{column_name}' in table '{table.name}'"
            )
        if len(table.columns) == 1:
            raise CatalogError("A table must have at least one column")

        key = table.name.lower()
        dependent = False
        for candidate in self.tables.values():
            if any(
                (
                    candidate.name.lower() == key
                    and any(name.lower() == column.name.lower()
                            for name in foreign_key.columns)
                )
                or (
                    foreign_key.referenced_table.lower() == key
                    and any(name.lower() == column.name.lower()
                            for name in foreign_key.referenced_columns)
                )
                for foreign_key in candidate.foreign_keys
            ):
                dependent = True
                break
        if any(
            any(name.lower() == column.name.lower() for name in index.columns)
            for index in table.indexes
        ):
            dependent = True
        if (dependent or column.primary_key or column.unique) and not cascade:
            raise CatalogError(
                f"Cannot drop column '{column.name}' because it is used by "
                "a key or index; use CASCADE to remove dependent objects"
            )

        snapshot = deepcopy(self.tables)
        column_index = table.columns.index(column)
        table.columns.pop(column_index)
        if cascade:
            if column.primary_key:
                table.columns = [
                    replace(item, primary_key=False)
                    for item in table.columns
                ]
            for candidate in self.tables.values():
                candidate.foreign_keys = [
                    foreign_key
                    for foreign_key in candidate.foreign_keys
                    if not (
                        (
                            candidate.name.lower() == key
                            and any(
                                name.lower() == column.name.lower()
                                for name in foreign_key.columns
                            )
                        )
                        or (
                            foreign_key.referenced_table.lower() == key
                            and any(
                                name.lower() == column.name.lower()
                                for name in foreign_key.referenced_columns
                            )
                        )
                    )
                ]
            table.indexes = [
                index
                for index in table.indexes
                if not any(
                    name.lower() == column.name.lower()
                    for name in index.columns
                )
            ]
        try:
            self.save(write_records)
        except Exception:
            self.tables = snapshot
            raise
        return column_index

    def rename_column(
        self,
        table_name,
        old_name,
        new_name,
        write_records=None,
    ):
        table = self.get_table(table_name)
        column = table.column(old_name)
        if column is None:
            raise CatalogError(
                f"Unknown column '{old_name}' in table '{table.name}'"
            )
        if table.column(new_name) is not None:
            raise CatalogError(f"Column '{new_name}' already exists")
        snapshot = deepcopy(self.tables)
        key = table.name.lower()
        table.columns = [
            replace(item, name=new_name)
            if item.name.lower() == column.name.lower()
            else item
            for item in table.columns
        ]
        for candidate in self.tables.values():
            candidate.foreign_keys = [
                ForeignKey(
                    tuple(
                        new_name
                        if candidate.name.lower() == key
                        and name.lower() == column.name.lower()
                        else name
                        for name in foreign_key.columns
                    ),
                    foreign_key.referenced_table,
                    tuple(
                        new_name
                        if foreign_key.referenced_table.lower() == key
                        and name.lower() == column.name.lower()
                        else name
                        for name in foreign_key.referenced_columns
                    ),
                )
                for foreign_key in candidate.foreign_keys
            ]
        table.indexes = [
            Index(
                index.name,
                tuple(
                    new_name
                    if name.lower() == column.name.lower()
                    else name
                    for name in index.columns
                ),
                index.unique,
            )
            for index in table.indexes
        ]
        try:
            self.save(write_records)
        except Exception:
            self.tables = snapshot
            raise

    def rename_table(self, old_name, new_name, write_records=None):
        table = self.get_table(old_name)
        if new_name.lower() in self.tables:
            raise CatalogError(f"Table '{new_name}' already exists")
        snapshot = deepcopy(self.tables)
        old_key = table.name.lower()
        del self.tables[old_key]
        table.name = new_name
        self.tables[new_name.lower()] = table
        for candidate in self.tables.values():
            candidate.foreign_keys = [
                ForeignKey(
                    foreign_key.columns,
                    new_name
                    if foreign_key.referenced_table.lower() == old_key
                    else foreign_key.referenced_table,
                    foreign_key.referenced_columns,
                )
                for foreign_key in candidate.foreign_keys
            ]
        try:
            self.save(write_records)
        except Exception:
            self.tables = snapshot
            raise

    def get_table(self, name: str):
        table = self.tables.get(name.lower())
        if table is None:
            raise CatalogError(f"Unknown table '{name}'")
        return table
