import json
import unittest
from unittest.mock import patch

from app import supervisor


class SupervisorAuditTests(unittest.TestCase):
    @patch("app.supervisor.store.add_message")
    @patch("app.supervisor.store.list_approvals", return_value=[
        {"id": "a1", "status": "PENDING"}
    ])
    @patch("app.supervisor.store.list_tasks", return_value=[
        {"id": "t1", "status": "IN_PROGRESS"},
        {"id": "t2", "status": "DRAFT_REVIEW"},
    ])
    @patch("app.supervisor.store.backend", return_value="postgresql")
    @patch("app.supervisor.store.check_connection", return_value=True)
    @patch("app.supervisor.get_groq_api_key", return_value="configured-but-not-tested")
    def test_healthy_audit_records_verified_checks_without_claiming_ai_roundtrip(
        self, groq_key, db_check, db_backend, tasks, approvals, add_message
    ):
        report = supervisor.run_audit()

        self.assertEqual(report["status"], "HEALTHY")
        self.assertTrue(report["checks"]["database_connected"])
        self.assertEqual(report["checks"]["database_backend"], "postgresql")
        self.assertEqual(report["checks"]["registered_bot_count"], 5)
        self.assertEqual(report["checks"]["tasks_total"], 2)
        self.assertEqual(report["checks"]["tasks_in_progress"], 1)
        self.assertEqual(report["checks"]["approvals_pending"], 1)
        self.assertTrue(report["checks"]["groq_key_configured"])
        self.assertNotIn("groq_response_verified", report["checks"])
        self.assertFalse(report["safety"]["external_publication"])
        add_message.assert_called_once()
        self.assertEqual(add_message.call_args.args[0], "supervisor")
        persisted = json.loads(add_message.call_args.args[1])
        self.assertEqual(persisted["supervisor"], "AUTOMA_X_SUPERVISOR")

    @patch("app.supervisor.store.add_message")
    @patch("app.supervisor.store.list_approvals", return_value=[])
    @patch("app.supervisor.store.list_tasks", return_value=[])
    @patch("app.supervisor.store.backend", return_value="sqlite")
    @patch("app.supervisor.store.check_connection", side_effect=RuntimeError("db offline"))
    @patch("app.supervisor.get_groq_api_key", return_value="")
    def test_degraded_audit_reports_issues_without_exposing_exception_details(
        self, groq_key, db_check, db_backend, tasks, approvals, add_message
    ):
        report = supervisor.run_audit()

        self.assertEqual(report["status"], "ATTENTION")
        self.assertFalse(report["checks"]["database_connected"])
        self.assertEqual(report["checks"]["database_error_type"], "RuntimeError")
        self.assertIn("Armazenamento não é PostgreSQL.", report["issues"])
        self.assertIn("Credencial Groq não detectada; presença não comprova resposta real.", report["issues"])
        self.assertNotIn("db offline", json.dumps(report, ensure_ascii=False))
        self.assertFalse(report["safety"]["secrets_modified"])
        self.assertFalse(report["safety"]["data_deleted"])

    @patch("app.supervisor.store.get_messages", return_value=[
        {"role": "supervisor", "content": json.dumps({"timestamp": "2026-11-09T01:00:00+00:00", "status": "ATTENTION"})},
        {"role": "user", "content": "unrelated"},
        {"role": "supervisor", "content": json.dumps({"timestamp": "2026-11-09T02:00:00+00:00", "status": "HEALTHY"})},
    ])
    def test_status_returns_latest_persisted_audit_first(self, get_messages):
        status = supervisor.get_status()

        self.assertTrue(status["enabled"])
        self.assertEqual(status["last_audit"]["timestamp"], "2026-11-09T02:00:00+00:00")
        self.assertEqual(status["recent_audits"][0]["status"], "HEALTHY")
        self.assertEqual(status["mode"], "authorized_autonomous_read_only_audit")


if __name__ == "__main__":
    unittest.main()
