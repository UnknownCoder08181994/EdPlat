"""
Q&A engine behavior and edge-case diagnostics.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.qa import module_banks  # noqa: E402
from backend.qa.engine import (  # noqa: E402
    _build_answer,
    _score_keywords,
    get_autocomplete,
    normalize,
    resolve_by_answer_id,
    resolve_query,
)


class TestQaEngineBehavior(unittest.TestCase):
    """Deterministic matching and robustness tests."""

    def test_01_normalize_lowercases_and_strips_punctuation(self):
        self.assertEqual(normalize("What's UP??"), "whats up")

    def test_02_normalize_preserves_numbers(self):
        self.assertEqual(normalize("Seal ID 106135"), "seal id 106135")

    def test_03_score_keywords_exact_phrase_has_high_weight(self):
        score = _score_keywords("what is copilot", ["what is copilot"])
        self.assertGreaterEqual(score, 10)

    def test_04_score_keywords_word_match_and_prefix_match(self):
        score = _score_keywords("instal", ["install"])
        self.assertGreaterEqual(score, 2)

    def test_05_resolve_query_hello_returns_answer(self):
        result = resolve_query("hello")
        self.assertEqual(result.get("type"), "answer")
        self.assertEqual(result.get("answerId"), "general-hello")

    def test_06_resolve_query_nonsense_returns_no_match(self):
        result = resolve_query("purple elephant moon")
        self.assertEqual(result, {"type": "noMatch"})

    def test_07_resolve_query_empty_returns_no_match(self):
        result = resolve_query("   ")
        self.assertEqual(result, {"type": "noMatch"})

    def test_08_resolve_query_module_scope_uses_module_bank(self):
        result = resolve_query("seal id", module_slug="copilot-basics")
        self.assertEqual(result.get("type"), "answer")
        self.assertIn(result.get("answerId"), module_banks["copilot-basics"]["answers"])

    def test_09_resolve_query_unknown_module_slug_falls_back_global(self):
        result = resolve_query("hello", module_slug="does-not-exist")
        self.assertEqual(result.get("type"), "answer")
        self.assertEqual(result.get("answerId"), "general-hello")

    def test_10_pending_followup_matches_option_before_main_qa(self):
        pending = {
            "options": [
                {"label": "Hello", "keywords": ["hello"], "answerId": "general-hello"},
                {"label": "Help", "keywords": ["help"], "answerId": "general-help"},
            ],
        }
        result = resolve_query("hello", pending_follow_up=pending)
        self.assertEqual(result.get("type"), "answer")
        self.assertEqual(result.get("answerId"), "general-hello")

    def test_11_build_answer_global_for_module_answer_has_module_ref(self):
        module_answer_id = next(iter(module_banks["copilot-basics"]["answers"]))
        text = module_banks["copilot-basics"]["answers"][module_answer_id]
        payload = _build_answer(module_answer_id, text, module_slug=None)
        self.assertIn("moduleRef", payload)

    def test_12_build_answer_module_scope_omits_module_ref(self):
        module_answer_id = next(iter(module_banks["copilot-basics"]["answers"]))
        text = module_banks["copilot-basics"]["answers"][module_answer_id]
        payload = _build_answer(module_answer_id, text, module_slug="copilot-basics")
        self.assertNotIn("moduleRef", payload)

    def test_13_resolve_by_answer_id_invalid_returns_no_match(self):
        result = resolve_by_answer_id("not-real-answer-id")
        self.assertEqual(result, {"type": "noMatch"})

    def test_14_get_autocomplete_respects_limit(self):
        results = get_autocomplete("what", limit=2)
        self.assertLessEqual(len(results), 2)

    def test_15_get_autocomplete_module_scope_subsets_module_suggestions(self):
        slug = "copilot-basics"
        results = get_autocomplete("copilot", module_slug=slug, limit=10)
        allowed = {s["text"] for s in module_banks[slug]["suggestions"]}
        for item in results:
            self.assertIn(item["text"], allowed)

    def test_16_resolve_query_none_input_should_not_crash(self):
        try:
            result = resolve_query(None)  # type: ignore[arg-type]
        except Exception as exc:  # pragma: no cover
            self.fail(f"resolve_query(None) raised {type(exc).__name__}: {exc}")
        self.assertEqual(result.get("type"), "noMatch")

    def test_17_get_autocomplete_none_input_should_not_crash(self):
        try:
            results = get_autocomplete(None)  # type: ignore[arg-type]
        except Exception as exc:  # pragma: no cover
            self.fail(f"get_autocomplete(None) raised {type(exc).__name__}: {exc}")
        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)

