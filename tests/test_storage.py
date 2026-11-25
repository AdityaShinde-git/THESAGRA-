import os
import struct
import tempfile
import unittest

from thesagra import DatabaseFile
from thesagra.storage.page import PAGE_SIZE, PageError


class DatabaseFileTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.directory.name, "test.tsg")

    def tearDown(self):
        self.directory.cleanup()

    def test_records_persist_after_reopen(self):
        db = DatabaseFile.create(self.path)
        page_id = db.allocate_page()
        records = [
            (1, "Ada", True, None),
            (2, "Linus", False, 3.25),
            (3, "Grace", True, b"\x00\xff"),
        ]
        db.write_records(page_id, records)

        reopened = DatabaseFile.open(self.path)
        self.assertEqual(reopened.read_records(page_id), [tuple(row) for row in records])

    def test_empty_record_is_supported(self):
        db = DatabaseFile.create(self.path)
        page_id = db.allocate_page()
        db.write_records(page_id, [()])
        self.assertEqual(db.read_records(page_id), [()])

    def test_integer_range_is_checked_by_serialization(self):
        db = DatabaseFile.create(self.path)
        page_id = db.allocate_page()
        with self.assertRaises(struct.error):
            db.write_records(page_id, [(2 ** 63,)])

    def test_truncated_file_fails_safely(self):
        db = DatabaseFile.create(self.path)
        with open(self.path, "r+b") as file:
            file.truncate(PAGE_SIZE - 1)
        with self.assertRaises(PageError):
            DatabaseFile.open(self.path)

    def test_checksum_corruption_fails_safely(self):
        db = DatabaseFile.create(self.path)
        page_id = db.allocate_page()
        db.write_records(page_id, [(1, "Ada")])

        with open(self.path, "r+b") as file:
            file.seek(page_id * PAGE_SIZE + 24)
            file.write(b"\xff")

        reopened = DatabaseFile.open(self.path)
        with self.assertRaises(PageError):
            reopened.read_records(page_id)


if __name__ == "__main__":
    unittest.main()
