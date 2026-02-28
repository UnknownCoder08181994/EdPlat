"""
App route and API contract diagnostics.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app  # noqa: E402


class TestAppRoutesAndApiContracts(unittest.TestCase):
    """Flask route checks and break-attempt API probes."""

    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()

    def test_01_core_pages_respond_200(self):
        for route in ["/", "/modules", "/chat"]:
            with self.subTest(route=route):
                response = self.client.get(route)
                self.assertEqual(response.status_code, 200)

    def test_02_module_detail_valid_slug_responds_200(self):
        response = self.client.get("/modules/copilot-basics")
        self.assertEqual(response.status_code, 200)

    def test_03_module_detail_invalid_slug_responds_404(self):
        response = self.client.get("/modules/not-a-module")
        self.assertEqual(response.status_code, 404)

    def test_04_module_viewer_valid_section_responds_200(self):
        response = self.client.get("/modules/copilot-basics/onboarding")
        self.assertEqual(response.status_code, 200)

    def test_05_module_viewer_invalid_section_responds_404(self):
        response = self.client.get("/modules/copilot-basics/not-a-section")
        self.assertEqual(response.status_code, 404)

    def test_06_favicon_route_responds_204(self):
        response = self.client.get("/favicon.ico")
        self.assertEqual(response.status_code, 204)

    def test_07_chat_endpoint_hello_returns_answer(self):
        response = self.client.post("/api/chat", json={"message": "hello"})
        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload.get("type"), "answer")
        self.assertIn("answerId", payload)
        self.assertIn("text", payload)

    def test_08_chat_endpoint_empty_message_returns_no_match(self):
        response = self.client.post("/api/chat", json={"message": ""})
        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload, {"type": "noMatch"})

    def test_09_chat_resolve_roundtrip_by_answer_id(self):
        hello = self.client.post("/api/chat", json={"message": "hello"}).get_json()
        answer_id = hello["answerId"]
        resolved = self.client.post("/api/chat/resolve", json={"answerId": answer_id})
        payload = resolved.get_json()
        self.assertEqual(resolved.status_code, 200)
        self.assertEqual(payload.get("type"), "answer")
        self.assertEqual(payload.get("answerId"), answer_id)

    def test_10_chat_resolve_unknown_answer_returns_no_match(self):
        response = self.client.post("/api/chat/resolve", json={"answerId": "missing-id"})
        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload, {"type": "noMatch"})

    def test_11_suggestions_endpoint_returns_list_shape(self):
        response = self.client.get("/api/suggestions", query_string={"q": "hello"})
        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(payload, list)
        if payload:
            self.assertIn("text", payload[0])
            self.assertIn("keywords", payload[0])

    def test_12_chips_endpoint_returns_label_icon_pairs(self):
        response = self.client.get("/api/chips")
        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(payload, list)
        self.assertGreaterEqual(len(payload), 1)
        self.assertIn("label", payload[0])
        self.assertIn("icon", payload[0])

    def test_13_static_video_cache_header(self):
        response = self.client.get("/static/videos/galaxy.mp4")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers.get("Cache-Control"),
            "public, max-age=31536000, immutable",
        )

    def test_14_static_css_cache_header(self):
        response = self.client.get("/static/css/main.built.css")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("Cache-Control"), "public, max-age=3600")

    def test_15_non_object_chat_payload_should_not_500(self):
        response = self.client.post("/api/chat", json=[])
        self.assertNotEqual(
            response.status_code,
            500,
            "API should handle non-object JSON without server error.",
        )

    def test_16_none_message_should_not_500(self):
        response = self.client.post("/api/chat", json={"message": None})
        self.assertNotEqual(
            response.status_code,
            500,
            "API should handle null message defensively without server error.",
        )

    def test_17_non_object_resolve_payload_should_not_500(self):
        response = self.client.post("/api/chat/resolve", json=[])
        self.assertNotEqual(
            response.status_code,
            500,
            "Resolve endpoint should handle non-object JSON without server error.",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)

