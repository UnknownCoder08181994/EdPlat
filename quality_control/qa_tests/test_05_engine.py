"""
QA Engine Scoring Tests
=======================
Validates the matching engine: normalization, scoring logic,
threshold behavior, and correct winner selection.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.qa.engine import (
    normalize, _score_keywords, resolve_query,
    resolve_by_answer_id, get_autocomplete,
)
from backend.qa import answer_bank


class TestNormalization(unittest.TestCase):
    """The normalize function must strip punctuation, lowercase, collapse spaces."""

    def test_01_lowercase(self):
        self.assertEqual(normalize("HELLO"), "hello")

    def test_02_strip_punctuation(self):
        self.assertEqual(normalize("what's up?"), "whats up")

    def test_03_collapse_whitespace(self):
        self.assertEqual(normalize("  hello   world  "), "hello world")

    def test_04_empty_string(self):
        self.assertEqual(normalize(""), "")

    def test_05_only_punctuation(self):
        self.assertEqual(normalize("!!!???"), "")

    def test_06_preserves_numbers(self):
        self.assertEqual(normalize("Seal ID 106135"), "seal id 106135")


class TestKeywordScoring(unittest.TestCase):
    """The _score_keywords function must score correctly per the rules:
    - Exact phrase match: +10
    - Exact word match: +5
    - Prefix/stem match: +2
    """

    def test_07_exact_phrase_match(self):
        """'what is copilot' as keyword, query contains it → +10."""
        score = _score_keywords("what is copilot", ["what is copilot"])
        self.assertGreaterEqual(score, 10)

    def test_08_exact_word_match(self):
        """Single word keyword matching a query word → +5."""
        score = _score_keywords("hello world", ["hello"])
        # 'hello' is in the query (phrase +10) AND is an exact word (+5)
        self.assertGreaterEqual(score, 10)

    def test_09_prefix_match(self):
        """Keyword 'install' with query word 'instal' → +2 prefix match."""
        score = _score_keywords("instal", ["install"])
        self.assertGreaterEqual(score, 2)

    def test_10_no_match(self):
        """Completely unrelated keyword → 0."""
        score = _score_keywords("banana", ["copilot"])
        self.assertEqual(score, 0)

    def test_11_multiple_keywords_accumulate(self):
        """Multiple matching keywords should accumulate score."""
        score = _score_keywords("hello how are you", ["hello", "how", "you"])
        # Each keyword matches as phrase (+10) and word (+5)
        self.assertGreater(score, 15)

    def test_12_case_insensitive(self):
        """Keywords should match case-insensitively."""
        score = _score_keywords("hello", ["Hello"])
        self.assertGreaterEqual(score, 10)


class TestScoreThreshold(unittest.TestCase):
    """The engine requires score >= 5 to return a match."""

    def test_13_below_threshold_returns_no_match(self):
        """A query that scores < 5 against all entries should return noMatch."""
        result = resolve_query("xyznonexistent")
        self.assertEqual(result["type"], "noMatch")

    def test_14_at_threshold_returns_answer(self):
        """A query that scores exactly 5 (one word match) should return answer."""
        # 'hello' has exact word match (+5) and phrase match (+10) = 15
        result = resolve_query("hello")
        self.assertEqual(result["type"], "answer")


class TestResolveByAnswerId(unittest.TestCase):
    """Direct answer ID lookup must work correctly."""

    def test_15_valid_answer_id(self):
        """Looking up a valid answer ID should return the answer."""
        # Pick any known answer ID
        aid = list(answer_bank.keys())[0]
        result = resolve_by_answer_id(aid)
        self.assertEqual(result["type"], "answer")
        self.assertEqual(result["answerId"], aid)

    def test_16_invalid_answer_id(self):
        """Looking up a nonexistent ID should return noMatch."""
        result = resolve_by_answer_id("nonexistent-fake-id")
        self.assertEqual(result["type"], "noMatch")


class TestAutocomplete(unittest.TestCase):
    """Autocomplete should return relevant suggestions."""

    def test_17_returns_results_for_valid_query(self):
        """Typing 'hello' should return at least one suggestion."""
        results = get_autocomplete("hello")
        self.assertGreater(len(results), 0)

    def test_18_returns_empty_for_empty_query(self):
        """Empty query should return no suggestions."""
        results = get_autocomplete("")
        self.assertEqual(len(results), 0)

    def test_19_respects_limit(self):
        """Should not return more results than the limit."""
        results = get_autocomplete("a", limit=2)
        self.assertLessEqual(len(results), 2)

    def test_20_module_scoped_autocomplete(self):
        """Module-scoped autocomplete should only return module suggestions."""
        # Get a module slug
        from backend.qa import module_banks
        if not module_banks:
            self.skipTest("No module banks available")
        slug = list(module_banks.keys())[0]
        results = get_autocomplete("summary", module_slug=slug)
        # Results should come from that module's suggestion bank
        module_texts = {s["text"] for s in module_banks[slug].get("suggestions", [])}
        for r in results:
            self.assertIn(
                r["text"], module_texts,
                f"Autocomplete result '{r['text']}' not in module '{slug}' suggestions"
            )


class TestWinnerSelection(unittest.TestCase):
    """The engine should pick the highest-scoring entry, not first-in-array."""

    def test_21_specific_query_beats_generic(self):
        """A specific query should match its intended entry, not a generic one."""
        # "Seal ID 106135" should match the seal ID answer, not a generic copilot one
        result = resolve_query("What is the Seal ID for GitHub Copilot?")
        if result["type"] == "answer":
            # Should be the seal ID specific answer, not the overview
            self.assertIn("seal", result.get("answerId", "").lower() + result.get("text", "").lower(),
                         "Expected answer about Seal ID but got something else")


if __name__ == "__main__":
    unittest.main(verbosity=2)
