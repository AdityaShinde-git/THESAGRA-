import threading
import time
import traceback

from .task_queue import TaskQueue


class WorkerError(Exception):
    pass


class Worker:
    def __init__(self, engine, poll_interval=0.05, engine_lock=None):
        self.engine = engine
        self.queue = TaskQueue(engine.database.path)
        self.engine_lock = engine_lock or threading.RLock()
        self.poll_interval = poll_interval
        self.running = False
        self.thread = None
        self.metrics = {
            "tasks_completed": 0,
            "tasks_failed": 0,
            "tasks_claimed": 0,
        }

    def start(self):
        if self.running:
            return
        self.queue.recover_interrupted()
        self.running = True
        self.thread = threading.Thread(
            target=self._loop,
            name="thesagra-worker",
            daemon=True,
        )
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread is not None:
            self.thread.join(timeout=2)

    def _loop(self):
        while self.running:
            task = self.queue.claim()
            if task is None:
                time.sleep(self.poll_interval)
                continue
            self.metrics["tasks_claimed"] += 1
            try:
                with self.engine_lock:
                    result = self.execute_task(task)
                self.queue.complete(task["task_id"], result)
                self.metrics["tasks_completed"] += 1
            except Exception as exc:
                self.queue.fail(task["task_id"], f"{exc}\n{traceback.format_exc()}")
                self.metrics["tasks_failed"] += 1

    def execute_task(self, task):
        import json

        payload = json.loads(task["payload"])
        task_type = task["task_type"]
        if task_type == "blob_reconcile":
            cleaned = self.engine.reconcile_blobs()
            return {"cleaned_object_ids": cleaned}
        if task_type == "integrity_check":
            issues = []
            for table_name, table in self.engine.catalog.tables.items():
                try:
                    self.engine.database.read_records(table.page_id)
                except Exception as exc:
                    issues.append({"table": table_name, "error": str(exc)})
            return {"issues": issues}
        if task_type == "graph_integrity_check":
            issues = []
            node_table = self.engine.catalog.get_table("__thesagra_nodes")
            edge_table = self.engine.catalog.get_table("__thesagra_edges")
            node_ids = {row[0] for row in self.engine.read_records(node_table.page_id)}
            for row in self.engine.read_records(edge_table.page_id):
                if row[1] not in node_ids or row[2] not in node_ids:
                    issues.append({"edge_id": row[0], "error": "missing endpoint"})
            return {"issues": issues}
        if task_type == "checkpoint":
            return {"status": "noop", "reason": "No checkpoint compaction configured"}
        raise WorkerError(f"Unknown task type: {task_type}")

    def status(self):
        tasks = self.queue.list()
        counts = {
            "queued": 0,
            "running": 0,
            "completed": 0,
            "failed": 0,
            "dead": 0,
        }
        for task in tasks:
            counts[task["state"]] = counts.get(task["state"], 0) + 1
        recent_tasks = [
            {
                key: task[key]
                for key in (
                    "task_id",
                    "task_type",
                    "state",
                    "attempts",
                    "max_attempts",
                    "created_at",
                    "started_at",
                    "completed_at",
                    "error",
                )
            }
            for task in tasks
        ]
        return {
            "running": self.running,
            "queue": counts,
            "metrics": dict(self.metrics),
            "tasks": recent_tasks,
        }
