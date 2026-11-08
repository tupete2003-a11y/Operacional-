import unittest
from unittest.mock import call, patch

from app.social_workflow import generate_social_workflow


class SocialWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.payload = {
            "objective": "Gerar pedidos de orçamento para manutenção de ar-condicionado",
            "platforms": ["Instagram", "TikTok"],
            "content_types": ["sales_banner", "video"],
        }

    @patch("app.social_workflow.time.sleep")
    @patch("app.social_workflow.store.create_approval")
    @patch("app.social_workflow.store.save_task")
    @patch("app.social_workflow.store.list_tasks", return_value=[])
    @patch("app.social_workflow.ask_agent", side_effect=[
        "Ideias", "Conteúdo", "Calendário",
        "STATUS: APROVADO\nRevisão completa",
        "STATUS: APROVADO\nSupervisão final"
    ])
    def test_runs_all_five_bots_and_requires_human_approval(
        self, ask_agent, list_tasks, save_task, create_approval, sleep
    ):
        result = generate_social_workflow(self.payload)

        self.assertEqual(result["status"], "DRAFT_REVIEW")
        self.assertEqual(
            [stage["bot_id"] for stage in result["stages"]],
            ["BOT_02", "BOT_03", "BOT_01", "BOT_04", "BOT_05"],
        )
        self.assertTrue(result["approval_required"])
        self.assertFalse(result["publishing_enabled"])
        self.assertEqual(ask_agent.call_count, 5)
        create_approval.assert_called_once()
        self.assertTrue(result["quality_gate"]["status"] == "READY_FOR_HUMAN_REVIEW")
        self.assertEqual(result["outputs"]["BOT_04"], "STATUS: APROVADO\nRevisão completa")
        self.assertEqual(result["outputs"]["BOT_05"], "STATUS: APROVADO\nSupervisão final")

    @patch("app.social_workflow.time.sleep")
    @patch("app.social_workflow.store.create_approval")
    @patch("app.social_workflow.store.save_task")
    @patch("app.social_workflow.store.list_tasks", return_value=[])
    @patch("app.social_workflow.ask_agent", side_effect=["Ideias", RuntimeError("provider unavailable")])
    def test_failure_is_saved_and_stops_the_remaining_bots(
        self, ask_agent, list_tasks, save_task, create_approval, sleep
    ):
        with self.assertRaisesRegex(RuntimeError, "BOT_03"):
            generate_social_workflow(self.payload)

        failed_task = save_task.call_args_list[-1].args[0]
        self.assertEqual(failed_task["status"], "FAILED")
        self.assertEqual(failed_task["result"]["failed_stage"], "BOT_03")
        self.assertFalse(failed_task["result"]["approval_required"])
        self.assertEqual(ask_agent.call_count, 2)
        create_approval.assert_not_called()


    @patch("app.social_workflow.time.sleep")
    @patch("app.social_workflow.store.create_approval")
    @patch("app.social_workflow.store.save_task")
    @patch("app.social_workflow.store.list_tasks", return_value=[])
    @patch("app.social_workflow.ask_agent", side_effect=[
        "Ideias", "Conteúdo", "Calendário",
        "STATUS: BLOQUEADO\nPromessa sem comprovação",
        "STATUS: BLOQUEADO\nSupervisão mantém o bloqueio"
    ])
    def test_quality_gate_blocks_when_bot04_or_bot05_blocks(
        self, ask_agent, list_tasks, save_task, create_approval, sleep
    ):
        result = generate_social_workflow(self.payload)

        self.assertEqual(result["quality_gate"]["status"], "BLOCKED")
        self.assertEqual(result["quality_gate"]["bot04_review"], "BLOCKED")
        self.assertEqual(result["quality_gate"]["bot05_supervision"], "BLOCKED")
        self.assertFalse(result["publishing_enabled"])
        self.assertTrue(result["approval_required"])

    @patch("app.social_workflow.store.save_task")
    @patch("app.social_workflow.store.list_tasks", return_value=[])
    @patch("app.social_workflow.ask_agent")
    def test_rejects_unknown_platform_before_calling_provider(
        self, ask_agent, list_tasks, save_task
    ):
        invalid_payload = dict(self.payload, platforms=["UnknownNetwork"])

        with self.assertRaisesRegex(ValueError, "Plataformas não suportadas"):
            generate_social_workflow(invalid_payload)

        ask_agent.assert_not_called()
        save_task.assert_not_called()


if __name__ == "__main__":
    unittest.main()
