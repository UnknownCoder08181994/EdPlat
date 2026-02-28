"""
QA Structure Tests
==================
Validates that every QA data file exports the correct types,
required fields, and follows naming conventions.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.qa import (
    answer_bank, suggestion_bank, qa_bank,
    module_banks, video_bank, next_questions_bank,
)


class TestAnswerStructure(unittest.TestCase):
    """Every answer ID and value must follow the expected format."""

    def test_01_answer_ids_are_kebab_case(self):
        """All answer IDs must be lowercase kebab-dash strings."""
        bad = []
        for aid in answer_bank:
            if aid != aid.lower():
                bad.append((aid, "not lowercase"))
            if " " in aid:
                bad.append((aid, "contains spaces"))
            if "__" in aid or aid.startswith("-") or aid.endswith("-"):
                bad.append((aid, "malformed dashes"))
        self.assertFalse(bad, f"Bad answer IDs: {bad}")

    def test_02_answer_values_are_nonempty_strings(self):
        """Every answer must be a non-empty string."""
        bad = []
        for aid, text in answer_bank.items():
            if not isinstance(text, str):
                bad.append((aid, f"type={type(text).__name__}"))
            elif len(text.strip()) == 0:
                bad.append((aid, "empty string"))
        self.assertFalse(bad, f"Bad answer values: {bad}")

    def test_03_answer_values_only_safe_html(self):
        """Answers should only use <strong> and <br> tags, nothing else."""
        import re
        allowed_tags = {"strong", "/strong", "br", "br/", "br /"}
        bad = []
        for aid, text in answer_bank.items():
            tags = re.findall(r'<(/?\w[^>]*)>', text)
            for tag in tags:
                tag_name = tag.split()[0].strip("/").lower()
                if tag.lower().strip() not in allowed_tags and tag_name not in {"strong", "br"}:
                    bad.append((aid, f"disallowed tag: <{tag}>"))
        self.assertFalse(bad, f"Answers with disallowed HTML: {bad}")

    def test_04_answer_values_minimum_length(self):
        """Answers should be at least 20 characters (not one-word stubs)."""
        bad = []
        for aid, text in answer_bank.items():
            if len(text.strip()) < 20:
                bad.append((aid, f"only {len(text.strip())} chars"))
        self.assertFalse(bad, f"Answers too short: {bad}")


class TestQAEntryStructure(unittest.TestCase):
    """Each QA_ENTRY must have valid keywords and point to a real answer."""

    def test_05_entries_have_keywords_list(self):
        """Every QA entry must have a non-empty 'keywords' list of strings."""
        bad = []
        for idx, entry in enumerate(qa_bank):
            kw = entry.get("keywords")
            if not isinstance(kw, list) or len(kw) == 0:
                bad.append((idx, "missing or empty keywords"))
            elif not all(isinstance(k, str) for k in kw):
                bad.append((idx, "keywords contains non-string"))
        self.assertFalse(bad, f"Bad QA entry keywords: {bad}")

    def test_06_entries_have_answer_or_followup(self):
        """Every QA entry needs either 'answer' (str) or 'followUp' (dict)."""
        bad = []
        for idx, entry in enumerate(qa_bank):
            has_answer = "answer" in entry
            has_followup = "followUp" in entry
            if not has_answer and not has_followup:
                bad.append((idx, "missing both 'answer' and 'followUp'"))
            if has_answer and has_followup:
                bad.append((idx, "has both 'answer' and 'followUp'"))
        self.assertFalse(bad, f"Bad QA entry structure: {bad}")

    def test_07_answer_refs_exist_in_answer_bank(self):
        """Every QA entry 'answer' value must exist as a key in answer_bank."""
        bad = []
        for idx, entry in enumerate(qa_bank):
            aid = entry.get("answer")
            if aid and aid not in answer_bank:
                bad.append((idx, aid))
        self.assertFalse(bad, f"QA entries pointing to missing answers: {bad}")

    def test_08_followup_options_have_required_fields(self):
        """Follow-up entries must have question + options with label/keywords/answerId."""
        bad = []
        for idx, entry in enumerate(qa_bank):
            fu = entry.get("followUp")
            if not fu:
                continue
            if not isinstance(fu.get("question"), str) or len(fu["question"]) < 5:
                bad.append((idx, "missing or short followUp.question"))
            opts = fu.get("options", [])
            if len(opts) < 2:
                bad.append((idx, f"followUp needs 2+ options, got {len(opts)}"))
            for oi, opt in enumerate(opts):
                if not opt.get("label"):
                    bad.append((idx, f"option[{oi}] missing label"))
                if not opt.get("keywords") or not isinstance(opt["keywords"], list):
                    bad.append((idx, f"option[{oi}] missing keywords list"))
                aid = opt.get("answerId")
                if not aid:
                    bad.append((idx, f"option[{oi}] missing answerId"))
                elif aid not in answer_bank:
                    bad.append((idx, f"option[{oi}] answerId '{aid}' not in answer_bank"))
        self.assertFalse(bad, f"Bad follow-up entries: {bad}")

    def test_09_keywords_are_lowercase(self):
        """All keywords should be lowercase for consistent matching."""
        bad = []
        for idx, entry in enumerate(qa_bank):
            for kw in entry.get("keywords", []):
                if kw != kw.lower():
                    bad.append((idx, kw))
        self.assertFalse(bad, f"Keywords not lowercase: {bad}")


class TestSuggestionStructure(unittest.TestCase):
    """Each suggestion must have text and keywords."""

    def test_10_suggestions_have_text_and_keywords(self):
        """Every suggestion needs 'text' (str) and 'keywords' (list)."""
        bad = []
        for idx, s in enumerate(suggestion_bank):
            if not isinstance(s.get("text"), str) or len(s["text"]) < 3:
                bad.append((idx, "missing or short text"))
            kw = s.get("keywords")
            if not isinstance(kw, list) or len(kw) == 0:
                bad.append((idx, "missing or empty keywords"))
        self.assertFalse(bad, f"Bad suggestions: {bad}")

    def test_11_suggestion_keywords_are_lowercase(self):
        """Suggestion keywords should be lowercase."""
        bad = []
        for idx, s in enumerate(suggestion_bank):
            for kw in s.get("keywords", []):
                if kw != kw.lower():
                    bad.append((idx, s.get("text"), kw))
        self.assertFalse(bad, f"Suggestion keywords not lowercase: {bad}")


class TestNextQuestionsStructure(unittest.TestCase):
    """Next-question suggestions must reference valid answers and be well-formed."""

    def test_12_next_question_keys_exist_in_answers(self):
        """Every NEXT_QUESTIONS key must be a valid answer ID."""
        bad = []
        for aid in next_questions_bank:
            if aid not in answer_bank:
                bad.append(aid)
        self.assertFalse(bad, f"NEXT_QUESTIONS keys not in answer_bank: {bad}")

    def test_13_next_questions_are_lists_of_strings(self):
        """Each value must be a list of strings."""
        bad = []
        for aid, nqs in next_questions_bank.items():
            if not isinstance(nqs, list):
                bad.append((aid, f"type={type(nqs).__name__}"))
                continue
            for i, q in enumerate(nqs):
                if not isinstance(q, str) or len(q) < 5:
                    bad.append((aid, f"item[{i}] invalid"))
        self.assertFalse(bad, f"Bad next questions: {bad}")

    def test_14_next_questions_end_with_question_mark_or_action(self):
        """Next questions should be questions or action phrases (not random text)."""
        bad = []
        for aid, nqs in next_questions_bank.items():
            for q in nqs:
                q_stripped = q.strip()
                has_question_word = any(
                    q_stripped.lower().startswith(w)
                    for w in ["what", "how", "why", "where", "when", "which",
                              "can", "do", "is", "are", "will", "should",
                              "tell", "show", "explain", "summarize", "give",
                              "introduce", "walk", "list", "recap", "outline",
                              "guide", "explore", "dive", "tips", "describe"]
                )
                if not q_stripped.endswith("?") and not has_question_word:
                    bad.append((aid, q_stripped))
        self.assertFalse(
            bad,
            f"Next questions that aren't questions or action phrases: {bad}"
        )


class TestVideoStructure(unittest.TestCase):
    """Video metadata must have required fields and point to real answers."""

    def test_15_video_keys_exist_in_answers(self):
        """Every VIDEOS key must be a valid answer ID."""
        bad = []
        for aid in video_bank:
            if aid not in answer_bank:
                bad.append(aid)
        self.assertFalse(bad, f"Video keys not in answer_bank: {bad}")

    def test_16_video_entries_have_required_fields(self):
        """Each video must have 'src' and 'label'."""
        bad = []
        for aid, v in video_bank.items():
            if not isinstance(v.get("src"), str) or len(v["src"]) < 5:
                bad.append((aid, "missing or short src"))
            if not isinstance(v.get("label"), str) or len(v["label"]) < 5:
                bad.append((aid, "missing or short label"))
        self.assertFalse(bad, f"Bad video entries: {bad}")

    def test_17_video_files_exist_on_disk(self):
        """Every video src must point to an actual file."""
        missing = []
        for aid, v in video_bank.items():
            src = v.get("src", "")
            path = ROOT / "frontend" / "static" / "videos" / src
            if not path.exists():
                missing.append((aid, src))
        self.assertFalse(missing, f"Missing video files: {missing}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
