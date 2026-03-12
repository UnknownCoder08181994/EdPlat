"""Integration Test 07: HARD Execution Scenarios

Tests the execution agent on scenarios that actually break in real terminal runs.
These are NOT simple one-file fixes -- they're multi-file projects with cascading
errors, cross-module import failures, and scenarios that push through the full
Phase 3 -> Phase 3.5 (Recoder) -> Phase 4 (Step-Fix) pipeline.

Scenarios:
  7A: Multi-file cross-import error (models/ imports from utils/ which has a bug)
  7B: Flask factory pattern with broken circular import
  7C: Project with diff markers left in code (simulates bad LLM edit)
  7D: Multiple cascading errors (3+ files broken)
  7E: Recoder stress test -- project needs holistic rewrite to work

Requires: LM Studio running at localhost:1234
"""

import os
import sys
import json
import time

BACKEND_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'backend')
sys.path.insert(0, os.path.abspath(BACKEND_DIR))

from helpers import (
    is_lm_studio_running, TestContext, collect_events,
    print_event_log, print_event_summary, find_events, find_event,
    has_event, count_events, check, observe, reset_counters, get_results,
)


def _run_hard_scenario(name, workspace_files, details, timeout=300,
                       expect_success=None, expect_recoder=False,
                       expect_min_attempts=1):
    """Run a hard execution scenario with detailed diagnostics.

    Args:
        expect_success: True/False/None. None means we don't assert, just observe.
        expect_recoder: If True, observe whether the recoder agent was triggered.
        expect_min_attempts: Minimum attempts before success (tests that fix is non-trivial).
    """
    print(f"\n  {'='*70}")
    print(f"  Scenario: {name}")
    print(f"  {'='*70}")

    ctx = TestContext(name.replace(' ', '_').replace(':', '').replace('/', '_')[:40])
    ctx.setup(workspace_files)

    try:
        ctx.create_task(details)
        ctx.create_plan(f"""# Task: {details}

### [x] Step: Requirements
### [x] Step: Technical Specification
### [x] Step: Planning
### [x] Step: Core Application
<!-- chat-id: {ctx.chat_id} -->
Build the application
Files: {', '.join(workspace_files.keys())}
""")

        # Create minimal artifacts so seed doesn't complain
        ctx.create_artifact('requirements.md', f'# Requirements\n- {details}\n')
        ctx.create_artifact('spec.md', f'# Spec\n- {details}\n')

        timer = ctx.set_timeout(timeout)

        from services.agent_service import AgentService

        print(f"  Running execution agent (timeout {timeout}s)...", flush=True)
        start = time.time()
        events = collect_events(
            AgentService.run_execution_stream(ctx.task_id, ctx.cancel_event),
            timeout=timeout,
        )
        elapsed = time.time() - start
        timer.cancel()

        print(f"\n  Completed in {elapsed:.0f}s, {len(events)} events", flush=True)

        # ---- Event Summary ----
        print_event_summary(events)

        # ---- Detailed Analysis ----
        print("\n  --- Execution Flow ---")

        # Pre-scan fixes
        fix_events = find_events(events, 'exec_fix')
        if fix_events:
            print(f"  Pre-scan/auto fixes: {len(fix_events)}")
            for _, data, ts in fix_events:
                tool = data.get('tool', '?')
                path = data.get('path', '?')
                result = str(data.get('result', ''))[:100]
                print(f"    [{ts:6.1f}s] {tool:20s} {path:20s} | {result}")

        # Execution attempts
        run_events = find_events(events, 'exec_run')
        attempts_detail = []
        for _, data, ts in run_events:
            attempt = data.get('attempt', '?')
            status = data.get('status', '?')
            exit_code = data.get('exitCode', '?')
            if status not in ('running',):
                attempts_detail.append((attempt, status, exit_code, ts))
                print(f"    Attempt {attempt}: {status} (exit={exit_code}) [{ts:.1f}s]")

        # Diagnoses
        diag_events = find_events(events, 'exec_diagnosis')
        if diag_events:
            print(f"\n  Diagnoses: {len(diag_events)}")
            for _, data, ts in diag_events:
                etype = data.get('type', '?')
                efile = data.get('file', '?')
                emsg = str(data.get('message', ''))[:120]
                print(f"    [{ts:6.1f}s] {etype:20s} | {os.path.basename(str(efile)):20s} | {emsg}")

        # LLM edits during Phase 3
        edit_events = find_events(events, 'exec_edit')
        if edit_events:
            print(f"\n  LLM edits: {len(edit_events)}")
            for _, data, ts in edit_events:
                path = data.get('path', '?')
                old = str(data.get('old_string', ''))[:50]
                new = str(data.get('new_string', ''))[:50]
                print(f"    [{ts:6.1f}s] {path}: '{old}' -> '{new}'")

        # Recoder detection
        status_events = find_events(events, 'exec_status')
        recoder_events = [e for e in status_events
                          if 'recoder' in str(e[1].get('status', '')).lower()
                          or 'Recoder' in str(e[1].get('status', ''))]
        revert_events = [e for e in status_events
                         if 'revert' in str(e[1].get('status', '')).lower()
                         or 'Reverted' in str(e[1].get('status', ''))]

        if recoder_events:
            print(f"\n  RECODER AGENT TRIGGERED:")
            for _, data, ts in recoder_events:
                print(f"    [{ts:6.1f}s] {data.get('status', '')[:150]}")
        if revert_events:
            print(f"\n  SNAPSHOT REVERTS:")
            for _, data, ts in revert_events:
                print(f"    [{ts:6.1f}s] {data.get('status', '')[:150]}")

        # Step-fix detection
        step_fix_events = [e for e in status_events
                           if 'step-fix' in str(e[1].get('status', '')).lower()
                           or 'Step fix' in str(e[1].get('status', ''))]
        if step_fix_events:
            print(f"\n  STEP-FIX TRIGGERED:")
            for _, data, ts in step_fix_events:
                print(f"    [{ts:6.1f}s] {data.get('status', '')[:150]}")

        # Final result
        done_event = find_event(events, 'exec_done')
        success = False
        total_attempts = 0
        if done_event:
            _, data, ts = done_event
            success = data.get('success', False)
            total_attempts = data.get('attempts', 0)
            fixes = data.get('fixes', [])
            output_preview = str(data.get('output', ''))[:200]
            print(f"\n  FINAL: success={success}, attempts={total_attempts}, "
                  f"fixes={len(fixes)}")
            print(f"  Output: {output_preview}")
        else:
            # Check for error events
            error_event = find_event(events, 'exec_error')
            if error_event:
                print(f"\n  EXEC_ERROR: {error_event[1].get('error', '?')}")
            timeout_event = find_event(events, '_timeout')
            if timeout_event:
                print(f"\n  TIMED OUT at {timeout_event[2]:.0f}s")

        # ---- Assertions ----
        print("\n  --- Assertions ---")

        check("events emitted", len(events) > 0)

        if expect_success is True:
            check("execution succeeded", success,
                  f"success={success}, attempts={total_attempts}")
        elif expect_success is False:
            check("execution correctly reported failure", not success or done_event is None,
                  f"success={success}")
        else:
            observe(f"execution {'succeeded' if success else 'failed (expected for hard task)'}",
                    True, f"attempts={total_attempts}")

        if expect_recoder:
            observe("recoder agent was triggered", len(recoder_events) > 0,
                    "recoder never ran")

        if expect_min_attempts > 1 and success:
            observe(f"took {total_attempts} attempts (expected >={expect_min_attempts})",
                    total_attempts >= expect_min_attempts)

        # Check execution.log
        exec_log_path = os.path.join(
            ctx.workspace_path, '.sentinel', 'tasks', ctx.task_id, 'execution.log')
        if os.path.isfile(exec_log_path):
            with open(exec_log_path, 'r', encoding='utf-8') as f:
                exec_log = json.load(f)
            check("execution.log written", True)
            if exec_log.get('warnings'):
                print(f"  Warnings: {exec_log['warnings'][:5]}")
            if exec_log.get('fixes'):
                fix_paths = [f.get('path', str(f)[:40]) if isinstance(f, dict)
                             else str(f)[:40] for f in exec_log['fixes'][:5]]
                print(f"  Logged fixes: {fix_paths}")
        else:
            observe("execution.log exists", False, "not found")

        # Show final file state
        print("\n  --- Final File State ---")
        for fname in sorted(workspace_files.keys()):
            fpath = os.path.join(ctx.workspace_path, fname.replace('/', os.sep))
            if os.path.isfile(fpath):
                with open(fpath, 'r', encoding='utf-8') as f:
                    content = f.read()
                lines = content.split('\n')
                print(f"  {fname} ({len(lines)} lines):")
                for i, line in enumerate(lines[:10], 1):
                    print(f"    {i:3d} | {line}")
                if len(lines) > 10:
                    print(f"    ... ({len(lines) - 10} more)")
            else:
                print(f"  {fname}: NOT FOUND (deleted or renamed)")

        p, f, o = get_results()
        return 'FAIL' if f > 0 else 'PASS'

    except Exception as e:
        import traceback
        print(f"\n  ERROR: {e}")
        traceback.print_exc()
        return 'FAIL'
    finally:
        ctx.teardown()


def run_test():
    reset_counters()
    print("\n" + "=" * 70)
    print("  TEST 07: HARD Execution Scenarios")
    print("=" * 70)

    ok, model = is_lm_studio_running()
    if not ok:
        print("  SKIP  LM Studio not available at localhost:1234")
        return 'SKIP'

    print(f"  LM Studio: CONNECTED (model: {model})")

    verdicts = []

    # ================================================================
    # 7A: Cross-module import error
    # utils/helpers.py has a NameError, models/user.py imports from it,
    # app.py imports from models. Chain: app -> models -> utils (broken)
    # ================================================================
    reset_counters()
    v = _run_hard_scenario(
        "7A: Cross-module import chain (3 files deep)",
        {
            'app.py': (
                'from models.user import User\n'
                '\n'
                'def main():\n'
                '    u = User("Alice")\n'
                '    print(f"User: {u.display_name()}")\n'
                '\n'
                'if __name__ == "__main__":\n'
                '    main()\n'
            ),
            'models/__init__.py': '',
            'models/user.py': (
                'from utils.helpers import format_name\n'
                '\n'
                'class User:\n'
                '    def __init__(self, name):\n'
                '        self.name = name\n'
                '\n'
                '    def display_name(self):\n'
                '        return format_name(self.name)\n'
            ),
            'utils/__init__.py': '',
            'utils/helpers.py': (
                'def format_name(name):\n'
                '    # Bug: undefined_formatter is not defined\n'
                '    return undefined_formatter(name.strip().title())\n'
            ),
        },
        "Build a user management app with name formatting",
        timeout=240,
        expect_success=None,  # Hard -- may or may not succeed
        expect_min_attempts=2,
    )
    verdicts.append(('7A', v))

    # ================================================================
    # 7B: Flask factory pattern with broken import
    # Common real-world pattern that frequently breaks
    # ================================================================
    reset_counters()
    v = _run_hard_scenario(
        "7B: Flask factory pattern (broken circular import)",
        {
            'app.py': (
                'from app_factory import create_app\n'
                '\n'
                'app = create_app()\n'
                '\n'
                'if __name__ == "__main__":\n'
                '    app.run(port=5050)\n'
            ),
            'app_factory.py': (
                'from flask import Flask\n'
                'from routes import register_routes\n'
                '\n'
                'def create_app():\n'
                '    app = Flask(__name__)\n'
                '    register_routes(app)\n'
                '    return app\n'
            ),
            'routes.py': (
                'from flask import jsonify\n'
                'from models import get_all_users\n'
                '\n'
                'def register_routes(app):\n'
                '    @app.route("/api/users")\n'
                '    def users():\n'
                '        return jsonify(get_all_users())\n'
                '\n'
                '    @app.route("/api/health")\n'
                '    def health():\n'
                '        return jsonify({"status": "ok"})\n'
            ),
            'models.py': (
                '# Bug: references db that doesn\'t exist\n'
                'from database import db\n'
                '\n'
                'class User:\n'
                '    def __init__(self, name, email):\n'
                '        self.name = name\n'
                '        self.email = email\n'
                '\n'
                'def get_all_users():\n'
                '    return db.query(User).all()\n'
            ),
            'requirements.txt': 'flask\n',
        },
        "Build a Flask API with factory pattern and user routes",
        timeout=300,
        expect_success=None,
        expect_recoder=True,
    )
    verdicts.append(('7B', v))

    # ================================================================
    # 7C: Diff markers left in code (simulates bad LLM edit)
    # This is the MOST COMMON real failure -- the LLM writes diff
    # markers into the file during a previous step
    # ================================================================
    reset_counters()
    v = _run_hard_scenario(
        "7C: Diff markers in code (bad previous edit)",
        {
            'main.py': (
                'import json\n'
                'import os\n'
                '\n'
                'def load_config(path="config.json"):\n'
                '    with open(path, "r") as f:\n'
                '        return json.load(f)\n'
                '\n'
                '<<<<<<< HEAD\n'
                'def process_data(config):\n'
                '    data_dir = config.get("data_dir", "data")\n'
                '    results = []\n'
                '    for fname in os.listdir(data_dir):\n'
                '        with open(os.path.join(data_dir, fname)) as f:\n'
                '            results.append(f.read())\n'
                '    return results\n'
                '=======\n'
                'def process_data(config):\n'
                '    return config.get("data", [])\n'
                '>>>>>>> feature-branch\n'
                '\n'
                'if __name__ == "__main__":\n'
                '    cfg = load_config()\n'
                '    result = process_data(cfg)\n'
                '    print(f"Processed {len(result)} items")\n'
            ),
            'config.json': '{"data_dir": "data", "data": [1, 2, 3]}\n',
        },
        "Build a data processing pipeline",
        timeout=180,
        expect_success=True,  # Pre-scan should strip diff markers
        expect_min_attempts=1,
    )
    verdicts.append(('7C', v))

    # ================================================================
    # 7D: Multiple cascading errors (4 broken files)
    # Every file has a different kind of error
    # ================================================================
    reset_counters()
    v = _run_hard_scenario(
        "7D: Multiple cascading errors (4 broken files)",
        {
            'main.py': (
                'from config import load_settings\n'
                'from processor import DataProcessor\n'
                'from reporter import generate_report\n'
                '\n'
                'def main():\n'
                '    settings = load_settings()\n'
                '    proc = DataProcessor(settings)\n'
                '    data = proc.run()\n'
                '    report = generate_report(data)\n'
                '    print(report)\n'
                '\n'
                'if __name__ == "__main__":\n'
                '    main()\n'
            ),
            'config.py': (
                'import json\n'
                '\n'
                '# Bug: missing colon\n'
                'def load_settings(path="settings.json")\n'
                '    with open(path) as f:\n'
                '        return json.load(f)\n'
            ),
            'processor.py': (
                '# Bug: uses undefined variable\n'
                'class DataProcessor:\n'
                '    def __init__(self, settings):\n'
                '        self.settings = settings\n'
                '        self.threshold = DEFAULT_THRESHOLD\n'
                '\n'
                '    def run(self):\n'
                '        data = list(range(self.settings.get("count", 10)))\n'
                '        return [x for x in data if x > self.threshold]\n'
            ),
            'reporter.py': (
                '# Bug: wrong import name\n'
                'from datetime import datatime\n'
                '\n'
                'def generate_report(data):\n'
                '    now = datatime.now().isoformat()\n'
                '    return f"Report at {now}: {len(data)} items processed"\n'
            ),
            'settings.json': '{"count": 20, "threshold": 5}\n',
        },
        "Build a data processing pipeline with config, processor, and reporter",
        timeout=300,
        expect_success=None,
        expect_recoder=True,
        expect_min_attempts=2,
    )
    verdicts.append(('7D', v))

    # ================================================================
    # 7E: Recoder stress -- project that NEEDS holistic rewrite
    # The errors are deeply intertwined -- can't fix one without the other
    # ================================================================
    reset_counters()
    v = _run_hard_scenario(
        "7E: Deeply intertwined errors (needs recoder)",
        {
            'app.py': (
                'from flask import Flask, jsonify, request\n'
                'from auth import require_auth, get_current_user\n'
                'from db import get_db, init_db\n'
                '\n'
                'app = Flask(__name__)\n'
                'init_db(app)\n'
                '\n'
                '@app.route("/api/profile")\n'
                '@require_auth\n'
                'def profile():\n'
                '    user = get_current_user(request)\n'
                '    return jsonify(user.to_dict())\n'
                '\n'
                '@app.route("/api/items")\n'
                'def items():\n'
                '    db = get_db()\n'
                '    return jsonify([i.to_dict() for i in db.get_items()])\n'
                '\n'
                'if __name__ == "__main__":\n'
                '    app.run(port=5051)\n'
            ),
            'auth.py': (
                '# Bug: imports from non-existent module\n'
                'from jwt_handler import decode_token\n'
                'from db import get_user_by_id\n'
                '\n'
                'def require_auth(f):\n'
                '    from functools import wraps\n'
                '    @wraps(f)\n'
                '    def decorated(*args, **kwargs):\n'
                '        token = request.headers.get("Authorization")\n'
                '        if not token:\n'
                '            return {"error": "No token"}, 401\n'
                '        user_id = decode_token(token)\n'
                '        return f(*args, **kwargs)\n'
                '    return decorated\n'
                '\n'
                'def get_current_user(request):\n'
                '    token = request.headers.get("Authorization")\n'
                '    user_id = decode_token(token)\n'
                '    return get_user_by_id(user_id)\n'
            ),
            'db.py': (
                '# Bug: references undefined engine\n'
                'from sqlalchemy import create_engine\n'
                '\n'
                'class Database:\n'
                '    def __init__(self):\n'
                '        self.engine = create_engine(DATABASE_URL)\n'
                '\n'
                '    def get_items(self):\n'
                '        return []\n'
                '\n'
                '_db = None\n'
                '\n'
                'def init_db(app):\n'
                '    global _db\n'
                '    _db = Database()\n'
                '\n'
                'def get_db():\n'
                '    return _db\n'
                '\n'
                'def get_user_by_id(uid):\n'
                '    return {"id": uid, "name": "Test"}\n'
            ),
            'requirements.txt': 'flask\n',
        },
        "Build a Flask API with auth, database, and user profiles",
        timeout=300,
        expect_success=None,
        expect_recoder=True,
    )
    verdicts.append(('7E', v))

    # ---- Summary ----
    print(f"\n  {'='*70}")
    print(f"  HARD SCENARIO RESULTS:")
    print(f"  {'='*70}")
    for label, v in verdicts:
        emoji = '  PASS ' if v == 'PASS' else '  FAIL ' if v == 'FAIL' else '  ---- '
        print(f"  {emoji} {label}: {v}")

    pass_count = sum(1 for _, v in verdicts if v == 'PASS')
    fail_count = sum(1 for _, v in verdicts if v == 'FAIL')
    print(f"\n  Total: {pass_count}/{len(verdicts)} passed, {fail_count} failed")

    # For hard tests, we don't fail on execution failure -- we OBSERVE
    # The goal is to see HOW the pipeline handles hard scenarios
    overall = 'FAIL' if fail_count > 0 else 'PASS'
    print(f"  Overall: {overall}")
    return overall


if __name__ == '__main__':
    result = run_test()
    sys.exit(0 if result in ('PASS', 'SKIP') else 1)
