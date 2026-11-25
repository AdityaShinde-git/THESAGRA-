import os
import socket
import struct
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from thesagra import THESAGRAClient, THESAGRAServer
from thesagra.drivers.python.client import THESAGRAConnection
from thesagra.drivers.python.errors import (
    AuthenticationError,
    ProtocolError as DriverProtocolError,
    QueryError,
)
from thesagra.server.protocol import (
    HEADER,
    MAGIC,
    MAX_MESSAGE_SIZE,
    PROTOCOL_VERSION,
    REQUEST,
)


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.directory.name, "server.db")
        self.server = THESAGRAServer(
            self.path,
            host="127.0.0.1",
            port=0,
            username="test",
            password="secret",
        )
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
        )
        self.thread.start()
        self.host, self.port = self.server.server_address

    def tearDown(self):
        self.server.shutdown()
        self.server.worker.stop()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.directory.cleanup()

    def client(self):
        client = THESAGRAClient(self.host, self.port)
        client.handshake("test", "secret")
        return client

    def test_auth_query_and_parameter_binding(self):
        client = THESAGRAClient(self.host, self.port)
        with self.assertRaises(RuntimeError):
            client.handshake("test", "wrong")
        client.close()

        client = self.client()
        self.assertTrue(
            client.query(
                "CREATE TABLE people (id INTEGER PRIMARY KEY, name TEXT);"
            )["ok"]
        )
        self.assertTrue(
            client.query(
                "INSERT INTO people VALUES (?, ?);",
                [1, "Ada"],
            )["ok"]
        )
        result = client.query(
            "SELECT name FROM people WHERE id=?;",
            [1],
        )
        self.assertEqual(result["rows"], [["Ada"]])
        client.close()

    def test_auth_failure_and_disconnect(self):
        client = THESAGRAClient(self.host, self.port)
        with self.assertRaises(RuntimeError):
            client.handshake("other", "secret")
        client.close()

        client = THESAGRAClient(self.host, self.port)
        response = client.handshake("test", "secret")
        self.assertIn("session_id", response)
        client.close()
        self.assertEqual(len(self.server.sessions), 0)

    def test_malformed_magic_is_rejected(self):
        connection = socket.create_connection((self.host, self.port), timeout=2)
        connection.sendall(struct.pack(">4sBBI", b"BAD!", 1, REQUEST, 2) + b"{}")
        connection.settimeout(2)
        try:
            connection.recv(1024)
        except (socket.timeout, ConnectionResetError):
            pass
        connection.close()

    def test_oversized_frame_is_rejected(self):
        connection = socket.create_connection((self.host, self.port), timeout=2)
        header = HEADER.pack(
            MAGIC,
            PROTOCOL_VERSION,
            REQUEST,
            MAX_MESSAGE_SIZE + 1,
        )
        connection.sendall(header)
        connection.settimeout(2)
        try:
            connection.recv(1024)
        except (socket.timeout, ConnectionResetError):
            pass
        connection.close()

    def test_python_connection_cursor_and_parameters(self):
        uri = (
            f"thesagra://test:secret@{self.host}:{self.port}/main"
        )
        with THESAGRAConnection(uri=uri) as connection:
            connection.execute(
                "CREATE TABLE people (id INTEGER PRIMARY KEY, name TEXT);"
            )
            connection.execute(
                "INSERT INTO people VALUES (?, ?);",
                [1, "Ada"],
            )
            cursor = connection.execute(
                "SELECT name FROM people WHERE id=?;",
                [1],
            )
            self.assertEqual(cursor.fetchall(), [("Ada",)])
            self.assertEqual(cursor.rowcount, 1)

    def test_mysql_style_sql_through_python_connection(self):
        with THESAGRAConnection(
            host=self.host,
            port=self.port,
            username="test",
            password="secret",
        ) as connection:
            connection.execute(
                "CREATE TABLE Nomads ("
                "id INT PRIMARY KEY AUTO_INCREMENT, "
                "name VARCHAR(100) NOT NULL, "
                "email VARCHAR(150) UNIQUE, "
                "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);"
            )
            connection.execute(
                "INSERT INTO Nomads (name, email) "
                "VALUES (?, ?);",
                ["John", "john@gmail.com"],
            )
            result = connection.execute(
                "SELECT id, name, email, created_at FROM Nomads;"
            )
            rows = result.fetchall()
            self.assertEqual(rows[0][:3], (1, "John", "john@gmail.com"))
            self.assertTrue(rows[0][3])
            connection.execute(
                "CREATE TABLE people (id INT PRIMARY KEY, name TEXT);"
            )
            connection.execute(
                "INSERT INTO people VALUES (?, ?);",
                [1, "John in people"],
            )
            connection.execute(
                "INSERT INTO Nomads (name, email) VALUES (?, ?);",
                ["Ada", "ada@example.com"],
            )
            joined = connection.execute(
                "SELECT n.id, n.name, p.name AS people_name "
                "FROM Nomads n LEFT JOIN people p ON n.id=p.id "
                "ORDER BY n.id;"
            )
            self.assertEqual(
                joined.fetchall(),
                [(1, "John", "John in people"), (2, "Ada", None)],
            )

    def test_multi_database_users_roles_and_isolation(self):
        data_directory = os.path.join(self.directory.name, "hosted")
        server = THESAGRAServer(
            os.path.join(self.directory.name, "unused.db"),
            host="127.0.0.1",
            port=0,
            username="root",
            password="strong-test-password",
            database_directory=data_directory,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        host, port = server.server_address
        try:
            with THESAGRAConnection(
                host=host,
                port=port,
                username="root",
                password="strong-test-password",
            ) as admin:
                admin.create_database("project_alpha")
                admin.create_database("project_beta")
                with self.assertRaises(DriverProtocolError):
                    admin.create_database("../outside")
                admin.create_role("alpha_rw")
                admin.create_role("alpha_readers")
                admin.create_role("engineering")
                admin.create_user("app_alpha", "alpha-secret")
                admin.create_user("analyst", "analyst-secret")
                admin.grant_role(
                    "alpha_rw",
                    "engineering",
                    member_type="ROLE",
                )
                with self.assertRaises(DriverProtocolError):
                    admin.grant_role(
                        "engineering",
                        "alpha_rw",
                        member_type="ROLE",
                    )
                admin.grant_role("engineering", "app_alpha")
                admin.grant_role("alpha_readers", "analyst")
                for privilege in ("CONNECT", "READ", "WRITE"):
                    admin.grant_database(
                        "alpha_rw",
                        "project_alpha",
                        privilege,
                    )
                for privilege in ("CONNECT", "READ"):
                    admin.grant_database(
                        "alpha_readers",
                        "project_alpha",
                        privilege,
                    )
                self.assertEqual(
                    admin.list_databases()["databases"],
                    ["project_alpha", "project_beta"],
                )

            with THESAGRAConnection(
                host=host,
                port=port,
                username="app_alpha",
                password="alpha-secret",
            ) as database_browser:
                self.assertTrue(database_browser.multi_database)
                self.assertFalse(database_browser.is_admin)
                self.assertEqual(
                    database_browser.list_databases()["databases"],
                    ["project_alpha"],
                )

            alpha_uri = (
                f"thesagra://app_alpha:alpha-secret@{host}:{port}/"
                "project_alpha"
            )
            with THESAGRAConnection(uri=alpha_uri) as application:
                application.execute(
                    "CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT);"
                )
                application.execute(
                    "INSERT INTO records VALUES (1, 'alpha');"
                )
                self.assertEqual(
                    application.execute(
                        "SELECT value FROM records;"
                    ).fetchall(),
                    [("alpha",)],
                )
                application.execute("BEGIN;")
                application.execute(
                    "INSERT INTO records VALUES (2, 'uncommitted');"
                )
                reader_started = threading.Event()
                reader_finished = threading.Event()
                reader_rows = []

                def read_during_transaction():
                    with THESAGRAConnection(uri=alpha_uri) as reader_connection:
                        reader_started.set()
                        reader_rows.extend(
                            reader_connection.execute(
                                "SELECT id FROM records ORDER BY id;"
                            ).fetchall()
                        )
                    reader_finished.set()

                reader_thread = threading.Thread(
                    target=read_during_transaction,
                    daemon=True,
                )
                reader_thread.start()
                self.assertTrue(reader_started.wait(timeout=2))
                self.assertFalse(reader_finished.wait(timeout=0.1))
                with THESAGRAConnection(
                    host=host,
                    port=port,
                    username="root",
                    password="strong-test-password",
                    database="project_beta",
                ) as other_project:
                    other_project.execute(
                        "CREATE TABLE records ("
                        "id INTEGER PRIMARY KEY, value TEXT);"
                    )
                application.commit()
                self.assertTrue(reader_finished.wait(timeout=3))
                reader_thread.join(timeout=1)
                self.assertEqual(reader_rows, [(1,), (2,)])

            with THESAGRAConnection(
                host=host,
                port=port,
                username="root",
                password="strong-test-password",
                database="project_beta",
            ) as beta:
                self.assertEqual(
                    beta.execute("SELECT * FROM records;").fetchall(),
                    [],
                )

            with THESAGRAConnection(
                host=host,
                port=port,
                username="analyst",
                password="analyst-secret",
                database="project_alpha",
            ) as reader:
                reader.execute("SELECT * FROM records;")
                with self.assertRaises(QueryError):
                    reader.execute(
                        "INSERT INTO records VALUES (2, 'denied');"
                    )

            with THESAGRAConnection(
                host=host,
                port=port,
                username="root",
                password="strong-test-password",
            ) as admin:
                admin.revoke_database(
                    "alpha_readers",
                    "project_alpha",
                    "READ",
                )
                admin.reset_password("analyst", "analyst-new-secret")

            with THESAGRAConnection(
                host=host,
                port=port,
                username="analyst",
                password="analyst-new-secret",
                database="project_alpha",
            ) as reader:
                with self.assertRaises(QueryError):
                    reader.execute("SELECT * FROM records;")

            with self.assertRaises(AuthenticationError):
                THESAGRAConnection(
                    host=host,
                    port=port,
                    username="analyst",
                    password="analyst-secret",
                    database="project_alpha",
                ).connect()

            with self.assertRaises(AuthenticationError):
                THESAGRAConnection(
                    host=host,
                    port=port,
                    username="app_alpha",
                    password="alpha-secret",
                    database="project_beta",
                ).connect()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_multi_database_registry_persists_after_restart(self):
        data_directory = os.path.join(self.directory.name, "persistent-host")

        def start_server():
            instance = THESAGRAServer(
                os.path.join(self.directory.name, "unused.db"),
                host="127.0.0.1",
                port=0,
                username="root",
                password="persistent-admin-secret",
                database_directory=data_directory,
            )
            server_thread = threading.Thread(
                target=instance.serve_forever,
                daemon=True,
            )
            server_thread.start()
            return instance, server_thread

        server, thread = start_server()
        host, port = server.server_address
        try:
            with THESAGRAConnection(
                host=host,
                port=port,
                username="root",
                password="persistent-admin-secret",
            ) as admin:
                admin.create_database("persistent_project")
                admin.create_role("persistent_readers")
                admin.create_user("persistent_app", "application-secret")
                admin.grant_role(
                    "persistent_readers",
                    "persistent_app",
                )
                admin.grant_database(
                    "persistent_readers",
                    "persistent_project",
                    "CONNECT",
                )
                admin.grant_database(
                    "persistent_readers",
                    "persistent_project",
                    "READ",
                )

            with THESAGRAConnection(
                host=host,
                port=port,
                username="root",
                password="persistent-admin-secret",
                database="persistent_project",
            ) as project:
                project.execute(
                    "CREATE TABLE saved (id INTEGER PRIMARY KEY);"
                )
                project.execute("INSERT INTO saved VALUES (7);")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        restarted, restarted_thread = start_server()
        restarted_host, restarted_port = restarted.server_address
        try:
            with THESAGRAConnection(
                uri=(
                    f"thesagra://persistent_app:application-secret@"
                    f"{restarted_host}:{restarted_port}/persistent_project"
                )
            ) as application:
                self.assertEqual(
                    application.execute("SELECT id FROM saved;").fetchall(),
                    [(7,)],
                )
        finally:
            restarted.shutdown()
            restarted.server_close()
            restarted_thread.join(timeout=2)

    def test_sql_create_database_and_use_switch_session_database(self):
        data_directory = os.path.join(self.directory.name, "sql-control")
        server = THESAGRAServer(
            os.path.join(self.directory.name, "unused-sql-control.db"),
            host="127.0.0.1",
            port=0,
            username="root",
            password="sql-control-secret",
            database_directory=data_directory,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        host, port = server.server_address
        try:
            with THESAGRAConnection(
                host=host,
                port=port,
                username="root",
                password="sql-control-secret",
            ) as admin:
                admin.create_database("initial_project")
                admin.create_database("private_project")
                admin.create_role("initial_connect")
                admin.create_user("project_user", "project-user-secret")
                admin.grant_role("initial_connect", "project_user")
                admin.grant_database(
                    "initial_connect",
                    "initial_project",
                    "CONNECT",
                )
            with THESAGRAConnection(
                host=host,
                port=port,
                username="root",
                password="sql-control-secret",
                database="initial_project",
            ) as connection:
                connection.execute("CREATE DATABASE thesagra_test;")
                connection.execute("USE thesagra_test;")
                self.assertEqual(connection.database, "thesagra_test")
                connection.execute(
                    "CREATE TABLE departments ("
                    "id INT PRIMARY KEY, name TEXT);"
                )
                connection.execute(
                    "INSERT INTO departments VALUES (1, 'Engineering');"
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT name FROM departments;"
                    ).fetchall(),
                    [("Engineering",)],
                )
            with THESAGRAConnection(
                host=host,
                port=port,
                username="project_user",
                password="project-user-secret",
                database="initial_project",
            ) as restricted:
                with self.assertRaises(QueryError):
                    restricted.execute("CREATE DATABASE forbidden_project;")
                with self.assertRaises(QueryError):
                    restricted.execute("USE private_project;")
                self.assertEqual(restricted.database, "initial_project")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_python_transaction_contract(self):
        with THESAGRAConnection(
            host=self.host,
            port=self.port,
            username="test",
            password="secret",
        ) as connection:
            connection.execute(
                "CREATE TABLE items (id INTEGER PRIMARY KEY);"
            )
            connection.begin()
            connection.execute("INSERT INTO items VALUES (5);")
            connection.rollback()
            cursor = connection.execute("SELECT * FROM items;")
            self.assertEqual(cursor.fetchall(), [])

    def test_python_graph_and_blob_contract(self):
        with THESAGRAConnection(
            host=self.host,
            port=self.port,
            username="test",
            password="secret",
        ) as connection:
            node = connection.create_node("Person", {"name": "Ada"}, 1)
            connection.create_node("Project", {"name": "Kernel"}, 2)
            connection.create_edge(1, 2, "WORKS_ON")
            paths = connection.traverse(1, depth=1)
            self.assertTrue(paths)
            self.assertEqual(node["node_id"], 1)

            object_id = connection.begin_blob_upload(
                "data.bin",
                "application/octet-stream",
            )
            connection.append_blob(object_id, b"hello")
            metadata = connection.finalize_blob(
                object_id,
                declared_size=5,
            )
            self.assertEqual(metadata["byte_length"], 5)
            self.assertEqual(
                connection.read_blob(object_id),
                b"hello",
            )
            graph = connection.list_graph()
            blobs = connection.list_blobs()
            self.assertEqual(len(graph["nodes"]), 2)
            self.assertEqual(len(graph["edges"]), 1)
            self.assertEqual(len(blobs["blobs"]), 1)
            connection.delete_blob(object_id)
            blobs = connection.list_blobs()
            self.assertEqual(blobs["blobs"][0]["state"], "deleted")

    def test_python_catalog_worker_and_shared_connection_contract(self):
        with THESAGRAConnection(
            host=self.host,
            port=self.port,
            username="test",
            password="secret",
        ) as connection:
            connection.execute(
                "CREATE TABLE people (id INTEGER PRIMARY KEY, name TEXT);"
            )
            catalog = connection.list_catalog()
            people = next(
                table for table in catalog["tables"]
                if table["name"] == "people"
            )
            self.assertEqual(people["columns"][0]["name"], "id")
            self.assertTrue(people["columns"][0]["primary_key"])
            connection.execute(
                "CREATE TABLE catalog_details ("
                "id INT PRIMARY KEY AUTO_INCREMENT, "
                "name VARCHAR(40) UNIQUE DEFAULT 'guest', "
                "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);"
            )
            details = next(
                table for table in connection.list_catalog()["tables"]
                if table["name"] == "catalog_details"
            )
            self.assertTrue(details["columns"][0]["auto_increment"])
            self.assertEqual(details["columns"][1]["max_length"], 40)
            self.assertTrue(details["columns"][1]["unique"])
            self.assertEqual(details["columns"][1]["default"], "guest")
            self.assertEqual(
                details["columns"][2]["default"],
                "CURRENT_TIMESTAMP",
            )

            task = connection.enqueue_task("integrity_check")
            status = connection.get_worker_status()
            self.assertIn(
                task["task_id"],
                [item["task_id"] for item in status["tasks"]],
            )

            with ThreadPoolExecutor(max_workers=3) as executor:
                results = list(executor.map(
                    lambda operation: operation(),
                    (
                        lambda: connection.execute(
                            "SELECT id FROM people;"
                        ).fetchall(),
                        connection.list_catalog,
                        connection.get_worker_status,
                    ),
                ))
            self.assertEqual(results[0], [])
            self.assertIn(
                "people",
                [table["name"] for table in results[1]["tables"]],
            )
            self.assertIn("tasks", results[2])


if __name__ == "__main__":
    unittest.main()
