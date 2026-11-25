import os
import socket
import tempfile
import threading
import unittest
import random
import json
import base64
from urllib.request import Request, urlopen

from thesagra import DatabaseFile, RelationalEngine, THESAGRAConnection
from thesagra.query.parser import (
    ParseError,
    parse,
    split_sql_statements,
)
from thesagra.server.server import THESAGRAServer
from thesagra.web import THESAGRAWebServer
from thesagra.security import hash_password, verify_password, FailureThrottle


class HardeningTests(unittest.TestCase):
    def test_modern_gui_module_builds(self):
        import thesagra.gui
        self.assertTrue(
            hasattr(thesagra.gui, "THESAGRAGui")
        )

    def test_sql_script_splitting_and_blob_file_extensions(self):
        from thesagra.gui import (
            _blob_extension,
            _blob_save_dialog_options,
        )

        script = (
            "-- header; ignored\n"
            "SELECT 'left;right'; /* ignored; */\n"
            "SELECT 2; -- trailing comment\n"
        )
        self.assertEqual(
            split_sql_statements(script),
            ["SELECT 'left;right'", "SELECT 2"],
        )
        self.assertEqual(
            _blob_extension("annual-report", "application/pdf"),
            ".pdf",
        )
        self.assertEqual(
            _blob_extension("annual-report.pdf", "application/pdf"),
            ".pdf",
        )
        save_options = _blob_save_dialog_options(
            "annual-report",
            "application/pdf",
        )
        self.assertEqual(save_options["initialfile"], "annual-report")
        self.assertEqual(save_options["defaultextension"], ".pdf")

    def test_pdf_page_can_be_rendered_for_blob_preview(self):
        import pypdfium2 as pdfium
        from thesagra.gui import _render_pdf_page

        output = bytearray(b"%PDF-1.4\n")
        objects = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            (
                b"<< /Type /Page /Parent 2 0 R "
                b"/MediaBox [0 0 100 120] /Resources << >> >>"
            ),
        ]
        offsets = [0]
        for object_number, content in enumerate(objects, 1):
            offsets.append(len(output))
            output.extend(
                f"{object_number} 0 obj\n".encode("ascii")
                + content
                + b"\nendobj\n"
            )
        xref_offset = len(output)
        output.extend(b"xref\n0 4\n0000000000 65535 f \n")
        for offset in offsets[1:]:
            output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
        output.extend(
            (
                f"trailer\n<< /Size 4 /Root 1 0 R >>\n"
                f"startxref\n{xref_offset}\n%%EOF\n"
            ).encode("ascii")
        )
        pdf = pdfium.PdfDocument(bytes(output))
        try:
            page_image = _render_pdf_page(pdf, 0, scale=1)
            self.assertEqual(page_image.size, (100, 120))
        finally:
            pdf.close()

    def test_password_hash_and_verification(self):
        encoded = hash_password("change-me")
        self.assertTrue(verify_password("change-me", encoded))
        self.assertFalse(verify_password("wrong", encoded))

    def test_failure_throttle(self):
        throttle = FailureThrottle(
            max_failures=3,
            window_seconds=60,
            lock_seconds=60,
        )
        self.assertFalse(throttle.blocked("127.0.0.1"))
        throttle.record_failure("127.0.0.1")
        throttle.record_failure("127.0.0.1")
        self.assertTrue(throttle.record_failure("127.0.0.1"))
        self.assertTrue(throttle.blocked("127.0.0.1"))
        throttle.record_success("127.0.0.1")
        self.assertFalse(throttle.blocked("127.0.0.1"))

    def test_malformed_sql_fuzz_smoke(self):
        engine = RelationalEngine(
            DatabaseFile.create(
                os.path.join(
                    tempfile.mkdtemp(),
                    "fuzz.db",
                )
            )
        )
        alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789(),;*='<>"
        random.seed(1)
        for _ in range(300):
            sql = "".join(
                random.choice(alphabet)
                for _ in range(random.randint(0, 80))
            )
            try:
                statement = parse(sql)
                engine.execute(statement)
            except (ParseError, Exception):
                pass

    def test_multiple_connections_can_query(self):
        directory = tempfile.TemporaryDirectory()
        path = os.path.join(directory.name, "load.db")
        server = THESAGRAServer(
            path,
            host="127.0.0.1",
            port=0,
            username="test",
            password="secret",
        )
        thread = threading.Thread(
            target=server.serve_forever,
            daemon=True,
        )
        thread.start()
        host, port = server.server_address
        with THESAGRAConnection(
            host=host,
            port=port,
            username="test",
            password="secret",
        ) as setup:
            setup.execute(
                "CREATE TABLE people (id INTEGER PRIMARY KEY, name TEXT);"
            )

        errors = []

        def worker(index):
            try:
                with THESAGRAConnection(
                    host=host,
                    port=port,
                    username="test",
                    password="secret",
                ) as connection:
                    cursor = connection.execute(
                        "SELECT * FROM people;"
                        if index % 2 == 0
                        else "EXPLAIN SELECT * FROM people;"
                    )
                    cursor.fetchall()
            except Exception as exc:
                errors.append(str(exc))

        threads = [
            threading.Thread(target=worker, args=(index,))
            for index in range(8)
        ]
        for item in threads:
            item.start()
        for item in threads:
            item.join(timeout=5)

        server.shutdown()
        server.worker.stop()
        server.server_close()
        thread.join(timeout=2)
        directory.cleanup()
        self.assertEqual(errors, [])

    def test_web_gui_status_query_blob_download(self):
        directory = tempfile.TemporaryDirectory()
        path = os.path.join(directory.name, "web.db")
        server = THESAGRAWebServer(
            path,
            host="127.0.0.1",
            port=0,
            username="test",
            password="secret",
        )
        thread = threading.Thread(
            target=server.serve_forever,
            daemon=True,
        )
        thread.start()
        host, port = server.server_address
        credentials = base64.b64encode(
            b"test:secret"
        ).decode("ascii")

        status_request = Request(
            f"http://{host}:{port}/api/status",
            headers={"Authorization": f"Basic {credentials}"},
        )
        with urlopen(status_request, timeout=5) as response:
            status = json.loads(response.read().decode("utf-8"))
        self.assertTrue(status["ok"])

        query_request = Request(
            f"http://{host}:{port}/api/query",
            data=json.dumps({
                "sql": "CREATE TABLE people "
                       "(id INTEGER PRIMARY KEY, name TEXT);",
            }).encode("utf-8"),
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(query_request, timeout=5) as response:
            query = json.loads(response.read().decode("utf-8"))
        self.assertTrue(query["ok"])

        begin_request = Request(
            f"http://{host}:{port}/api/blob/begin",
            data=json.dumps({
                "name": "test.bin",
                "mime_type": "application/octet-stream",
                "metadata": {},
                "max_size": 5,
            }).encode("utf-8"),
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(begin_request, timeout=5) as response:
            begun = json.loads(response.read().decode("utf-8"))
        object_id = begun["object_id"]

        append_request = Request(
            f"http://{host}:{port}/api/blob/append",
            data=json.dumps({
                "object_id": object_id,
                "data": base64.b64encode(b"hello").decode("ascii"),
            }).encode("utf-8"),
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(append_request, timeout=5) as response:
            appended = json.loads(response.read().decode("utf-8"))
        self.assertTrue(appended["ok"])

        finalize_request = Request(
            f"http://{host}:{port}/api/blob/finalize",
            data=json.dumps({
                "object_id": object_id,
                "declared_size": 5,
            }).encode("utf-8"),
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(finalize_request, timeout=5) as response:
            finalized = json.loads(response.read().decode("utf-8"))
        self.assertTrue(finalized["ok"])

        download_request = Request(
            f"http://{host}:{port}/api/blob/download?id={object_id}",
            headers={"Authorization": f"Basic {credentials}"},
        )
        with urlopen(download_request, timeout=5) as response:
            downloaded = response.read()
        self.assertEqual(downloaded, b"hello")

        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        directory.cleanup()


if __name__ == "__main__":
    unittest.main()
