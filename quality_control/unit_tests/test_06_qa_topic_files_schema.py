"""
Schema checks across individual backend.qa topic data files.
"""

import importlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

QA_ROOT = ROOT / "backend" / "qa"


def _topic_module_names() -> list[str]:
    names = []
    for path in sorted(QA_ROOT.glob("*/*.py")):
        if path.name == "__init__.py":
            continue
        rel = path.relative_to(ROOT).with_suffix("")
        names.append(rel.as_posix().replace("/", "."))
    return names


class TestQaTopicFilesSchema(unittest.TestCase):
    """Data contract checks for each category topic file."""

    PLACEHOLDER_TOKENS = (
        "coming soon",
        "to be determined",
        "lorem ipsum",
        "todo",
        "tbd",
    )

    def test_01_topic_modules_discovered(self):
        modules = _topic_module_names()
        self.assertGreaterEqual(len(modules), 12)

    def test_02_topic_modules_import_cleanly(self):
        failures = []
        for mod_name in _topic_module_names():
            try:
                importlib.import_module(mod_name)
            except Exception as exc:  # pragma: no cover
                failures.append((mod_name, str(exc)))
        self.assertFalse(failures, f"Topic module import failures: {failures}")

    def test_03_required_exports_exist(self):
        bad = []
        for mod_name in _topic_module_names():
            mod = importlib.import_module(mod_name)
            for attr in ("ANSWERS", "SUGGESTIONS", "QA_ENTRIES"):
                if not hasattr(mod, attr):
                    bad.append((mod_name, attr))
        self.assertFalse(bad, f"Missing required exports: {bad}")

    def test_04_answers_shape(self):
        bad = []
        for mod_name in _topic_module_names():
            answers = getattr(importlib.import_module(mod_name), "ANSWERS", {})
            if not isinstance(answers, dict):
                bad.append((mod_name, "ANSWERS-not-dict"))
                continue
            for aid, text in answers.items():
                if not isinstance(aid, str) or not aid:
                    bad.append((mod_name, "bad-answer-id", aid))
                if not isinstance(text, str) or not text.strip():
                    bad.append((mod_name, "bad-answer-text", aid))
        self.assertFalse(bad, f"Bad answers shape: {bad}")

    def test_05_suggestions_shape(self):
        bad = []
        for mod_name in _topic_module_names():
            suggestions = getattr(importlib.import_module(mod_name), "SUGGESTIONS", [])
            if not isinstance(suggestions, list):
                bad.append((mod_name, "SUGGESTIONS-not-list"))
                continue
            for idx, s in enumerate(suggestions):
                if not isinstance(s.get("text"), str):
                    bad.append((mod_name, idx, "text"))
                if not isinstance(s.get("keywords"), list):
                    bad.append((mod_name, idx, "keywords"))
        self.assertFalse(bad, f"Bad suggestions shape: {bad}")

    def test_06_qa_entries_shape_and_refs(self):
        bad = []
        for mod_name in _topic_module_names():
            mod = importlib.import_module(mod_name)
            entries = getattr(mod, "QA_ENTRIES", [])
            answers = getattr(mod, "ANSWERS", {})
            if not isinstance(entries, list):
                bad.append((mod_name, "QA_ENTRIES-not-list"))
                continue
            for idx, entry in enumerate(entries):
                kw = entry.get("keywords")
                if not isinstance(kw, list) or not kw:
                    bad.append((mod_name, idx, "keywords"))
                has_answer = "answer" in entry
                has_followup = "followUp" in entry
                if has_answer == has_followup:
                    bad.append((mod_name, idx, "answer-followUp-shape"))
                if has_answer and entry["answer"] not in answers:
                    bad.append((mod_name, idx, f"missing-answer-ref:{entry['answer']}"))
                if has_followup:
                    for opt in entry.get("followUp", {}).get("options", []):
                        aid = opt.get("answerId")
                        if aid and aid not in answers:
                            bad.append((mod_name, idx, f"missing-followup-ref:{aid}"))
        self.assertFalse(bad, f"Bad QA entries shape: {bad}")

    def test_07_next_questions_keys_reference_local_answers(self):
        bad = []
        for mod_name in _topic_module_names():
            mod = importlib.import_module(mod_name)
            answers = getattr(mod, "ANSWERS", {})
            next_q = getattr(mod, "NEXT_QUESTIONS", {})
            if not isinstance(next_q, dict):
                bad.append((mod_name, "NEXT_QUESTIONS-not-dict"))
                continue
            for aid, questions in next_q.items():
                if aid not in answers:
                    bad.append((mod_name, f"next-question-missing-answer:{aid}"))
                if not isinstance(questions, list):
                    bad.append((mod_name, f"next-question-list-type:{aid}"))
        self.assertFalse(bad, f"Bad NEXT_QUESTIONS shape: {bad}")

    def test_08_keywords_are_lowercase(self):
        bad = []
        for mod_name in _topic_module_names():
            mod = importlib.import_module(mod_name)
            for entry in getattr(mod, "QA_ENTRIES", []):
                for kw in entry.get("keywords", []):
                    if kw != kw.lower():
                        bad.append((mod_name, kw))
        self.assertFalse(bad, f"Uppercase keywords found: {bad}")

    def test_09_answers_do_not_include_placeholder_tokens(self):
        bad = []
        for mod_name in _topic_module_names():
            answers = getattr(importlib.import_module(mod_name), "ANSWERS", {})
            for aid, text in answers.items():
                lowered = text.lower()
                for token in self.PLACEHOLDER_TOKENS:
                    if token in lowered:
                        bad.append((mod_name, aid, token))
        self.assertFalse(bad, f"Placeholder tokens found in answers: {bad}")

    def test_10_module_banks_export_shape_when_present(self):
        bad = []
        for mod_name in _topic_module_names():
            mod = importlib.import_module(mod_name)
            module_banks = getattr(mod, "MODULE_BANKS", None)
            if module_banks is None:
                continue
            if not isinstance(module_banks, dict):
                bad.append((mod_name, "MODULE_BANKS-not-dict"))
        self.assertFalse(bad, f"Bad MODULE_BANKS exports: {bad}")


if __name__ == "__main__":
    unittest.main(verbosity=2)

