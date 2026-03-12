"""Integration Test 03: Review Agent 4-Pass Pipeline

Tests whether the review agent:
  - Pass 1 (deterministic) catches code issues via _validate_project_integrity
  - Pass 2 (API check) detects import typos via LLM
  - Pass 3 (quality) finds logic issues via LLM
  - Pass 4 (fix+summary) applies remaining fixes via LLM
  - Writes review-issues.json and review-summary.json

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


def run_test():
    reset_counters()
    print("\n" + "=" * 70)
    print("  TEST 03: Review Agent 4-Pass Pipeline")
    print("=" * 70)

    ok, model = is_lm_studio_running()
    if not ok:
        print("  SKIP  LM Studio not available at localhost:1234")
        return 'SKIP'

    print(f"  LM Studio: CONNECTED (model: {model})")

    # The buggy app.py has:
    # 1. Import typo: jsonfy instead of jsonify
    # 2. Undefined variable usage: undefined_config
    buggy_code = (
        'from flask import Flask, jsonfy\n'
        '\n'
        'app = Flask(__name__)\n'
        '\n'
        '@app.route("/api/data")\n'
        'def get_data():\n'
        '    return jsonfy({"key": "value", "config": undefined_config})\n'
        '\n'
        '@app.route("/api/health")\n'
        'def health():\n'
        '    return jsonfy({"status": "ok"})\n'
        '\n'
        'if __name__ == "__main__":\n'
        '    app.run(port=5088)\n'
    )

    ctx = TestContext("review_pipeline")
    ctx.setup({
        'app.py': buggy_code,
        'requirements.txt': 'flask\n',
    })

    try:
        ctx.create_task("Build a Flask REST API")

        # The chat MUST have a WriteFile tool call so the review agent discovers app.py
        write_tool_call = json.dumps({
            "name": "WriteFile",
            "arguments": {"path": "app.py", "content": buggy_code}
        })
        ctx.create_chat(
            name="Core Application",
            messages=[
                {
                    "id": "msg-1",
                    "role": "user",
                    "content": "Create app.py with Flask routes",
                    "timestamp": "2026-02-17T10:00:00",
                },
                {
                    "id": "msg-2",
                    "role": "assistant",
                    "content": f"I'll create app.py.\n\n<tool_code>{write_tool_call}</tool_code>",
                    "timestamp": "2026-02-17T10:00:05",
                },
                {
                    "id": "msg-3",
                    "role": "user",
                    "content": "Tool Result: Successfully wrote to app.py [meta:is_new=True,added=14,removed=0]",
                    "timestamp": "2026-02-17T10:00:06",
                    "is_tool_result": True,
                },
            ],
        )

        # Plan with implementation step linked to this chat
        ctx.create_plan(f"""# Task: Build a Flask REST API

### [x] Step: Requirements
### [x] Step: Technical Specification
### [x] Step: Planning
### [x] Step: Core Application
<!-- chat-id: {ctx.chat_id} -->
Build the Flask API
Files: app.py
""")

        ctx.create_artifact('requirements.md', (
            '# Requirements\n'
            '- Flask REST API\n'
            '- GET /api/data returns JSON\n'
            '- GET /api/health returns status\n'
        ))
        ctx.create_artifact('spec.md', (
            '# Technical Specification\n'
            '- Python 3 + Flask\n'
            '- Use jsonify for JSON responses\n'
            '- No undefined variables\n'
        ))

        timer = ctx.set_timeout(300)

        from services.agent_service import AgentService

        print("\n  Running review agent...")
        events = collect_events(
            AgentService.run_review_stream(
                ctx.task_id, ctx.chat_id,
                "Review the code for issues",
                cancel_event=ctx.cancel_event,
            ),
            timeout=300,
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

        # Pass events
        pass_events = find_events(events, 'review_pass')
        check("review_pass events emitted", len(pass_events) > 0,
              f"count={len(pass_events)}")

        # Check each pass appeared
        pass_types = [e[1].get('pass', '') for e in pass_events]
        observe("deterministic pass started", 'deterministic' in pass_types,
                f"passes={pass_types}")
        observe("api_check pass started", 'api_check' in pass_types,
                f"passes={pass_types}")
        observe("quality pass started", 'quality' in pass_types,
                f"passes={pass_types}")

        # Pass 1: Deterministic code check
        code_check = find_event(events, 'review_code_check')
        if code_check:
            issues = code_check[1].get('issues', [])
            print(f"\n  Pass 1 issues ({len(issues)}):")
            for issue in issues[:5]:
                print(f"    - {str(issue)[:120]}")
            observe("Pass 1 found issues", len(issues) > 0)
            # Check if it caught the import typo
            import_issue = any('jsonfy' in str(i).lower() or 'import' in str(i).lower()
                               for i in issues)
            observe("Pass 1 caught import-related issue", import_issue,
                    f"issues: {[str(i)[:80] for i in issues]}")
        else:
            observe("review_code_check event exists", False)

        # Review edits
        edit_events = find_events(events, 'review_edit')
        print(f"\n  Edits made: {len(edit_events)}")
        for _, data, ts in edit_events:
            print(f"    [{ts:6.1f}s] {data.get('path', '?')}: "
                  f"'{str(data.get('old_string', ''))[:40]}' -> "
                  f"'{str(data.get('new_string', ''))[:40]}'")

        observe("at least one edit was made", len(edit_events) > 0)

        # Check for jsonfy -> jsonify fix
        jsonify_fixed = any(
            'jsonfy' in str(e[1].get('old_string', '')) and
            'jsonify' in str(e[1].get('new_string', ''))
            for e in edit_events
        )
        observe("jsonfy -> jsonify fix applied", jsonify_fixed)

        # Review done event
        done_event = find_event(events, 'review_done')
        if done_event:
            _, data, ts = done_event
            edits_in_done = data.get('edits', [])
            content = data.get('content', '')
            print(f"\n  Review done: {len(edits_in_done)} edits, content={len(content)} chars")
            check("review_done event has content", len(content) > 0)
        else:
            check("review_done event emitted", False, "not found")

        # Check files on disk
        app_path = os.path.join(ctx.workspace_path, 'app.py')
        if os.path.isfile(app_path):
            with open(app_path, 'r', encoding='utf-8') as f:
                final_content = f.read()
            observe("jsonfy fixed in final file", 'jsonfy' not in final_content,
                    f"still contains 'jsonfy'")
            if 'jsonify' in final_content:
                observe("jsonify present in final file", True)

            print(f"\n  --- Final app.py ---")
            for i, line in enumerate(final_content.split('\n')[:20], 1):
                print(f"  {i:3d} | {line}")

        # Check for review artifacts
        artifacts_dir = os.path.join(ctx.workspace_path, '.sentinel', 'tasks', ctx.task_id)
        issues_path = os.path.join(artifacts_dir, 'review-issues.json')
        summary_path = os.path.join(artifacts_dir, 'review-summary.json')

        observe("review-issues.json written", os.path.isfile(issues_path))
        observe("review-summary.json written", os.path.isfile(summary_path))

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
