"""
QA Answer Quality Tests
=======================
Validates that answers are specific (not generic filler), make sense
for the topic they belong to, and give actionable feedback.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.qa import answer_bank, qa_bank, module_banks
from backend.qa.engine import resolve_query, normalize


class TestAnswerSpecificity(unittest.TestCase):
    """Answers must be specific and actionable, not generic fluff."""

    # Generic filler phrases that indicate a lazy answer
    GENERIC_PHRASES = [
        "this is a placeholder",
        "coming soon",
        "to be determined",
        "lorem ipsum",
        "todo",
        "tbd",
        "insert answer here",
        "work in progress",
    ]

    def test_01_no_placeholder_answers(self):
        """Answers must not contain placeholder or stub text."""
        bad = []
        for aid, text in answer_bank.items():
            text_lower = text.lower()
            for phrase in self.GENERIC_PHRASES:
                if phrase in text_lower:
                    bad.append((aid, f"contains '{phrase}'"))
        self.assertFalse(bad, f"Placeholder answers found: {bad}")

    def test_02_answers_have_substance(self):
        """Answers should have at least 3 words (not just "Yes" or "No")."""
        bad = []
        for aid, text in answer_bank.items():
            # Strip HTML for word count
            import re
            clean = re.sub(r'<[^>]+>', '', text)
            words = clean.split()
            if len(words) < 3:
                bad.append((aid, f"only {len(words)} words"))
        self.assertFalse(bad, f"Answers too thin: {bad}")

    def test_03_answer_id_matches_category_prefix(self):
        """Answer IDs should start with their category prefix."""
        valid_prefixes = [
            "general", "copilot", "smartsdk", "stratos",
            "prompting", "fullstack", "downloads",
        ]
        bad = []
        for aid in answer_bank:
            prefix = aid.split("-")[0]
            if prefix not in valid_prefixes:
                bad.append((aid, f"prefix '{prefix}' not in valid list"))
        self.assertFalse(bad, f"Answer IDs with invalid category prefix: {bad}")


class TestAnswerRelevanceToKeywords(unittest.TestCase):
    """The answer text should be relevant to the keywords that trigger it."""

    def test_04_answer_mentions_at_least_one_keyword(self):
        """The answer text should contain at least one of the triggering keywords.
        This catches mismatched answer<->keyword pairings.
        Exempts general category and broad-intent entries."""
        import re
        bad = []
        # Generic intent words that don't need to appear in the answer
        generic = {"summarize", "summary", "video", "overview", "about",
                   "example", "practical", "demo", "show", "recap",
                   "what", "how", "introduction", "use case"}
        for entry in qa_bank:
            aid = entry.get("answer")
            if not aid or aid not in answer_bank:
                continue
            if aid.startswith("general-"):
                continue
            keywords = entry.get("keywords", [])
            specific_kws = [kw for kw in keywords if kw.lower() not in generic]
            if not specific_kws:
                continue
            text_lower = re.sub(r'<[^>]+>', '', answer_bank[aid]).lower()
            found = any(kw.lower() in text_lower for kw in specific_kws)
            if not found:
                bad.append((aid, specific_kws[:5]))
        self.assertFalse(
            bad,
            f"Answers that don't mention any specific triggering keywords "
            f"(possible mismatch): {bad}"
        )


class TestNoMatchReturnsCleanly(unittest.TestCase):
    """Queries with no match should return noMatch, not crash or return wrong answers."""

    NONSENSE_QUERIES = [
        "asdfjkl",
        "zzzzzz",
        "12345678",
        "xylophone zebra",
        "purple elephant moon",
    ]

    def test_05_nonsense_queries_return_no_match(self):
        """Random gibberish should not match any QA entry."""
        bad = []
        for q in self.NONSENSE_QUERIES:
            result = resolve_query(q)
            if result["type"] != "noMatch":
                bad.append((q, result.get("answerId")))
        self.assertFalse(
            bad,
            f"Nonsense queries that incorrectly matched: {bad}"
        )

    def test_06_empty_query_returns_no_match(self):
        """Empty or whitespace-only queries must return noMatch."""
        for q in ["", "   ", "\n\t"]:
            result = resolve_query(q)
            self.assertEqual(
                result["type"], "noMatch",
                f"Empty query '{repr(q)}' should return noMatch"
            )


class TestAnswerConsistency(unittest.TestCase):
    """Cross-check answer content for internal consistency."""

    def test_07_no_broken_html_in_answers(self):
        """Check for unclosed <strong> tags."""
        import re
        bad = []
        for aid, text in answer_bank.items():
            opens = len(re.findall(r'<strong>', text, re.IGNORECASE))
            closes = len(re.findall(r'</strong>', text, re.IGNORECASE))
            if opens != closes:
                bad.append((aid, f"opens={opens}, closes={closes}"))
        self.assertFalse(bad, f"Answers with mismatched <strong> tags: {bad}")

    def test_08_no_double_spaces_in_answers(self):
        """Answers should not have double spaces (sloppy formatting)."""
        bad = []
        for aid, text in answer_bank.items():
            # Allow double newlines (paragraph breaks) but not double spaces inline
            lines = text.split("\n")
            for line in lines:
                if "  " in line.strip():
                    bad.append((aid, "double space in line"))
                    break
        self.assertFalse(bad, f"Answers with double spaces: {bad}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
