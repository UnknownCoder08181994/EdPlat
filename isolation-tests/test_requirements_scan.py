"""Isolation test: _scan_and_generate_requirements()

Tests that the RequirementsScan correctly:
  1. Identifies third-party imports (flask, requests, etc.)
  2. Ignores local modules (auth/, routes/, utils/, models.py, etc.)
  3. Ignores stdlib (os, sys, json, etc.)
  4. Ignores dev tools (pytest, black, flake8, etc.)
  5. Maps import names to pip names (PIL -> Pillow, etc.)
  6. Doesn't duplicate existing entries in requirements.txt
"""

import os
import sys
import shutil
import tempfile

# ── Patch imports so we can load agent_service in isolation ──────────
# We need to make the backend directory importable and stub out
# heavy dependencies that aren't relevant to this test.

BACKEND_DIR = os.path.join(os.path.dirname(__file__), '..', 'backend')
sys.path.insert(0, os.path.abspath(BACKEND_DIR))

# Stub out modules that agent_service imports but we don't need
class FakeConfig:
    STORAGE_DIR = tempfile.mkdtemp()
    LM_STUDIO_URL = 'http://localhost:1234'
    LM_STUDIO_MODEL = 'test'

sys.modules['config'] = type(sys)('config')
sys.modules['config'].Config = FakeConfig

# Stub services that get imported at module level
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
        # Add expected attributes
        if mod_name == 'prompts.execution':
            fake.PIP_NAME_MAP = {
                'Pillow': 'PIL', 'opencv-python': 'cv2', 'scikit-learn': 'sklearn',
                'PyYAML': 'yaml', 'beautifulsoup4': 'bs4', 'python-dotenv': 'dotenv',
                'psycopg2-binary': 'psycopg2',
            }
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
# Test helpers
# ═══════════════════════════════════════════════════════════════

def _make_workspace(structure: dict, base_dir: str = None) -> str:
    """Create a temp workspace with given file structure.

    structure = {
        'app/__init__.py': 'from flask import Flask\\n...',
        'app/routes/auth.py': 'from flask_login import ...',
        'models.py': 'import sqlalchemy',
        'requirements.txt': 'flask\\n',
    }
    """
    ws = base_dir or tempfile.mkdtemp(prefix='zenflow_test_')
    for rel_path, content in structure.items():
        full = os.path.join(ws, rel_path.replace('/', os.sep))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, 'w', encoding='utf-8') as f:
            f.write(content)
    return ws


def _read_requirements(ws):
    """Read requirements.txt and return set of normalized package names."""
    req_path = os.path.join(ws, 'requirements.txt')
    if not os.path.isfile(req_path):
        return set()
    pkgs = set()
    with open(req_path, 'r') as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith('#'):
                pkgs.add(s.split('==')[0].split('>=')[0].split('<=')[0].strip().lower())
    return pkgs


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
# TEST 1: Basic third-party detection
# ═══════════════════════════════════════════════════════════════
print("\n=== TEST 1: Basic third-party detection ===")
ws = _make_workspace({
    'app.py': (
        'from flask import Flask\n'
        'import requests\n'
        'import os\n'
        'import json\n'
        '\n'
        'app = Flask(__name__)\n'
    ),
})
added = AgentService._scan_and_generate_requirements(ws)
reqs = _read_requirements(ws)

check("flask detected", 'flask' in reqs, f"reqs={reqs}")
check("requests detected", 'requests' in reqs, f"reqs={reqs}")
check("os NOT added (stdlib)", 'os' not in reqs, f"reqs={reqs}")
check("json NOT added (stdlib)", 'json' not in reqs, f"reqs={reqs}")
check("added list correct", set(a.lower() for a in added) == {'flask', 'requests'},
      f"added={added}")
shutil.rmtree(ws)


# ═══════════════════════════════════════════════════════════════
# TEST 2: Local subpackages NOT treated as third-party
# (The bug that caused auth, routes, utils, etc. to appear)
# ═══════════════════════════════════════════════════════════════
print("\n=== TEST 2: Local subpackages not treated as third-party ===")
ws = _make_workspace({
    'app/__init__.py': (
        'from flask import Flask\n'
        'def create_app():\n'
        '    app = Flask(__name__)\n'
        '    return app\n'
    ),
    'app/routes/__init__.py': '',
    'app/routes/auth.py': (
        'from flask import Blueprint\n'
        'auth_bp = Blueprint("auth", __name__)\n'
    ),
    'app/routes/api.py': (
        'from flask import Blueprint, jsonify\n'
        'api_bp = Blueprint("api", __name__)\n'
    ),
    'app/models/__init__.py': '',
    'app/models/user.py': (
        'from sqlalchemy import Column, Integer, String\n'
    ),
    'app/extensions.py': (
        'from flask_sqlalchemy import SQLAlchemy\n'
        'db = SQLAlchemy()\n'
    ),
    'app/utils/__init__.py': '',
    'app/utils/helpers.py': (
        'import os\n'
        'def get_config(): pass\n'
    ),
    'app/metrics.py': (
        'import time\n'
        'def track(): pass\n'
    ),
    'app/export.py': (
        'import csv\n'
        'def export_data(): pass\n'
    ),
    'app/widgets.py': (
        'import json\n'
        'class Widget: pass\n'
    ),
    'run.py': (
        'from app import create_app\n'
        'app = create_app()\n'
        'app.run()\n'
    ),
    'requirements.txt': '',
})

added = AgentService._scan_and_generate_requirements(ws)
reqs = _read_requirements(ws)
added_lower = set(a.lower() for a in added)

# These should be recognized as LOCAL and NOT added
check("auth NOT added (local subpackage)", 'auth' not in reqs, f"reqs={reqs}")
check("routes NOT added (local subpackage)", 'routes' not in reqs, f"reqs={reqs}")
check("utils NOT added (local subpackage)", 'utils' not in reqs, f"reqs={reqs}")
check("models NOT added (local subpackage)", 'models' not in reqs, f"reqs={reqs}")
check("extensions NOT added (local module)", 'extensions' not in reqs, f"reqs={reqs}")
check("export NOT added (local module)", 'export' not in reqs, f"reqs={reqs}")
check("metrics NOT added (local module)", 'metrics' not in reqs, f"reqs={reqs}")
check("widgets NOT added (local module)", 'widgets' not in reqs, f"reqs={reqs}")
check("app NOT added (local package)", 'app' not in reqs, f"reqs={reqs}")

# These SHOULD be added (real third-party)
check("flask IS added", 'flask' in reqs, f"reqs={reqs}")
check("sqlalchemy IS added", 'sqlalchemy' in reqs, f"reqs={reqs}")
check("flask_sqlalchemy IS added", 'flask_sqlalchemy' in reqs or 'flask-sqlalchemy' in reqs,
      f"reqs={reqs}")

print(f"  [info] Added packages: {added}")
shutil.rmtree(ws)


# ═══════════════════════════════════════════════════════════════
# TEST 3: Dev tools excluded (pytest, black, etc.)
# ═══════════════════════════════════════════════════════════════
print("\n=== TEST 3: Dev tools excluded ===")
ws = _make_workspace({
    'app.py': (
        'import flask\n'
        'import pytest\n'
        'import black\n'
        'import flake8\n'
        'import mypy\n'
        'import coverage\n'
    ),
})
added = AgentService._scan_and_generate_requirements(ws)
reqs = _read_requirements(ws)

check("flask IS added", 'flask' in reqs, f"reqs={reqs}")
check("pytest NOT added (dev tool)", 'pytest' not in reqs, f"reqs={reqs}")
check("black NOT added (dev tool)", 'black' not in reqs, f"reqs={reqs}")
check("flake8 NOT added (dev tool)", 'flake8' not in reqs, f"reqs={reqs}")
check("mypy NOT added (dev tool)", 'mypy' not in reqs, f"reqs={reqs}")
check("coverage NOT added (dev tool)", 'coverage' not in reqs, f"reqs={reqs}")
shutil.rmtree(ws)


# ═══════════════════════════════════════════════════════════════
# TEST 4: Import name -> pip name mapping
# ═══════════════════════════════════════════════════════════════
print("\n=== TEST 4: Import-to-pip name mapping ===")
ws = _make_workspace({
    'app.py': (
        'from PIL import Image\n'
        'import yaml\n'
        'from bs4 import BeautifulSoup\n'
        'from dotenv import load_dotenv\n'
    ),
})
added = AgentService._scan_and_generate_requirements(ws)
reqs = _read_requirements(ws)

check("Pillow added (not PIL)", 'pillow' in reqs or 'Pillow' in {a for a in added},
      f"reqs={reqs}, added={added}")
check("PyYAML added (not yaml)", 'pyyaml' in reqs or 'PyYAML' in {a for a in added},
      f"reqs={reqs}, added={added}")
check("beautifulsoup4 added (not bs4)", 'beautifulsoup4' in reqs or 'beautifulsoup4' in {a for a in added},
      f"reqs={reqs}, added={added}")
check("python-dotenv added (not dotenv)", 'python-dotenv' in reqs or 'python-dotenv' in {a for a in added},
      f"reqs={reqs}, added={added}")
shutil.rmtree(ws)


# ═══════════════════════════════════════════════════════════════
# TEST 5: Existing requirements not duplicated
# ═══════════════════════════════════════════════════════════════
print("\n=== TEST 5: Existing requirements not duplicated ===")
ws = _make_workspace({
    'app.py': (
        'from flask import Flask\n'
        'import requests\n'
        'import redis\n'
    ),
    'requirements.txt': 'flask==2.3.0\nrequests>=2.28\n',
})
added = AgentService._scan_and_generate_requirements(ws)
added_lower = set(a.lower() for a in added)

check("flask NOT re-added", 'flask' not in added_lower, f"added={added}")
check("requests NOT re-added", 'requests' not in added_lower, f"added={added}")
check("redis IS added (new)", 'redis' in added_lower, f"added={added}")

# Verify requirements.txt doesn't have duplicates
with open(os.path.join(ws, 'requirements.txt'), 'r') as f:
    lines = [l.strip() for l in f if l.strip() and not l.startswith('#')]
check("no duplicate lines", len(lines) == len(set(l.lower().split('==')[0].split('>=')[0] for l in lines)),
      f"lines={lines}")
shutil.rmtree(ws)


# ═══════════════════════════════════════════════════════════════
# TEST 6: Deep nested local modules recognized
# ═══════════════════════════════════════════════════════════════
print("\n=== TEST 6: Deep nested local modules ===")
ws = _make_workspace({
    'src/__init__.py': '',
    'src/core/__init__.py': '',
    'src/core/engine.py': 'import json\nclass Engine: pass\n',
    'src/core/helpers/__init__.py': '',
    'src/core/helpers/formatter.py': 'def fmt(): pass\n',
    'src/api/__init__.py': '',
    'src/api/views.py': (
        'from flask import Flask\n'
        'from core import engine\n'        # local
        'from helpers import formatter\n'  # local (helpers dir exists)
        'from api import views\n'          # local
    ),
    'main.py': (
        'from src.core import engine\n'
        'import requests\n'
    ),
})
added = AgentService._scan_and_generate_requirements(ws)
reqs = _read_requirements(ws)

check("core NOT added (local)", 'core' not in reqs, f"reqs={reqs}")
check("helpers NOT added (local)", 'helpers' not in reqs, f"reqs={reqs}")
check("api NOT added (local)", 'api' not in reqs, f"reqs={reqs}")
check("engine NOT added (local .py)", 'engine' not in reqs, f"reqs={reqs}")
check("formatter NOT added (local .py)", 'formatter' not in reqs, f"reqs={reqs}")
check("src NOT added (local)", 'src' not in reqs, f"reqs={reqs}")
check("views NOT added (local .py)", 'views' not in reqs, f"reqs={reqs}")
check("flask IS added", 'flask' in reqs, f"reqs={reqs}")
check("requests IS added", 'requests' in reqs, f"reqs={reqs}")
shutil.rmtree(ws)


# ═══════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════
print(f"\n{'='*60}")
print(f"RequirementsScan:  {passed} passed, {failed} failed")
print(f"{'='*60}")
sys.exit(1 if failed > 0 else 0)
