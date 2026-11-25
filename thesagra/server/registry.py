import os
import re
import sqlite3
import threading
from contextlib import contextmanager

from ..security import hash_password, verify_password
from ..storage.database import DatabaseFile


DATABASE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,62}$")
PRIVILEGES = {"CONNECT", "READ", "WRITE", "ADMIN"}


class RegistryError(Exception):
    pass


class DatabaseRegistry:
    """System catalog for named databases and database access grants."""

    def __init__(self, data_directory, username, password_hash):
        self.data_directory = os.path.abspath(os.fspath(data_directory))
        self.database_directory = os.path.join(
            self.data_directory,
            "databases",
        )
        self.path = os.path.join(self.data_directory, "system.sqlite3")
        self.lock = threading.RLock()
        os.makedirs(self.database_directory, exist_ok=True)
        self._initialize()
        self._bootstrap_admin(username, password_hash)

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def _session(self):
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self):
        with self.lock:
            with self._session() as connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS users (
                        username TEXT PRIMARY KEY COLLATE NOCASE,
                        password_hash TEXT NOT NULL,
                        is_superuser INTEGER NOT NULL DEFAULT 0
                    );
                    CREATE TABLE IF NOT EXISTS roles (
                        role_name TEXT PRIMARY KEY COLLATE NOCASE
                    );
                    CREATE TABLE IF NOT EXISTS memberships (
                        role_name TEXT NOT NULL COLLATE NOCASE,
                        member_type TEXT NOT NULL
                            CHECK (member_type IN ('USER', 'ROLE')),
                        member_name TEXT NOT NULL COLLATE NOCASE,
                        PRIMARY KEY (role_name, member_type, member_name),
                        FOREIGN KEY (role_name) REFERENCES roles(role_name)
                            ON DELETE CASCADE
                    );
                    CREATE TABLE IF NOT EXISTS databases (
                        name TEXT PRIMARY KEY COLLATE NOCASE,
                        path TEXT NOT NULL UNIQUE
                    );
                    CREATE TABLE IF NOT EXISTS database_grants (
                        role_name TEXT NOT NULL COLLATE NOCASE,
                        database_name TEXT NOT NULL COLLATE NOCASE,
                        privilege TEXT NOT NULL
                            CHECK (privilege IN
                                ('CONNECT', 'READ', 'WRITE', 'ADMIN')),
                        PRIMARY KEY (role_name, database_name, privilege),
                        FOREIGN KEY (role_name) REFERENCES roles(role_name)
                            ON DELETE CASCADE,
                        FOREIGN KEY (database_name) REFERENCES databases(name)
                            ON DELETE CASCADE
                    );
                    """
                )

    def _bootstrap_admin(self, username, password_hash):
        if not username or not password_hash:
            raise RegistryError(
                "Multi-database mode requires an administrator username "
                "and password or password hash"
            )
        with self.lock:
            with self._session() as connection:
                existing = connection.execute(
                    "SELECT username FROM users WHERE is_superuser=1"
                ).fetchone()
                if existing:
                    return
                connection.execute(
                    """
                    INSERT INTO users (username, password_hash, is_superuser)
                    VALUES (?, ?, 1)
                    """,
                    (username, password_hash),
                )

    @staticmethod
    def validate_database_name(name):
        if not isinstance(name, str) or not DATABASE_NAME.fullmatch(name):
            raise RegistryError(
                "Database names must start with a letter and contain only "
                "letters, digits, or underscores (up to 63 characters)"
            )
        return name

    @staticmethod
    def _validate_identity(name, kind):
        if (
            not isinstance(name, str)
            or not name
            or len(name) > 63
            or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name)
        ):
            raise RegistryError(
                f"{kind} names must start with a letter and contain only "
                "letters, digits, or underscores (up to 63 characters)"
            )
        return name

    def database_path(self, name):
        name = self.validate_database_name(name)
        with self.lock:
            with self._session() as connection:
                row = connection.execute(
                    "SELECT path FROM databases WHERE name=?",
                    (name,),
                ).fetchone()
        if row is None:
            raise RegistryError(f"Database '{name}' does not exist")
        return os.path.join(self.database_directory, row["path"])

    def create_database(self, name, owner_role=None):
        name = self.validate_database_name(name)
        if owner_role is not None:
            owner_role = self._validate_identity(owner_role, "Role")
        path = os.path.join(self.database_directory, name + ".db")
        with self.lock:
            if os.path.exists(path):
                raise RegistryError(
                    f"Database file for '{name}' already exists"
                )
            DatabaseFile.create(path)
            try:
                with self._session() as connection:
                    connection.execute(
                        "INSERT INTO databases (name, path) VALUES (?, ?)",
                        (name, name + ".db"),
                    )
                    if owner_role is not None:
                        role = connection.execute(
                            "SELECT role_name FROM roles WHERE role_name=?",
                            (owner_role,),
                        ).fetchone()
                        if role is None:
                            raise RegistryError(
                                f"Role '{owner_role}' does not exist"
                            )
                        connection.execute(
                            """
                            INSERT INTO database_grants
                                (role_name, database_name, privilege)
                            VALUES (?, ?, 'ADMIN')
                            """,
                            (owner_role, name),
                        )
            except Exception:
                if os.path.isfile(path):
                    os.remove(path)
                raise
        return path

    def create_user(self, username, password, is_superuser=False):
        username = self._validate_identity(username, "User")
        encoded = hash_password(password)
        with self.lock:
            try:
                with self._session() as connection:
                    connection.execute(
                        """
                        INSERT INTO users
                            (username, password_hash, is_superuser)
                        VALUES (?, ?, ?)
                        """,
                        (username, encoded, int(bool(is_superuser))),
                    )
            except sqlite3.IntegrityError as exc:
                raise RegistryError(
                    f"User '{username}' already exists"
                ) from exc

    def reset_password(self, username, password):
        username = self._validate_identity(username, "User")
        encoded = hash_password(password)
        with self.lock:
            with self._session() as connection:
                cursor = connection.execute(
                    "UPDATE users SET password_hash=? WHERE username=?",
                    (encoded, username),
                )
                if cursor.rowcount != 1:
                    raise RegistryError(f"User '{username}' does not exist")

    def create_role(self, role_name):
        role_name = self._validate_identity(role_name, "Role")
        with self.lock:
            try:
                with self._session() as connection:
                    connection.execute(
                        "INSERT INTO roles (role_name) VALUES (?)",
                        (role_name,),
                    )
            except sqlite3.IntegrityError as exc:
                raise RegistryError(
                    f"Role '{role_name}' already exists"
                ) from exc

    def grant_role(self, role_name, member_name, member_type="USER"):
        role_name = self._validate_identity(role_name, "Role")
        member_name = self._validate_identity(member_name, "Member")
        member_type = str(member_type).upper()
        if member_type not in ("USER", "ROLE"):
            raise RegistryError("Member type must be USER or ROLE")
        if member_type == "ROLE" and role_name.lower() == member_name.lower():
            raise RegistryError("A role cannot be granted to itself")
        with self.lock:
            with self._session() as connection:
                role = connection.execute(
                    "SELECT role_name FROM roles WHERE role_name=?",
                    (role_name,),
                ).fetchone()
                if role is None:
                    raise RegistryError(f"Role '{role_name}' does not exist")
                table = "users" if member_type == "USER" else "roles"
                key = "username" if member_type == "USER" else "role_name"
                member = connection.execute(
                    f"SELECT {key} FROM {table} WHERE {key}=?",
                    (member_name,),
                ).fetchone()
                if member is None:
                    raise RegistryError(
                        f"{member_type.title()} '{member_name}' does not exist"
                    )
                if member_type == "ROLE" and self._role_inherits(
                    connection,
                    role_name,
                    member_name,
                ):
                    raise RegistryError("Role membership would create a cycle")
                try:
                    connection.execute(
                        """
                        INSERT INTO memberships
                            (role_name, member_type, member_name)
                        VALUES (?, ?, ?)
                        """,
                        (role_name, member_type, member_name),
                    )
                except sqlite3.IntegrityError as exc:
                    raise RegistryError("Role membership already exists") from exc

    def revoke_role(self, role_name, member_name, member_type="USER"):
        role_name = self._validate_identity(role_name, "Role")
        member_name = self._validate_identity(member_name, "Member")
        member_type = str(member_type).upper()
        if member_type not in ("USER", "ROLE"):
            raise RegistryError("Member type must be USER or ROLE")
        with self.lock:
            with self._session() as connection:
                cursor = connection.execute(
                    """
                    DELETE FROM memberships
                    WHERE role_name=? AND member_type=? AND member_name=?
                    """,
                    (role_name, member_type, member_name),
                )
                if cursor.rowcount != 1:
                    raise RegistryError("Role membership does not exist")

    def _role_inherits(self, connection, member_role, target_role):
        pending = [member_role.lower()]
        visited = set()
        while pending:
            current = pending.pop()
            if current == target_role.lower():
                return True
            if current in visited:
                continue
            visited.add(current)
            rows = connection.execute(
                """
                SELECT role_name FROM memberships
                WHERE member_type='ROLE' AND member_name=?
                """,
                (current,),
            ).fetchall()
            pending.extend(row["role_name"].lower() for row in rows)
        return False

    def grant_database(self, role_name, database_name, privilege):
        role_name = self._validate_identity(role_name, "Role")
        database_name = self.validate_database_name(database_name)
        privilege = str(privilege).upper()
        if privilege not in PRIVILEGES:
            raise RegistryError(
                "Privilege must be CONNECT, READ, WRITE, or ADMIN"
            )
        with self.lock:
            with self._session() as connection:
                try:
                    connection.execute(
                        """
                        INSERT INTO database_grants
                            (role_name, database_name, privilege)
                        VALUES (?, ?, ?)
                        """,
                        (role_name, database_name, privilege),
                    )
                except sqlite3.IntegrityError as exc:
                    raise RegistryError(
                        "Role or database does not exist, or grant already exists"
                    ) from exc

    def revoke_database(self, role_name, database_name, privilege):
        role_name = self._validate_identity(role_name, "Role")
        database_name = self.validate_database_name(database_name)
        privilege = str(privilege).upper()
        if privilege not in PRIVILEGES:
            raise RegistryError(
                "Privilege must be CONNECT, READ, WRITE, or ADMIN"
            )
        with self.lock:
            with self._session() as connection:
                cursor = connection.execute(
                    """
                    DELETE FROM database_grants
                    WHERE role_name=? AND database_name=? AND privilege=?
                    """,
                    (role_name, database_name, privilege),
                )
                if cursor.rowcount != 1:
                    raise RegistryError("Database grant does not exist")

    def authenticate(self, username, password):
        if not isinstance(username, str) or not isinstance(password, str):
            return None
        with self.lock:
            with self._session() as connection:
                row = connection.execute(
                    """
                    SELECT username, password_hash, is_superuser
                    FROM users WHERE username=?
                    """,
                    (username,),
                ).fetchone()
        if row is None or not verify_password(password, row["password_hash"]):
            return None
        return {
            "username": row["username"],
            "is_superuser": bool(row["is_superuser"]),
        }

    def _roles_for_user(self, connection, username):
        roles = set()
        pending = [("USER", username.lower())]
        while pending:
            member_type, member_name = pending.pop()
            rows = connection.execute(
                """
                SELECT role_name FROM memberships
                WHERE member_type=? AND member_name=?
                """,
                (member_type, member_name),
            ).fetchall()
            for row in rows:
                role = row["role_name"].lower()
                if role not in roles:
                    roles.add(role)
                    pending.append(("ROLE", role))
        return roles

    def has_privilege(self, principal, database_name, privilege):
        if principal["is_superuser"]:
            return True
        database_name = self.validate_database_name(database_name)
        privilege = str(privilege).upper()
        if privilege not in PRIVILEGES:
            return False
        with self.lock:
            with self._session() as connection:
                if connection.execute(
                    "SELECT 1 FROM databases WHERE name=?",
                    (database_name,),
                ).fetchone() is None:
                    return False
                roles = self._roles_for_user(
                    connection,
                    principal["username"],
                )
                if not roles:
                    return False
                placeholders = ",".join("?" for _ in roles)
                rows = connection.execute(
                    f"""
                    SELECT privilege FROM database_grants
                    WHERE database_name=? AND role_name IN ({placeholders})
                    """,
                    (database_name, *sorted(roles)),
                ).fetchall()
        granted = {row["privilege"] for row in rows}
        return "ADMIN" in granted or privilege in granted

    def require(self, principal, database_name, privilege):
        if database_name is None:
            raise RegistryError("Select a database when connecting")
        if not self.has_privilege(principal, database_name, privilege):
            raise RegistryError(
                f"Permission denied: {privilege} on database '{database_name}'"
            )

    def list_databases(self, principal):
        with self.lock:
            with self._session() as connection:
                names = [
                    row["name"]
                    for row in connection.execute(
                        "SELECT name FROM databases ORDER BY name COLLATE NOCASE"
                    ).fetchall()
                ]
        if principal["is_superuser"]:
            return names
        return [
            name for name in names
            if self.has_privilege(principal, name, "CONNECT")
        ]
