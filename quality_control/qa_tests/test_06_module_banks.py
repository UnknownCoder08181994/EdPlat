"""
QA Module Bank Segregation Tests
=================================
Validates that module banks are properly isolated,
each module has the right data, and scoped queries
don't leak across module boundaries.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.qa import (
    answer_bank, module_banks, answer_module_map,
    next_questions_bank, video_bank,
)
from backend.qa.engine import resolve_query


class TestModuleBankStructure(unittest.TestCase):
    """Each module bank must have all required keys."""

    REQUIRED_KEYS = ["answers", "suggestions", "qa_entries"]

    def test_01_all_module_banks_have_required_keys(self):
        """Every module bank must have answers, suggestions, and qa_entries."""
        bad = []
        for slug, bank in module_banks.items():
            for key in self.REQUIRED_KEYS:
                if key not in bank:
                    bad.append((slug, f"missing '{key}'"))
        self.assertFalse(bad, f"Module banks missing required keys: {bad}")

    def test_02_module_bank_answers_are_dicts(self):
        """Module bank answers must be dicts."""
        bad = []
        for slug, bank in module_banks.items():
            if not isinstance(bank.get("answers"), dict):
                bad.append((slug, type(bank.get("answers")).__name__))
        self.assertFalse(bad, f"Module bank answers not dicts: {bad}")

    def test_03_module_bank_qa_entries_are_lists(self):
        """Module bank qa_entries must be lists."""
        bad = []
        for slug, bank in module_banks.items():
            if not isinstance(bank.get("qa_entries"), list):
                bad.append((slug, type(bank.get("qa_entries")).__name__))
        self.assertFalse(bad, f"Module bank qa_entries not lists: {bad}")

    def test_04_module_bank_suggestions_are_lists(self):
        """Module bank suggestions must be lists."""
        bad = []
        for slug, bank in module_banks.items():
            if not isinstance(bank.get("suggestions"), list):
                bad.append((slug, type(bank.get("suggestions")).__name__))
        self.assertFalse(bad, f"Module bank suggestions not lists: {bad}")

    def test_05_module_banks_are_nonempty(self):
        """Each module bank must have at least one answer and one QA entry."""
        bad = []
        for slug, bank in module_banks.items():
            if len(bank.get("answers", {})) == 0:
                bad.append((slug, "no answers"))
            if len(bank.get("qa_entries", [])) == 0:
                bad.append((slug, "no qa_entries"))
            if len(bank.get("suggestions", [])) == 0:
                bad.append((slug, "no suggestions"))
        self.assertFalse(bad, f"Empty module banks: {bad}")


class TestModuleBankIsolation(unittest.TestCase):
    """Module-scoped queries must NOT leak across modules."""

    def test_06_module_answers_use_consistent_category_prefix(self):
        """All answer IDs within a module bank should share the same category prefix."""
        bad = []
        for slug, bank in module_banks.items():
            answers = list(bank.get("answers", {}).keys())
            if not answers:
                continue
            # All answers in a bank should share the same first prefix segment
            prefixes = set(aid.split("-")[0] for aid in answers)
            if len(prefixes) > 1:
                bad.append((slug, f"mixed prefixes: {prefixes}"))
        self.assertFalse(
            bad,
            f"Module banks with mixed category prefixes in answer IDs: {bad}"
        )

    def test_07_module_qa_entries_only_reference_own_answers(self):
        """QA entries in a module bank should only reference that module's answers."""
        bad = []
        for slug, bank in module_banks.items():
            own_answers = set(bank.get("answers", {}).keys())
            for idx, entry in enumerate(bank.get("qa_entries", [])):
                aid = entry.get("answer")
                if aid and aid not in own_answers:
                    bad.append((slug, idx, aid))
                # Check follow-up options too
                for opt in entry.get("followUp", {}).get("options", []):
                    faid = opt.get("answerId")
                    if faid and faid not in own_answers:
                        bad.append((slug, idx, f"followUp:{faid}"))
        self.assertFalse(
            bad,
            f"Module QA entries referencing answers outside their module: {bad}"
        )

    def test_08_scoped_query_returns_module_answer(self):
        """A scoped query should return an answer from the correct module."""
        for slug, bank in module_banks.items():
            # Use the first suggestion as a test query
            suggestions = bank.get("suggestions", [])
            if not suggestions:
                continue
            query = suggestions[0]["text"]
            result = resolve_query(query, module_slug=slug)
            if result["type"] == "answer":
                own_answers = set(bank.get("answers", {}).keys())
                self.assertIn(
                    result["answerId"], own_answers,
                    f"Scoped query for '{slug}' returned answer from wrong module: "
                    f"'{result['answerId']}'"
                )


class TestAnswerModuleMap(unittest.TestCase):
    """The answer_module_map should correctly map module answers to their slugs."""

    def test_09_all_module_answers_in_map(self):
        """Every module bank answer should appear in answer_module_map."""
        missing = []
        for slug, bank in module_banks.items():
            for aid in bank.get("answers", {}):
                if aid not in answer_module_map:
                    missing.append((slug, aid))
        self.assertFalse(
            missing,
            f"Module answers missing from answer_module_map: {missing}"
        )

    def test_10_map_points_to_correct_module(self):
        """Each answer_module_map entry should point to the right slug."""
        bad = []
        for slug, bank in module_banks.items():
            for aid in bank.get("answers", {}):
                mapped = answer_module_map.get(aid, {})
                if mapped.get("slug") != slug:
                    bad.append((aid, f"expected={slug}", f"got={mapped.get('slug')}"))
        self.assertFalse(bad, f"answer_module_map points to wrong module: {bad}")

    def test_11_general_answers_not_in_module_map(self):
        """General category answers should NOT be in the module map."""
        bad = []
        for aid in answer_bank:
            if aid.startswith("general-") and aid in answer_module_map:
                bad.append(aid)
        self.assertFalse(
            bad,
            f"General answers incorrectly in answer_module_map: {bad}"
        )


class TestModuleNextQuestions(unittest.TestCase):
    """Module-scoped next-questions must stay within module boundaries."""

    def test_12_module_next_question_keys_match_module_answers(self):
        """Next-question keys in a module bank must be that module's answer IDs."""
        bad = []
        for slug, bank in module_banks.items():
            nqs = bank.get("next_questions", {})
            own_answers = set(bank.get("answers", {}).keys())
            for aid in nqs:
                if aid not in own_answers:
                    bad.append((slug, aid))
        self.assertFalse(
            bad,
            f"Module next-question keys not in module's own answers: {bad}"
        )


class TestGlobalBankContainsAll(unittest.TestCase):
    """The global banks should be the union of all category/module banks."""

    def test_13_all_module_answers_in_global_bank(self):
        """Every module bank answer must also exist in the global answer_bank."""
        missing = []
        for slug, bank in module_banks.items():
            for aid, text in bank.get("answers", {}).items():
                if aid not in answer_bank:
                    missing.append((slug, aid))
        self.assertFalse(
            missing,
            f"Module answers missing from global answer_bank: {missing}"
        )

    def test_14_global_bank_has_general_answers(self):
        """The global bank must contain general category answers."""
        general_ids = [aid for aid in answer_bank if aid.startswith("general-")]
        self.assertGreater(
            len(general_ids), 0,
            "No general category answers found in global answer_bank"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
