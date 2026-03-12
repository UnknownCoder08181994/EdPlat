"""Shared infrastructure for integration tests.

Provides:
  - LM Studio availability check
  - Workspace / task / chat scaffolding
  - Config patching for test isolation
  - SSE event collector and printer
  - Assertion helpers
"""

import os
import sys
import json
import time
import shutil
import tempfile
import threading
import uuid
import re
from datetime import datetime

# Add backend to path
BACKEND_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'backend')
sys.path.insert(0, os.path.abspath(BACKEND_DIR))

# ---------------------------------------------------------------
# LM Studio check
# ---------------------------------------------------------------

def is_lm_studio_running():
    """Check if LM Studio is serving at localhost:1234."""
    try:
        import requests
        resp = requests.get('http://localhost:1234/v1/models', timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            models = data.get('data', [])
            if models:
                return True, models[0].get('id', 'unknown')
            return True, 'unknown'
        return False, ''
    except Exception:
        return False, ''


def get_model_name():
    """Return the currently loaded model name, or 'unavailable'."""
    ok, name = is_lm_studio_running()
    return name if ok else 'unavailable'


# ---------------------------------------------------------------
# Config patching
# ---------------------------------------------------------------

_original_storage_dir = None

def patch_config(temp_dir):
    """Patch Config.STORAGE_DIR to temp_dir for test isolation.
    Returns a cleanup function that restores the original.
    """
    global _original_storage_dir
    from config import Config
    _original_storage_dir = Config.STORAGE_DIR
    Config.STORAGE_DIR = temp_dir
    # Ensure subdirectories exist
    os.makedirs(os.path.join(temp_dir, 'tasks'), exist_ok=True)
    os.makedirs(os.path.join(temp_dir, 'projects'), exist_ok=True)
    os.makedirs(os.path.join(temp_dir, 'workspaces'), exist_ok=True)

    def restore():
        Config.STORAGE_DIR = _original_storage_dir
    return restore


# ---------------------------------------------------------------
# Workspace scaffolding
# ---------------------------------------------------------------

def make_workspace(structure):
    """Create a temp workspace directory with files from a dict.

    structure: {'path/to/file.py': 'content', ...}
    Returns the workspace path.
    """
    ws = tempfile.mkdtemp(prefix='zenflow_int_')
    for rel_path, content in structure.items():
        full = os.path.join(ws, rel_path.replace('/', os.sep))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, 'w', encoding='utf-8') as f:
            f.write(content)
    return ws


def make_task(storage_dir, task_id, workspace_path, details,
              workflow_type='Full SDD workflow', complexity=5):
    """Write a task JSON file to storage."""
    task = {
        "id": task_id,
        "projectId": "test-project",
        "workflowType": workflow_type,
        "details": details,
        "settings": {"complexity": complexity},
        "status": "In Progress",
        "branch": "test-branch",
        "workspacePath": workspace_path,
        "workspaceMethod": "copy",
        "createdAt": datetime.now().isoformat(),
    }
    task_path = os.path.join(storage_dir, 'tasks', f'{task_id}.json')
    os.makedirs(os.path.dirname(task_path), exist_ok=True)
    with open(task_path, 'w', encoding='utf-8') as f:
        json.dump(task, f, indent=2)
    return task


def make_chat(storage_dir, task_id, chat_id, name="Test Chat", messages=None):
    """Write a chat JSON file to storage."""
    chat = {
        "id": chat_id,
        "taskId": task_id,
        "name": name,
        "createdAt": datetime.now().isoformat(),
        "messages": messages or [],
        "status": "active",
    }
    chat_dir = os.path.join(storage_dir, 'chats', task_id)
    os.makedirs(chat_dir, exist_ok=True)
    chat_path = os.path.join(chat_dir, f'{chat_id}.json')
    with open(chat_path, 'w', encoding='utf-8') as f:
        json.dump(chat, f, indent=2)
    return chat


def make_plan(workspace_path, task_id, plan_content):
    """Write plan.md into .sentinel/tasks/{task_id}/plan.md."""
    artifacts_dir = os.path.join(workspace_path, '.sentinel', 'tasks', task_id)
    os.makedirs(artifacts_dir, exist_ok=True)
    plan_path = os.path.join(artifacts_dir, 'plan.md')
    with open(plan_path, 'w', encoding='utf-8') as f:
        f.write(plan_content)
    return artifacts_dir


def make_artifact(workspace_path, task_id, filename, content):
    """Write an artifact file (requirements.md, spec.md, etc.) to .sentinel/tasks/{id}/."""
    artifacts_dir = os.path.join(workspace_path, '.sentinel', 'tasks', task_id)
    os.makedirs(artifacts_dir, exist_ok=True)
    path = os.path.join(artifacts_dir, filename)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    return path


# ---------------------------------------------------------------
# SSE Event Collector
# ---------------------------------------------------------------

def collect_events(generator, timeout=180):
    """Consume an SSE generator and return a list of (event_type, data_dict, elapsed_seconds).

    Handles:
      - 'event: TYPE\\ndata: JSON\\n\\n' format
      - Multi-line data
      - Heartbeat comments (lines starting with ':')
      - Timeout via threading.Timer + cancel_event
    """
    events = []
    start = time.time()

    try:
        for chunk in generator:
            elapsed = time.time() - start
            if elapsed > timeout:
                events.append(('_timeout', {}, elapsed))
                break

            if not chunk or not isinstance(chunk, str):
                continue

            # Parse SSE format
            lines = chunk.strip().split('\n')
            event_type = 'message'
            data_str = ''

            for line in lines:
                line = line.strip()
                if line.startswith(':'):
                    continue  # heartbeat
                if line.startswith('event: '):
                    event_type = line[7:].strip()
                elif line.startswith('data: '):
                    data_str = line[6:]
                elif line.startswith('data:'):
                    data_str = line[5:]

            if not data_str and not event_type:
                continue

            # Parse JSON data
            data = {}
            if data_str:
                try:
                    data = json.loads(data_str)
                except (json.JSONDecodeError, ValueError):
                    data = {'_raw': data_str}

            events.append((event_type, data, round(elapsed, 1)))

    except GeneratorExit:
        events.append(('_generator_exit', {}, round(time.time() - start, 1)))
    except Exception as e:
        events.append(('_error', {'error': str(e)}, round(time.time() - start, 1)))

    return events


# ---------------------------------------------------------------
# Event analysis helpers
# ---------------------------------------------------------------

def find_events(events, event_type):
    """Return all events matching the given type."""
    return [(t, d, ts) for t, d, ts in events if t == event_type]


def find_event(events, event_type, predicate=None):
    """Return the first event matching type and optional predicate on data dict."""
    for t, d, ts in events:
        if t == event_type:
            if predicate is None or predicate(d):
                return (t, d, ts)
    return None


def has_event(events, event_type, predicate=None):
    """Check if any event matches."""
    return find_event(events, event_type, predicate) is not None


def count_events(events, event_type):
    """Count events of a given type."""
    return sum(1 for t, _, _ in events if t == event_type)


# ---------------------------------------------------------------
# Event logging
# ---------------------------------------------------------------

def print_event_log(events, max_data_len=200):
    """Print a formatted timeline of events."""
    for i, (etype, data, ts) in enumerate(events):
        # Format data for display
        if '_raw' in data:
            data_str = data['_raw'][:max_data_len]
        elif 'token' in data:
            # Token events are noisy, just show length
            data_str = f"({len(data.get('token', ''))} chars)"
        elif 'result' in data and len(str(data.get('result', ''))) > max_data_len:
            data_str = str(data['result'])[:max_data_len] + '...'
        else:
            data_str = json.dumps(data)
            if len(data_str) > max_data_len:
                data_str = data_str[:max_data_len] + '...'

        print(f"  [{ts:6.1f}s] {etype:25s} | {data_str}")


def print_event_summary(events):
    """Print a summary of event counts by type."""
    counts = {}
    for t, _, _ in events:
        counts[t] = counts.get(t, 0) + 1
    print("  Event summary:")
    for etype, count in sorted(counts.items()):
        print(f"    {etype:25s}: {count}")


# ---------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------

_passed = 0
_failed = 0
_observed = 0

def reset_counters():
    global _passed, _failed, _observed
    _passed = 0
    _failed = 0
    _observed = 0


def check(name, condition, detail=''):
    """Assert with PASS/FAIL output."""
    global _passed, _failed
    if condition:
        print(f"  PASS  {name}")
        _passed += 1
    else:
        print(f"  FAIL  {name}  {detail}")
        _failed += 1
    return condition


def observe(name, condition, detail=''):
    """Observe a condition (logged but not counted as failure)."""
    global _observed
    if condition:
        print(f"  OK    {name}")
    else:
        print(f"  NOTE  {name}  {detail}")
        _observed += 1
    return condition


def get_results():
    """Return (passed, failed, observed) counts."""
    return _passed, _failed, _observed


# ---------------------------------------------------------------
# Test setup / teardown
# ---------------------------------------------------------------

class TestContext:
    """Manages temp directories and config patching for a single test."""

    def __init__(self, test_name):
        self.test_name = test_name
        self.storage_dir = None
        self.workspace_path = None
        self.task_id = str(uuid.uuid4())
        self.chat_id = str(uuid.uuid4())
        self._restore_config = None
        self.cancel_event = threading.Event()

    def setup(self, workspace_files=None):
        """Create temp dirs, patch config, create workspace."""
        self.storage_dir = tempfile.mkdtemp(prefix='zenflow_int_storage_')
        self._restore_config = patch_config(self.storage_dir)

        if workspace_files:
            self.workspace_path = make_workspace(workspace_files)
        else:
            self.workspace_path = tempfile.mkdtemp(prefix='zenflow_int_ws_')

        return self

    def teardown(self):
        """Restore config, clean up temp dirs."""
        if self._restore_config:
            self._restore_config()
        if self.storage_dir:
            shutil.rmtree(self.storage_dir, ignore_errors=True)
        if self.workspace_path:
            shutil.rmtree(self.workspace_path, ignore_errors=True)

    def create_task(self, details, **kwargs):
        """Create task JSON in storage."""
        return make_task(self.storage_dir, self.task_id, self.workspace_path, details, **kwargs)

    def create_chat(self, name="Test Chat", messages=None):
        """Create chat JSON in storage."""
        return make_chat(self.storage_dir, self.task_id, self.chat_id, name, messages)

    def create_plan(self, plan_content):
        """Write plan.md for this task."""
        return make_plan(self.workspace_path, self.task_id, plan_content)

    def create_artifact(self, filename, content):
        """Write an artifact file."""
        return make_artifact(self.workspace_path, self.task_id, filename, content)

    def set_timeout(self, seconds):
        """Set a timer that cancels the agent after N seconds."""
        def _cancel():
            self.cancel_event.set()
        timer = threading.Timer(seconds, _cancel)
        timer.daemon = True
        timer.start()
        return timer
