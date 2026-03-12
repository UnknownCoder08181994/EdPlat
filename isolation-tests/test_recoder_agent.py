"""Isolation test: Recoder Agent (_run_recoder_agent)

Tests the ACTUAL recoder agent Phase 3.5 with mocked LLM:
  1. Reads all project files correctly
  2. Builds error history from exec_history
  3. Calls LLM via _run_review_pass with correct tools
  4. On success: validates by re-running project
  5. On failure (error count increases): reverts snapshot
  6. Yields SSE events throughout
  7. Final yield is {'success': bool}
"""

import os
import sys
import json
import shutil
import tempfile
import time
import threading
import unittest.mock as mock

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
            fake.build_diagnose_prompt = lambda *a, **kw: 'diagnose'
            fake.build_dependency_prompt = lambda *a, **kw: 'deps'
            fake.build_recoder_prompt = lambda *a, **kw: 'You are the recoder. Fix all broken files.'
        if mod_name == 'services.llm_engine':
            fake.get_llm_engine = lambda: None
            fake.LLMEngine = type('LLMEngine', (), {'THINK_PREFIX': '<think>'})
        if mod_name == 'services.task_service':
            fake.TaskService = type('TaskService', (), {})
        if mod_name == 'services.tool_service':
            class _FakeToolService:
                def __init__(self, *args, **kwargs):
                    # First positional arg or workspace_path kwarg is the workspace
                    self._workspace = kwargs.get('workspace_path') or (args[0] if args else None)
                def execute_tool(self, tool_name, tool_args):
                    if tool_name == 'WriteFile':
                        path = tool_args.get('path', '')
                        content = tool_args.get('content', '')
                        # Actually write the file so snapshot/revert works
                        if self._workspace and path:
                            full = os.path.join(self._workspace, path)
                            os.makedirs(os.path.dirname(full), exist_ok=True)
                            with open(full, 'w') as f:
                                f.write(content)
                        return f'File written: {path}'
                    elif tool_name == 'EditFile':
                        return f'File edited: {tool_args.get("path", "")}'
                    elif tool_name == 'ReadFile':
                        return 'contents'
                    elif tool_name == 'RunCommand':
                        return 'ok'
                    return 'ok'
            fake.ToolService = _FakeToolService
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


# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------

def _make_workspace(structure: dict) -> str:
    ws = tempfile.mkdtemp(prefix='zenflow_recoder_')
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


class MockLLM:
    THINK_PREFIX = '<think>'
    def __init__(self, responses):
        self._responses = responses
        self._idx = 0
    def stream_chat(self, *args, **kwargs):
        if self._idx < len(self._responses):
            tokens = self._responses[self._idx]
            self._idx += 1
            for t in tokens:
                yield t
        else:
            yield "DONE"


# ===============================================================
# TEST 1: Snapshot captures all files before recoder runs
# ===============================================================
print("\n=== TEST 1: Snapshot captures project files ===")
ws = _make_workspace({
    'app.py': 'from flask import Flask\napp = Flask(__name__)\n',
    'models.py': 'class User:\n    pass\n',
    'requirements.txt': 'flask\n',
    'templates/index.html': '<h1>Hello</h1>\n',
})

snapshot = AgentService._snapshot_project_files(ws)
check("app.py in snapshot", 'app.py' in snapshot)
check("models.py in snapshot", 'models.py' in snapshot)
check("requirements.txt in snapshot", 'requirements.txt' in snapshot)
check("templates/index.html in snapshot", 'templates/index.html' in snapshot)
check("snapshot has correct content", snapshot.get('app.py', '').startswith('from flask'))
shutil.rmtree(ws)


# ===============================================================
# TEST 2: Recoder with mock LLM that writes a fix
# ===============================================================
print("\n=== TEST 2: Recoder agent - LLM writes fix via WriteFile ===")
ws = _make_workspace({
    'app.py': 'pritn("hello")  # typo\n',
    'requirements.txt': '',
})

# Mock the LLM to return a WriteFile tool call
fix_content = 'print("hello")\n'
llm_response = [
    'I see the typo. Let me fix it.\n\n',
    '<tool_code>',
    json.dumps({
        "name": "WriteFile",
        "arguments": {"path": "app.py", "content": fix_content}
    }),
    '</tool_code>',
]
done_response = ["DONE. The typo has been fixed."]

mock_llm = MockLLM([llm_response, done_response])

# We need to mock get_llm_engine and _run_project_subprocess
# The recoder calls get_llm_engine() internally, and _run_project_subprocess to validate
with mock.patch('services.agent_service.get_llm_engine', return_value=mock_llm):
    # Mock subprocess: first call returns error (pre-fix), second returns success (post-fix)
    subprocess_results = iter([
        (1, '', 'SyntaxError: invalid syntax'),  # Before fix validation
        (0, 'hello', ''),                         # After fix validation
    ])

    def mock_subprocess(command, workspace_path, timeout=30):
        try:
            return next(subprocess_results)
        except StopIteration:
            return (0, 'hello', '')

    with mock.patch.object(AgentService, '_run_project_subprocess', side_effect=mock_subprocess):
        events = []
        final_result = None

        for item in AgentService._run_recoder_agent(
            workspace_path=ws,
            entry_point='app.py',
            command='python app.py',
            is_server=False,
            exec_history=[
                {'attempt': 1, 'error': 'SyntaxError', 'fixes': [], 'success': False,
                 'error_output': 'SyntaxError: invalid syntax'}
            ],
            all_fixes=[],
            spec_context='A simple hello world script.',
            integrity_issues=[],
            cancel_event=None,
        ):
            if isinstance(item, dict):
                final_result = item
            else:
                events.append(item)

check("events were yielded", len(events) > 0, f"num events={len(events)}")
check("final result is dict", final_result is not None, f"got={final_result}")
check("SSE events are strings", all(isinstance(e, str) for e in events))

# Check that some exec_ events were emitted
exec_events = [e for e in events if 'exec_' in e or 'review_' in e or 'recoder' in e.lower()]
check("execution/review events emitted", len(exec_events) > 0,
      f"event samples={[e[:60] for e in events[:5]]}")

shutil.rmtree(ws)


# ===============================================================
# TEST 3: Recoder reverts when error count increases
# ===============================================================
print("\n=== TEST 3: Recoder reverts on worse errors ===")
ws = _make_workspace({
    'app.py': 'import os\nprint(os.getcwd())\n',
})

original_content = 'import os\nprint(os.getcwd())\n'

# LLM "fixes" the file but makes it worse
bad_fix = [
    '<tool_code>',
    json.dumps({
        "name": "WriteFile",
        "arguments": {"path": "app.py", "content": "TOTALLY BROKEN GARBAGE\nimport nonexistent\n"}
    }),
    '</tool_code>',
]
bad_done = ["DONE"]
mock_llm_bad = MockLLM([bad_fix, bad_done])

with mock.patch('services.agent_service.get_llm_engine', return_value=mock_llm_bad):
    # Subprocess: before = 1 error, after = MORE errors
    call_count = [0]
    def mock_sub_worse(command, workspace_path, timeout=30):
        call_count[0] += 1
        if call_count[0] <= 1:
            return (1, '', 'NameError: name x is not defined')
        else:
            # Worse: more errors
            return (1, '', 'ModuleNotFoundError: No module named nonexistent\n'
                           'SyntaxError: invalid syntax\n'
                           'ImportError: cannot import\n'
                           'TypeError: bad type\n')

    with mock.patch.object(AgentService, '_run_project_subprocess', side_effect=mock_sub_worse):
        final = None
        for item in AgentService._run_recoder_agent(
            workspace_path=ws,
            entry_point='app.py',
            command='python app.py',
            is_server=False,
            exec_history=[{'attempt': 1, 'error': 'NameError', 'fixes': [],
                           'success': False, 'error_output': 'NameError'}],
            all_fixes=[],
            spec_context='',
            integrity_issues=[],
            cancel_event=None,
        ):
            if isinstance(item, dict):
                final = item

# After revert, the original content should be restored
with open(os.path.join(ws, 'app.py'), 'r') as f:
    restored = f.read()
check("file reverted to original", restored == original_content,
      f"got={restored[:100]}")
check("recoder reported failure", final is not None and not final.get('success', True),
      f"final={final}")
shutil.rmtree(ws)


# ===============================================================
# TEST 4: Recoder handles cancellation
# ===============================================================
print("\n=== TEST 4: Recoder handles cancellation ===")
ws = _make_workspace({'app.py': 'print("test")\n'})
cancel = threading.Event()
cancel.set()

mock_llm_cancel = MockLLM([["should not run"]])
with mock.patch('services.agent_service.get_llm_engine', return_value=mock_llm_cancel):
    with mock.patch.object(AgentService, '_run_project_subprocess', return_value=(0, '', '')):
        final = None
        event_count = 0
        for item in AgentService._run_recoder_agent(
            workspace_path=ws, entry_point='app.py', command='python app.py',
            is_server=False, exec_history=[], all_fixes=[], spec_context='',
            integrity_issues=[], cancel_event=cancel,
        ):
            if isinstance(item, dict):
                final = item
            else:
                event_count += 1

check("cancelled recoder yields result", final is not None, f"final={final}")
check("cancelled recoder reports failure", final is not None and not final.get('success', True))
shutil.rmtree(ws)


# ===============================================================
# TEST 5: Recoder reads all file types
# ===============================================================
print("\n=== TEST 5: Recoder reads multiple file types ===")
ws = _make_workspace({
    'app.py': 'main code\n',
    'config.yaml': 'key: value\n',
    'setup.cfg': '[metadata]\nname=test\n',
    'data.json': '{"x": 1}\n',
    'README.md': '# Project\n',
    'styles.css': 'body { color: red; }\n',
    'binary.png': '\x89PNG\r\n',  # Should be skipped (no .png in SOURCE_EXTS)
})

snapshot = AgentService._snapshot_project_files(ws)
check("app.py captured", 'app.py' in snapshot)
check("config.yaml captured", 'config.yaml' in snapshot)
check("setup.cfg captured", 'setup.cfg' in snapshot)
check("data.json captured", 'data.json' in snapshot)
check("README.md captured", 'README.md' in snapshot)
check("styles.css captured", 'styles.css' in snapshot)
check("binary.png NOT captured", 'binary.png' not in snapshot, f"keys={list(snapshot.keys())}")
shutil.rmtree(ws)


# ===============================================================
# Summary
# ===============================================================
print(f"\n{'='*60}")
print(f"RecoderAgent:  {passed} passed, {failed} failed")
print(f"{'='*60}")
sys.exit(1 if failed > 0 else 0)
