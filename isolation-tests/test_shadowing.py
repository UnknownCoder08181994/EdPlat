"""Isolation test: _detect_shadowing_files()

Tests that shadow detection correctly:
  1. Detects flask.py shadowing the pip flask package
  2. Renames the shadowing file to flask_app.py
  3. Updates imports in other files that referenced the local flask.py
  4. Does NOT rename __init__.py, setup.py, conftest.py
  5. Does NOT rename files that don't shadow anything
  6. Handles collision (flask_app.py already exists -> uses flask_local.py)
  7. Only rewrites imports that reference LOCAL names, not pip names
"""

import os
import sys
import shutil
import tempfile

# ── Patch imports so we can load agent_service in isolation ──────────
BACKEND_DIR = os.path.join(os.path.dirname(__file__), '..', 'backend')
sys.path.insert(0, os.path.abspath(BACKEND_DIR))

# Stub out modules
class FakeConfig:
    STORAGE_DIR = tempfile.mkdtemp()
    LM_STUDIO_URL = 'http://localhost:1234'
    LM_STUDIO_MODEL = 'test'

sys.modules['config'] = type(sys)('config')
sys.modules['config'].Config = FakeConfig

for mod_name in [
    'services.llm_engine', 'services.task_service', 'services.tool_service',
    'services.micro_agents', 'services.reward_scorer', 'services.experience_memory',
    'services.reward_agent',
    'prompts', 'prompts.execution', 'prompts.system_prompt',
    'prompts.requirements', 'prompts.technical_specification',
    'prompts.planning', 'prompts.implementation',
    'prompts.review', 'prompts.nudges', 'prompts.context_wiring',
    'prompts.task_reformat',
]:
    if mod_name not in sys.modules:
        fake = type(sys)('fake_' + mod_name)
        if mod_name == 'prompts.execution':
            fake.PIP_NAME_MAP = {}
            fake.build_diagnose_prompt = lambda *a, **kw: ''
            fake.build_dependency_prompt = lambda *a, **kw: ''
            fake.build_recoder_prompt = lambda *a, **kw: ''
        if mod_name == 'services.llm_engine':
            fake.get_llm_engine = lambda: None
            fake.LLMEngine = type('LLMEngine', (), {})
        if mod_name == 'services.task_service':
            fake.TaskService = type('TaskService', (), {})
        if mod_name == 'services.tool_service':
            fake.ToolService = type('ToolService', (), {})
        if mod_name == 'services.micro_agents':
            fake.post_write_checks = lambda *a, **kw: []
            fake.build_signature_index = lambda *a, **kw: {}
            fake.scan_downstream_dependencies = lambda *a, **kw: []
            fake.track_progress = lambda *a, **kw: None
            fake.optimize_history = lambda *a, **kw: []
            fake.run_tests = lambda *a, **kw: None
            fake.ImportGraph = type('ImportGraph', (), {})
        if mod_name == 'services.reward_scorer':
            fake.score_step = lambda *a, **kw: 0
            fake.score_execution = lambda *a, **kw: 0
            fake.score_task = lambda *a, **kw: 0
        if mod_name == 'services.experience_memory':
            fake.ExperienceMemory = type('ExperienceMemory', (), {})
        if mod_name == 'services.reward_agent':
            fake.generate_lessons = lambda *a, **kw: []
        if mod_name == 'prompts':
            fake.build_requirements_prompt = lambda *a, **kw: ''
            fake.build_technical_specification_prompt = lambda *a, **kw: ''
            fake.build_planning_prompt = lambda *a, **kw: ''
            fake.build_implementation_prompt = lambda *a, **kw: ''
            fake.build_code_context = lambda *a, **kw: ''
            fake.build_read_before_write_rules = lambda *a, **kw: ''
            fake.build_system_prompt = lambda *a, **kw: ''
            fake.build_review_prompt = lambda *a, **kw: ''
            fake.build_api_check_prompt = lambda *a, **kw: ''
            fake.build_quality_check_prompt = lambda *a, **kw: ''
            fake.build_fix_summary_prompt = lambda *a, **kw: ''
            fake.nudges = type(sys)('nudges')
        sys.modules[mod_name] = fake

from services.agent_service import AgentService


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _make_workspace(structure: dict) -> str:
    ws = tempfile.mkdtemp(prefix='zenflow_shadow_')
    for rel_path, content in structure.items():
        full = os.path.join(ws, rel_path.replace('/', os.sep))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, 'w', encoding='utf-8') as f:
            f.write(content)
    return ws


passed = 0
failed = 0

def check(name, condition, detail=''):
    global passed, failed
    if condition:
        print(f"  PASS  {name}")
        passed += 1
    else:
        print(f"  FAIL  {name}  {detail}")
        failed += 1


# ═══════════════════════════════════════════════════════════════
# TEST 1: flask.py shadows pip flask -> renamed to flask_app.py
# ═══════════════════════════════════════════════════════════════
print("\n=== TEST 1: flask.py renamed to flask_app.py ===")
ws = _make_workspace({
    'flask.py': (
        '# This is a LOCAL file that shadows pip flask\n'
        'def my_helper():\n'
        '    return "I am local flask"\n'
        '\n'
        'SECRET = "abc123"\n'
    ),
    'app.py': (
        'from flask import Flask\n'
        'from flask import my_helper\n'
        '\n'
        'app = Flask(__name__)\n'
        'print(my_helper())\n'
    ),
})

results = AgentService._detect_shadowing_files(ws)

check("one shadowing file detected", len(results) == 1, f"results={results}")
if results:
    check("file was flask.py", results[0]['file'] == 'flask.py', f"got={results[0]['file']}")
    check("renamed to flask_app.py", results[0]['renamed_to'] == 'flask_app.py',
          f"got={results[0]['renamed_to']}")
    check("flask.py no longer exists", not os.path.exists(os.path.join(ws, 'flask.py')))
    check("flask_app.py exists", os.path.isfile(os.path.join(ws, 'flask_app.py')))

# Check that app.py imports were updated correctly
with open(os.path.join(ws, 'app.py'), 'r') as f:
    app_content = f.read()
check("pip import unchanged (from flask import Flask)",
      'from flask import Flask' in app_content or 'from flask_app import Flask' not in app_content,
      f"content={app_content}")
# The local import should be rewritten since my_helper is defined in the old file
check("local import rewritten (my_helper -> flask_app)",
      'from flask_app import my_helper' in app_content,
      f"content={app_content}")
shutil.rmtree(ws)


# ═══════════════════════════════════════════════════════════════
# TEST 2: Non-shadowing file NOT renamed
# ═══════════════════════════════════════════════════════════════
print("\n=== TEST 2: Non-shadowing file NOT renamed ===")
ws = _make_workspace({
    'my_project.py': 'print("hello")\n',
    'helpers.py': 'def helper(): pass\n',
})
results = AgentService._detect_shadowing_files(ws)
check("no shadowing detected", len(results) == 0, f"results={results}")
check("my_project.py still exists", os.path.isfile(os.path.join(ws, 'my_project.py')))
check("helpers.py still exists", os.path.isfile(os.path.join(ws, 'helpers.py')))
shutil.rmtree(ws)


# ═══════════════════════════════════════════════════════════════
# TEST 3: setup.py, conftest.py NOT renamed even though they match
# ═══════════════════════════════════════════════════════════════
print("\n=== TEST 3: Special files NOT renamed ===")
ws = _make_workspace({
    'setup.py': 'from setuptools import setup\nsetup(name="test")\n',
    'conftest.py': 'import pytest\n',
    '__init__.py': '# top-level init\n',
})
results = AgentService._detect_shadowing_files(ws)
check("no files renamed", len(results) == 0, f"results={results}")
check("setup.py still exists", os.path.isfile(os.path.join(ws, 'setup.py')))
check("conftest.py still exists", os.path.isfile(os.path.join(ws, 'conftest.py')))
shutil.rmtree(ws)


# ═══════════════════════════════════════════════════════════════
# TEST 4: Collision — flask_app.py already exists -> uses flask_local.py
# ═══════════════════════════════════════════════════════════════
print("\n=== TEST 4: Collision handling (flask_app.py exists -> flask_local.py) ===")
ws = _make_workspace({
    'flask.py': (
        'def local_func():\n'
        '    return 42\n'
    ),
    'flask_app.py': (
        '# This already exists\n'
        'print("I am flask_app")\n'
    ),
})
results = AgentService._detect_shadowing_files(ws)
check("one file detected", len(results) == 1, f"results={results}")
if results:
    check("renamed to flask_local.py", results[0]['renamed_to'] == 'flask_local.py',
          f"got={results[0]['renamed_to']}")
    check("flask_local.py exists", os.path.isfile(os.path.join(ws, 'flask_local.py')))
    check("flask_app.py untouched", os.path.isfile(os.path.join(ws, 'flask_app.py')))
shutil.rmtree(ws)


# ═══════════════════════════════════════════════════════════════
# TEST 5: Multiple shadows — flask.py AND requests.py
# ═══════════════════════════════════════════════════════════════
print("\n=== TEST 5: Multiple shadowing files ===")
ws = _make_workspace({
    'flask.py': 'def my_flask(): pass\n',
    'requests.py': 'def my_get(): pass\n',
    'app.py': (
        'from flask import my_flask\n'
        'from requests import my_get\n'
    ),
})
results = AgentService._detect_shadowing_files(ws)
renamed_files = {r['file'] for r in results}
check("flask.py detected", 'flask.py' in renamed_files, f"renamed={renamed_files}")
check("requests.py detected", 'requests.py' in renamed_files, f"renamed={renamed_files}")
check("flask.py no longer exists", not os.path.exists(os.path.join(ws, 'flask.py')))
check("requests.py no longer exists", not os.path.exists(os.path.join(ws, 'requests.py')))
shutil.rmtree(ws)


# ═══════════════════════════════════════════════════════════════
# TEST 6: Bare import + attribute usage updated
# ═══════════════════════════════════════════════════════════════
print("\n=== TEST 6: Bare import + attribute usage ===")
ws = _make_workspace({
    'requests.py': (
        'BASE_URL = "http://example.com"\n'
        'def get(url): pass\n'
    ),
    'main.py': (
        'import requests\n'
        '\n'
        'url = requests.BASE_URL\n'
        'data = requests.get(url)\n'
    ),
})
results = AgentService._detect_shadowing_files(ws)
check("requests.py detected", len(results) >= 1)

with open(os.path.join(ws, 'main.py'), 'r') as f:
    content = f.read()
check("import rewritten to requests_app", 'import requests_app' in content,
      f"content={content}")
check("requests.BASE_URL -> requests_app.BASE_URL", 'requests_app.BASE_URL' in content,
      f"content={content}")
check("requests.get -> requests_app.get", 'requests_app.get' in content,
      f"content={content}")
shutil.rmtree(ws)


# ═══════════════════════════════════════════════════════════════
# TEST 7: stdlib shadow (json.py)
# ═══════════════════════════════════════════════════════════════
print("\n=== TEST 7: stdlib shadow (json.py) ===")
ws = _make_workspace({
    'json.py': (
        'def parse(s): pass\n'
    ),
    'app.py': (
        'from json import parse\n'
    ),
})
results = AgentService._detect_shadowing_files(ws)
check("json.py detected as shadow", len(results) == 1, f"results={results}")
if results:
    check("renamed to json_app.py", results[0]['renamed_to'] == 'json_app.py',
          f"got={results[0]['renamed_to']}")
shutil.rmtree(ws)


# ═══════════════════════════════════════════════════════════════
# TEST 8: Empty workspace -> no errors
# ═══════════════════════════════════════════════════════════════
print("\n=== TEST 8: Empty workspace ===")
ws = tempfile.mkdtemp(prefix='zenflow_shadow_empty_')
results = AgentService._detect_shadowing_files(ws)
check("no results on empty workspace", len(results) == 0, f"results={results}")
shutil.rmtree(ws)


# ═══════════════════════════════════════════════════════════════
# TEST 9: requirements.txt packages also trigger shadow detection
# ═══════════════════════════════════════════════════════════════
print("\n=== TEST 9: requirements.txt packages trigger shadow detection ===")
ws = _make_workspace({
    'boto3.py': 'def upload(): pass\n',
    'requirements.txt': 'boto3==1.28.0\nflask\n',
})
results = AgentService._detect_shadowing_files(ws)
renamed_files = {r['file'] for r in results}
check("boto3.py detected (via requirements.txt)", 'boto3.py' in renamed_files,
      f"renamed={renamed_files}")
shutil.rmtree(ws)


# ═══════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════
print(f"\n{'='*60}")
print(f"ShadowDetection:  {passed} passed, {failed} failed")
print(f"{'='*60}")
sys.exit(1 if failed > 0 else 0)
