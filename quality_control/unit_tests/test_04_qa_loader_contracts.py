"""
Q&A loader integrity tests for merged and module-scoped banks.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.qa import (  # noqa: E402
    answer_bank,
    answer_module_map,
    module_banks,
    next_questions_bank,
    qa_bank,
    suggestion_bank,
    video_bank,
)


class TestQaLoaderContracts(unittest.TestCase):
    """Bank shape and cross-reference tests."""

    def test_01_global_banks_are_non_empty(self):
        self.assertGreaterEqual(len(answer_bank), 1)
        self.assertGreaterEqual(len(suggestion_bank), 1)
        self.assertGreaterEqual(len(qa_bank), 1)

    def test_02_expected_dynamic_general_modules_answer_exists(self):
        self.assertIn("general-modules", answer_bank)

    def test_03_every_qa_entry_has_answer_or_followup(self):
        bad = []
        for idx, entry in enumerate(qa_bank):
            has_answer = "answer" in entry
            has_fu = "followUp" in entry
            if has_answer == has_fu:
                bad.append(idx)
        self.assertFalse(bad, f"Bad answer/followUp shape in entries: {bad}")

    def test_04_global_answer_references_are_valid(self):
        bad = []
        for idx, entry in enumerate(qa_bank):
            aid = entry.get("answer")
            if aid and aid not in answer_bank:
                bad.append((idx, aid))
        self.assertFalse(bad, f"Global QA entries reference missing answers: {bad}")

    def test_05_global_followup_option_references_are_valid(self):
        bad = []
        for idx, entry in enumerate(qa_bank):
            for opt in entry.get("followUp", {}).get("options", []):
                aid = opt.get("answerId")
                if aid and aid not in answer_bank:
                    bad.append((idx, aid))
        self.assertFalse(bad, f"Global followUp options reference missing answers: {bad}")

    def test_06_module_banks_have_required_keys(self):
        required = {"answers", "suggestions", "qa_entries", "next_questions"}
        bad = []
        for slug, bank in module_banks.items():
            missing = required.difference(bank.keys())
            if missing:
                bad.append((slug, sorted(missing)))
        self.assertFalse(bad, f"Module banks missing required keys: {bad}")

    def test_07_module_banks_not_empty(self):
        bad = []
        for slug, bank in module_banks.items():
            if not bank.get("answers"):
                bad.append((slug, "answers"))
            if not bank.get("qa_entries"):
                bad.append((slug, "qa_entries"))
            if not bank.get("suggestions"):
                bad.append((slug, "suggestions"))
        self.assertFalse(bad, f"Module banks unexpectedly empty: {bad}")

    def test_08_module_qa_entries_reference_own_answers_only(self):
        bad = []
        for slug, bank in module_banks.items():
            own = set(bank.get("answers", {}).keys())
            for idx, entry in enumerate(bank.get("qa_entries", [])):
                aid = entry.get("answer")
                if aid and aid not in own:
                    bad.append((slug, idx, aid))
                for opt in entry.get("followUp", {}).get("options", []):
                    oid = opt.get("answerId")
                    if oid and oid not in own:
                        bad.append((slug, idx, f"followUp:{oid}"))
        self.assertFalse(bad, f"Module QA leakage: {bad}")

    def test_09_answer_module_map_covers_all_module_answers(self):
        missing = []
        for slug, bank in module_banks.items():
            for aid in bank.get("answers", {}):
                if aid not in answer_module_map:
                    missing.append((slug, aid))
        self.assertFalse(missing, f"Missing answer_module_map entries: {missing}")

    def test_10_answer_module_map_has_no_general_answers(self):
        bad = []
        for aid in answer_module_map:
            if aid.startswith("general-"):
                bad.append(aid)
        self.assertFalse(bad, f"general-* answers should not be in answer_module_map: {bad}")

    def test_11_next_questions_keys_exist_in_answers(self):
        missing = [aid for aid in next_questions_bank if aid not in answer_bank]
        self.assertFalse(missing, f"next_questions keys missing in answer_bank: {missing}")

    def test_12_video_keys_exist_in_answers(self):
        missing = [aid for aid in video_bank if aid not in answer_bank]
        self.assertFalse(missing, f"video keys missing in answer_bank: {missing}")

    def test_13_video_paths_exist_for_video_bank(self):
        missing = []
        for aid, data in video_bank.items():
            src = data.get("src", "")
            path = ROOT / "frontend" / "static" / "videos" / src
            if not path.exists():
                missing.append((aid, src))
        self.assertFalse(missing, f"Missing files referenced in video_bank: {missing}")

    def test_14_suggestions_shape(self):
        bad = []
        for idx, suggestion in enumerate(suggestion_bank):
            if not isinstance(suggestion.get("text"), str):
                bad.append((idx, "text"))
            if not isinstance(suggestion.get("keywords"), list):
                bad.append((idx, "keywords"))
        self.assertFalse(bad, f"Bad suggestion shapes: {bad}")

    def test_15_module_next_questions_key_ownership(self):
        bad = []
        for slug, bank in module_banks.items():
            own_answers = set(bank.get("answers", {}))
            for aid in bank.get("next_questions", {}):
                if aid not in own_answers:
                    bad.append((slug, aid))
        self.assertFalse(bad, f"Module next_questions keys outside module answers: {bad}")


if __name__ == "__main__":
    unittest.main(verbosity=2)

