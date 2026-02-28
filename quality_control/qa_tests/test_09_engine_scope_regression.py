"""
Engine determinism and scope regression tests.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.qa import module_banks  # noqa: E402
from backend.qa.engine import (  # noqa: E402
    _score_keywords,
    get_autocomplete,
    normalize,
    resolve_query,
)


class TestEngineScopeRegression(unittest.TestCase):
    """Additional QA regression checks for deterministic matching behavior."""

    def test_01_same_query_repeated_is_deterministic(self):
        first = resolve_query("What is the Seal ID for GitHub Copilot?", module_slug="copilot-basics")
        second = resolve_query("What is the Seal ID for GitHub Copilot?", module_slug="copilot-basics")
        self.assertEqual(first, second)

    def test_02_threshold_sanity_low_signal_query_no_match(self):
        result = resolve_query("x")
        self.assertEqual(result, {"type": "noMatch"})

    def test_03_module_scope_prevents_cross_module_answer_ids(self):
        slug = "copilot-basics"
        own_answers = set(module_banks[slug]["answers"].keys())
        result = resolve_query("how do i request copilot access", module_slug=slug)
        if result.get("type") == "answer":
            self.assertIn(result.get("answerId"), own_answers)

    def test_04_module_scope_unknown_slug_uses_global_bank(self):
        result = resolve_query("hello", module_slug="missing-slug")
        self.assertEqual(result.get("type"), "answer")
        self.assertEqual(result.get("answerId"), "general-hello")

    def test_05_pending_followup_option_priority(self):
        pending = {
            "options": [
                {"label": "Option A", "keywords": ["hello"], "answerId": "general-hello"},
                {"label": "Option B", "keywords": ["help"], "answerId": "general-help"},
            ],
        }
        result = resolve_query("hello", pending_follow_up=pending)
        self.assertEqual(result.get("type"), "answer")
        self.assertEqual(result.get("answerId"), "general-hello")

    def test_06_normalize_keeps_expected_tokens(self):
        self.assertEqual(normalize("  Seal ID: 106135!! "), "seal id 106135")

    def test_07_score_keywords_accumulates_multiple_matches(self):
        score = _score_keywords("hello help", ["hello", "help"])
        self.assertGreaterEqual(score, 20)

    def test_08_autocomplete_empty_query_returns_none(self):
        self.assertEqual(get_autocomplete(""), [])

    def test_09_autocomplete_limit_is_enforced(self):
        results = get_autocomplete("what", limit=3)
        self.assertLessEqual(len(results), 3)

    def test_10_module_autocomplete_only_returns_module_texts(self):
        slug = "copilot-basics"
        module_texts = {s["text"] for s in module_banks[slug]["suggestions"]}
        results = get_autocomplete("copilot", module_slug=slug, limit=10)
        for row in results:
            self.assertIn(row["text"], module_texts)

    def test_11_nonsense_batch_queries_return_no_match(self):
        for query in ["asdfghjkl", "qwertyuiop", "1234567890", "purple elephant moon"]:
            with self.subTest(query=query):
                self.assertEqual(resolve_query(query), {"type": "noMatch"})


if __name__ == "__main__":
    unittest.main(verbosity=2)

