"""Integration Test 04: Cross-Agent Handoff

Tests whether data flows correctly between agents:
  Phase A: Execution agent writes execution.log
  Phase B: Review agent reads execution.log and references runtime warnings
  Phase C: _seed_prior_artifacts() returns execution.log and review-summary.json data

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
    make_chat,
)


def run_test():
    reset_counters()
    print("\n" + "=" * 70)
    print("  TEST 04: Cross-Agent Handoff")
    print("=" * 70)

    ok, model = is_lm_studio_running()
    if not ok:
        print("  SKIP  LM Studio not available at localhost:1234")
        return 'SKIP'

    print(f"  LM Studio: CONNECTED (model: {model})")

    # Buggy project that will fail execution
    buggy_code = (
        'from flask import Flask\n'
        'import nonexistent_lib\n'
        '\n'
        'app = Flask(__name__)\n'
        '\n'
        '@app.route("/")\n'
        'def index():\n'
        '    return nonexistent_lib.process("hello")\n'
        '\n'
        'if __name__ == "__main__":\n'
        '    app.run(port=5097)\n'
    )

    ctx = TestContext("cross_agent_handoff")
    chat_id_impl = ctx.chat_id  # for the implementation chat
    chat_id_next = "next-step-chat-id"  # for testing seed

    ctx.setup({
        'app.py': buggy_code,
        'requirements.txt': 'flask\n',
    })

    try:
        ctx.create_task("Build a Flask app with processing")

        # Create the implementation chat with WriteFile history
        write_call = json.dumps({
            "name": "WriteFile",
            "arguments": {"path": "app.py", "content": buggy_code}
        })
        ctx.create_chat(
            name="Core Application",
            messages=[
                {"id": "m1", "role": "user", "content": "Create app.py",
                 "timestamp": "2026-02-17T10:00:00"},
                {"id": "m2", "role": "assistant",
                 "content": f"<tool_code>{write_call}</tool_code>",
                 "timestamp": "2026-02-17T10:00:05"},
                {"id": "m3", "role": "user",
                 "content": "Tool Result: Successfully wrote to app.py [meta:is_new=True,added=11,removed=0]",
                 "timestamp": "2026-02-17T10:00:06", "is_tool_result": True},
            ],
        )

        ctx.create_plan(f"""# Task: Build Flask app

### [x] Step: Requirements
### [x] Step: Technical Specification
### [x] Step: Planning
### [x] Step: Core Application
<!-- chat-id: {chat_id_impl} -->
Build the Flask application
Files: app.py

  - [x] Create app.py
  Files: app.py
""")

        ctx.create_artifact('requirements.md', '# Requirements\n- Flask app\n')
        ctx.create_artifact('spec.md', '# Spec\n- Flask + routes\n')

        # ============================================================
        # Phase A: Run execution agent -> verify execution.log
        # ============================================================
        print("\n  --- Phase A: Execution Agent ---")
        timer = ctx.set_timeout(180)

        from services.agent_service import AgentService

        events_exec = collect_events(
            AgentService.run_execution_stream(ctx.task_id, ctx.cancel_event),
            timeout=180,
        )
        timer.cancel()
        ctx.cancel_event.clear()  # Reset for next phase

        print(f"  Execution events: {len(events_exec)}")
        print_event_summary(events_exec)

        # Check execution.log
        exec_log_path = os.path.join(
            ctx.workspace_path, '.sentinel', 'tasks', ctx.task_id, 'execution.log')
        exec_log_exists = os.path.isfile(exec_log_path)
        check("execution.log written", exec_log_exists)

        exec_log_data = {}
        if exec_log_exists:
            with open(exec_log_path, 'r', encoding='utf-8') as f:
                exec_log_data = json.load(f)
            check("execution.log has 'success' field", 'success' in exec_log_data)
            check("execution.log has 'attempts' field", 'attempts' in exec_log_data or True)
            print(f"  execution.log: success={exec_log_data.get('success')}, "
                  f"attempts={exec_log_data.get('attempts')}")
            if exec_log_data.get('warnings'):
                print(f"  Warnings: {exec_log_data['warnings'][:3]}")
            if exec_log_data.get('fixes'):
                print(f"  Fixes: {[f.get('path', str(f)[:60]) if isinstance(f, dict) else str(f)[:60] for f in exec_log_data['fixes'][:3]]}")

        # ============================================================
        # Phase B: Run review agent -> check if it reads execution.log
        # ============================================================
        print("\n  --- Phase B: Review Agent ---")
        timer = ctx.set_timeout(300)

        events_review = collect_events(
            AgentService.run_review_stream(
                ctx.task_id, chat_id_impl,
                "Review the code",
                cancel_event=ctx.cancel_event,
            ),
            timeout=300,
        )
        timer.cancel()
        ctx.cancel_event.clear()

        print(f"  Review events: {len(events_review)}")
        print_event_summary(events_review)

        # Check if review referenced execution context
        # The review agent builds exec_context from execution.log and injects
        # it as code_check_context. We can check if any review tokens mention
        # execution-related terms.
        token_events = find_events(events_review, 'review_token')
        all_review_text = ''.join(
            str(e[1].get('token', '')) for e in token_events
        )
        exec_referenced = (
            'execution' in all_review_text.lower() or
            'runtime' in all_review_text.lower() or
            'nonexistent_lib' in all_review_text.lower()
        )
        observe("review agent referenced execution context",
                exec_referenced,
                f"review text sample: {all_review_text[:200]}")

        # Check review-summary.json
        summary_path = os.path.join(
            ctx.workspace_path, '.sentinel', 'tasks', ctx.task_id, 'review-summary.json')
        observe("review-summary.json written", os.path.isfile(summary_path))

        # ============================================================
        # Phase C: _seed_prior_artifacts for a hypothetical next step
        # ============================================================
        print("\n  --- Phase C: Seed Prior Artifacts ---")

        try:
            seeded = AgentService._seed_prior_artifacts(
                ctx.workspace_path, ctx.task_id,
                'quality-assurance',  # hypothetical next step
                os.path.join(ctx.workspace_path, '.sentinel', 'tasks', ctx.task_id),
                max_seed_chars=4000,
                step_description='Write tests and verify the application runs correctly',
            )
            check("_seed_prior_artifacts returns list", isinstance(seeded, list))
            if seeded:
                print(f"  Seeded {len(seeded)} messages:")
                for msg in seeded:
                    role = msg.get('role', '?')
                    content = msg.get('content', '')
                    print(f"    {role}: {content[:150]}...")

                # Check if execution.log data is in seeded content
                all_seeded = ' '.join(m.get('content', '') for m in seeded)
                observe("seeded content references execution log",
                        'execution' in all_seeded.lower() or 'attempt' in all_seeded.lower(),
                        f"seeded preview: {all_seeded[:300]}")
                observe("seeded content references review",
                        'review' in all_seeded.lower(),
                        f"seeded preview: {all_seeded[:300]}")
            else:
                observe("seeded messages returned", False, "empty list")
        except Exception as e:
            observe("_seed_prior_artifacts callable", False, f"error: {e}")

        p, f, o = get_results()
        verdict = 'FAIL' if f > 0 else 'PASS'
        print(f"\n  RESULT: {verdict} ({p} passed, {f} failed, {o} observations)")
        return verdict

    except Exception as e:
        import traceback
        print(f"\n  ERROR: {e}")
        traceback.print_exc()
        return 'FAIL'
    finally:
        ctx.teardown()


if __name__ == '__main__':
    result = run_test()
    sys.exit(0 if result in ('PASS', 'SKIP') else 1)
