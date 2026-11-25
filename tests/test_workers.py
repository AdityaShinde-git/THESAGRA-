import os
import tempfile
import time
import unittest
import gc

from thesagra import (
    DatabaseFile,
    RelationalEngine,
    backup_database,
    integrity_check,
    restore_database,
)
from thesagra.workers import TaskQueue, Worker


class WorkerAndOperationsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.directory.name, "phase9.db")
        self.database = DatabaseFile.create(self.path)
        self.engine = RelationalEngine(self.database)

    def tearDown(self):
        gc.collect()
        time.sleep(0.05)
        self.directory.cleanup()

    def wait_for_task(self, worker, task_id, timeout=3):
        deadline = time.time() + timeout
        while time.time() < deadline:
            task = worker.queue.get(task_id)
            if task["state"] in ("completed", "dead"):
                return task
            time.sleep(0.02)
        return worker.queue.get(task_id)

    def test_queue_idempotency_and_integrity_task(self):
        queue = TaskQueue(self.path)
        first = queue.enqueue(
            "integrity_check",
            {},
            idempotency_key="same-task",
        )
        duplicate = queue.enqueue(
            "integrity_check",
            {"different": True},
            idempotency_key="same-task",
        )
        self.assertEqual(first, duplicate)

        worker = Worker(self.engine)
        worker.start()
        completed = self.wait_for_task(worker, first)
        worker.stop()
        self.assertEqual(completed["state"], "completed")

    def test_worker_retries_unknown_task(self):
        worker = Worker(self.engine)
        worker.start()
        task_id = worker.queue.enqueue(
            "unknown_task",
            {},
            max_attempts=2,
        )
        completed = self.wait_for_task(worker, task_id)
        worker.stop()
        self.assertEqual(completed["state"], "dead")
        self.assertGreaterEqual(completed["attempts"], 2)

    def test_blob_reconcile_task(self):
        object_id = self.engine.begin_blob_upload("deleted.bin")
        self.engine.append_blob_chunk(object_id, b"content")
        self.engine.finalize_blob(object_id)
        self.engine.delete_blob(object_id)

        worker = Worker(self.engine)
        worker.start()
        task_id = worker.queue.enqueue("blob_reconcile")
        completed = self.wait_for_task(worker, task_id)
        worker.stop()
        self.assertEqual(completed["state"], "completed")

    def test_backup_integrity_and_restore(self):
        self.engine.execute(
            __import__(
                "thesagra.query.parser",
                fromlist=["parse"],
            ).parse(
                "CREATE TABLE users (id INTEGER PRIMARY KEY);"
            )
        )
        integrity = integrity_check(self.path)
        self.assertEqual(integrity["issues"], [])

        backup = os.path.join(self.directory.name, "backup.zip")
        backup_database(self.path, backup)
        restored = os.path.join(self.directory.name, "restored.db")
        restore_database(backup, restored)
        restored_database = DatabaseFile.open(restored)
        self.assertGreaterEqual(restored_database.page_count(), 2)


if __name__ == "__main__":
    unittest.main()
