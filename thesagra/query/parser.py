import re
from dataclasses import dataclass
from typing import Any, List, Optional


class ParseError(Exception):
    pass


@dataclass
class ColumnDefinition:
    name: str
    type_name: str
    nullable: bool
    primary_key: bool
    unique: bool = False
    auto_increment: bool = False
    default_value: Any = None
    default_current_timestamp: bool = False
    type_length: Optional[int] = None


@dataclass
class CreateTable:
    name: str
    columns: List[ColumnDefinition]
    foreign_keys: Optional[List[Any]] = None


@dataclass
class ForeignKeyDefinition:
    columns: List[str]
    referenced_table: str
    referenced_columns: List[str]


@dataclass
class CreateIndex:
    name: str
    table: str
    columns: List[str]
    unique: bool = False


@dataclass
class DropTable:
    name: str
    if_exists: bool = False
    cascade: bool = False


@dataclass
class AlterTable:
    table: str
    action: str
    definition: Optional[ColumnDefinition] = None
    old_name: Optional[str] = None
    new_name: Optional[str] = None
    if_exists: bool = False
    cascade: bool = False


@dataclass
class Insert:
    table: str
    columns: Optional[List[str]]
    values: List[Any]
    rows: Optional[List[List[Any]]] = None


@dataclass
class Where:
    column: str
    operator: str
    value: Any
    qualifier: Optional[str] = None
    conditions: Optional[List[Any]] = None


@dataclass
class Having:
    aggregate: str
    column: str
    operator: str
    value: Any


@dataclass
class Join:
    table: str
    left_column: Optional[str]
    right_column: Optional[str]
    alias: Optional[str] = None
    join_type: str = "INNER"


@dataclass
class SelectedColumn:
    name: Optional[str] = None
    aggregate: Optional[str] = None
    alias: Optional[str] = None


@dataclass
class Explain:
    statement: Any


@dataclass
class Select:
    columns: Optional[List[Any]]
    table: str
    where: Optional[Where] = None
    order_by: Optional[str] = None
    descending: bool = False
    limit: Optional[int] = None
    join: Optional[Join] = None
    group_by: Optional[str] = None
    table_alias: Optional[str] = None
    additional_joins: Optional[List[Join]] = None
    distinct: bool = False
    having: Optional[Having] = None


@dataclass
class Assignment:
    column: str
    value: Any


@dataclass
class ArithmeticExpression:
    column: str
    operator: str
    value: Any


@dataclass
class Update:
    table: str
    assignments: List[Assignment]
    where: Optional[Where] = None


@dataclass
class Delete:
    table: str
    where: Optional[Where] = None


@dataclass
class Begin:
    pass


@dataclass
class Commit:
    pass


@dataclass
class Rollback:
    pass


@dataclass
class GraphMatch:
    left_label: str
    relationship_type: str
    right_label: str


TOKEN = re.compile(
    r"""
    (?P<SPACE>\s+)
  | (?P<NUMBER>-?(?:\d+\.\d+|\d+))
  | (?P<STRING>'(?:''|[^'])*')
  | (?P<BLOB>X'[0-9A-Fa-f]*')
  | (?P<OP><=|>=|!=|=|<|>)
  | (?P<DOT>\.)
  | (?P<PUNCT>[(),;*+\[\]:/-])
  | (?P<IDENT>[A-Za-z_][A-Za-z_0-9]*)
  """,
    re.X,
)


class Lexer:
    def __init__(self, sql: str):
        self.sql = sql
        self.position = 0

    def tokens(self):
        result = []
        while self.position < len(self.sql):
            match = TOKEN.match(self.sql, self.position)
            if not match:
                raise ParseError(
                    f"Unexpected character at position {self.position}"
                )
            kind = match.lastgroup
            text = match.group(0)
            self.position = match.end()
            if kind == "SPACE":
                continue
            if kind == "STRING":
                result.append(("STRING", text[1:-1].replace("''", "'")))
            elif kind == "BLOB":
                result.append(("BLOB", bytes.fromhex(text[2:-1])))
            elif kind == "NUMBER":
                result.append(
                    (
                        "NUMBER",
                        float(text) if "." in text else int(text),
                    )
                )
            else:
                result.append((kind, text))
        result.append(("EOF", ""))
        return result


class Parser:
    def __init__(self, sql: str):
        self.tokens = Lexer(sql).tokens()
        self.position = 0

    def peek(self, value=None):
        kind, text = self.tokens[self.position]
        if value is None:
            return text
        if value.upper() == "EOF":
            return kind == "EOF"
        return str(text).upper() == value.upper()

    def accept(self, value):
        if self.peek(value):
            self.position += 1
            return True
        return False

    def expect(self, value):
        if not self.accept(value):
            raise ParseError(f"Expected '{value}'")

    def expect_keyword(self):
        kind, text = self.tokens[self.position]
        if kind != "IDENT":
            raise ParseError("Expected keyword")
        self.position += 1
        return text

    def identifier(self):
        kind, text = self.tokens[self.position]
        if kind != "IDENT":
            raise ParseError("Expected identifier")
        self.position += 1
        return text

    def qualified_name(self):
        first = self.identifier()
        if self.accept("."):
            return first, self.identifier()
        return None, first

    def parse(self):
        if self.accept("EXPLAIN"):
            statement = self.parse_statement()
            if not self.accept(";"):
                self.expect("EOF")
            return Explain(statement)
        statement = self.parse_statement()
        if not self.accept(";"):
            self.expect("EOF")
        return statement

    def parse_statement(self):
        if self.accept("MATCH"):
            statement = self.graph_match()
        elif self.accept("CREATE"):
            if self.accept("UNIQUE"):
                self.expect("INDEX")
                statement = self.create_index(unique=True)
            elif self.accept("INDEX"):
                statement = self.create_index()
            else:
                statement = self.create_table()
        elif self.accept("DROP"):
            statement = self.drop_table()
        elif self.accept("ALTER"):
            statement = self.alter_table()
        elif self.accept("INSERT"):
            statement = self.insert()
        elif self.accept("SELECT"):
            statement = self.select()
        elif self.accept("UPDATE"):
            statement = self.update()
        elif self.accept("DELETE"):
            statement = self.delete()
        elif self.accept("BEGIN"):
            statement = Begin()
        elif self.accept("START"):
            self.expect("TRANSACTION")
            statement = Begin()
        elif self.accept("COMMIT"):
            statement = Commit()
        elif self.accept("ROLLBACK"):
            statement = Rollback()
        else:
            raise ParseError("Unsupported statement")
        return statement

    def drop_table(self):
        self.expect("TABLE")
        if_exists = False
        if self.accept("IF"):
            self.expect("EXISTS")
            if_exists = True
        name = self.identifier()
        cascade = self.accept("CASCADE")
        if not cascade:
            self.accept("RESTRICT")
        return DropTable(name, if_exists, cascade)

    def alter_table(self):
        self.expect("TABLE")
        table = self.identifier()
        if self.accept("ADD"):
            self.accept("COLUMN")
            if_not_exists = False
            if self.accept("IF"):
                self.expect("NOT")
                self.expect("EXISTS")
                if_not_exists = True
            return AlterTable(
                table,
                "add_column",
                definition=self.column_definition(),
                if_exists=if_not_exists,
            )
        if self.accept("DROP"):
            self.accept("COLUMN")
            if_exists = False
            if self.accept("IF"):
                self.expect("EXISTS")
                if_exists = True
            column = self.identifier()
            cascade = self.accept("CASCADE")
            if not cascade:
                self.accept("RESTRICT")
            return AlterTable(
                table,
                "drop_column",
                old_name=column,
                if_exists=if_exists,
                cascade=cascade,
            )
        if self.accept("RENAME"):
            if self.accept("COLUMN") or not self.peek("TO"):
                old_name = self.identifier()
                self.expect("TO")
                new_name = self.identifier()
                return AlterTable(
                    table,
                    "rename_column",
                    old_name=old_name,
                    new_name=new_name,
                )
            self.expect("TO")
            return AlterTable(
                table,
                "rename_table",
                new_name=self.identifier(),
            )
        raise ParseError(
            "ALTER TABLE supports ADD COLUMN, DROP COLUMN, and RENAME"
        )

    def graph_match(self):
        self.expect("(")
        left_label = self.identifier()
        if self.accept(":"):
            left_label = self.identifier()
        else:
            left_label = None
        self.expect(")")
        relationship_type = None
        if self.accept("-"):
            self.expect("[")
            self.expect(":")
            relationship_type = self.identifier()
            self.expect("]")
            self.expect("-")
            self.expect(">")
        else:
            raise ParseError("MATCH requires a directed relationship")
        self.expect("(")
        right_label = self.identifier()
        if self.accept(":"):
            right_label = self.identifier()
        else:
            right_label = None
        self.expect(")")
        if not isinstance(left_label, str) or not isinstance(right_label, str):
            if left_label is not None and right_label is not None:
                pass
        if left_label is None:
            left_label = "*"
        if right_label is None:
            right_label = "*"
        return GraphMatch(left_label, relationship_type, right_label)

    def create_table(self):
        self.expect("TABLE")
        name = self.identifier()
        self.expect("(")
        columns = []
        primary_key_columns = []
        foreign_keys = []
        while True:
            if self.accept("CONSTRAINT"):
                self.identifier()
            if self.accept("PRIMARY"):
                self.expect("KEY")
                primary_key_columns.extend(self.identifier_list())
            elif self.accept("FOREIGN"):
                self.expect("KEY")
                foreign_columns = self.identifier_list()
                self.expect("REFERENCES")
                referenced_table = self.identifier()
                referenced_columns = self.identifier_list()
                foreign_keys.append(
                    ForeignKeyDefinition(
                        foreign_columns,
                        referenced_table,
                        referenced_columns,
                    )
                )
            else:
                columns.append(self.column_definition())
            if not self.accept(","):
                break
        self.expect(")")
        column_map = {column.name.lower(): column for column in columns}
        for column_name in primary_key_columns:
            column = column_map.get(column_name.lower())
            if column is None:
                raise ParseError(
                    f"Unknown primary key column '{column_name}'"
                )
            column.primary_key = True
            column.nullable = False
        return CreateTable(name, columns, foreign_keys)

    def column_definition(self):
        column_name = self.identifier()
        type_name = self.identifier().upper()
        type_length = None
        type_scale = None
        if self.accept("("):
            kind, length = self.tokens[self.position]
            if kind != "NUMBER" or not isinstance(length, int) or length < 1:
                raise ParseError("Type length must be a positive integer")
            self.position += 1
            type_length = length
            if self.accept(","):
                kind, scale = self.tokens[self.position]
                if (
                    kind != "NUMBER"
                    or not isinstance(scale, int)
                    or scale < 0
                ):
                    raise ParseError(
                        "Type scale must be a non-negative integer"
                    )
                self.position += 1
                type_scale = scale
            self.expect(")")
        nullable = True
        primary_key = False
        unique = False
        auto_increment = False
        default_value = None
        default_current_timestamp = False
        while (
            not self.peek(",")
            and not self.peek(")")
            and not self.peek(";")
            and not self.peek("EOF")
        ):
            if self.accept("PRIMARY"):
                self.expect("KEY")
                primary_key = True
                nullable = False
            elif self.accept("NOT"):
                self.expect("NULL")
                nullable = False
            elif self.accept("NULL"):
                nullable = True
            elif self.accept("UNIQUE"):
                unique = True
            elif self.accept("AUTO_INCREMENT") or self.accept("AUTOINCREMENT"):
                auto_increment = True
            elif self.accept("DEFAULT"):
                if self.accept("CURRENT_TIMESTAMP"):
                    default_current_timestamp = True
                else:
                    default_value = self.literal()
            else:
                raise ParseError(
                    f"Unsupported column constraint '{self.peek()}'"
                )
        return ColumnDefinition(
            name=column_name,
            type_name=type_name,
            nullable=nullable,
            primary_key=primary_key,
            unique=unique,
            auto_increment=auto_increment,
            default_value=default_value,
            default_current_timestamp=default_current_timestamp,
            type_length=type_length,
        )

    def create_index(self, unique=False):
        name = self.identifier()
        self.expect("ON")
        table = self.identifier()
        columns = self.identifier_list()
        return CreateIndex(name, table, columns, unique)

    def identifier_list(self):
        self.expect("(")
        names = [self.identifier()]
        while self.accept(","):
            names.append(self.identifier())
        self.expect(")")
        return names

    def insert(self):
        self.expect("INTO")
        table = self.identifier()
        columns = None
        if self.accept("("):
            columns = []
            while True:
                columns.append(self.identifier())
                if not self.accept(","):
                    break
            self.expect(")")
        self.expect("VALUES")
        rows = [self.value_list()]
        while self.accept(","):
            rows.append(self.value_list())
        return Insert(table, columns, rows[0], rows)

    def value_list(self):
        self.expect("(")
        values = []
        while True:
            values.append(self.literal())
            if not self.accept(","):
                break
        self.expect(")")
        return values

    def literal(self):
        kind, text = self.tokens[self.position]
        if kind in ("NUMBER", "STRING", "BLOB"):
            self.position += 1
            return text
        if kind == "IDENT" and text.upper() in ("NULL", "TRUE", "FALSE"):
            self.position += 1
            if text.upper() == "NULL":
                return None
            return text.upper() == "TRUE"
        raise ParseError("Expected literal value")

    def select(self):
        distinct = self.accept("DISTINCT")
        if self.accept("*"):
            columns = None
        else:
            columns = [self.selected_column()]
            while self.accept(","):
                columns.append(self.selected_column())
        self.expect("FROM")
        table = self.identifier()
        table_alias = self.optional_alias(
            {
                "INNER", "LEFT", "RIGHT", "FULL", "CROSS", "OUTER",
                "JOIN", "WHERE", "GROUP", "ORDER", "LIMIT",
            }
        )
        joins = []
        while True:
            join_type = None
            if self.accept("INNER"):
                self.expect("JOIN")
                join_type = "INNER"
            elif self.accept("LEFT"):
                self.accept("OUTER")
                self.expect("JOIN")
                join_type = "LEFT"
            elif self.accept("RIGHT"):
                self.accept("OUTER")
                self.expect("JOIN")
                join_type = "RIGHT"
            elif self.accept("FULL"):
                self.accept("OUTER")
                self.expect("JOIN")
                join_type = "FULL"
            elif self.accept("CROSS"):
                self.expect("JOIN")
                join_type = "CROSS"
            elif self.accept("JOIN"):
                join_type = "INNER"
            if join_type is None:
                break
            join_table = self.identifier()
            join_alias = self.optional_alias(
                {
                    "ON", "INNER", "LEFT", "RIGHT", "FULL", "CROSS",
                    "JOIN", "WHERE", "GROUP", "ORDER", "LIMIT", "HAVING",
                }
            )
            if join_type == "CROSS":
                joins.append(
                    Join(join_table, None, None, join_alias, join_type)
                )
            else:
                self.expect("ON")
                left_qualifier, left_column = self.qualified_name()
                self.expect("=")
                right_qualifier, right_column = self.qualified_name()
                joins.append(
                    Join(
                        join_table,
                        f"{left_qualifier}.{left_column}"
                        if left_qualifier else left_column,
                        f"{right_qualifier}.{right_column}"
                        if right_qualifier else right_column,
                        join_alias,
                        join_type,
                    )
                )
        where = self.where_clause()
        group_by = None
        if self.accept("GROUP"):
            self.expect("BY")
            qualifier, group_by = self.qualified_name()
            if qualifier:
                group_by = f"{qualifier}.{group_by}"
        having = None
        if self.accept("HAVING"):
            aggregate = self.selected_column()
            if aggregate.aggregate is None:
                raise ParseError("HAVING requires an aggregate expression")
            kind, operator = self.tokens[self.position]
            if kind != "OP":
                raise ParseError("Expected comparison operator in HAVING")
            self.position += 1
            having = Having(
                aggregate.aggregate,
                aggregate.name,
                operator,
                self.value_expression(),
            )
        order_by = None
        descending = False
        if self.accept("ORDER"):
            self.expect("BY")
            qualifier, order_by = self.qualified_name()
            if qualifier:
                order_by = f"{qualifier}.{order_by}"
            if self.accept("DESC"):
                descending = True
            else:
                self.accept("ASC")
        limit = None
        if self.accept("LIMIT"):
            kind, text = self.tokens[self.position]
            if kind != "NUMBER" or not isinstance(text, int) or text < 0:
                raise ParseError("LIMIT requires a non-negative integer")
            self.position += 1
            limit = text
        return Select(
            columns,
            table,
            where,
            order_by,
            descending,
            limit,
            joins[0] if joins else None,
            group_by,
            table_alias,
            joins[1:] if len(joins) > 1 else [],
            distinct,
            having,
        )

    def optional_alias(self, reserved):
        if self.accept("AS"):
            return self.identifier()
        kind, text = self.tokens[self.position]
        if kind == "IDENT" and text.upper() not in reserved:
            self.position += 1
            return text
        return None

    def selected_column(self):
        kind, text = self.tokens[self.position]
        if kind == "IDENT" and text.upper() in ("COUNT", "SUM", "AVG", "MIN", "MAX"):
            aggregate = text.upper()
            self.position += 1
            self.expect("(")
            if self.accept("*"):
                name = "*"
            else:
                qualifier, name = self.qualified_name()
                if qualifier:
                    name = f"{qualifier}.{name}"
            self.expect(")")
            alias = self.column_alias()
            return SelectedColumn(name=name, aggregate=aggregate, alias=alias)
        qualifier, name = self.qualified_name()
        if qualifier:
            name = f"{qualifier}.{name}"
        return SelectedColumn(name=name, alias=self.column_alias())

    def column_alias(self):
        if self.accept("AS"):
            return self.identifier()
        return None

    def where_clause(self):
        if not self.accept("WHERE"):
            return None
        conditions = [self.where_condition()]
        while self.accept("AND"):
            conditions.append(self.where_condition())
        if len(conditions) == 1:
            return conditions[0]
        return Where("", "", None, conditions=conditions)

    def where_condition(self):
        qualifier, column = self.qualified_name()
        if self.accept("IS"):
            if self.accept("NOT"):
                self.expect("NULL")
                operator = "IS NOT NULL"
            else:
                self.expect("NULL")
                operator = "IS NULL"
            return Where(column, operator, None, qualifier)
        if self.accept("BETWEEN"):
            lower = self.value_expression()
            self.expect("AND")
            upper = self.value_expression()
            return Where(column, "BETWEEN", (lower, upper), qualifier)
        if self.accept("LIKE"):
            return Where(
                column,
                "LIKE",
                self.value_expression(),
                qualifier,
            )
        if self.accept("IN"):
            self.expect("(")
            if self.accept("SELECT"):
                value = self.select()
                self.expect(")")
            else:
                values = [self.literal()]
                while self.accept(","):
                    values.append(self.literal())
                self.expect(")")
                value = values
            return Where(column, "IN", value, qualifier)
        kind, operator = self.tokens[self.position]
        if kind != "OP":
            raise ParseError("Expected comparison operator")
        self.position += 1
        return Where(
            column,
            operator,
            self.value_expression(),
            qualifier,
        )

    def value_expression(self):
        if self.accept("("):
            if self.accept("SELECT"):
                value = self.select()
                self.expect(")")
                return value
            raise ParseError("Expected SELECT after '('")
        return self.literal()

    def update(self):
        table = self.identifier()
        self.expect("SET")
        assignments = []
        while True:
            column = self.identifier()
            self.expect("=")
            assignments.append(
                Assignment(column, self.assignment_value())
            )
            if not self.accept(","):
                break
        return Update(table, assignments, self.where_clause())

    def assignment_value(self):
        kind, text = self.tokens[self.position]
        if kind == "IDENT" and text.upper() not in ("NULL", "TRUE", "FALSE"):
            column = self.identifier()
            kind, operator = self.tokens[self.position]
            if kind == "PUNCT" and operator in ("+", "-", "*", "/"):
                self.position += 1
                return ArithmeticExpression(
                    column,
                    operator,
                    self.literal(),
                )
            self.position -= 1
        return self.literal()

    def delete(self):
        self.expect("FROM")
        table = self.identifier()
        return Delete(table, self.where_clause())


def parse(sql: str):
    return Parser(sql).parse()


def split_sql_statements(script: str):
    statements = []
    current = []
    position = 0
    in_string = False
    in_line_comment = False
    in_block_comment = False

    while position < len(script):
        character = script[position]
        following = (
            script[position + 1]
            if position + 1 < len(script)
            else ""
        )

        if in_line_comment:
            if character in "\r\n":
                in_line_comment = False
                current.append(" ")
            position += 1
            continue
        if in_block_comment:
            if character == "*" and following == "/":
                in_block_comment = False
                current.append(" ")
                position += 2
            else:
                position += 1
            continue
        if in_string:
            current.append(character)
            if character == "'" and following == "'":
                current.append(following)
                position += 2
                continue
            if character == "'":
                in_string = False
            position += 1
            continue
        if character == "-" and following == "-":
            in_line_comment = True
            position += 2
            continue
        if character == "/" and following == "*":
            in_block_comment = True
            position += 2
            continue
        if character == "'":
            in_string = True
            current.append(character)
        elif character == ";":
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
        else:
            current.append(character)
        position += 1

    statement = "".join(current).strip()
    if statement:
        statements.append(statement)
    if in_string:
        raise ParseError("Unterminated string literal")
    if in_block_comment:
        raise ParseError("Unterminated block comment")
    return statements
