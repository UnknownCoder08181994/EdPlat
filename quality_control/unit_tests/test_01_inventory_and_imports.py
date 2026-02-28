"""
Inventory and import diagnostics for project-owned Python source files.
"""

import importlib
import py_compile
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _source_python_files() -> list[Path]:
    files: list[Path] = [ROOT / "app.py"]
    files.extend(sorted((ROOT / "backend").rglob("*.py")))
    return [p for p in files if "__pycache__" not in p.parts]


def _module_name(path: Path) -> str:
    rel = path.relative_to(ROOT).with_suffix("")
    if rel.as_posix() == "app":
        return "app"
    mod = rel.as_posix().replace("/", ".")
    if mod.endswith(".__init__"):
        mod = mod[: -len(".__init__")]
    return mod


class TestInventoryAndImports(unittest.TestCase):
    """Phase-1 style inventory and import checks."""

    def test_01_source_file_inventory_contains_core_targets(self):
        files = {p.relative_to(ROOT).as_posix() for p in _source_python_files()}
        self.assertIn("app.py", files)
        self.assertIn("backend/modules/__init__.py", files)
        self.assertIn("backend/qa/__init__.py", files)
        self.assertIn("backend/qa/engine.py", files)
        self.assertGreaterEqual(len(files), 35)

    def test_02_every_source_file_under_400_lines(self):
        too_long = []
        for path in _source_python_files():
            lines = len(path.read_text(encoding="utf-8").splitlines())
            if lines > 400:
                too_long.append((path.relative_to(ROOT).as_posix(), lines))
        self.assertFalse(too_long, f"Source files over 400 lines: {too_long}")

    def test_03_all_source_files_compile(self):
        failures = []
        for path in _source_python_files():
            try:
                py_compile.compile(str(path), doraise=True)
            except Exception as exc:  # pragma: no cover
                failures.append((path.relative_to(ROOT).as_posix(), str(exc)))
        self.assertFalse(failures, f"Compile failures: {failures}")

    def test_04_app_module_importable(self):
        module = importlib.import_module("app")
        self.assertTrue(hasattr(module, "app"), "Expected Flask app object in app.py")

    def test_05_backend_package_importable(self):
        module = importlib.import_module("backend")
        self.assertIsNotNone(module)

    def test_06_backend_modules_importable(self):
        module = importlib.import_module("backend.modules")
        self.assertTrue(hasattr(module, "get_module"))
        self.assertTrue(hasattr(module, "get_all_modules"))

    def test_07_backend_qa_importable(self):
        module = importlib.import_module("backend.qa")
        self.assertTrue(hasattr(module, "answer_bank"))
        self.assertTrue(hasattr(module, "qa_bank"))

    def test_08_all_backend_source_modules_import(self):
        failures = []
        for path in _source_python_files():
            mod = _module_name(path)
            try:
                importlib.import_module(mod)
            except Exception as exc:  # pragma: no cover
                failures.append((mod, str(exc)))
        self.assertFalse(failures, f"Import failures: {failures}")

    def test_09_qa_topic_file_inventory(self):
        topic_files = sorted((ROOT / "backend" / "qa").glob("*/*.py"))
        topic_files = [
            p for p in topic_files
            if p.name != "__init__.py" and "__pycache__" not in p.parts
        ]
        self.assertGreaterEqual(len(topic_files), 12)

    def test_10_module_registry_inventory(self):
        reg_files = sorted((ROOT / "backend" / "modules").glob("*/registry.py"))
        rel = {p.relative_to(ROOT).as_posix() for p in reg_files}
        self.assertIn("backend/modules/copilot_basics/registry.py", rel)
        self.assertIn("backend/modules/building_smartsdk/registry.py", rel)
        self.assertIn("backend/modules/advanced_copilot_patterns/registry.py", rel)
        self.assertEqual(len(rel), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)

