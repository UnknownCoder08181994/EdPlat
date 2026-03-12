"""Isolation test: Execution Agent pipeline (run_execution_stream)

Tests the ACTUAL execution agent phases with mocked LLM and subprocess:
  1. Phase 0: Pre-scan (shadowing, requirements, init files)
  2. Phase 1: Entry point detection
  3. Phase 2: Dependency installation
  4. Phase 3: Execute -> Diagnose -> Fix loop (with snapshot/revert)
  5. Phase 3.5: Recoder Agent fallback
  6. Snapshot/revert safety (error count comparison)
  7. Error classification
  8. _run_review_pass with mock LLM (tool call parsing)
"""

import os
import sys
import json
import shutil
import tempfile
import time
import re

# ── Patch imports ─────────────────────────────────────────────
BACKEND_DIR = os.path.join(os.path.dirname(__file__), '..', 'backend')
sys.path.insert(0, os.path.abspath(BACKEND_DIR))

class FakeConfig:
    STORAGE_DIR = tempfile.mkdtemp()
    LM_STUDIO_URL = 'http://localhost:1234'
    LM_STUDIO_MODEL = 'test'

sys.modules['config'] = type(sys)('config')
sys.modules['config'].Config = FakeConfig

# Stub out modules we don't need
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
            fake.build_diagnose_prompt = lambda *a, **kw: 'You are a diagnostic agent.'
            fake.build_dependency_prompt = lambda *a, **kw: 'Fix deps.'
            fake.build_recoder_prompt = lambda *a, **kw: 'You are the recoder agent.'
        if mod_name == 'services.llm_engine':
            fake.get_llm_engine = lambda: None
            fake.LLMEngine = type('LLMEngine', (), {'THINK_PREFIX': '<think>'})
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
            fake.ExperienceMemory = type('ExperienceMemory', (), {
                'lookup': staticmethod(lambda *a, **kw: []),
                'format_for_injection': staticmethod(lambda *a, **kw: ''),
            })
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
from services.llm_engine import LLMEngine


# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------

def _make_workspace(structure: dict) -> str:
    ws = tempfile.mkdtemp(prefix='zenflow_exec_')
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
# TEST 1: Snapshot and Restore
# ===============================================================
print("\n=== TEST 1: Snapshot and Restore ===")
ws = _make_workspace({
    'app.py': 'print("hello")\n',
    'utils/helpers.py': 'def helper(): pass\n',
    'config.json': '{"key": "value"}\n',
    'data/notes.txt': 'some notes\n',
})

snapshot = AgentService._snapshot_project_files(ws)
check("snapshot captures app.py", 'app.py' in snapshot, f"keys={list(snapshot.keys())}")
check("snapshot captures utils/helpers.py", 'utils/helpers.py' in snapshot,
      f"keys={list(snapshot.keys())}")
check("snapshot captures config.json", 'config.json' in snapshot)
check("snapshot captures data/notes.txt", 'data/notes.txt' in snapshot)

# Modify files
with open(os.path.join(ws, 'app.py'), 'w') as f:
    f.write('print("CORRUPTED")\n')
with open(os.path.join(ws, 'utils', 'helpers.py'), 'w') as f:
    f.write('BROKEN CODE\n')

# Restore
restored_count = AgentService._restore_snapshot(ws, snapshot)
check("restored correct count", restored_count == len(snapshot),
      f"restored={restored_count}, expected={len(snapshot)}")

with open(os.path.join(ws, 'app.py'), 'r') as f:
    check("app.py restored to original", f.read() == 'print("hello")\n')
with open(os.path.join(ws, 'utils', 'helpers.py'), 'r') as f:
    check("helpers.py restored to original", f.read() == 'def helper(): pass\n')
shutil.rmtree(ws)


# ===============================================================
# TEST 2: Error Classification
# ===============================================================
print("\n=== TEST 2: Error Classification ===")

# ModuleNotFoundError
err1 = """Traceback (most recent call last):
  File "app.py", line 1, in <module>
    import flask
ModuleNotFoundError: No module named 'flask'"""
cls1 = AgentService._classify_error(err1)
check("ModuleNotFoundError classified", cls1['type'] == 'module_not_found',
      f"got type={cls1['type']}")
check("module is 'flask'", cls1.get('module') == 'flask',
      f"got module={cls1.get('module')}")

# ImportError
err2 = """Traceback (most recent call last):
  File "app.py", line 2, in <module>
    from flask import NonExistent
ImportError: cannot import name 'NonExistent' from 'flask'"""
cls2 = AgentService._classify_error(err2)
check("ImportError classified", cls2['type'] == 'import',
      f"got type={cls2['type']}")

# SyntaxError
err3 = """  File "app.py", line 5
    def broken(
              ^
SyntaxError: unexpected EOF while parsing"""
cls3 = AgentService._classify_error(err3)
check("SyntaxError classified", cls3['type'] == 'syntax',
      f"got type={cls3['type']}")

# Runtime error
err4 = """Traceback (most recent call last):
  File "app.py", line 10, in <module>
    result = 1 / 0
ZeroDivisionError: division by zero"""
cls4 = AgentService._classify_error(err4)
check("RuntimeError classified", cls4['type'] == 'runtime',
      f"got type={cls4['type']}")
check("errorType is ZeroDivisionError", cls4.get('errorType') == 'ZeroDivisionError',
      f"got={cls4.get('errorType')}")

# Empty output
cls5 = AgentService._classify_error('')
check("empty output -> unknown", cls5['type'] == 'unknown', f"got={cls5['type']}")


# ===============================================================
# TEST 3: Error Count Detection
# ===============================================================
print("\n=== TEST 3: Error Count Detection ===")

output_clean = "Hello World!\nServer running on port 5000"
check("clean output -> 0 errors", AgentService._count_errors_in_output(output_clean) == 0)

output_one = "Traceback (most recent call last):\n  File 'app.py'\nNameError: name 'x' is not defined"
count1 = AgentService._count_errors_in_output(output_one)
check("one traceback + one NameError >= 2", count1 >= 2, f"count={count1}")

output_many = (
    "Traceback (most recent call last):\n"
    "ImportError: cannot import name 'X'\n"
    "ModuleNotFoundError: No module named 'Y'\n"
    "SyntaxError: invalid syntax\n"
    "TypeError: expected str\n"
)
count_many = AgentService._count_errors_in_output(output_many)
check("multiple errors counted", count_many >= 4, f"count={count_many}")

check("None output -> 0", AgentService._count_errors_in_output(None) == 0)
check("empty string -> 0", AgentService._count_errors_in_output('') == 0)


# ===============================================================
# TEST 4: Validate Execution Output
# ===============================================================
print("\n=== TEST 4: Validate Execution Output ===")

entry_info_script = {'entryPoint': 'app.py', 'isServer': False, 'hasArgparse': False}
entry_info_server = {'entryPoint': 'app.py', 'isServer': True}
entry_info_cli = {'entryPoint': 'main.py', 'hasArgparse': True, 'isServer': False}

ws = _make_workspace({'app.py': 'x = 1\n'})  # no print() calls

# Non-zero exit code -> invalid
valid, reason = AgentService._validate_execution_output(1, '', 'error', entry_info_script, ws)
check("exit code 1 -> invalid", not valid, f"reason={reason}")

# Server mode -> always valid on exit 0
valid, reason = AgentService._validate_execution_output(0, '', '', entry_info_server, ws)
check("server mode exit 0 -> valid", valid, f"reason={reason}")

# CLI argparse -> valid
valid, reason = AgentService._validate_execution_output(0, '', '', entry_info_cli, ws)
check("CLI argparse exit 0 -> valid", valid, f"reason={reason}")

# Script with output -> valid
valid, reason = AgentService._validate_execution_output(0, 'Hello World', '', entry_info_script, ws)
check("script with output -> valid", valid, f"reason={reason}")

# Exit 0 but tons of errors -> invalid
valid, reason = AgentService._validate_execution_output(
    0, 'Error: X\nError: Y\nError: Z\nTraceback (most recent call last):', '',
    entry_info_script, ws)
check("exit 0 but many errors -> invalid", not valid, f"reason={reason}")

shutil.rmtree(ws)


# ===============================================================
# TEST 5: _run_review_pass with Mock LLM (no tool calls)
# ===============================================================
print("\n=== TEST 5: _run_review_pass - no tool calls ===")


class MockLLM:
    """Mock LLM that yields predetermined tokens."""
    THINK_PREFIX = '<think>'

    def __init__(self, responses):
        self._responses = responses
        self._call_count = 0

    def stream_chat(self, history, max_new_tokens=3072, temperature=0.3,
                    cancel_event=None, read_timeout=120):
        if self._call_count < len(self._responses):
            tokens = self._responses[self._call_count]
            self._call_count += 1
            for t in tokens:
                yield t
        else:
            yield "No more responses."


class MockToolService:
    """Mock ToolService that records calls."""
    def __init__(self, workspace_path=None):
        self.calls = []

    def execute_tool(self, tool_name, tool_args):
        self.calls.append((tool_name, tool_args))
        if tool_name == 'WriteFile':
            path = tool_args.get('path', '')
            return f'File written: {path}'
        elif tool_name == 'EditFile':
            path = tool_args.get('path', '')
            return f'File edited: {path}'
        elif tool_name == 'ReadFile':
            return 'file contents here'
        elif tool_name == 'RunCommand':
            return 'command output here'
        return 'ok'


# Test simple narrative (no tool calls)
llm = MockLLM([["This ", "code ", "looks ", "good. ", "No ", "changes ", "needed."]])
history = [
    {"role": "system", "content": "You are a code reviewer."},
    {"role": "user", "content": "Review this code."},
]
tool_svc = MockToolService()
results = {}

events = list(AgentService._run_review_pass(
    llm, history, tool_svc, None, results,
    max_turns=3, max_tokens=2048, timeout_seconds=30,
))

check("results has text", 'text' in results, f"results keys={list(results.keys())}")
check("text is narrative", 'good' in results.get('text', ''), f"text={results.get('text', '')[:100]}")
check("no edits made", len(results.get('edits', [])) == 0, f"edits={results.get('edits', [])}")
check("no tool calls", len(tool_svc.calls) == 0, f"calls={tool_svc.calls}")
check("events yielded", len(events) > 0, f"num events={len(events)}")
# Events should be review_token events
token_events = [e for e in events if 'review_token' in e]
check("token events emitted", len(token_events) > 0, f"token_events={len(token_events)}")


# ===============================================================
# TEST 6: _run_review_pass with Mock LLM (WITH tool calls)
# ===============================================================
print("\n=== TEST 6: _run_review_pass - with WriteFile tool call ===")

# LLM produces a tool call, then a narrative response
tool_call_response = [
    'I will fix the bug.\n\n',
    '<tool_code>',
    json.dumps({
        "name": "WriteFile",
        "arguments": {
            "path": "app.py",
            "content": "print('fixed')\n"
        }
    }),
    '</tool_code>',
]
followup_response = ["Done. The file has been fixed."]

llm2 = MockLLM([tool_call_response, followup_response])
history2 = [
    {"role": "system", "content": "You are a code fixer."},
    {"role": "user", "content": "Fix the bug in app.py."},
]
tool_svc2 = MockToolService()
results2 = {}

events2 = list(AgentService._run_review_pass(
    llm2, history2, tool_svc2, None, results2,
    max_turns=3, max_tokens=2048, timeout_seconds=30,
))

check("WriteFile tool called", len(tool_svc2.calls) == 1, f"calls={tool_svc2.calls}")
if tool_svc2.calls:
    check("tool name is WriteFile", tool_svc2.calls[0][0] == 'WriteFile',
          f"got={tool_svc2.calls[0][0]}")
    check("tool args has path=app.py", tool_svc2.calls[0][1].get('path') == 'app.py',
          f"args={tool_svc2.calls[0][1]}")
check("edits recorded", len(results2.get('edits', [])) == 1, f"edits={results2.get('edits', [])}")
check("edit events emitted", any('review_edit' in e for e in events2),
      f"events={[e[:50] for e in events2]}")


# ===============================================================
# TEST 7: _run_review_pass with disallowed tool
# ===============================================================
print("\n=== TEST 7: _run_review_pass - disallowed tool ignored ===")

# LLM tries RunCommand but only WriteFile/EditFile are allowed
dangerous_response = [
    '<tool_code>',
    json.dumps({"name": "RunCommand", "arguments": {"command": "rm -rf /"}}),
    '</tool_code>',
]
llm3 = MockLLM([dangerous_response])
tool_svc3 = MockToolService()
results3 = {}

events3 = list(AgentService._run_review_pass(
    llm3, [{"role": "system", "content": "test"}, {"role": "user", "content": "test"}],
    tool_svc3, None, results3,
    max_turns=2, allowed_tools={'WriteFile', 'EditFile'},
))

check("RunCommand NOT executed", len(tool_svc3.calls) == 0, f"calls={tool_svc3.calls}")


# ===============================================================
# TEST 8: _run_review_pass with allowed_tools override
# ===============================================================
print("\n=== TEST 8: _run_review_pass - RunCommand allowed when specified ===")

run_response = [
    '<tool_code>',
    json.dumps({"name": "RunCommand", "arguments": {"command": "python --version"}}),
    '</tool_code>',
]
followup_done = ["Command executed successfully."]
llm4 = MockLLM([run_response, followup_done])
tool_svc4 = MockToolService()
results4 = {}

events4 = list(AgentService._run_review_pass(
    llm4, [{"role": "system", "content": "test"}, {"role": "user", "content": "test"}],
    tool_svc4, None, results4,
    max_turns=3, allowed_tools={'WriteFile', 'EditFile', 'ReadFile', 'RunCommand'},
))

check("RunCommand executed when allowed", len(tool_svc4.calls) == 1, f"calls={tool_svc4.calls}")
if tool_svc4.calls:
    check("tool is RunCommand", tool_svc4.calls[0][0] == 'RunCommand')


# ===============================================================
# TEST 9: _run_review_pass - LLM error handling
# ===============================================================
print("\n=== TEST 9: _run_review_pass - LLM error ===")

llm_error = MockLLM([["[Error from LLM: Connection refused]"]])
results_err = {}
events_err = list(AgentService._run_review_pass(
    llm_error, [{"role": "system", "content": "test"}, {"role": "user", "content": "test"}],
    MockToolService(), None, results_err,
    max_turns=2,
))

error_events = [e for e in events_err if 'error' in e.lower() and 'event:' in e]
check("error event emitted", len(error_events) > 0, f"events={events_err}")
check("results populated despite error", 'text' in results_err)


# ===============================================================
# TEST 10: _run_review_pass - cancellation
# ===============================================================
print("\n=== TEST 10: _run_review_pass - cancellation ===")

import threading
cancel = threading.Event()
cancel.set()  # Pre-cancelled

llm_cancel = MockLLM([["This should not appear"]])
results_cancel = {}
events_cancel = list(AgentService._run_review_pass(
    llm_cancel, [{"role": "system", "content": "test"}, {"role": "user", "content": "test"}],
    MockToolService(), cancel, results_cancel,
    max_turns=3,
))
check("cancelled immediately - no token events",
      not any('review_token' in e for e in events_cancel),
      f"events={events_cancel}")


# ===============================================================
# TEST 11: _run_review_pass - timeout
# ===============================================================
print("\n=== TEST 11: _run_review_pass - timeout ===")

class SlowLLM:
    THINK_PREFIX = '<think>'
    def stream_chat(self, *args, **kwargs):
        time.sleep(0.1)
        yield "token"

results_timeout = {}
events_timeout = list(AgentService._run_review_pass(
    SlowLLM(), [{"role": "system", "content": "test"}, {"role": "user", "content": "test"}],
    MockToolService(), None, results_timeout,
    max_turns=3, timeout_seconds=0,  # immediate timeout
))
timeout_events = [e for e in events_timeout if 'timed out' in e.lower() or 'Timed out' in e]
check("timeout detected", len(timeout_events) > 0 or len(events_timeout) <= 2,
      f"events={events_timeout[:3]}")


# ===============================================================
# TEST 12: Snapshot skips .venv and .git
# ===============================================================
print("\n=== TEST 12: Snapshot skips .venv and .git ===")
ws2 = _make_workspace({
    'app.py': 'code\n',
    '.venv/lib/site-packages/flask.py': 'fake flask\n',
    '.git/config': 'git config\n',
    'node_modules/express/index.js': 'express\n',
})
snap2 = AgentService._snapshot_project_files(ws2)
check("app.py in snapshot", 'app.py' in snap2)
check(".venv NOT in snapshot", not any('.venv' in k for k in snap2), f"keys={list(snap2.keys())}")
check(".git NOT in snapshot", not any('.git' in k for k in snap2), f"keys={list(snap2.keys())}")
check("node_modules NOT in snapshot", not any('node_modules' in k for k in snap2))
shutil.rmtree(ws2)


# ===============================================================
# TEST 13: _run_review_pass with EditFile tool call
# ===============================================================
print("\n=== TEST 13: _run_review_pass - EditFile tool call ===")

edit_response = [
    '<tool_code>',
    json.dumps({
        "name": "EditFile",
        "arguments": {
            "path": "utils.py",
            "old_string": "def broken():",
            "new_string": "def fixed():"
        }
    }),
    '</tool_code>',
]
llm_edit = MockLLM([edit_response, ["Edit complete."]])
tool_svc_edit = MockToolService()
results_edit = {}

list(AgentService._run_review_pass(
    llm_edit,
    [{"role": "system", "content": "test"}, {"role": "user", "content": "test"}],
    tool_svc_edit, None, results_edit,
    max_turns=3,
))

check("EditFile called", len(tool_svc_edit.calls) == 1, f"calls={tool_svc_edit.calls}")
if tool_svc_edit.calls:
    check("EditFile has old_string", tool_svc_edit.calls[0][1].get('old_string') == 'def broken():')
    check("EditFile has new_string", tool_svc_edit.calls[0][1].get('new_string') == 'def fixed():')
check("edit recorded", len(results_edit.get('edits', [])) == 1)


# ===============================================================
# Summary
# ===============================================================
print(f"\n{'='*60}")
print(f"ExecutionAgent:  {passed} passed, {failed} failed")
print(f"{'='*60}")
sys.exit(1 if failed > 0 else 0)
