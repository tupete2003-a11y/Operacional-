import unittest

from app import model_studio, model_studio_media, store
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

    def test_unknown_platform_is_rejected(self):
        with self.assertRaises(ValueError):
            model_studio.create_production_plan({
                "objective": "Criar foto em ambiente externo",
                "reference_id": "reference-approved-01",
                "platform": "YouTube",
            })


if __name__ == "__main__":
    unittest.main()
