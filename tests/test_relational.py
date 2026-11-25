import hashlib
import os
import tempfile
import unittest
from unittest.mock import patch

from thesagra import DatabaseFile, RelationalEngine, parse
from thesagra.query.engine import QueryError
from thesagra.graph.model import GraphError
from thesagra.blobs.model import BlobError


class RelationalEngineTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.directory.name, "test.db")

    def tearDown(self):
        self.directory.cleanup()

    def engine(self):
        database = (
            DatabaseFile.open(self.path)
            if os.path.exists(self.path)
            else DatabaseFile.create(self.path)
        )
        return RelationalEngine(database)

    def execute(self, engine, sql):
        return engine.execute(parse(sql))

    def test_create_insert_select_and_persistence(self):
        engine = self.engine()
        self.execute(
            engine,
            "CREATE TABLE people (id INTEGER PRIMARY KEY, name TEXT NOT NULL, active BOOLEAN);",
        )
        self.execute(
            engine,
            "INSERT INTO people VALUES (1, 'Ada', TRUE);",
        )
        self.execute(
            engine,
            "INSERT INTO people (name, id) VALUES ('Linus', 2);",
        )

        reopened = self.engine()
        result = self.execute(
            reopened,
            "SELECT name, id FROM people ORDER BY id DESC;",
        )
        self.assertEqual(result.columns, ["name", "id"])
        self.assertEqual(result.rows, [("Linus", 2), ("Ada", 1)])

    def test_primary_key_and_type_constraints(self):
        engine = self.engine()
        self.execute(
            engine,
            "CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT NOT NULL);",
        )
        self.execute(engine, "INSERT INTO items VALUES (1, 'First');")
        with self.assertRaises(QueryError):
            self.execute(engine, "INSERT INTO items VALUES (1, 'Duplicate');")
        with self.assertRaises(QueryError):
            self.execute(engine, "INSERT INTO items VALUES (2, NULL);")
        with self.assertRaises(QueryError):
            self.execute(engine, "INSERT INTO items VALUES ('bad', 'Wrong type');")

    def test_alter_table_migrations_persist_schema_and_rows(self):
        engine = self.engine()
        self.execute(
            engine,
            "CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT NOT NULL);",
        )
        self.execute(
            engine,
            "CREATE TABLE sessions (account_id INTEGER, "
            "FOREIGN KEY (account_id) REFERENCES accounts(id));",
        )
        self.execute(
            engine,
            "INSERT INTO accounts VALUES (1, 'Ada'), (2, 'Linus');",
        )
        self.execute(
            engine,
            "ALTER TABLE accounts ADD COLUMN active BOOLEAN "
            "NOT NULL DEFAULT TRUE;",
        )
        self.assertEqual(
            self.execute(
                engine,
                "SELECT active FROM accounts ORDER BY id;",
            ).rows,
            [(True,), (True,)],
        )
        self.execute(
            engine,
            "ALTER TABLE accounts RENAME active TO enabled;",
        )
        self.execute(
            engine,
            "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS enabled BOOLEAN;",
        )
        self.execute(engine, "ALTER TABLE accounts RENAME TO users;")

        reopened = self.engine()
        self.assertEqual(
            self.execute(
                reopened,
                "SELECT name, enabled FROM users ORDER BY id;",
            ).rows,
            [("Ada", True), ("Linus", True)],
        )
        self.assertEqual(
            reopened.catalog.get_table("sessions").foreign_keys[0].referenced_table,
            "users",
        )
        self.execute(
            reopened,
            "ALTER TABLE users DROP COLUMN IF EXISTS missing_column;",
        )
        self.execute(reopened, "ALTER TABLE users DROP COLUMN enabled;")
        self.assertEqual(
            self.execute(reopened, "SELECT * FROM users;").columns,
            ["id", "name"],
        )

    def test_alter_table_requires_valid_defaults_and_cascades_dependencies(self):
        engine = self.engine()
        self.execute(
            engine,
            "CREATE TABLE departments (id INTEGER PRIMARY KEY, name TEXT);",
        )
        self.execute(
            engine,
            "CREATE TABLE employees (department_id INTEGER, "
            "FOREIGN KEY (department_id) REFERENCES departments(id));",
        )
        self.execute(
            engine,
            "INSERT INTO departments VALUES (1, 'Engineering');",
        )
        with self.assertRaises(QueryError):
            self.execute(
                engine,
                "ALTER TABLE departments ADD COLUMN code TEXT NOT NULL;",
            )
        with self.assertRaises(QueryError):
            self.execute(
                engine,
                "ALTER TABLE departments DROP COLUMN id;",
            )
        self.execute(
            engine,
            "ALTER TABLE departments DROP COLUMN id CASCADE;",
        )
        self.assertEqual(
            self.execute(
                engine,
                "SELECT name FROM departments;",
            ).rows,
            [("Engineering",)],
        )
        reopened = self.engine()
        self.assertEqual(
            reopened.catalog.get_table("employees").foreign_keys,
            [],
        )

    def test_relational_suite_sql_features(self):
        engine = self.engine()
        self.execute(
            engine,
            "CREATE TABLE departments ("
            "id INT PRIMARY KEY, name VARCHAR(100) NOT NULL UNIQUE);",
        )
        self.execute(
            engine,
            "CREATE TABLE employees ("
            "id INT PRIMARY KEY, name VARCHAR(100) NOT NULL, "
            "email VARCHAR(150) UNIQUE, salary DECIMAL(10,2), "
            "department_id INT, manager_id INT, "
            "FOREIGN KEY (department_id) REFERENCES departments(id), "
            "FOREIGN KEY (manager_id) REFERENCES employees(id));",
        )
        self.execute(
            engine,
            "CREATE TABLE projects ("
            "id INT PRIMARY KEY, project_name VARCHAR(150) NOT NULL, "
            "budget DECIMAL(12,2));",
        )
        self.execute(
            engine,
            "CREATE TABLE employee_projects ("
            "employee_id INT, project_id INT, assigned_date DATE, "
            "PRIMARY KEY (employee_id, project_id), "
            "FOREIGN KEY (employee_id) REFERENCES employees(id), "
            "FOREIGN KEY (project_id) REFERENCES projects(id));",
        )
        self.execute(
            engine,
            "INSERT INTO departments VALUES "
            "(1, 'Engineering'), (2, 'Marketing'), "
            "(3, 'Human Resources'), (4, 'Finance');",
        )
        self.execute(
            engine,
            "INSERT INTO employees VALUES "
            "(1, 'John', 'john@test.com', 75000, 1, NULL), "
            "(2, 'Alice', 'alice@test.com', 65000, 1, 1), "
            "(3, 'Bob', 'bob@test.com', 55000, 2, NULL), "
            "(4, 'David', 'david@test.com', 60000, 1, 1);",
        )
        self.execute(
            engine,
            "INSERT INTO projects VALUES "
            "(1, 'Database Engine', 500000), "
            "(2, 'Marketing Platform', 200000);",
        )
        self.execute(
            engine,
            "INSERT INTO employee_projects VALUES "
            "(1, 1, '2026-01-01'), (2, 1, '2026-01-02'), "
            "(3, 2, '2026-01-03');",
        )
        with self.assertRaises(QueryError):
            self.execute(
                engine,
                "INSERT INTO employee_projects VALUES "
                "(99, 1, '2026-01-04');",
            )
        with self.assertRaises(QueryError):
            self.execute(
                engine,
                "INSERT INTO employee_projects VALUES "
                "(1, 1, '2026-01-04');",
            )
        self.assertEqual(
            self.execute(
                engine,
                "SELECT name FROM employees "
                "WHERE salary BETWEEN 60000 AND 70000;",
            ).rows,
            [("Alice",), ("David",)],
        )
        self.assertEqual(
            self.execute(
                engine,
                "SELECT name FROM employees WHERE name LIKE 'A%';",
            ).rows,
            [("Alice",)],
        )
        self.assertEqual(
            len(self.execute(
                engine,
                "SELECT e.name, d.name, p.project_name "
                "FROM employees e "
                "LEFT JOIN departments d ON e.department_id=d.id "
                "LEFT JOIN employee_projects ep ON e.id=ep.employee_id "
                "LEFT JOIN projects p ON ep.project_id=p.id;",
            ).rows),
            4,
        )
        self.assertEqual(
            self.execute(
                engine,
                "SELECT e.name AS employee, m.name AS manager "
                "FROM employees e LEFT JOIN employees m "
                "ON e.manager_id=m.id;",
            ).columns,
            ["employee", "manager"],
        )
        self.assertEqual(
            self.execute(
                engine,
                "SELECT COUNT(*) AS total_employees FROM employees;",
            ).rows,
            [(4,)],
        )
        self.assertEqual(
            self.execute(
                engine,
                "SELECT MIN(salary), MAX(salary) FROM employees;",
            ).rows,
            [(55000.0, 75000.0)],
        )
        grouped = self.execute(
            engine,
            "SELECT department_id, AVG(salary) AS average_salary "
            "FROM employees GROUP BY department_id "
            "HAVING AVG(salary) > 60000;",
        )
        self.assertEqual(grouped.rows, [(1, 66666.66666666667)])
        self.assertEqual(
            self.execute(
                engine,
                "SELECT name FROM employees WHERE salary > "
                "(SELECT AVG(salary) FROM employees);",
            ).rows,
            [("John",), ("Alice",)],
        )
        self.assertEqual(
            self.execute(
                engine,
                "SELECT name FROM employees WHERE department_id IN "
                "(SELECT id FROM departments WHERE name='Engineering');",
            ).rows,
            [("John",), ("Alice",), ("David",)],
        )
        self.assertEqual(
            len(self.execute(
                engine,
                "SELECT DISTINCT department_id FROM employees;",
            ).rows),
            2,
        )
        self.execute(
            engine,
            "CREATE INDEX idx_employee_name ON employees(name);",
        )
        self.execute(engine, "START TRANSACTION;")
        self.execute(
            engine,
            "UPDATE employees SET salary=999 WHERE department_id=1;",
        )
        self.execute(engine, "ROLLBACK;")
        self.assertEqual(
            self.execute(
                engine,
                "SELECT salary FROM employees WHERE id=1;",
            ).rows,
            [(75000.0,)],
        )
        self.execute(
            engine,
            "UPDATE employees SET salary = salary + 5000 WHERE id = 2;",
        )
        self.assertEqual(
            self.execute(
                engine,
                "SELECT salary FROM employees WHERE id=2;",
            ).rows,
            [(70000.0,)],
        )
        self.execute(
            engine,
            "UPDATE employees SET department_id = 2 WHERE id = 4;",
        )
        self.execute(engine, "START TRANSACTION;")
        self.execute(
            engine,
            "UPDATE employees SET salary = salary + 5000 "
            "WHERE department_id = 1;",
        )
        self.execute(engine, "ROLLBACK;")
        self.execute(
            engine,
            "DELETE FROM employee_projects "
            "WHERE employee_id=3 AND project_id=2;",
        )
        reopened = self.engine()
        self.assertEqual(
            len(reopened.catalog.get_table("employees").foreign_keys),
            2,
        )
        self.assertEqual(
            reopened.catalog.get_table("employees").indexes[0].name,
            "idx_employee_name",
        )

    def test_mysql_style_column_types_constraints_and_defaults(self):
        engine = self.engine()
        self.execute(
            engine,
            """
            CREATE TABLE Nomads (
                id INT PRIMARY KEY AUTO_INCREMENT,
                name VARCHAR(100) NOT NULL,
                email VARCHAR(150) UNIQUE,
                age INT,
                city VARCHAR(100),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """,
        )
        self.execute(
            engine,
            "INSERT INTO Nomads (name, email, age, city) "
            "VALUES ('John', 'john@gmail.com', 25, 'Mumbai');",
        )
        result = self.execute(
            engine,
            "SELECT id, name, email, age, city, created_at FROM Nomads;",
        )
        self.assertEqual(len(result.rows), 1)
        row = result.rows[0]
        self.assertEqual(row[:5], (1, "John", "john@gmail.com", 25, "Mumbai"))
        self.assertTrue(row[5])

        reopened = self.engine()
        self.execute(
            reopened,
            "INSERT INTO Nomads (name, email, age, city) "
            "VALUES ('Ada', 'ada@example.com', 30, 'London');",
        )
        rows = self.execute(
            reopened,
            "SELECT id FROM Nomads ORDER BY id;",
        ).rows
        self.assertEqual(rows, [(1,), (2,)])
        self.execute(
            reopened,
            "CREATE TABLE people (id INT PRIMARY KEY, name VARCHAR(100));",
        )
        self.execute(
            reopened,
            "INSERT INTO people VALUES (1, 'John from people');",
        )
        self.execute(
            reopened,
            "INSERT INTO people VALUES (2, 'Ada from people');",
        )
        joined = self.execute(
            reopened,
            """
            SELECT
                n.id,
                n.name,
                n.email,
                n.age,
                n.city,
                n.created_at,
                p.name AS people_name
            FROM Nomads n
            INNER JOIN people p
                ON n.id = p.id;
            """,
        )
        self.assertEqual(joined.columns[-1], "people_name")
        self.assertEqual(
            [row[-1] for row in joined.rows],
            ["John from people", "Ada from people"],
        )

        with self.assertRaises(QueryError):
            self.execute(
                reopened,
                "INSERT INTO Nomads (name, email) "
                "VALUES ('Other', 'john@gmail.com');",
            )
        with self.assertRaises(QueryError):
            self.execute(
                reopened,
                "UPDATE Nomads SET email='john@gmail.com' WHERE id=2;",
            )
        with self.assertRaises(QueryError):
            long_name = "N" * 101
            self.execute(
                reopened,
                "INSERT INTO Nomads (name, email) VALUES "
                f"('{long_name}', 'long@example.com');",
            )

    def test_update_delete_where_and_limit(self):
        engine = self.engine()
        self.execute(
            engine,
            "CREATE TABLE scores (id INTEGER PRIMARY KEY, value INTEGER);",
        )
        for id_value in (1, 2, 3):
            self.execute(
                engine,
                f"INSERT INTO scores VALUES ({id_value}, {id_value * 10});",
            )

        updated = self.execute(
            engine,
            "UPDATE scores SET value = 99 WHERE id >= 2;",
        )
        self.assertEqual(updated.rowcount, 2)

        selected = self.execute(
            engine,
            "SELECT id, value FROM scores WHERE value >= 99 ORDER BY id LIMIT 1;",
        )
        self.assertEqual(selected.rows, [(2, 99)])

        deleted = self.execute(engine, "DELETE FROM scores WHERE id = 3;")
        self.assertEqual(deleted.rowcount, 1)
        remaining = self.execute(engine, "SELECT * FROM scores;")
        self.assertEqual(remaining.rows, [(1, 10), (2, 99)])

    def test_duplicate_table_is_rejected(self):
        engine = self.engine()
        self.execute(engine, "CREATE TABLE users (id INTEGER PRIMARY KEY);")
        with self.assertRaises(QueryError):
            self.execute(engine, "CREATE TABLE users (id INTEGER PRIMARY KEY);")

    def test_drop_table_restrict_cascade_and_if_exists(self):
        engine = self.engine()
        self.execute(
            engine,
            "CREATE TABLE departments (id INT PRIMARY KEY);",
        )
        self.execute(
            engine,
            "CREATE TABLE employees ("
            "id INT PRIMARY KEY, department_id INT, "
            "FOREIGN KEY (department_id) REFERENCES departments(id));",
        )
        with self.assertRaisesRegex(QueryError, "referenced by foreign key"):
            self.execute(engine, "DROP TABLE departments;")
        self.execute(engine, "DROP TABLE departments CASCADE;")
        self.assertNotIn("departments", engine.catalog.tables)
        self.assertEqual(
            engine.catalog.get_table("employees").foreign_keys,
            [],
        )
        self.execute(engine, "DROP TABLE employees;")
        self.execute(engine, "DROP TABLE IF EXISTS missing_table;")
        with self.assertRaises(QueryError):
            self.execute(engine, "SELECT * FROM employees;")

    def test_inner_join(self):
        engine = self.engine()
        self.execute(
            engine,
            "CREATE TABLE people (id INTEGER PRIMARY KEY, team_id INTEGER);",
        )
        self.execute(
            engine,
            "CREATE TABLE teams (id INTEGER PRIMARY KEY, name TEXT);",
        )
        self.execute(engine, "INSERT INTO people VALUES (1, 10);")
        self.execute(engine, "INSERT INTO people VALUES (2, 20);")
        self.execute(engine, "INSERT INTO teams VALUES (10, 'Core');")
        self.execute(engine, "INSERT INTO teams VALUES (20, 'Apps');")

        result = self.execute(
            engine,
            "SELECT people.id, teams.name FROM people JOIN teams "
            "ON people.team_id=teams.id;",
        )
        self.assertEqual(result.rows, [(1, "Core"), (2, "Apps")])

    def test_outer_cross_joins_and_null_predicates(self):
        engine = self.engine()
        self.execute(
            engine,
            "CREATE TABLE people (id INTEGER PRIMARY KEY, team_id INTEGER);",
        )
        self.execute(
            engine,
            "CREATE TABLE teams (id INTEGER PRIMARY KEY, name TEXT);",
        )
        self.execute(engine, "INSERT INTO people VALUES (1, 10);")
        self.execute(engine, "INSERT INTO people VALUES (2, 30);")
        self.execute(engine, "INSERT INTO teams VALUES (10, 'Core');")
        self.execute(engine, "INSERT INTO teams VALUES (20, 'Apps');")

        left = self.execute(
            engine,
            "SELECT p.id, t.name FROM people p "
            "LEFT JOIN teams t ON p.team_id=t.id ORDER BY p.id;",
        )
        self.assertEqual(left.rows, [(1, "Core"), (2, None)])

        missing = self.execute(
            engine,
            "SELECT p.id FROM people p LEFT OUTER JOIN teams t "
            "ON p.team_id=t.id WHERE t.id IS NULL;",
        )
        self.assertEqual(missing.rows, [(2,)])

        right = self.execute(
            engine,
            "SELECT p.id, t.name FROM people p "
            "RIGHT JOIN teams t ON p.team_id=t.id ORDER BY t.id;",
        )
        self.assertEqual(right.rows, [(1, "Core"), (None, "Apps")])

        full = self.execute(
            engine,
            "SELECT p.id, t.name FROM people p "
            "FULL OUTER JOIN teams t ON p.team_id=t.id;",
        )
        self.assertEqual(
            set(full.rows),
            {(1, "Core"), (2, None), (None, "Apps")},
        )

        cross = self.execute(
            engine,
            "SELECT p.id, t.id FROM people p CROSS JOIN teams t;",
        )
        self.assertEqual(len(cross.rows), 4)

    def test_aggregates_and_group_by(self):
        engine = self.engine()
        self.execute(
            engine,
            "CREATE TABLE scores (id INTEGER PRIMARY KEY, team TEXT, value INTEGER);",
        )
        self.execute(engine, "INSERT INTO scores VALUES (1, 'Core', 10);")
        self.execute(engine, "INSERT INTO scores VALUES (2, 'Core', 20);")
        self.execute(engine, "INSERT INTO scores VALUES (3, 'Apps', 5);")

        result = self.execute(
            engine,
            "SELECT team, COUNT(*), SUM(value), AVG(value) "
            "FROM scores GROUP BY team;",
        )
        self.assertEqual(set(result.rows), {
            ("Apps", 1, 5, 5.0),
            ("Core", 2, 30, 15.0),
        })

    def test_explain_and_primary_lookup_plan(self):
        engine = self.engine()
        self.execute(
            engine,
            "CREATE TABLE people (id INTEGER PRIMARY KEY, name TEXT);",
        )
        result = self.execute(
            engine,
            "EXPLAIN SELECT name FROM people WHERE id=1;",
        )
        plan = [row[0] for row in result.rows]
        self.assertIn("Primary Key Lookup: people.id", plan)

    def test_begin_commit_and_rollback(self):
        engine = self.engine()
        self.execute(engine, "CREATE TABLE items (id INTEGER PRIMARY KEY);")

        self.execute(engine, "BEGIN;")
        self.execute(engine, "INSERT INTO items VALUES (1);")
        staged = self.execute(engine, "SELECT * FROM items;")
        self.assertEqual(staged.rows, [(1,)])
        self.execute(engine, "ROLLBACK;")
        remaining = self.execute(engine, "SELECT * FROM items;")
        self.assertEqual(remaining.rows, [])

        self.execute(engine, "BEGIN;")
        self.execute(engine, "INSERT INTO items VALUES (2);")
        self.execute(engine, "COMMIT;")
        reopened = self.engine()
        remaining = self.execute(reopened, "SELECT * FROM items;")
        self.assertEqual(remaining.rows, [(2,)])

    def test_wal_recovery_replays_committed_pages(self):
        engine = self.engine()
        self.execute(engine, "CREATE TABLE items (id INTEGER PRIMARY KEY);")
        self.execute(engine, "BEGIN;")
        self.execute(engine, "INSERT INTO items VALUES (7);")
        self.execute(engine, "COMMIT;")

        reopened = self.engine()
        result = self.execute(reopened, "SELECT * FROM items;")
        self.assertEqual(result.rows, [(7,)])

    def test_uncommitted_wal_change_is_not_replayed(self):
        engine = self.engine()
        self.execute(engine, "CREATE TABLE items (id INTEGER PRIMARY KEY);")
        engine.wal.begin(900)
        engine.wal.append_page(
            900,
            2,
            b"",
        )

        reopened = self.engine()
        result = self.execute(reopened, "SELECT * FROM items;")
        self.assertEqual(result.rows, [])

    def test_graph_nodes_edges_and_traversal(self):
        engine = self.engine()
        ada = engine.create_node("Person", {"name": "Ada"}, node_id=1)
        linus = engine.create_node("Person", {"name": "Linus"}, node_id=2)
        project = engine.create_node("Project", {"name": "Kernel"}, node_id=3)
        engine.create_edge(1, 2, "KNOWS")
        engine.create_edge(1, 3, "WORKS_ON")

        self.assertEqual(ada.node_id, 1)
        self.assertEqual(linus.node_id, 2)
        self.assertEqual(project.node_id, 3)
        paths = engine.traverse(1, depth=2)
        target_ids = {path[-1].node_id for path in paths}
        self.assertIn(2, target_ids)
        self.assertIn(3, target_ids)

    def test_graph_persistence_and_invalid_edge(self):
        engine = self.engine()
        engine.create_node("Person", node_id=10)
        engine.create_edge(10, 10, "SELf")

        reopened = self.engine()
        node = reopened.get_node(10)
        self.assertEqual(node.label, "Person")
        with self.assertRaises(GraphError):
            reopened.create_edge(10, 999, "INVALID")

    def test_graph_depth_and_relationship_limit(self):
        engine = self.engine()
        engine.create_node("N", node_id=1)
        engine.create_node("N", node_id=2)
        engine.create_node("N", node_id=3)
        engine.create_edge(1, 2, "KNOWS")
        engine.create_edge(2, 3, "LIKES")

        one_hop = engine.traverse(1, depth=1)
        self.assertEqual([path[-1].node_id for path in one_hop], [1, 2])
        likes = engine.traverse(1, depth=2, relationship_type="LIKES")
        self.assertEqual(likes, [(engine.get_node(1),)])

    def test_chunked_blob_upload_persistence_and_range(self):
        engine = self.engine()
        object_id = engine.begin_blob_upload(
            "image.bin",
            "application/octet-stream",
            {"category": "test"},
            max_size=1024,
        )
        payload = bytes(range(256)) * 3
        engine.append_blob_chunk(object_id, payload[:400])
        engine.append_blob_chunk(object_id, payload[400:])
        metadata = engine.finalize_blob(object_id, declared_size=len(payload))
        self.assertEqual(metadata.byte_length, len(payload))
        self.assertEqual(
            engine.read_blob_range(object_id, 398, 10),
            payload[398:408],
        )
        reopened = self.engine()
        reopened_metadata = reopened.get_blob_metadata(object_id)
        self.assertEqual(reopened_metadata.state, "ready")
        self.assertEqual(
            b"".join(reopened.stream_blob(object_id, 100)),
            payload,
        )

    def test_blob_size_checksum_and_delete(self):
        engine = self.engine()
        object_id = engine.begin_blob_upload("file.txt", "text/plain")
        engine.append_blob_chunk(object_id, b"hello")
        with self.assertRaises(Exception):
            engine.finalize_blob(object_id, declared_size=4)

        metadata = engine.finalize_blob(object_id, declared_size=5)
        self.assertEqual(metadata.checksum, metadata.checksum)
        engine.delete_blob(object_id)
        cleaned = engine.reconcile_blobs()
        self.assertIn(object_id, cleaned)
        deleted_metadata = engine.get_blob_metadata(object_id)
        self.assertEqual(deleted_metadata.state, "deleted")

    def test_blob_corruption_is_detected(self):
        engine = self.engine()
        object_id = engine.begin_blob_upload("corrupt.bin")
        engine.append_blob_chunk(object_id, b"abcdef")
        engine.finalize_blob(object_id)
        chunk_directory = os.path.join(
            os.path.splitext(self.path)[0] + ".blobs",
            str(object_id),
        )
        chunk_path = os.path.join(chunk_directory, "0.chunk")
        with open(chunk_path, "wb") as chunk_file:
            chunk_file.write(b"XXXXX!")
        with self.assertRaises(Exception):
            engine.read_blob_range(object_id)

    def test_blob_append_recovers_from_uncommitted_chunk_files(self):
        engine = self.engine()
        object_id = engine.begin_blob_upload("recover.bin")
        engine.append_blob_chunk(object_id, b"before")

        with patch.object(
            engine,
            "commit",
            side_effect=OSError("simulated process interruption"),
        ):
            with self.assertRaises(OSError):
                engine.append_blob_chunk(object_id, b"after")

        recovered = self.engine()
        self.assertEqual(recovered.get_blob_metadata(object_id).byte_length, 6)
        directory = os.path.join(
            os.path.splitext(self.path)[0] + ".blobs",
            str(object_id),
        )
        self.assertTrue(os.path.exists(os.path.join(directory, "1.chunk")))
        chunk_table = recovered.catalog.get_table("__thesagra_blob_chunks")
        chunk_rows = recovered.read_records(chunk_table.page_id)
        chunk_rows.append((
            object_id,
            1,
            6,
            5,
            hashlib.sha256(b"after").hexdigest(),
        ))
        recovered.write_records(chunk_table.page_id, chunk_rows)
        self.assertEqual(recovered.reconcile_blobs(), [])
        self.assertFalse(os.path.exists(os.path.join(directory, "1.chunk")))
        self.assertEqual(
            len(recovered.read_records(chunk_table.page_id)),
            1,
        )

        recovered.append_blob_chunk(object_id, b"after")
        recovered.finalize_blob(object_id, declared_size=11)
        self.assertEqual(recovered.read_blob_range(object_id), b"beforeafter")

    def test_blob_commit_replays_after_database_page_install_failure(self):
        engine = self.engine()
        object_id = engine.begin_blob_upload("wal-recover.bin")
        with patch.object(
            engine.database,
            "_write_page",
            side_effect=OSError("simulated page installation failure"),
        ):
            with self.assertRaises(OSError):
                engine.append_blob_chunk(object_id, b"committed")

        recovered = self.engine()
        metadata = recovered.get_blob_metadata(object_id)
        self.assertEqual(metadata.byte_length, len(b"committed"))
        recovered.finalize_blob(object_id, declared_size=len(b"committed"))
        self.assertEqual(
            recovered.read_blob_range(object_id),
            b"committed",
        )

    def test_blob_reconciliation_rejects_active_transaction(self):
        engine = self.engine()
        engine.begin()
        with self.assertRaises(BlobError):
            engine.reconcile_blobs()
        engine.rollback()

    def test_graph_match_syntax(self):
        engine = self.engine()
        engine.create_node("Person", {"name": "Ada"}, node_id=1)
        engine.create_node("Project", {"name": "Kernel"}, node_id=2)
        engine.create_edge(1, 2, "WORKS_ON")
        result = self.execute(
            engine,
            "MATCH (p:Person)-[:WORKS_ON]->(q:Project);",
        )
        self.assertEqual(
            result.rows,
            [(1, "Person", 2, "Project")],
        )


if __name__ == "__main__":
    unittest.main()
