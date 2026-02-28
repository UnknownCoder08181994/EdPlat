# Unit Test Execution Report

- Run timestamp: `2026-02-24 21:06:38 -05:00`
- Command: `python -m unittest discover -s unit_tests -v`
- Suite file: `unit_tests/test_oit_python_suite.py`
- Scope covered: 37 Python source files (`app.py` + `backend/**/*.py`, excluding `venv/`, `__pycache__/`, `debug/`, `unit_tests/`)

## Summary

- Total tests: **10**
- Passed: **9**
- Failed: **1**
- Errors: **0**
- Overall status: **FAILED**

## Test Inventory

1. `test_01_all_python_files_compile` - PASS
2. `test_02_all_python_modules_import` - PASS
3. `test_03_python_file_inventory_guard` - PASS
4. `test_04_flask_core_pages_respond_200` - PASS
5. `test_05_faq_page_route_is_not_exposed` - PASS
6. `test_06_module_viewer_first_section_route_available` - PASS
7. `test_07_api_chat_and_resolve_roundtrip` - PASS
8. `test_08_api_chat_rejects_non_json` - PASS
9. `test_09_all_registry_video_paths_exist` - **FAIL**
10. `test_10_qa_bank_answer_reference_integrity` - PASS

## Failure

### Registry video placeholders missing for infrastructure modules

- Failing test: `test_09_all_registry_video_paths_exist`
- Assertion: all module registry video paths should exist under `frontend/static/videos/`
- Actual: **17** missing references, all to `messages.mp4`
- Affected module registries:
  - `backend/modules/building_smartsdk/registry.py:23`
  - `backend/modules/building_smartsdk/registry.py:25`
  - `backend/modules/building_smartsdk/registry.py:27`
  - `backend/modules/building_smartsdk/registry.py:29`
  - `backend/modules/building_smartsdk/registry.py:31`
  - `backend/modules/building_smartsdk/registry.py:33`
  - `backend/modules/building_smartsdk/registry.py:35`
  - `backend/modules/advanced_copilot_patterns/registry.py:24`
  - `backend/modules/advanced_copilot_patterns/registry.py:26`
  - `backend/modules/advanced_copilot_patterns/registry.py:28`
  - `backend/modules/advanced_copilot_patterns/registry.py:30`
  - `backend/modules/advanced_copilot_patterns/registry.py:32`
  - `backend/modules/advanced_copilot_patterns/registry.py:34`
  - `backend/modules/advanced_copilot_patterns/registry.py:36`
  - `backend/modules/advanced_copilot_patterns/registry.py:38`
  - `backend/modules/advanced_copilot_patterns/registry.py:40`
  - `backend/modules/advanced_copilot_patterns/registry.py:42`
- Agents docs explicitly list `messages.mp4` in the UI videos folder:
  - `agents.md:139`

#### How to fix

1. Add `frontend/static/videos/messages.mp4`, or
2. Point those registry sections to existing video files, or
3. If infrastructure modules are intentionally incomplete, scope this test to enabled modules only.

## What Passed

- `/faq` expectation now aligns with agents route contract (not exposed route).
- All Python files compile and import successfully.
- Core pages `/`, `/modules`, `/chat` return `200`.
- Active module viewer route based on registry section ID is valid.
- `/api/chat` + `/api/chat/resolve` round-trip is valid.
- `/api/chat` correctly rejects non-JSON payloads (`400`).
- Global and module-scoped Q&A answer references are internally consistent.

## Notes

- No application code was changed as part of this request.
- This report reflects current behavior and test outcomes only.
