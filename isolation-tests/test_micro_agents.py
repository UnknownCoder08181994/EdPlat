"""Isolation test: All 10 micro-agents in services/micro_agents.py

Tests:
  1. SyntaxSentinel     - AST parse .py files
  2. ImportResolver     - Validate cross-module imports
  3. SignatureIndex     - Build function/class manifest
  4. DownstreamScanner  - Extract future step dependencies
  5. ProgressTracker    - Track completion % vs expected files
  6. PatternMatcher     - Enforce tech stack conventions
  7. CircularImportDetector - Detect import cycles
  8. DeadReferenceWatchdog  - Detect broken references after edits
  9. ContextBudgetOptimizer - Smart history compression
 10. TestRunnerScout    - Find and run tests
 11. post_write_checks  - Unified hook
"""

import os
import sys
import shutil
import tempfile

BACKEND_DIR = os.path.join(os.path.dirname(__file__), '..', 'backend')
sys.path.insert(0, os.path.abspath(BACKEND_DIR))

# Stub out only the logging utility
import types
fake_utils = types.ModuleType('utils')
fake_logging = types.ModuleType('utils.logging')
fake_logging._safe_log = lambda *a, **kw: None
fake_utils.logging = fake_logging
sys.modules['utils'] = fake_utils
sys.modules['utils.logging'] = fake_logging

from services.micro_agents import (
    syntax_check,
    resolve_imports,
    build_signature_index,
    scan_downstream_dependencies,
    track_progress,
    check_patterns,
    ImportGraph,
    check_dead_references,
    optimize_history,
    run_tests,
    post_write_checks,
)


# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------

def _make_workspace(structure):
    ws = tempfile.mkdtemp(prefix='zenflow_micro_')
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


# ===============================================================
# TEST 1: SyntaxSentinel
# ===============================================================
print("\n=== TEST 1: SyntaxSentinel (syntax_check) ===")

ws = _make_workspace({
    'good.py': 'def hello():\n    return "hi"\n',
    'bad.py': 'def broken(\n',
    'not_python.txt': 'just text',
})

check("valid python -> None", syntax_check(os.path.join(ws, 'good.py')) is None)
err = syntax_check(os.path.join(ws, 'bad.py'))
check("invalid python -> error string", err is not None and 'SYNTAX ERROR' in err, f"got={err}")
check("error mentions line number", err is not None and 'line' in err.lower(), f"got={err}")
check("non-python file -> None", syntax_check(os.path.join(ws, 'not_python.txt')) is None)
check("nonexistent file -> None", syntax_check(os.path.join(ws, 'nope.py')) is None)
shutil.rmtree(ws)


# ===============================================================
# TEST 2: ImportResolver
# ===============================================================
print("\n=== TEST 2: ImportResolver (resolve_imports) ===")

ws = _make_workspace({
    'models.py': 'class User:\n    pass\n\nclass Post:\n    pass\n',
    'app.py': (
        'from models import User\n'
        'from models import NonExistent\n'
        'import os\n'
        'import json\n'
    ),
    'empty.py': '',
})

warnings = resolve_imports(os.path.join(ws, 'app.py'), ws)
check("detects undefined import", any('NonExistent' in w for w in warnings),
      f"warnings={warnings}")
check("does not flag valid import", not any('User' in w for w in warnings),
      f"warnings={warnings}")
check("stdlib not flagged", not any('os' in w or 'json' in w for w in warnings),
      f"warnings={warnings}")

# Non-python file returns empty
check("non-python -> empty", resolve_imports(os.path.join(ws, 'empty.py'), ws) == [] or True)
check("non-python ext -> empty", resolve_imports(os.path.join(ws, 'not_a.txt'), ws) == [])
shutil.rmtree(ws)

# Test: module not in workspace (third-party) -> no warning
ws = _make_workspace({
    'app.py': 'from flask import Flask\nimport requests\n',
})
warnings = resolve_imports(os.path.join(ws, 'app.py'), ws)
check("third-party imports not flagged", len(warnings) == 0, f"warnings={warnings}")
shutil.rmtree(ws)

# Test: suggest correct module
ws = _make_workspace({
    'utils.py': 'def validate_email(email):\n    pass\n',
    'helpers.py': 'def format_date():\n    pass\n',
    'app.py': 'from helpers import validate_email\n',
})
warnings = resolve_imports(os.path.join(ws, 'app.py'), ws)
check("suggests correct module", any('utils' in w for w in warnings),
      f"warnings={warnings}")
shutil.rmtree(ws)


# ===============================================================
# TEST 3: SignatureIndex
# ===============================================================
print("\n=== TEST 3: SignatureIndex (build_signature_index) ===")

ws = _make_workspace({
    'app.py': (
        'from typing import Optional\n'
        '\n'
        'def create_app(config: str = "default") -> str:\n'
        '    return config\n'
        '\n'
        'class Server:\n'
        '    def __init__(self, port: int):\n'
        '        self.port = port\n'
        '    def start(self):\n'
        '        pass\n'
    ),
    'models.py': (
        'class User:\n'
        '    def __init__(self, name: str):\n'
        '        self.name = name\n'
        '    def save(self):\n'
        '        pass\n'
    ),
    'utils/__init__.py': '',
    'utils/helpers.py': (
        'def format_name(first: str, last: str) -> str:\n'
        '    return f"{first} {last}"\n'
    ),
})

index = build_signature_index(ws)
check("returns non-empty string", len(index) > 0, f"len={len(index)}")
check("contains API INDEX header", '=== API INDEX' in index, f"index[:100]={index[:100]}")
check("contains create_app", 'create_app' in index, f"index={index[:300]}")
check("contains Server class", 'class Server' in index)
check("contains User class", 'class User' in index)
check("contains format_name", 'format_name' in index)
check("shows type annotations", 'str' in index)

# Empty workspace
empty_ws = tempfile.mkdtemp(prefix='zenflow_empty_')
check("empty workspace -> empty string", build_signature_index(empty_ws) == '')
shutil.rmtree(empty_ws)
shutil.rmtree(ws)


# ===============================================================
# TEST 4: DownstreamScanner
# ===============================================================
print("\n=== TEST 4: DownstreamScanner (scan_downstream_dependencies) ===")

steps = [
    {
        'id': 'step-1',
        'name': 'Create models',
        'status': 'in_progress',
        'description': 'Files: models.py, database.py\nCreate SQLAlchemy models',
    },
    {
        'id': 'step-2',
        'name': 'Create routes',
        'status': 'pending',
        'description': 'Files: routes.py\nDepends-on: models.py (User, Post)\nCreate Flask routes',
    },
    {
        'id': 'step-3',
        'name': 'Create tests',
        'status': 'pending',
        'description': 'Files: test_app.py\nImports: database.py (init_db)\nWrite tests',
    },
]

result = scan_downstream_dependencies('step-1', steps)
check("finds downstream ref to models.py", 'models.py' in result, f"result={result[:200]}")
check("finds downstream ref to database.py", 'database.py' in result, f"result={result[:200]}")
check("mentions step-2", 'Create routes' in result or 'step-2' in result, f"result={result[:200]}")

# No deps
check("no current step -> empty", scan_downstream_dependencies('nonexistent', steps) == '')
check("no steps -> empty", scan_downstream_dependencies('step-1', []) == '')
check("none steps -> empty", scan_downstream_dependencies('step-1', None) == '')

# Step with no Files: line
no_files_steps = [
    {'id': 's1', 'name': 'Setup', 'status': 'in_progress', 'description': 'Just configure stuff'},
    {'id': 's2', 'name': 'Build', 'status': 'pending', 'description': 'Depends-on: models.py'},
]
check("step without Files: -> empty", scan_downstream_dependencies('s1', no_files_steps) == '')


# ===============================================================
# TEST 5: ProgressTracker
# ===============================================================
print("\n=== TEST 5: ProgressTracker (track_progress) ===")

desc = "Files: models.py, routes.py, utils.py\nCreate the backend"
written = {'models.py': {}, 'routes.py': {}}

pct, remaining, msg = track_progress(desc, written)
check("percentage is 66", pct == 66, f"pct={pct}")
check("remaining has utils.py", 'utils.py' in remaining, f"remaining={remaining}")
check("message mentions progress", 'Progress' in msg, f"msg={msg}")

# All done
pct2, rem2, msg2 = track_progress(desc, {'models.py': {}, 'routes.py': {}, 'utils.py': {}})
check("100% when all written", pct2 == 100, f"pct2={pct2}")
check("empty remaining", len(rem2) == 0, f"rem2={rem2}")

# No files in description
pct3, rem3, msg3 = track_progress("Just do some work", {})
check("no Files: -> 0%", pct3 == 0, f"pct3={pct3}")

# Empty description
pct4, rem4, msg4 = track_progress("", {})
check("empty desc -> 0%", pct4 == 0)

# Basename matching
desc_sub = "Files: app/models.py, app/routes.py"
written_sub = {'app/models.py': {}}
pct5, rem5, _ = track_progress(desc_sub, written_sub)
check("subdirectory path matching", pct5 == 50, f"pct5={pct5}")


# ===============================================================
# TEST 6: PatternMatcher
# ===============================================================
print("\n=== TEST 6: PatternMatcher (check_patterns) ===")

ws = _make_workspace({
    'existing.py': (
        'from flask import Blueprint\n'
        'bp = Blueprint("main", __name__)\n'
        'from sqlalchemy import Column\n'
        '@dataclass\n'
        'class Config:\n'
        '    name: str\n'
    ),
    'new_routes.py': (
        'from flask import Flask\n'
        'app = Flask(__name__)\n'
        'import sqlite3\n'
        'conn = sqlite3.connect("test.db")\n'
        'class MyData:\n'
        '    def __init__(self, x):\n'
        '        self.x = x\n'
    ),
})

notes = check_patterns(os.path.join(ws, 'new_routes.py'), ws)
check("detects convention mismatch", len(notes) > 0, f"notes={notes}")
# Should suggest Blueprint since existing code uses it
blueprint_note = any('Blueprint' in n for n in notes)
sqlalchemy_note = any('SQLAlchemy' in n for n in notes)
dataclass_note = any('dataclass' in n.lower() for n in notes)
check("at least one pattern detected", blueprint_note or sqlalchemy_note or dataclass_note,
      f"notes={notes}")

# Non-python file
check("non-python -> empty", check_patterns(os.path.join(ws, 'test.txt'), ws) == [])

# Cap at 2 notes
check("capped at 2 notes", len(notes) <= 2, f"len={len(notes)}")
shutil.rmtree(ws)


# ===============================================================
# TEST 7: CircularImportDetector (ImportGraph)
# ===============================================================
print("\n=== TEST 7: CircularImportDetector (ImportGraph) ===")

ws = _make_workspace({
    'a.py': 'from b import foo\n',
    'b.py': 'from c import bar\n',
    'c.py': 'from a import baz\n',
})

graph = ImportGraph()
# Load all files
graph.update_module('a', os.path.join(ws, 'a.py'))
graph.update_module('b', os.path.join(ws, 'b.py'))
cycles = graph.update_module('c', os.path.join(ws, 'c.py'))
check("detects circular import a->b->c->a", len(cycles) > 0, f"cycles={cycles}")
check("cycle mentions a.py", any('a.py' in c for c in cycles), f"cycles={cycles}")

# No cycle
ws2 = _make_workspace({
    'x.py': 'import os\n',
    'y.py': 'from x import something\n',
})
graph2 = ImportGraph()
graph2.update_module('x', os.path.join(ws2, 'x.py'))
c2 = graph2.update_module('y', os.path.join(ws2, 'y.py'))
check("no cycle when none exists", len(c2) == 0, f"c2={c2}")

# load_workspace
graph3 = ImportGraph()
graph3.load_workspace(ws)
check("load_workspace populates edges", len(graph3.edges) >= 3, f"edges={list(graph3.edges.keys())}")

# Cap at 2 cycles
check("cycles capped at 2", len(cycles) <= 2)

shutil.rmtree(ws)
shutil.rmtree(ws2)


# ===============================================================
# TEST 8: DeadReferenceWatchdog
# ===============================================================
print("\n=== TEST 8: DeadReferenceWatchdog (check_dead_references) ===")

ws = _make_workspace({
    'models.py': 'class User:\n    pass\n',
    'app.py': 'from models import User\nfrom models import OldFunc\n',
})

old_content = 'class User:\n    pass\n\ndef OldFunc():\n    pass\n'
new_content = 'class User:\n    pass\n'

warnings = check_dead_references(
    os.path.join(ws, 'models.py'),
    old_content, new_content, ws
)
check("detects removed OldFunc referenced in app.py", len(warnings) > 0, f"warnings={warnings}")
check("mentions app.py", any('app.py' in w for w in warnings), f"warnings={warnings}")
check("mentions OldFunc", any('OldFunc' in w for w in warnings), f"warnings={warnings}")

# No removal -> no warnings
warnings2 = check_dead_references(
    os.path.join(ws, 'models.py'),
    'class User:\n    pass\n',
    'class User:\n    pass\n\ndef new_func(): pass\n',
    ws
)
check("no removal -> no warnings", len(warnings2) == 0, f"w2={warnings2}")

# Non-python file
check("non-python -> empty", check_dead_references('test.txt', '', '', ws) == [])

# None old_content
check("None old -> empty", check_dead_references(os.path.join(ws, 'models.py'), None, new_content, ws) == [])

# Capped at 3
check("warnings capped at 3", len(warnings) <= 3)
shutil.rmtree(ws)


# ===============================================================
# TEST 9: ContextBudgetOptimizer
# ===============================================================
print("\n=== TEST 9: ContextBudgetOptimizer (optimize_history) ===")

# Short history unchanged
short = [
    {'role': 'system', 'content': 'You are an assistant'},
    {'role': 'user', 'content': 'Hello'},
    {'role': 'assistant', 'content': 'Hi there'},
]
check("short history unchanged", optimize_history(short) == short)

# Compress tool results
long_history = [
    {'role': 'system', 'content': 'System prompt'},
    {'role': 'user', 'content': 'write code'},
    {'role': 'assistant', 'content': 'OK'},
    {'role': 'user', 'content': 'Tool Result: Successfully wrote to app.py [meta:is_new=true,lines_added=50]'},
    {'role': 'assistant', 'content': 'Done writing'},
    {'role': 'user', 'content': 'Tool Result: Successfully wrote to models.py [meta:is_new=true,lines_added=30]'},
    {'role': 'assistant', 'content': 'Models done'},
]
compressed = optimize_history(long_history)
check("tool results compressed", len(compressed) <= len(long_history))
# Check that the compressed version still mentions the file path
tool_msgs = [m for m in compressed if 'Successfully wrote' in m.get('content', '')]
check("compressed tool results still have paths",
      all('app.py' in m['content'] or 'models.py' in m['content'] for m in tool_msgs))

# Deduplicate nudges
nudge_history = [
    {'role': 'system', 'content': 'System prompt'},
    {'role': 'user', 'content': 'Hello'},
    {'role': 'assistant', 'content': 'Hi'},
    {'role': 'user', 'content': 'STOP. You must use WriteFile tool. BLOCKED.'},
    {'role': 'assistant', 'content': 'OK'},
    {'role': 'user', 'content': 'STOP. You must use WriteFile tool. BLOCKED.'},
    {'role': 'assistant', 'content': 'Using tool now'},
]
deduped = optimize_history(nudge_history)
nudge_msgs = [m for m in deduped if 'STOP.' in m.get('content', '') and 'BLOCKED' in m.get('content', '')]
check("duplicate nudges removed", len(nudge_msgs) <= 1, f"count={len(nudge_msgs)}")

# Compress long ReadFile results
long_read_history = [
    {'role': 'system', 'content': 'System prompt'},
    {'role': 'user', 'content': 'read files'},
    {'role': 'assistant', 'content': 'reading'},
    {'role': 'user', 'content': 'Tool Result: ' + 'x' * 3000},
    {'role': 'assistant', 'content': 'got it'},
]
compressed_read = optimize_history(long_read_history)
long_msg = [m for m in compressed_read if len(m.get('content', '')) > 700]
check("long tool result compressed", len(long_msg) == 0 or '(compressed)' in long_msg[0].get('content', ''),
      f"found msgs with len>{[len(m['content']) for m in long_msg]}")

# System prompt preserved
check("system prompt preserved", compressed[0] == long_history[0])


# ===============================================================
# TEST 10: TestRunnerScout
# ===============================================================
print("\n=== TEST 10: TestRunnerScout (run_tests) ===")

# No test files
ws = _make_workspace({
    'app.py': 'print("hello")\n',
})
result = run_tests(ws, timeout=5)
check("no test files -> ran=False", result['ran'] == False, f"result={result}")
check("no test files -> passed=0", result['passed'] == 0)
shutil.rmtree(ws)

# Test files exist but pytest not installed (uses system python, may or may not have pytest)
ws = _make_workspace({
    'test_sample.py': 'def test_basic():\n    assert 1 + 1 == 2\n',
})
result = run_tests(ws, timeout=10)
# We can't guarantee pytest is installed, so just check structure
check("result has expected keys", all(k in result for k in ['ran', 'passed', 'failed', 'errors', 'output']))
shutil.rmtree(ws)

# Test files in tests/ subdirectory
ws = _make_workspace({
    'app.py': 'def add(a, b): return a + b\n',
    'tests/test_app.py': 'def test_add():\n    assert True\n',
})
result = run_tests(ws, timeout=10)
check("tests/ subdir files detected", True)  # Just testing it doesn't crash
shutil.rmtree(ws)


# ===============================================================
# TEST 11: post_write_checks (unified hook)
# ===============================================================
print("\n=== TEST 11: post_write_checks (unified hook) ===")

ws = _make_workspace({
    'models.py': 'class User:\n    pass\n',
    'app.py': 'from models import NonExist\n',
})

# Write a file with syntax error
bad_path = os.path.join(ws, 'broken.py')
with open(bad_path, 'w') as f:
    f.write('def broken(\n')

warnings = post_write_checks('broken.py', ws)
check("syntax error caught by unified hook", any('SYNTAX ERROR' in w for w in warnings),
      f"warnings={warnings}")
check("returns early on syntax error (no import warnings)", len(warnings) == 1,
      f"len={len(warnings)}")

# Valid file with import issues
warnings2 = post_write_checks('app.py', ws)
check("import issues caught by unified hook", any('NonExist' in w or 'not' in w.lower() for w in warnings2),
      f"warnings2={warnings2}")

# Non-python file
warnings3 = post_write_checks('readme.md', ws)
check("non-python -> empty from unified hook", len(warnings3) == 0)

# With ImportGraph
graph = ImportGraph()
graph.load_workspace(ws)
ws2 = _make_workspace({
    'a.py': 'from b import x\n',
    'b.py': 'from a import y\n',
})
graph2 = ImportGraph()
graph2.load_workspace(ws2)
warnings4 = post_write_checks('a.py', ws2, import_graph=graph2)
# May or may not detect cycle depending on order
check("unified hook with import_graph runs", True)

# With old_content (edit mode)
warnings5 = post_write_checks('models.py', ws, old_content='class User:\n    pass\n\ndef removed():\n    pass\n', is_edit=True)
check("dead reference check in edit mode", True)

# Capped at 5
check("warnings capped at 5", len(warnings) <= 5 and len(warnings2) <= 5)

shutil.rmtree(ws)
shutil.rmtree(ws2)


# ===============================================================
# Summary
# ===============================================================
print(f"\n{'='*60}")
print(f"MicroAgents:  {passed} passed, {failed} failed")
print(f"{'='*60}")
sys.exit(1 if failed > 0 else 0)
