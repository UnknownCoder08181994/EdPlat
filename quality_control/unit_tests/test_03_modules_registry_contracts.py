"""
Module registry and loader contract tests.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.modules import MODULES, get_all_modules, get_module  # noqa: E402
from backend.modules.advanced_copilot_patterns.registry import MODULE as ADVANCED_MODULE  # noqa: E402
from backend.modules.building_smartsdk.registry import MODULE as BUILDING_MODULE  # noqa: E402
from backend.modules.copilot_basics.registry import MODULE as COPILOT_MODULE  # noqa: E402


class TestModuleRegistryContracts(unittest.TestCase):
    """Schema and linkage checks for module registries."""

    def test_01_get_module_returns_dict_for_enabled_slug(self):
        module = get_module("copilot-basics")
        self.assertIsInstance(module, dict)

    def test_02_get_module_returns_none_for_unknown_slug(self):
        self.assertIsNone(get_module("unknown-module"))

    def test_03_get_all_modules_returns_slug_data_tuples(self):
        all_modules = get_all_modules()
        self.assertIsInstance(all_modules, list)
        self.assertGreaterEqual(len(all_modules), 1)
        slug, data = all_modules[0]
        self.assertIsInstance(slug, str)
        self.assertIsInstance(data, dict)

    def test_04_enabled_modules_dict_matches_loader(self):
        all_modules = dict(get_all_modules())
        self.assertEqual(set(all_modules.keys()), set(MODULES.keys()))

    def test_05_required_top_level_keys_exist(self):
        required = {
            "title", "subtitle", "category", "accent", "difficulty", "duration",
            "ai_native", "author", "description", "learning_objectives", "sections",
        }
        for mod in [COPILOT_MODULE, BUILDING_MODULE, ADVANCED_MODULE]:
            with self.subTest(module=mod["title"]):
                self.assertTrue(required.issubset(mod.keys()))

    def test_06_author_shape_is_consistent(self):
        for mod in [COPILOT_MODULE, BUILDING_MODULE, ADVANCED_MODULE]:
            with self.subTest(module=mod["title"]):
                author = mod.get("author", {})
                self.assertIsInstance(author.get("name"), str)
                self.assertIsInstance(author.get("role"), str)
                self.assertIsInstance(author.get("initials"), str)
                self.assertGreaterEqual(len(author["initials"]), 2)

    def test_07_sections_are_non_empty_and_ids_unique(self):
        for mod in [COPILOT_MODULE, BUILDING_MODULE, ADVANCED_MODULE]:
            with self.subTest(module=mod["title"]):
                sections = mod.get("sections", [])
                self.assertGreaterEqual(len(sections), 1)
                ids = [s.get("id") for s in sections]
                self.assertEqual(len(ids), len(set(ids)), "Section IDs must be unique.")

    def test_08_section_contract_fields(self):
        for mod in [COPILOT_MODULE, BUILDING_MODULE, ADVANCED_MODULE]:
            for section in mod.get("sections", []):
                with self.subTest(module=mod["title"], section=section.get("id")):
                    self.assertIsInstance(section.get("id"), str)
                    self.assertIsInstance(section.get("title"), str)
                    self.assertIn("video", section)
                    self.assertIn("start", section)
                    self.assertIsInstance(section.get("description"), str)

    def test_09_copilot_video_path_points_to_file(self):
        section = COPILOT_MODULE["sections"][0]
        video_rel = section["video"]
        video_path = ROOT / "frontend" / "static" / "videos" / video_rel
        self.assertTrue(video_path.exists(), f"Missing module video: {video_rel}")

    def test_10_disabled_registries_use_null_video_placeholders(self):
        for mod in [BUILDING_MODULE, ADVANCED_MODULE]:
            for section in mod.get("sections", []):
                with self.subTest(module=mod["title"], section=section["id"]):
                    self.assertIsNone(
                        section.get("video"),
                        "Inactive module registry sections should keep video placeholders as None.",
                    )

    def test_11_learning_objectives_are_non_empty_strings(self):
        for mod in [COPILOT_MODULE, BUILDING_MODULE, ADVANCED_MODULE]:
            for objective in mod.get("learning_objectives", []):
                with self.subTest(module=mod["title"]):
                    self.assertIsInstance(objective, str)
                    self.assertGreater(len(objective.strip()), 3)

    def test_12_enabled_module_difficulty_is_beginner(self):
        self.assertEqual(COPILOT_MODULE.get("difficulty"), "beginner")


if __name__ == "__main__":
    unittest.main(verbosity=2)

