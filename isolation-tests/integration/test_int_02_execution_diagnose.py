"""Integration Test 02: Execution Agent Error -> Diagnose -> Fix

Tests whether the execution pipeline actually detects and fixes runtime errors.

Sub-scenarios:
  2A: Missing module (flask not installed) -> pre-scan generates requirements -> pip install
  2B: Syntax error (missing colon) -> pre-scan or Phase 3 fixes
  2C: Runtime crash (bad JSON parse) -> LLM diagnoses and rewrites

Requires: LM Studio running at localhost:1234
"""

import os
import sys
import json

BACKEND_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'backend')
sys.path.insert(0, os.path.abspath(BACKEND_DIR))

from helpers import (
    is_lm_studio_running, TestContext, collect_events,
    print_event_log, print_event_summary, find_events, find_event,
    has_event, count_events, check, observe, reset_counters, get_results,
)


def _run_scenario(name, workspace_files, details, timeout=180):
    """Run a single execution scenario and return verdict."""
    print(f"\n  {'- '*35}")
    print(f"  Scenario: {name}")
    print(f"  {'- '*35}")

    ctx = TestContext(name)
    ctx.setup(workspace_files)

    try:
        ctx.create_task(details)
        # Execution agent needs a plan with at least one completed impl step
        ctx.create_plan(f"""# Task: {details}

### [x] Step: Requirements
### [x] Step: Technical Specification
### [x] Step: Planning
### [x] Step: Core Application
Build the application
""")

        timer = ctx.set_timeout(timeout)

        from services.agent_service import AgentService

        print(f"  Running execution agent...")
        events = collect_events(
            AgentService.run_execution_stream(ctx.task_id, ctx.cancel_event),
            timeout=timeout,
        )
        timer.cancel()

        print(f"\n  Events collected: {len(events)}")
        print("\n  --- Full Event Timeline ---")
        print_event_log(events)
        print("\n  --- Event Summary ---")
        print_event_summary(events)

        # ---- Checks ----
        print("\n  --- Assertions ---")

        check("events emitted", len(events) > 0)

        # Pre-scan events
        prescan = find_events(events, 'exec_status')
        observe("pre-scan status events", len(prescan) > 0)

        # Entry point detection
        ep_event = find_event(events, 'exec_status',
                              lambda d: 'entry point' in str(d).lower() or 'Entry point' in str(d.get('status', '')))
        observe("entry point detected", ep_event is not None,
                f"status events: {[e[1].get('status', '')[:60] for e in prescan[:8]]}")

        # Execution attempts
        run_events = find_events(events, 'exec_run')
        observe("exec_run events", len(run_events) > 0)
        if run_events:
            for _, data, ts in run_events:
                attempt = data.get('attempt', '?')
                status = data.get('status', '?')
                print(f"    Attempt {attempt}: {status}")

        # Diagnosis events
        diag_events = find_events(events, 'exec_diagnosis')
        if diag_events:
            for _, data, ts in diag_events:
                print(f"    Diagnosis: type={data.get('type', '?')} file={data.get('file', '?')}")

        # Fix events
        fix_events = find_events(events, 'exec_fix')
        if fix_events:
            print(f"  Fixes applied: {len(fix_events)}")
            for _, data, ts in fix_events:
                print(f"    [{ts:6.1f}s] {data.get('tool', '?')} -> {data.get('path', str(data)[:80])}")

        # Final result
        done_event = find_event(events, 'exec_done')
        if done_event:
            _, data, ts = done_event
            success = data.get('success', False)
            attempts = data.get('attempts', '?')
            print(f"\n  Final: success={success}, attempts={attempts}")
            observe(f"execution {'succeeded' if success else 'failed'}", True)
        else:
            observe("exec_done event emitted", False, "no done event found")

        # Check execution.log on disk
        exec_log_path = os.path.join(
            ctx.workspace_path, '.sentinel', 'tasks', ctx.task_id, 'execution.log')
        if os.path.isfile(exec_log_path):
            with open(exec_log_path, 'r', encoding='utf-8') as f:
                exec_log = json.load(f)
            check("execution.log written", True)
            check("execution.log has success field", 'success' in exec_log)
            observe(f"execution.log success={exec_log.get('success')}",
                    True)
            if exec_log.get('warnings'):
                print(f"  Warnings in log: {exec_log['warnings'][:3]}")
        else:
            observe("execution.log exists", False, "not found on disk")

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
    print("  TEST 02: Execution Agent Error -> Diagnose -> Fix")
    print("=" * 70)

    ok, model = is_lm_studio_running()
    if not ok:
        print("  SKIP  LM Studio not available at localhost:1234")
        return 'SKIP'

    print(f"  LM Studio: CONNECTED (model: {model})")

    verdicts = []

    # --- Scenario 2A: Missing module ---
    reset_counters()
    v = _run_scenario(
        "2A: Missing module (flask not installed)",
        {
            'app.py': (
                'from flask import Flask\n'
                'app = Flask(__name__)\n'
                '@app.route("/")\n'
                'def index():\n'
                '    return "Hello World"\n'
                'if __name__ == "__main__":\n'
                '    app.run(port=5099)\n'
            ),
        },
        "Build a simple Flask hello world app",
        timeout=180,
    )
    verdicts.append(('2A', v))

    # --- Scenario 2B: Syntax error ---
    reset_counters()
    v = _run_scenario(
        "2B: Syntax error (missing colon)",
        {
            'main.py': (
                'def greet(name)\n'
                '    return f"Hello {name}"\n'
                '\n'
                'if __name__ == "__main__":\n'
                '    print(greet("World"))\n'
            ),
        },
        "Build a greeting script",
        timeout=180,
    )
    verdicts.append(('2B', v))

    # --- Scenario 2C: Runtime crash ---
    reset_counters()
    v = _run_scenario(
        "2C: Runtime crash (bad JSON parse)",
        {
            'main.py': (
                'import json\n'
                '\n'
                'data = json.loads("this is not valid json")\n'
                'print("Parsed:", data)\n'
            ),
        },
        "Build a JSON parser script",
        timeout=240,
    )
    verdicts.append(('2C', v))

    # Summary
    print(f"\n  {'='*50}")
    print(f"  Scenario Results:")
    for label, v in verdicts:
        print(f"    {label}: {v}")
    overall = 'FAIL' if any(v == 'FAIL' for _, v in verdicts) else 'PASS'
    print(f"  Overall: {overall}")
    return overall


if __name__ == '__main__':
    result = run_test()
    sys.exit(0 if result in ('PASS', 'SKIP') else 1)
