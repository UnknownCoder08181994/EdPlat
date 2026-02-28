"""
QA Deep Text Analysis (Part 2)
===============================
Continuation of test_07_deep_analysis.py — additional advanced
duplicate/similarity detection tests.

Tests in this file: 08–15
Covers: question phrasing diversity, keyword stem diversity,
score margin analysis, and answer readability.
"""

import re
import sys
import unittest
from collections import Counter
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Add qa_tests dir so we can import the sibling module directly
_QA_TESTS_DIR = str(Path(__file__).resolve().parent)
if _QA_TESTS_DIR not in sys.path:
    sys.path.insert(0, _QA_TESTS_DIR)

from backend.qa import (
    answer_bank, suggestion_bank, qa_bank,
    module_banks, next_questions_bank,
)

# Import shared text utilities from Part 1
from test_07_deep_analysis import (
    strip_html, content_words, porter_stem, stemmed_words, jaccard,
)


# ---------------------------------------------------------------------------
# Tests (Part 2: tests 08–15)
# ---------------------------------------------------------------------------

class TestQuestionPhrasingDiversity(unittest.TestCase):
    """Detect next-questions that ask the same thing with different words."""

    def _question_fingerprint(self, text: str) -> set[str]:
        """Create a stemmed content-word fingerprint for a question."""
        return set(stemmed_words(text))

    def test_08_next_questions_have_diverse_fingerprints(self):
        """The 3 next-questions for an answer should have distinct word fingerprints.
        Jaccard on stemmed content words must be <0.60 between any pair."""
        bad = []
        for aid, nqs in next_questions_bank.items():
            fps = [(q, self._question_fingerprint(q)) for q in nqs]
            for (q1, fp1), (q2, fp2) in combinations(fps, 2):
                sim = jaccard(fp1, fp2)
                if sim > 0.60:
                    bad.append((aid, q1, q2, f"stemmed_jaccard={sim:.0%}"))
        self.assertFalse(
            bad,
            f"Next questions with >60% stemmed word overlap "
            f"(asking the same thing differently): {bad}"
        )

    def test_09_suggestion_texts_have_diverse_fingerprints(self):
        """No two suggestions should have >60% stemmed content word overlap."""
        fps = [(s["text"], set(stemmed_words(s["text"])))
               for s in suggestion_bank]
        bad = []
        for (t1, fp1), (t2, fp2) in combinations(fps, 2):
            sim = jaccard(fp1, fp2)
            if sim > 0.60:
                bad.append((t1, t2, f"stemmed_jaccard={sim:.0%}"))
        self.assertFalse(
            bad,
            f"Suggestions with >60% stemmed word overlap: {bad}"
        )


class TestKeywordStemDiversity(unittest.TestCase):
    """After stemming, keywords within an entry should be diverse — not
    multiple inflections of the same root."""

    def test_10_no_redundant_stemmed_keywords(self):
        """Within a single QA entry, stemmed keywords should collapse to
        at least 60% unique stems. If 'install', 'installing', 'installed'
        are all keywords, they stem to the same thing and waste slots."""
        bad = []
        for idx, entry in enumerate(qa_bank):
            kws = entry.get("keywords", [])
            if len(kws) < 3:
                continue
            stems = [porter_stem(k) for k in kws]
            unique_ratio = len(set(stems)) / len(stems)
            if unique_ratio < 0.60:
                duped_stems = [s for s, c in Counter(stems).items() if c > 1]
                aid = entry.get("answer", f"entry[{idx}]")
                bad.append((aid, f"unique_ratio={unique_ratio:.0%}",
                            f"duplicate_stems={duped_stems}"))
        self.assertFalse(
            bad,
            f"QA entries with too many same-stem keywords (wasted slots): {bad}"
        )


class TestScoreMarginAnalysis(unittest.TestCase):
    """For every suggestion/next-question, verify the winning score has
    a healthy margin over the runner-up — thin margins cause flaky matches."""

    def _score_all(self, query: str, entries: list) -> list[tuple]:
        """Return sorted [(score, answer_id), ...] for a query."""
        from backend.qa.engine import _score_keywords, normalize
        nq = normalize(query)
        scored = []
        for entry in entries:
            s = _score_keywords(nq, entry.get("keywords", []))
            aid = entry.get("answer", "followUp")
            scored.append((s, aid))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored

    def test_11_suggestion_score_margin_at_least_20pct(self):
        """The winning entry should outscore the runner-up by at least 20%.
        Thin margins mean a slight keyword tweak could flip the winner."""
        thin = []
        for s in suggestion_bank:
            scored = self._score_all(s["text"], qa_bank)
            if len(scored) < 2:
                continue
            best, second = scored[0][0], scored[1][0]
            if best <= 0:
                continue
            margin = (best - second) / best
            if margin < 0.20 and second > 0:
                thin.append((s["text"], f"best={best}", f"second={second}",
                             f"margin={margin:.0%}", scored[0][1], scored[1][1]))
        self.assertFalse(
            thin,
            f"Suggestions with <20% score margin (fragile matches): {thin}"
        )

    def test_12_next_question_score_margin_at_least_10pct(self):
        """Next-questions need at least 10% margin to avoid wrong-answer risk.
        Same-category ties are exempt: if the top two entries share the same
        category prefix, a tie is acceptable (user gets a relevant answer
        either way, just a different facet of the same topic)."""
        thin = []
        for aid, nqs in next_questions_bank.items():
            for q in nqs:
                scored = self._score_all(q, qa_bank)
                if len(scored) < 2:
                    continue
                best, second = scored[0][0], scored[1][0]
                if best <= 0:
                    continue
                margin = (best - second) / best
                if margin < 0.10 and second > 0:
                    # Exempt same-category ties — both answers are about the same topic
                    cat1 = scored[0][1].split("-")[0]
                    cat2 = scored[1][1].split("-")[0]
                    if cat1 == cat2:
                        continue
                    thin.append((aid, q, f"best={best}", f"second={second}",
                                 f"margin={margin:.0%}"))
        self.assertFalse(
            thin,
            f"Next questions with <10% score margin (fragile matches): {thin}"
        )


class TestAnswerReadability(unittest.TestCase):
    """Basic readability checks — sentence structure, variety, clarity."""

    def test_13_answers_have_multiple_sentences(self):
        """Non-greeting answers should have at least 2 sentences for substance."""
        bad = []
        for aid, text in answer_bank.items():
            if aid.startswith("general-"):
                continue
            clean = strip_html(text)
            # Count sentence-ending punctuation
            sentences = re.split(r'[.!?]+', clean)
            sentences = [s.strip() for s in sentences if len(s.strip()) > 5]
            if len(sentences) < 2:
                bad.append((aid, f"only {len(sentences)} sentence(s)"))
        self.assertFalse(
            bad,
            f"Answers with fewer than 2 sentences (need more detail): {bad}"
        )

    def test_14_no_repeated_sentences_within_answer(self):
        """An answer should not repeat the same sentence verbatim."""
        bad = []
        for aid, text in answer_bank.items():
            clean = strip_html(text)
            sentences = re.split(r'[.!?]+', clean)
            sentences = [s.strip().lower() for s in sentences if len(s.strip()) > 10]
            dupes = [s for s, c in Counter(sentences).items() if c > 1]
            if dupes:
                bad.append((aid, dupes[0][:50]))
        self.assertFalse(
            bad,
            f"Answers with repeated sentences: {bad}"
        )

    def test_15_answer_vocabulary_richness(self):
        """Content word type-token ratio should be >0.30 — low ratio means
        the same words are repeated excessively."""
        bad = []
        for aid, text in answer_bank.items():
            words = content_words(text)
            if len(words) < 10:
                continue
            ttr = len(set(words)) / len(words)
            if ttr < 0.30:
                bad.append((aid, f"type_token_ratio={ttr:.2f}"))
        self.assertFalse(
            bad,
            f"Answers with low vocabulary richness (<30% unique content words): {bad}"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
