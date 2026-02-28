"""
Reachability and contract checks for QA banks.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.qa import answer_bank, module_banks, qa_bank  # noqa: E402
from backend.qa.engine import resolve_query  # noqa: E402


class TestTopicBankReachability(unittest.TestCase):
    """Verifies that prewritten answers are reachable through deterministic entries."""

    def test_01_every_global_answer_has_at_least_one_referencing_entry(self):
        referenced = {entry.get("answer") for entry in qa_bank if entry.get("answer")}
        missing = [aid for aid in answer_bank if aid not in referenced]
        self.assertFalse(
            missing,
            f"Answers with no global QA entry references: {missing}",
        )

    def test_02_every_module_answer_has_referencing_entry(self):
        missing = []
        for slug, bank in module_banks.items():
            refs = {entry.get("answer") for entry in bank.get("qa_entries", []) if entry.get("answer")}
            for aid in bank.get("answers", {}):
                if aid not in refs:
                    missing.append((slug, aid))
        self.assertFalse(missing, f"Module answers without QA entry refs: {missing}")

    def test_03_each_global_entry_first_keyword_reaches_not_no_match(self):
        bad = []
        for idx, entry in enumerate(qa_bank):
            if "answer" not in entry:
                continue
            kw = entry.get("keywords", [])
            if not kw:
                continue
            result = resolve_query(kw[0])
            if result.get("type") == "noMatch":
                bad.append((idx, entry["answer"], kw[0]))
        self.assertFalse(bad, f"Global entries with unreachable first keyword: {bad}")

    def test_04_each_module_entry_first_keyword_reaches_not_no_match(self):
        bad = []
        for slug, bank in module_banks.items():
            for idx, entry in enumerate(bank.get("qa_entries", [])):
                if "answer" not in entry:
                    continue
                kw = entry.get("keywords", [])
                if not kw:
                    continue
                result = resolve_query(kw[0], module_slug=slug)
                if result.get("type") == "noMatch":
                    bad.append((slug, idx, entry["answer"], kw[0]))
        self.assertFalse(bad, f"Module entries with unreachable first keyword: {bad}")

    def test_05_answer_prefixes_remain_within_current_known_set(self):
        known = {"general", "copilot", "smartsdk", "stratos", "prompting", "fullstack"}
        bad = []
        for aid in answer_bank:
            prefix = aid.split("-")[0]
            if prefix not in known:
                bad.append(aid)
        self.assertFalse(bad, f"Unexpected answer prefixes: {bad}")

    def test_06_global_reachability_sample_queries(self):
        queries = [
            "hello",
            "what modules are available",
            "what is smartsdk",
            "what are stratos workflows",
            "what is prompt engineering",
            "what is full-stack ai integration",
        ]
        failures = []
        for query in queries:
            result = resolve_query(query)
            if result.get("type") == "noMatch":
                failures.append(query)
        self.assertFalse(failures, f"Expected global sample queries to resolve: {failures}")

    def test_07_module_reachability_sample_queries(self):
        samples = [
            ("copilot-basics", "seal id"),
            ("smartsdk-fundamentals", "what is smartsdk"),
            ("building-smartsdk", "building with smartsdk overview"),
            ("stratos-setup", "how to set up stratos"),
            ("stratos-workflows", "workflow triggers"),
            ("prompt-engineering", "what is prompt engineering"),
            ("fullstack-ai-integration", "what will i build"),
        ]
        failures = []
        for slug, query in samples:
            result = resolve_query(query, module_slug=slug)
            if result.get("type") == "noMatch":
                failures.append((slug, query))
        self.assertFalse(failures, f"Expected module sample queries to resolve: {failures}")


if __name__ == "__main__":
    unittest.main(verbosity=2)

