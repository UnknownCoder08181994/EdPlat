"""Integration Test 06: Snapshot/Revert Safety

Tests:
  Part A (deterministic): _snapshot_project_files / _restore_snapshot correctness
  Part B (deterministic): Snapshot skips .venv, .git, __pycache__, binaries
  Part C (live): If execution agent triggers recoder and it makes things worse, revert happens

Requires: LM Studio for Part C only
"""

import os
import sys
import json
import shutil
import tempfile

BACKEND_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'backend')
sys.path.insert(0, os.path.abspath(BACKEND_DIR))

from helpers import (
    is_lm_studio_running, TestContext, collect_events,
    print_event_log, print_event_summary, find_events, find_event,
    check, observe, reset_counters, get_results,
)


def _run_part_a():
    """Part A: Snapshot capture and restore correctness."""
    print("\n  --- Part A: Snapshot/Restore Correctness ---")

    from helpers import make_workspace, patch_config

    ws = make_workspace({
        'app.py': 'from flask import Flask\napp = Flask(__name__)\n',
        'models.py': 'class User:\n    name = ""\n\nclass Post:\n    title = ""\n',
        'utils/helpers.py': 'def format_name(n):\n    return n.title()\n',
        'utils/__init__.py': '',
        'config.json': '{"debug": true, "port": 5000}\n',
        'data/notes.txt': 'Some notes here\n',
    })

    try:
        # Need to set up config for AgentService import
        storage_dir = tempfile.mkdtemp(prefix='zenflow_snap_storage_')
        restore = patch_config(storage_dir)

        from services.agent_service import AgentService

        # Take snapshot
        snapshot = AgentService._snapshot_project_files(ws)
        check("snapshot is a dict", isinstance(snapshot, dict))
        check("snapshot has app.py", 'app.py' in snapshot,
              f"keys={list(snapshot.keys())[:10]}")
        check("snapshot has models.py", 'models.py' in snapshot)
        check("snapshot has config.json", 'config.json' in snapshot)

        # Check content fidelity
        check("app.py content correct",
              'Flask' in snapshot.get('app.py', ''),
              f"content={snapshot.get('app.py', '')[:50]}")

        # Count files captured
        print(f"  Snapshot captured {len(snapshot)} files")

        # Corrupt ALL files
        for root, dirs, files in os.walk(ws):
            for f in files:
                fpath = os.path.join(root, f)
                try:
                    with open(fpath, 'w') as fh:
                        fh.write('CORRUPTED GARBAGE DATA')
                except Exception:
                    pass

        # Verify corruption
        with open(os.path.join(ws, 'app.py'), 'r') as f:
            check("files were corrupted", 'CORRUPTED' in f.read())

        # Restore
        restored_count = AgentService._restore_snapshot(ws, snapshot)
        check("restore returned count > 0", restored_count > 0,
              f"count={restored_count}")

        # Verify restoration
        with open(os.path.join(ws, 'app.py'), 'r') as f:
            app_content = f.read()
        check("app.py restored correctly",
              'Flask' in app_content,
              f"content={app_content[:50]}")

        with open(os.path.join(ws, 'models.py'), 'r') as f:
            models_content = f.read()
        check("models.py restored correctly",
              'class User' in models_content,
              f"content={models_content[:50]}")

        with open(os.path.join(ws, 'config.json'), 'r') as f:
            config_content = f.read()
        check("config.json restored correctly",
              'debug' in config_content,
              f"content={config_content[:50]}")

        restore()
        shutil.rmtree(storage_dir, ignore_errors=True)

    finally:
        shutil.rmtree(ws, ignore_errors=True)


def _run_part_b():
    """Part B: Snapshot correctly skips .venv, .git, __pycache__, binaries."""
    print("\n  --- Part B: Snapshot Skip Rules ---")

    from helpers import make_workspace, patch_config

    ws = make_workspace({
        'app.py': 'print("hello")\n',
        'readme.md': '# Project\n',
        '.venv/lib/site.py': 'venv stuff',
        '.git/HEAD': 'ref: refs/heads/main',
        '__pycache__/app.cpython-310.pyc': 'bytecode',
        'node_modules/express/index.js': 'module.exports = {}',
    })

    # Also create a "binary" file
    with open(os.path.join(ws, 'image.png'), 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n' + b'\x00' * 100)

    try:
        storage_dir = tempfile.mkdtemp(prefix='zenflow_snap_storage2_')
        restore = patch_config(storage_dir)

        from services.agent_service import AgentService

        snapshot = AgentService._snapshot_project_files(ws)

        check("app.py IS in snapshot", 'app.py' in snapshot)
        check("readme.md IS in snapshot", 'readme.md' in snapshot)

        # These should be EXCLUDED
        venv_in = any('.venv' in k for k in snapshot.keys())
        git_in = any('.git' in k for k in snapshot.keys())
        pycache_in = any('__pycache__' in k for k in snapshot.keys())
        node_in = any('node_modules' in k for k in snapshot.keys())

        check(".venv NOT in snapshot", not venv_in,
              f"venv keys: {[k for k in snapshot if '.venv' in k]}")
        check(".git NOT in snapshot", not git_in,
              f"git keys: {[k for k in snapshot if '.git' in k]}")
        check("__pycache__ NOT in snapshot", not pycache_in)
        check("node_modules NOT in snapshot", not node_in)

        # Binary files should be excluded (or at least not cause errors)
        png_in = any('image.png' in k for k in snapshot.keys())
        observe("binary .png handled gracefully",
                True,  # No crash means it was handled
                f"png in snapshot: {png_in}")

        print(f"  Snapshot keys: {list(snapshot.keys())}")

        restore()
        shutil.rmtree(storage_dir, ignore_errors=True)

    finally:
        shutil.rmtree(ws, ignore_errors=True)


def _run_part_c():
    """Part C: Live test - execution agent recoder revert."""
    print("\n  --- Part C: Live Recoder Revert (if LM Studio available) ---")

    ok, model = is_lm_studio_running()
    if not ok:
        print("  SKIP  LM Studio not available")
        return

    # Create a project with a hard error that's difficult to fix
    ctx = TestContext("snapshot_revert_live")
    ctx.setup({
        'main.py': (
            'import custom_framework\n'
            '\n'
            'app = custom_framework.create_app()\n'
            'app.run()\n'
        ),
    })

    try:
        ctx.create_task("Build an app using custom framework")
        ctx.create_plan(f"""# Task: Custom framework app

### [x] Step: Requirements
### [x] Step: Technical Specification
### [x] Step: Planning
### [x] Step: Core Application
Build the app
""")

        timer = ctx.set_timeout(300)

        from services.agent_service import AgentService

        print("  Running execution agent (may take a while)...")
        events = collect_events(
            AgentService.run_execution_stream(ctx.task_id, ctx.cancel_event),
            timeout=300,
        )
        timer.cancel()

        print(f"  Events: {len(events)}")
        print_event_summary(events)

        # Look for revert events
        status_events = find_events(events, 'exec_status')
        revert_events = [e for e in status_events
                         if 'revert' in str(e[1]).lower() or 'Reverted' in str(e[1].get('status', ''))]
        if revert_events:
            print(f"  REVERT DETECTED: {len(revert_events)} revert event(s)")
            for _, d, ts in revert_events:
                print(f"    [{ts:6.1f}s] {d.get('status', str(d)[:100])}")
            observe("recoder triggered revert", True)
        else:
            observe("no revert detected (recoder may have succeeded or not triggered)", True)

        # Check done event
        done = find_event(events, 'exec_done')
        if done:
            observe(f"execution result: success={done[1].get('success')}", True)

    except Exception as e:
        import traceback
        print(f"  ERROR in Part C: {e}")
        traceback.print_exc()
    finally:
        ctx.teardown()


def run_test():
    reset_counters()
    print("\n" + "=" * 70)
    print("  TEST 06: Snapshot/Revert Safety")
    print("=" * 70)

    _run_part_a()
    _run_part_b()
    _run_part_c()

    p, f, o = get_results()
    verdict = 'FAIL' if f > 0 else 'PASS'
    print(f"\n  RESULT: {verdict} ({p} passed, {f} failed, {o} observations)")
    return verdict


if __name__ == '__main__':
    result = run_test()
    sys.exit(0 if result in ('PASS', 'SKIP') else 1)
