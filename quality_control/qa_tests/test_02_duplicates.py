"""
QA Duplicate & Similarity Tests
================================
Detects duplicate answer IDs, duplicate keywords across entries,
and entries that are too similar (would confuse the scoring engine).
"""

import sys
import unittest
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.qa import (
    answer_bank, suggestion_bank, qa_bank,
    module_banks, next_questions_bank,
)
from backend.qa.engine import _score_keywords, normalize


class TestNoDuplicateAnswerIDs(unittest.TestCase):
    """Answer IDs must be unique globally and within each module bank."""

    def test_01_no_duplicate_global_answer_ids(self):
        """The global answer_bank merge should have caught duplicates,
        but verify at test time too."""
        # answer_bank is a dict so duplicates would have been overwritten.
        # Instead, collect IDs from all category files and check.
        from backend.qa.general import ANSWERS as ga
        from backend.qa.copilot import ANSWERS as ca
        from backend.qa.smartsdk import ANSWERS as sa
        from backend.qa.stratos import ANSWERS as ta
        from backend.qa.prompting import ANSWERS as pa
        from backend.qa.fullstack import ANSWERS as fa

        all_ids = []
        for bank in [ga, ca, sa, ta, pa, fa]:
            all_ids.extend(bank.keys())

        # Also include auto-generated answers
        if "general-modules" in answer_bank:
            all_ids.append("general-modules")

        dupes = [aid for aid, count in Counter(all_ids).items() if count > 1]
        self.assertFalse(dupes, f"Duplicate answer IDs across categories: {dupes}")

    def test_02_no_duplicate_answer_ids_within_module_banks(self):
        """Within each module bank, answer IDs must be unique."""
        bad = []
        for slug, bank in module_banks.items():
            ids = list(bank.get("answers", {}).keys())
            dupes = [aid for aid, c in Counter(ids).items() if c > 1]
            if dupes:
                bad.append((slug, dupes))
        self.assertFalse(bad, f"Duplicate answer IDs within module banks: {bad}")


class TestNoDuplicateQAEntries(unittest.TestCase):
    """No two QA entries should point to the same answer ID."""

    def test_03_no_duplicate_answer_targets_in_global_bank(self):
        """Two QA entries pointing to the same answer create ambiguity."""
        targets = []
        for entry in qa_bank:
            aid = entry.get("answer")
            if aid:
                targets.append(aid)
        dupes = [aid for aid, c in Counter(targets).items() if c > 1]
        self.assertFalse(
            dupes,
            f"Multiple QA entries point to the same answer ID: {dupes}"
        )

    def test_04_no_duplicate_answer_targets_per_module(self):
        """Within each module bank, no two entries should target the same answer."""
        bad = []
        for slug, bank in module_banks.items():
            targets = []
            for entry in bank.get("qa_entries", []):
                aid = entry.get("answer")
                if aid:
                    targets.append(aid)
            dupes = [aid for aid, c in Counter(targets).items() if c > 1]
            if dupes:
                bad.append((slug, dupes))
        self.assertFalse(bad, f"Duplicate answer targets in module banks: {bad}")


class TestKeywordOverlap(unittest.TestCase):
    """Entries with high keyword overlap will compete and cause wrong matches."""

    def _keyword_overlap_ratio(self, kw1, kw2):
        """Return the Jaccard similarity of two keyword lists."""
        s1 = set(k.lower() for k in kw1)
        s2 = set(k.lower() for k in kw2)
        if not s1 or not s2:
            return 0.0
        return len(s1 & s2) / len(s1 | s2)

    def test_05_no_high_keyword_overlap_in_same_category(self):
        """Within the same category prefix, entries must not overlap >60%."""
        from itertools import combinations
        # Group entries by category prefix (first part of answer ID)
        categories = {}
        for entry in qa_bank:
            aid = entry.get("answer", "")
            prefix = aid.split("-")[0] if aid else "unknown"
            categories.setdefault(prefix, []).append(entry)

        bad = []
        for prefix, entries in categories.items():
            for e1, e2 in combinations(entries, 2):
                kw1 = e1.get("keywords", [])
                kw2 = e2.get("keywords", [])
                ratio = self._keyword_overlap_ratio(kw1, kw2)
                if ratio > 0.6:
                    a1 = e1.get("answer", "followUp")
                    a2 = e2.get("answer", "followUp")
                    bad.append((a1, a2, f"{ratio:.0%}"))
        self.assertFalse(
            bad,
            f"Same-category QA entries with >60% keyword overlap: {bad}"
        )

    def test_06_no_high_keyword_overlap_per_module(self):
        """Within each module bank, entries must not overlap >60%."""
        bad = []
        for slug, bank in module_banks.items():
            entries = bank.get("qa_entries", [])
            for i, e1 in enumerate(entries):
                for j, e2 in enumerate(entries):
                    if j <= i:
                        continue
                    kw1 = e1.get("keywords", [])
                    kw2 = e2.get("keywords", [])
                    ratio = self._keyword_overlap_ratio(kw1, kw2)
                    if ratio > 0.6:
                        a1 = e1.get("answer", "followUp")
                        a2 = e2.get("answer", "followUp")
                        bad.append((slug, a1, a2, f"{ratio:.0%}"))
        self.assertFalse(
            bad,
            f"Module entries with >60% keyword overlap: {bad}"
        )


class TestScoringCollisions(unittest.TestCase):
    """Simulate real queries and ensure the top-scoring entry wins clearly."""

    def _get_top_two_scores(self, query, entries):
        """Return (best_entry, best_score, second_score) for a query."""
        nq = normalize(query)
        scored = []
        for entry in entries:
            s = _score_keywords(nq, entry.get("keywords", []))
            scored.append((s, entry))
        scored.sort(key=lambda x: x[0], reverse=True)
        if len(scored) < 2:
            return scored[0] if scored else (None, 0, 0)
        best_score = scored[0][0]
        second_score = scored[1][0]
        best_entry = scored[0][1]
        return best_entry, best_score, second_score

    def test_07_no_tied_scores_for_suggestion_texts_per_module(self):
        """Within each module, suggestion text should produce a clear winner."""
        ties = []
        for slug, bank in module_banks.items():
            entries = bank.get("qa_entries", [])
            for s in bank.get("suggestions", []):
                query = s["text"]
                _, best, second = self._get_top_two_scores(query, entries)
                if best > 0 and best == second:
                    ties.append((slug, query, best))
        self.assertFalse(
            ties,
            f"Module suggestions that produce tied scores (ambiguous): {ties}"
        )

    def test_08_no_tied_scores_for_next_questions_per_module(self):
        """Within each module, next-questions should match clearly."""
        ties = []
        for slug, bank in module_banks.items():
            entries = bank.get("qa_entries", [])
            nqs = bank.get("next_questions", {})
            for aid, questions in nqs.items():
                for q in questions:
                    _, best, second = self._get_top_two_scores(q, entries)
                    if best > 0 and best == second:
                        ties.append((slug, aid, q, best))
        self.assertFalse(
            ties,
            f"Module next questions that produce tied scores: {ties}"
        )


class TestNoDuplicateSuggestions(unittest.TestCase):
    """Suggestion texts should be unique."""

    def test_09_no_duplicate_suggestion_text(self):
        """No two suggestions should have the same display text."""
        texts = [s["text"] for s in suggestion_bank]
        dupes = [t for t, c in Counter(texts).items() if c > 1]
        self.assertFalse(dupes, f"Duplicate suggestion texts: {dupes}")

    def test_10_no_duplicate_next_question_text_per_answer(self):
        """Within a single answer's next questions, no duplicates."""
        bad = []
        for aid, nqs in next_questions_bank.items():
            dupes = [q for q, c in Counter(nqs).items() if c > 1]
            if dupes:
                bad.append((aid, dupes))
        self.assertFalse(bad, f"Duplicate next questions per answer: {bad}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
