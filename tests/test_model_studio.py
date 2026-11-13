import unittest
from unittest.mock import patch

from app import model_studio, model_studio_media, model_studio_orchestrator, store
from PIL import Image
import io


class ModelStudioTests(unittest.TestCase):
    def test_five_specialized_bots_are_registered(self):
        self.assertEqual(len(model_studio.MODEL_STUDIO_BOTS), 5)
        self.assertEqual(
            [bot["id"] for bot in model_studio.MODEL_STUDIO_BOTS],
            ["BOT_01", "BOT_02", "BOT_03", "BOT_04", "BOT_05"],
        )

    def test_dashboard_keeps_generation_and_publishing_disabled(self):
        status = model_studio.dashboard()
        self.assertEqual(status["project"], "AUTOMA X — MODEL STUDIO")
        self.assertFalse(status["image_generation"]["generation_enabled"])
        self.assertFalse(status["publishing"]["enabled"])
        self.assertIn("configured", status["chat"])
        self.assertFalse(status["chat"]["verified"])

    def test_plan_requires_reference(self):
        with self.assertRaises(ValueError):
            model_studio.create_production_plan({"objective": "Criar foto realista"})

    def test_plan_is_not_a_generation(self):
        plan = model_studio.create_production_plan({
            "objective": "Criar foto em ambiente externo",
            "reference_id": "reference-approved-01",
            "platform": "Instagram",
        })
        self.assertEqual(plan["status"], "PLANNED_REFERENCE_REQUIRED")
        self.assertFalse(plan["generation"]["started"])
        self.assertFalse(plan["publishing"]["started"])


    def test_reference_image_is_normalized_and_quality_checked(self):
        buffer = io.BytesIO()
        Image.new("RGB", (900, 900), (120, 130, 140)).save(buffer, format="PNG")
        normalized, mime, width, height = model_studio_media._inspect_and_normalize(buffer.getvalue())
        self.assertEqual(mime, "image/jpeg")
        self.assertEqual((width, height), (900, 900))
        self.assertEqual(model_studio_media._quality_report(normalized)["identity_consistency"], "NOT_AUTOMATICALLY_VERIFIED")

    def test_unsupported_image_is_rejected(self):
        with self.assertRaises(model_studio_media.ModelStudioError):
            model_studio_media._inspect_and_normalize(b"not an image")


    def test_media_tables_initialize_with_review_state(self):
        store.init_db()
        with store.connect() as conn:
            rows = conn.execute("PRAGMA table_info(model_generated_images)").fetchall()
        columns = {row["name"] for row in rows}
        self.assertIn("encrypted_data", columns)
        self.assertIn("review_status", columns)
        self.assertIn("review_note", columns)

    @patch("app.llm.ask_agent")
    def test_chat_uses_master_operational_and_recent_context(self, mocked_ask):
        mocked_ask.return_value = "Vamos organizar a próxima produção."
        history = [{"role": "user", "content": "Quero fotos naturais."}]
        reply = model_studio.chat_with_master("Planeje a próxima cena.", history)
        self.assertEqual(reply, "Vamos organizar a próxima produção.")
        agent, prompt = mocked_ask.call_args.args
        self.assertEqual(agent["id"], "BOT_05")
        self.assertEqual(agent["name"], "Master Operational")
        self.assertIn("Quero fotos naturais.", prompt)
        self.assertIn("Planeje a próxima cena.", prompt)

    def test_chat_rejects_empty_message(self):
        with self.assertRaises(ValueError):
            model_studio.chat_with_master(" ")

    def test_unknown_platform_is_rejected(self):
        with self.assertRaises(ValueError):
            model_studio.create_production_plan({
                "objective": "Criar foto em ambiente externo",
                "reference_id": "reference-approved-01",
                "platform": "YouTube",
            })


    def test_executor_tables_are_persistent(self):
        store.init_db()
        with store.connect() as conn:
            runs = conn.execute("PRAGMA table_info(agent_runs)").fetchall()
            steps = conn.execute("PRAGMA table_info(agent_run_steps)").fetchall()
        self.assertIn("status", {row["name"] for row in runs})
        self.assertIn("attempt", {row["name"] for row in steps})
        self.assertIn("output_json", {row["name"] for row in steps})

    @patch("app.model_studio_orchestrator.model_studio_media.reference_status")
    @patch("app.model_studio_orchestrator.ask_agent")
    def test_bot05_executes_planning_steps_then_pauses_for_paid_approval(self, mocked_ask, mocked_reference):
        store.init_db()
        mocked_reference.return_value = {"registered": True, "reference_id": "reference-test"}
        mocked_ask.return_value = "Briefing concluído."
        run = model_studio_orchestrator.create_run(
            "Criar fotografia natural em um café", "group", "photorealistic"
        )
        model_studio_orchestrator.process_run(run["id"])
        current = model_studio_orchestrator.get_run(run["id"])
        self.assertEqual(current["status"], "WAITING_APPROVAL")
        self.assertEqual([step["status"] for step in current["steps"][:2]], ["SUCCEEDED", "SUCCEEDED"])
        self.assertEqual(current["steps"][2]["status"], "WAITING_APPROVAL")
        self.assertFalse(current["publishing"]["enabled"])
        self.assertEqual(mocked_ask.call_count, 2)

    @patch("app.model_studio_orchestrator.model_studio_media.reference_status")
    @patch("app.model_studio_orchestrator.ask_agent")
    def test_rejecting_paid_generation_stops_run_without_image_call(self, mocked_ask, mocked_reference):
        store.init_db()
        mocked_reference.return_value = {"registered": True, "reference_id": "reference-test"}
        mocked_ask.return_value = "Etapa concluída."
        run = model_studio_orchestrator.create_run(
            "Criar fotografia natural em um jardim", "group", "photorealistic"
        )
        model_studio_orchestrator.process_run(run["id"])
        rejected = model_studio_orchestrator.approve_generation(run["id"], "REJECT")
        self.assertEqual(rejected["status"], "REJECTED")
        self.assertEqual(rejected["steps"][2]["status"], "SKIPPED")


if __name__ == "__main__":
    unittest.main()
