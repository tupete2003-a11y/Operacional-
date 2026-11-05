import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import store


class StorePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "automa_x_test.db"
        self.db_patch = patch.object(store, "DB_PATH", self.db_path)
        self.db_patch.start()
        store.init_db()

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_task_survives_new_connection(self):
        task = {
            "id": "task-persistence-test",
            "request": "Validar persistência local",
            "status": "DRAFT_REVIEW",
            "plan": {"selected_agents": ["BOT_05", "BOT_02", "BOT_03", "BOT_04", "BOT_01"]},
            "result": {"approval_required": True},
            "created_at": store.now(),
        }
        store.save_task(task)

        # get_task opens a fresh SQLite connection, proving committed data is readable.
        loaded = store.get_task(task["id"])
        self.assertEqual(loaded["status"], "DRAFT_REVIEW")
        self.assertEqual(loaded["plan"]["selected_agents"], task["plan"]["selected_agents"])
        self.assertTrue(loaded["result"]["approval_required"])

    def test_approval_create_list_and_decision(self):
        store.create_approval("approval-persistence-test", "task-persistence-test", "Review test")
        listed = store.list_approvals()
        self.assertTrue(any(row["id"] == "approval-persistence-test" and row["status"] == "PENDING" for row in listed))

        self.assertTrue(store.set_approval("approval-persistence-test", "APPROVED"))
        refreshed = {row["id"]: row for row in store.list_approvals()}
        self.assertEqual(refreshed["approval-persistence-test"]["status"], "APPROVED")


if __name__ == "__main__":
    unittest.main()
