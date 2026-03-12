"""Isolation test: _check_third_party_dep()

Tests that the integrity checker correctly:
  1. Flags missing dependencies (not in requirements.txt, not installed)
  2. Flags uninstalled dependencies (in requirements.txt but not installed)
  3. Accepts packages that are both in requirements.txt AND installed
  4. Ignores local modules (auth.py, auth/__init__.py, auth/*)
  5. Ignores dev tools (pytest, black, flake8, etc.)
  6. Handles import-to-pip name mapping (PIL -> Pillow, etc.)
  7. Handles underscore/hyphen normalization
"""

import os
import sys
import tempfile

# ── Patch imports ─────────────────────────────────────────────
BACKEND_DIR = os.path.join(os.path.dirname(__file__), '..', 'backend')
sys.path.insert(0, os.path.abspath(BACKEND_DIR))

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
# TEST 1: Missing dependency — not in reqs, not installed
# ═══════════════════════════════════════════════════════════════
print("\n=== TEST 1: Missing dependency ===")
issues = []
AgentService._check_third_party_dep(
    top_pkg='redis',
    rel_p='app.py',
    reqs_packages=set(),
    installed_packages={'flask', 'requests'},
    import_to_pip={},
    py_files={'app.py', 'models.py'},
    issues=issues,
)
check("one issue flagged", len(issues) == 1, f"issues={issues}")
check("issue mentions 'Missing dependency'", 'Missing dependency' in issues[0] if issues else '',
      f"issues={issues}")
check("issue mentions 'redis'", 'redis' in issues[0] if issues else '', f"issues={issues}")


# ═══════════════════════════════════════════════════════════════
# TEST 2: Uninstalled dependency — in reqs but not installed
# ═══════════════════════════════════════════════════════════════
print("\n=== TEST 2: Uninstalled dependency ===")
issues = []
AgentService._check_third_party_dep(
    top_pkg='redis',
    rel_p='app.py',
    reqs_packages={'redis'},
    installed_packages={'flask', 'requests'},
    import_to_pip={},
    py_files={'app.py'},
    issues=issues,
)
check("one issue flagged", len(issues) == 1, f"issues={issues}")
check("issue mentions 'Uninstalled dependency'", 'Uninstalled dependency' in issues[0] if issues else '',
      f"issues={issues}")


# ═══════════════════════════════════════════════════════════════
# TEST 3: Package OK — in reqs AND installed -> no issue
# ═══════════════════════════════════════════════════════════════
print("\n=== TEST 3: Package in reqs AND installed -> no issue ===")
issues = []
AgentService._check_third_party_dep(
    top_pkg='flask',
    rel_p='app.py',
    reqs_packages={'flask'},
    installed_packages={'flask', 'requests'},
    import_to_pip={},
    py_files={'app.py'},
    issues=issues,
)
check("no issues", len(issues) == 0, f"issues={issues}")


# ═══════════════════════════════════════════════════════════════
# TEST 4: Local file guard — auth.py exists -> skip
# ═══════════════════════════════════════════════════════════════
print("\n=== TEST 4: Local file guard (auth.py) ===")
issues = []
AgentService._check_third_party_dep(
    top_pkg='auth',
    rel_p='app.py',
    reqs_packages=set(),
    installed_packages=set(),
    import_to_pip={},
    py_files={'app.py', 'auth.py'},
    issues=issues,
)
check("no issues (auth.py is local)", len(issues) == 0, f"issues={issues}")


# ═══════════════════════════════════════════════════════════════
# TEST 5: Local package guard — auth/__init__.py exists -> skip
# ═══════════════════════════════════════════════════════════════
print("\n=== TEST 5: Local package guard (auth/__init__.py) ===")
issues = []
AgentService._check_third_party_dep(
    top_pkg='auth',
    rel_p='app.py',
    reqs_packages=set(),
    installed_packages=set(),
    import_to_pip={},
    py_files={'app.py', 'auth/__init__.py', 'auth/views.py'},
    issues=issues,
)
check("no issues (auth/ is local package)", len(issues) == 0, f"issues={issues}")


# ═══════════════════════════════════════════════════════════════
# TEST 6: Local subpackage guard — auth/ prefix exists -> skip
# ═══════════════════════════════════════════════════════════════
print("\n=== TEST 6: Local subpackage guard (files under auth/) ===")
issues = []
AgentService._check_third_party_dep(
    top_pkg='auth',
    rel_p='main.py',
    reqs_packages=set(),
    installed_packages=set(),
    import_to_pip={},
    py_files={'main.py', 'auth/login.py', 'auth/register.py'},
    issues=issues,
)
check("no issues (auth/ has .py files)", len(issues) == 0, f"issues={issues}")


# ═══════════════════════════════════════════════════════════════
# TEST 7: Dev tool guard — pytest, black, etc. skipped
# ═══════════════════════════════════════════════════════════════
print("\n=== TEST 7: Dev tool packages skipped ===")
dev_tools = ['pytest', 'black', 'flake8', 'mypy', 'pylint', 'coverage', 'ruff']
for tool in dev_tools:
    issues = []
    AgentService._check_third_party_dep(
        top_pkg=tool,
        rel_p='test_app.py',
        reqs_packages=set(),
        installed_packages=set(),
        import_to_pip={},
        py_files={'test_app.py'},
        issues=issues,
    )
    check(f"{tool} skipped (dev tool)", len(issues) == 0, f"issues={issues}")


# ═══════════════════════════════════════════════════════════════
# TEST 8: Import-to-pip mapping (PIL -> Pillow)
# ═══════════════════════════════════════════════════════════════
print("\n=== TEST 8: Import-to-pip mapping ===")
issues = []
AgentService._check_third_party_dep(
    top_pkg='PIL',
    rel_p='image_processor.py',
    reqs_packages={'pillow'},       # pip name
    installed_packages={'pillow'},   # pip name in installed
    import_to_pip={'pil': ['pillow', 'Pillow']},
    py_files={'image_processor.py'},
    issues=issues,
)
check("PIL mapped to Pillow -> no issue", len(issues) == 0, f"issues={issues}")


# ═══════════════════════════════════════════════════════════════
# TEST 9: Underscore/hyphen normalization
# ═══════════════════════════════════════════════════════════════
print("\n=== TEST 9: Underscore/hyphen normalization ===")
issues = []
AgentService._check_third_party_dep(
    top_pkg='flask_login',
    rel_p='auth.py',
    reqs_packages={'flask-login'},  # hyphen in reqs
    installed_packages={'flask_login'},  # underscore in installed
    import_to_pip={},
    py_files={'auth.py'},
    issues=issues,
)
check("flask_login matches flask-login -> no issue", len(issues) == 0, f"issues={issues}")


# ═══════════════════════════════════════════════════════════════
# TEST 10: No installed_packages (empty) — only checks reqs
# ═══════════════════════════════════════════════════════════════
print("\n=== TEST 10: Empty installed_packages ===")
issues = []
AgentService._check_third_party_dep(
    top_pkg='redis',
    rel_p='cache.py',
    reqs_packages={'redis'},
    installed_packages=set(),  # empty = can't check installed
    import_to_pip={},
    py_files={'cache.py'},
    issues=issues,
)
# When installed_packages is empty, the "Uninstalled" check is skipped
# (because `if installed_packages:` is False)
check("no 'Uninstalled' issue when installed_packages is empty",
      not any('Uninstalled' in i for i in issues), f"issues={issues}")


# ═══════════════════════════════════════════════════════════════
# TEST 11: Combination — multiple packages, mixed results
# ═══════════════════════════════════════════════════════════════
print("\n=== TEST 11: Mixed scenario ===")
issues = []
py_files = {'app.py', 'utils.py', 'models/__init__.py', 'models/user.py'}
reqs = {'flask', 'sqlalchemy', 'redis'}
installed = {'flask', 'sqlalchemy'}

# flask — in reqs, installed -> OK
AgentService._check_third_party_dep('flask', 'app.py', reqs, installed, {}, py_files, issues)
# sqlalchemy — in reqs, installed -> OK
AgentService._check_third_party_dep('sqlalchemy', 'models/user.py', reqs, installed, {}, py_files, issues)
# redis — in reqs, NOT installed -> Uninstalled
AgentService._check_third_party_dep('redis', 'app.py', reqs, installed, {}, py_files, issues)
# celery — NOT in reqs, NOT installed -> Missing
AgentService._check_third_party_dep('celery', 'app.py', reqs, installed, {}, py_files, issues)
# models — local package -> skip
AgentService._check_third_party_dep('models', 'app.py', reqs, installed, {}, py_files, issues)
# utils — local file -> skip
AgentService._check_third_party_dep('utils', 'app.py', reqs, installed, {}, py_files, issues)
# pytest — dev tool -> skip
AgentService._check_third_party_dep('pytest', 'test.py', reqs, installed, {}, py_files, issues)

check("exactly 2 issues", len(issues) == 2, f"issues={issues}")
check("redis flagged as Uninstalled", any('redis' in i and 'Uninstalled' in i for i in issues),
      f"issues={issues}")
check("celery flagged as Missing", any('celery' in i and 'Missing' in i for i in issues),
      f"issues={issues}")
check("models NOT flagged", not any('models' in i for i in issues), f"issues={issues}")
check("utils NOT flagged", not any("'utils'" in i for i in issues), f"issues={issues}")
check("pytest NOT flagged", not any('pytest' in i for i in issues), f"issues={issues}")


# ═══════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════
print(f"\n{'='*60}")
print(f"IntegrityCheck:  {passed} passed, {failed} failed")
print(f"{'='*60}")
sys.exit(1 if failed > 0 else 0)
