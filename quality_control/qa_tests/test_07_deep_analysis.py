"""
QA Deep Text Analysis (Part 1)
===============================
Advanced duplicate/similarity detection using algorithmic NLP techniques.
No AI/ML — uses difflib, Porter stemming, TF-IDF cosine similarity,
n-gram overlap, and edit distance to catch near-duplicates and
poorly differentiated content.

Part 2 lives in test_07_deep_analysis_ext.py.
"""

import math
import re
import sys
import unittest
from collections import Counter
from difflib import SequenceMatcher
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.qa import (
    answer_bank, suggestion_bank, qa_bank,
    module_banks, next_questions_bank,
)

# ---------------------------------------------------------------------------
# Text utilities (no external libraries)
# ---------------------------------------------------------------------------

# Domain-specific proper nouns — expected to repeat across answers about the same topic.
# Filtered from n-gram overlap analysis to avoid false positives on product names.
DOMAIN_TERMS = frozenset({
    "github", "copilot", "epix", "codehub", "smartsdk", "stratos",
    "mytechhub", "techhub", "awmit", "awm", "jpmorgan",
    "vs", "code", "vscode", "cloud", "native", "enterprise",
    "oauth", "sid", "api",
})

# Common English stop words — filtered from analysis to focus on content words
STOP_WORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "shall",
    "should", "may", "might", "must", "can", "could", "to", "of", "in",
    "for", "on", "with", "at", "by", "from", "as", "into", "through",
    "during", "before", "after", "above", "below", "between", "out",
    "about", "up", "down", "off", "over", "under", "again", "further",
    "then", "once", "here", "there", "when", "where", "why", "how",
    "all", "each", "every", "both", "few", "more", "most", "other",
    "some", "such", "no", "nor", "not", "only", "own", "same", "so",
    "than", "too", "very", "just", "and", "but", "or", "if", "that",
    "this", "these", "those", "it", "its", "i", "me", "my", "we",
    "our", "you", "your", "he", "him", "his", "she", "her", "they",
    "them", "their", "what", "which", "who", "whom",
})


def strip_html(text: str) -> str:
    """Remove HTML tags from text."""
    return re.sub(r'<[^>]+>', '', text)


def tokenize(text: str) -> list[str]:
    """Lowercase, strip HTML/punctuation, split into words."""
    clean = strip_html(text).lower()
    clean = re.sub(r'[^\w\s]', '', clean)
    return clean.split()


def content_words(text: str) -> list[str]:
    """Tokenize and remove stop words — keeps only content-bearing words."""
    return [w for w in tokenize(text) if w not in STOP_WORDS]


def porter_stem(word: str) -> str:
    """Minimal Porter stemmer — strips common English suffixes.
    Not a full implementation but catches 80% of inflections."""
    w = word.lower()
    # Step 1: plurals and -ed/-ing
    if w.endswith("sses"):
        w = w[:-2]
    elif w.endswith("ies"):
        w = w[:-2]
    elif w.endswith("ss"):
        pass
    elif w.endswith("s") and len(w) > 3:
        w = w[:-1]

    if w.endswith("eed"):
        pass
    elif w.endswith("ed") and len(w) > 4:
        w = w[:-2]
    elif w.endswith("ing") and len(w) > 5:
        w = w[:-3]

    # Step 2: common derivational suffixes
    for suffix in ("ational", "ation", "ator"):
        if w.endswith(suffix) and len(w) - len(suffix) > 2:
            w = w[:-len(suffix)]
            break
    for suffix in ("fulness", "ously", "ively", "ment", "ness", "ible", "able", "ment"):
        if w.endswith(suffix) and len(w) - len(suffix) > 2:
            w = w[:-len(suffix)]
            break

    return w


def stemmed_words(text: str) -> list[str]:
    """Content words after Porter stemming."""
    return [porter_stem(w) for w in content_words(text)]


def bigrams(words: list[str]) -> list[str]:
    """Generate word bigrams from a token list."""
    return [f"{words[i]} {words[i+1]}" for i in range(len(words) - 1)]


def trigrams(words: list[str]) -> list[str]:
    """Generate word trigrams from a token list."""
    return [f"{words[i]} {words[i+1]} {words[i+2]}" for i in range(len(words) - 2)]


def cosine_similarity(vec1: Counter, vec2: Counter) -> float:
    """Cosine similarity between two word-frequency Counter vectors."""
    if not vec1 or not vec2:
        return 0.0
    shared = set(vec1.keys()) & set(vec2.keys())
    dot = sum(vec1[k] * vec2[k] for k in shared)
    mag1 = math.sqrt(sum(v * v for v in vec1.values()))
    mag2 = math.sqrt(sum(v * v for v in vec2.values()))
    if mag1 == 0 or mag2 == 0:
        return 0.0
    return dot / (mag1 * mag2)


def jaccard(set1: set, set2: set) -> float:
    """Jaccard index between two sets."""
    if not set1 and not set2:
        return 0.0
    return len(set1 & set2) / len(set1 | set2)


def tfidf_vectors(documents: dict[str, str]) -> dict[str, Counter]:
    """Build TF-IDF vectors for a collection of documents.
    Returns {doc_id: Counter(term: tfidf_weight)}."""
    # Term frequency per doc
    tf = {}
    for doc_id, text in documents.items():
        words = stemmed_words(text)
        total = len(words) if words else 1
        tf[doc_id] = {w: c / total for w, c in Counter(words).items()}

    # Document frequency
    n_docs = len(documents)
    df = Counter()
    for doc_id in tf:
        for term in tf[doc_id]:
            df[term] += 1

    # TF-IDF
    vectors = {}
    for doc_id in tf:
        vec = Counter()
        for term, freq in tf[doc_id].items():
            idf = math.log((n_docs + 1) / (df[term] + 1)) + 1
            vec[term] = freq * idf
        vectors[doc_id] = vec
    return vectors


# ---------------------------------------------------------------------------
# Tests (Part 1: tests 01–07)
# ---------------------------------------------------------------------------

class TestFuzzyDuplicateSuggestions(unittest.TestCase):
    """Detect near-duplicate suggestions using SequenceMatcher ratio."""

    def test_01_no_near_duplicate_suggestion_texts(self):
        """Two suggestions with >80% character-level similarity are too similar.
        Uses difflib.SequenceMatcher which computes longest common subsequence."""
        bad = []
        texts = [(i, s["text"]) for i, s in enumerate(suggestion_bank)]
        for (i, t1), (j, t2) in combinations(texts, 2):
            ratio = SequenceMatcher(None, t1.lower(), t2.lower()).ratio()
            if ratio > 0.80:
                bad.append((t1, t2, f"{ratio:.0%}"))
        self.assertFalse(
            bad,
            f"Near-duplicate suggestions (>80% SequenceMatcher): {bad}"
        )

    def test_02_no_near_duplicate_next_question_texts_globally(self):
        """Across ALL next-question lists, no two questions should be >80% similar."""
        all_nqs = []
        for aid, nqs in next_questions_bank.items():
            for q in nqs:
                all_nqs.append((aid, q))

        bad = []
        for (aid1, q1), (aid2, q2) in combinations(all_nqs, 2):
            ratio = SequenceMatcher(None, q1.lower(), q2.lower()).ratio()
            if ratio > 0.80:
                bad.append((aid1, q1, aid2, q2, f"{ratio:.0%}"))
        self.assertFalse(
            bad,
            f"Near-duplicate next questions (>80% SequenceMatcher): {bad}"
        )


class TestAnswerContentSimilarity(unittest.TestCase):
    """Detect answers that say the same thing using TF-IDF cosine similarity."""

    @classmethod
    def setUpClass(cls):
        """Build TF-IDF vectors for all answers once."""
        cls.vectors = tfidf_vectors(answer_bank)

    def test_03_no_high_cosine_similarity_answers_same_category(self):
        """Two answers in the same category with cosine >0.85 are too similar.
        TF-IDF cosine measures topical overlap weighted by term rarity."""
        # Group by category prefix
        categories = {}
        for aid in answer_bank:
            prefix = aid.split("-")[0]
            categories.setdefault(prefix, []).append(aid)

        bad = []
        for prefix, aids in categories.items():
            for a1, a2 in combinations(aids, 2):
                sim = cosine_similarity(self.vectors[a1], self.vectors[a2])
                if sim > 0.85:
                    bad.append((a1, a2, f"cosine={sim:.2f}"))
        self.assertFalse(
            bad,
            f"Same-category answers with >85% TF-IDF cosine similarity "
            f"(saying the same thing): {bad}"
        )

    def test_04_answers_in_same_module_are_differentiated(self):
        """Within each module, answer TF-IDF cosine must be <0.85.
        Module answers naturally share vocabulary about the same topic,
        so we use a slightly relaxed threshold vs cross-category (0.85)."""
        bad = []
        for slug, bank in module_banks.items():
            aids = list(bank.get("answers", {}).keys())
            for a1, a2 in combinations(aids, 2):
                if a1 in self.vectors and a2 in self.vectors:
                    sim = cosine_similarity(self.vectors[a1], self.vectors[a2])
                    if sim > 0.85:
                        bad.append((slug, a1, a2, f"cosine={sim:.2f}"))
        self.assertFalse(
            bad,
            f"Module answers with >85% TF-IDF cosine (need more differentiation): {bad}"
        )


class TestStemmedKeywordCoverage(unittest.TestCase):
    """After stemming, verify keyword-to-answer alignment is strong."""

    def test_05_stemmed_keywords_appear_in_answer(self):
        """After Porter stemming both keywords and answer text,
        at least one stemmed keyword should match a stemmed answer word.
        This catches inflection mismatches (e.g. 'installing' vs 'install')."""
        generic_stems = {porter_stem(w) for w in {
            "summarize", "summary", "video", "overview", "about",
            "example", "practical", "demo", "show", "recap",
            "what", "how", "introduction", "use", "case",
        }}
        bad = []
        for entry in qa_bank:
            aid = entry.get("answer")
            if not aid or aid not in answer_bank or aid.startswith("general-"):
                continue
            kw_stems = {porter_stem(k) for k in entry.get("keywords", [])} - generic_stems
            if not kw_stems:
                continue
            answer_stems = set(stemmed_words(answer_bank[aid]))
            if not kw_stems & answer_stems:
                bad.append((aid, sorted(kw_stems)[:5], "no stemmed overlap"))
        self.assertFalse(
            bad,
            f"After stemming, keywords have zero overlap with answer text: {bad}"
        )


class TestNgramOverlap(unittest.TestCase):
    """Use bigram/trigram overlap to detect answers sharing too many phrases."""

    def test_06_no_high_bigram_overlap_same_category(self):
        """Two answers sharing >50% of their bigrams are paraphrasing each other."""
        categories = {}
        for aid, text in answer_bank.items():
            prefix = aid.split("-")[0]
            categories.setdefault(prefix, []).append(aid)

        bad = []
        for prefix, aids in categories.items():
            bigram_sets = {}
            for aid in aids:
                words = content_words(answer_bank[aid])
                bigram_sets[aid] = set(bigrams(words))

            for a1, a2 in combinations(aids, 2):
                if not bigram_sets[a1] or not bigram_sets[a2]:
                    continue
                overlap = jaccard(bigram_sets[a1], bigram_sets[a2])
                if overlap > 0.50:
                    bad.append((a1, a2, f"bigram_jaccard={overlap:.0%}"))
        self.assertFalse(
            bad,
            f"Same-category answers with >50% bigram overlap (paraphrasing): {bad}"
        )

    def test_07_no_shared_long_phrases_between_answers(self):
        """Detect 4+ word phrases that appear in multiple answers verbatim.
        This catches copy-paste content across different answers.
        Excludes 4-grams containing domain-specific proper nouns (product names
        like 'GitHub Copilot Business Cloud Native') since those naturally repeat
        across answers about the same product/process."""
        # Build 4-gram sets per answer, filtering domain terms
        four_grams = {}
        for aid, text in answer_bank.items():
            words = content_words(text)
            grams = set()
            for i in range(len(words) - 3):
                gram_words = words[i:i+4]
                # Skip 4-grams that contain domain-specific proper nouns
                if any(w in DOMAIN_TERMS for w in gram_words):
                    continue
                grams.add(" ".join(gram_words))
            four_grams[aid] = grams

        def _section_prefix(aid: str) -> str:
            """Get the section prefix (all but last segment) for grouping."""
            parts = aid.rsplit("-", 1)
            return parts[0] if len(parts) > 1 else aid

        bad = []
        checked = set()
        for a1, a2 in combinations(answer_bank.keys(), 2):
            # Only check within same category
            if a1.split("-")[0] != a2.split("-")[0]:
                continue
            # Exempt answers in the same section (e.g., overview vs summary)
            # — they describe the same topic and naturally share process phrases
            if _section_prefix(a1) == _section_prefix(a2):
                continue
            shared = four_grams.get(a1, set()) & four_grams.get(a2, set())
            if len(shared) > 3:
                pair = tuple(sorted([a1, a2]))
                if pair not in checked:
                    checked.add(pair)
                    bad.append((a1, a2, f"{len(shared)} shared 4-grams",
                                list(shared)[:3]))
        self.assertFalse(
            bad,
            f"Answers sharing >3 verbatim 4-word phrases (copy-paste): {bad}"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
