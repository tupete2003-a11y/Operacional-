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

    @patch("app.social_workflow.store.create_approval")
    @patch("app.social_workflow.store.save_task")
    @patch("app.social_workflow.store.list_tasks", return_value=[])
    @patch("app.social_workflow.ask_agent", side_effect=[
        "Estratégia", "Ideias", "Conteúdo", "Revisão", "Calendário"
    ])
    def test_runs_all_five_bots_and_requires_human_approval(
        self, ask_agent, list_tasks, save_task, create_approval
    ):
        result = generate_social_workflow(self.payload)

        self.assertEqual(result["status"], "DRAFT_REVIEW")
        self.assertEqual(
            [stage["bot_id"] for stage in result["stages"]],
            ["BOT_05", "BOT_02", "BOT_03", "BOT_04", "BOT_01"],
        )
        self.assertTrue(result["approval_required"])
        self.assertFalse(result["publishing_enabled"])
        self.assertEqual(ask_agent.call_count, 5)
        create_approval.assert_called_once()
        self.assertEqual(result["outputs"]["BOT_04"], "Revisão")

    @patch("app.social_workflow.store.create_approval")
    @patch("app.social_workflow.store.save_task")
    @patch("app.social_workflow.store.list_tasks", return_value=[])
    @patch("app.social_workflow.ask_agent", side_effect=["Estratégia", RuntimeError("provider unavailable")])
    def test_failure_is_saved_and_stops_the_remaining_bots(
        self, ask_agent, list_tasks, save_task, create_approval
    ):
        with self.assertRaisesRegex(RuntimeError, "BOT_02"):
            generate_social_workflow(self.payload)

        failed_task = save_task.call_args_list[-1].args[0]
        self.assertEqual(failed_task["status"], "FAILED")
        self.assertEqual(failed_task["result"]["failed_stage"], "BOT_02")
        self.assertFalse(failed_task["result"]["approval_required"])
        self.assertEqual(ask_agent.call_count, 2)
        create_approval.assert_not_called()

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
