"""
QA Suggestion & Next-Question Tests
====================================
Validates that suggestions actually match QA entries,
next-questions resolve to real answers, and everything
makes sense from a user perspective.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.qa import (
    answer_bank, suggestion_bank, qa_bank,
    module_banks, next_questions_bank,
)
from backend.qa.engine import resolve_query, get_autocomplete


class TestSuggestionsResolve(unittest.TestCase):
    """Every suggestion, when typed by the user, should match a QA entry."""

    def test_01_suggestion_text_resolves_to_answer(self):
        """Using a suggestion's text as a query should produce an answer."""
        bad = []
        for s in suggestion_bank:
            result = resolve_query(s["text"])
            if result["type"] == "noMatch":
                bad.append(s["text"])
        self.assertFalse(
            bad,
            f"Suggestions that don't resolve to any answer: {bad}"
        )

    def test_02_suggestion_appears_in_autocomplete_for_full_text(self):
        """Each suggestion should appear when you type its full text."""
        bad = []
        for s in suggestion_bank:
            # Use the full suggestion text — should always match itself
            results = get_autocomplete(s["text"], limit=20)
            result_texts = [r["text"] for r in results]
            if s["text"] not in result_texts:
                bad.append(s["text"])
        self.assertFalse(
            bad,
            f"Suggestions not found in autocomplete for their own full text: {bad}"
        )


class TestNextQuestionsResolve(unittest.TestCase):
    """Every next-question, when typed, should resolve to an answer."""

    def test_03_next_questions_resolve_to_answer(self):
        """Using a next-question as a query should produce an answer or followUp."""
        bad = []
        for aid, nqs in next_questions_bank.items():
            for q in nqs:
                result = resolve_query(q)
                if result["type"] == "noMatch":
                    bad.append((aid, q))
        self.assertFalse(
            bad,
            f"Next questions that don't resolve to any answer: {bad}"
        )

    def test_04_next_questions_dont_resolve_to_same_answer(self):
        """A next-question should NOT loop back to the same answer it came from."""
        bad = []
        for aid, nqs in next_questions_bank.items():
            for q in nqs:
                result = resolve_query(q)
                if result.get("answerId") == aid:
                    bad.append((aid, q))
        self.assertFalse(
            bad,
            f"Next questions that loop back to the same answer (circular): {bad}"
        )

    def test_05_next_questions_are_diverse(self):
        """The 3 next-questions for an answer should resolve to different answers."""
        bad = []
        for aid, nqs in next_questions_bank.items():
            resolved_ids = []
            for q in nqs:
                result = resolve_query(q)
                rid = result.get("answerId")
                if rid:
                    resolved_ids.append(rid)
            # Check for duplicates among resolved answer IDs
            if len(resolved_ids) != len(set(resolved_ids)):
                bad.append((aid, resolved_ids))
        self.assertFalse(
            bad,
            f"Next questions that resolve to the same answer (redundant): {bad}"
        )


class TestModuleScopedSuggestions(unittest.TestCase):
    """Module-scoped suggestions should only match within their module."""

    def test_06_module_suggestions_resolve_within_module(self):
        """Each module's suggestions should resolve when scoped to that module."""
        bad = []
        for slug, bank in module_banks.items():
            for s in bank.get("suggestions", []):
                result = resolve_query(s["text"], module_slug=slug)
                if result["type"] == "noMatch":
                    bad.append((slug, s["text"]))
        self.assertFalse(
            bad,
            f"Module suggestions that don't resolve in their own scope: {bad}"
        )


class TestNextQuestionsScopedToModule(unittest.TestCase):
    """Module next-questions should resolve somewhere (global or scoped)."""

    def test_07_module_next_questions_resolve_globally(self):
        """Each module's next-questions should produce answers globally.
        Cross-module references are intentional (e.g. 'Tell me about Stratos'
        from a Copilot module), so we check global resolution, not scoped."""
        bad = []
        for slug, bank in module_banks.items():
            nqs = bank.get("next_questions", {})
            for aid, questions in nqs.items():
                for q in questions:
                    result = resolve_query(q)  # global scope
                    if result["type"] == "noMatch":
                        bad.append((slug, aid, q))
        self.assertFalse(
            bad,
            f"Module next-questions that don't resolve globally: {bad}"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
