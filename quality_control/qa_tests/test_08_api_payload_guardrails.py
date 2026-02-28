"""
API payload guardrail checks focused on QA/chat behavior.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app  # noqa: E402
from backend.qa import module_banks  # noqa: E402


class TestApiPayloadGuardrails(unittest.TestCase):
    """Break-attempt tests for request payload handling and scope behavior."""

    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()

    def test_01_valid_chat_payload_returns_structured_response(self):
        response = self.client.post("/api/chat", json={"message": "hello"})
        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertIn(payload.get("type"), {"answer", "followUp", "noMatch"})

    def test_02_valid_resolve_payload_returns_structured_response(self):
        response = self.client.post("/api/chat/resolve", json={"answerId": "general-hello"})
        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertIn(payload.get("type"), {"answer", "noMatch"})

    def test_03_non_object_chat_payload_should_not_500(self):
        response = self.client.post("/api/chat", json=[])
        self.assertNotEqual(
            response.status_code,
            500,
            "Non-object JSON payload currently crashes /api/chat.",
        )

    def test_04_null_message_chat_payload_should_not_500(self):
        response = self.client.post("/api/chat", json={"message": None})
        self.assertNotEqual(
            response.status_code,
            500,
            "Null message currently crashes /api/chat.",
        )

    def test_05_non_object_resolve_payload_should_not_500(self):
        response = self.client.post("/api/chat/resolve", json=[])
        self.assertNotEqual(
            response.status_code,
            500,
            "Non-object JSON payload currently crashes /api/chat/resolve.",
        )

    def test_06_missing_message_returns_no_match(self):
        response = self.client.post("/api/chat", json={})
        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload, {"type": "noMatch"})

    def test_07_suggestions_empty_query_returns_empty_list(self):
        response = self.client.get("/api/suggestions", query_string={"q": ""})
        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload, [])

    def test_08_module_filtered_suggestions_are_module_local(self):
        slug = "copilot-basics"
        module_texts = {s["text"] for s in module_banks[slug].get("suggestions", [])}
        response = self.client.get("/api/suggestions", query_string={"q": "copilot", "module": slug})
        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        for item in payload:
            self.assertIn(item["text"], module_texts)

    def test_09_chips_endpoint_shape(self):
        response = self.client.get("/api/chips")
        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(payload, list)
        self.assertGreaterEqual(len(payload), 1)
        self.assertIn("label", payload[0])
        self.assertIn("icon", payload[0])

    def test_10_module_scope_query_resolves_within_module(self):
        response = self.client.post(
            "/api/chat",
            json={"message": "seal id", "moduleSlug": "copilot-basics"},
        )
        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload.get("type"), "answer")
        self.assertIn(payload.get("answerId"), module_banks["copilot-basics"]["answers"])

    def test_11_unknown_module_slug_falls_back_to_global(self):
        response = self.client.post(
            "/api/chat",
            json={"message": "hello", "moduleSlug": "not-real"},
        )
        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload.get("answerId"), "general-hello")


if __name__ == "__main__":
    unittest.main(verbosity=2)

