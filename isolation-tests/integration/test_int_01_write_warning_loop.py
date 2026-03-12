"""Integration Test 01: Main Agent Write -> Warning -> Fix Loop

Tests whether the LLM actually responds to micro-agent warnings.

Flow:
  1. Main agent writes app.py (should import from models.py)
  2. post_write_checks fires if imports are wrong or syntax is bad
  3. Warning is appended to tool result and sent to LLM
  4. Does the LLM fix the issue on its next turn?

Requires: LM Studio running at localhost:1234
"""

import os
import sys
import ast
import json

# Setup path before any backend imports
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
    print("  TEST 01: Main Agent Write -> Warning -> Fix Loop")
    print("=" * 70)

    ok, model = is_lm_studio_running()
    if not ok:
        print("  SKIP  LM Studio not available at localhost:1234")
        return 'SKIP'

    print(f"  LM Studio: CONNECTED (model: {model})")

    ctx = TestContext("write_warning_loop")
    ctx.setup({
        'models.py': (
            'class User:\n'
            '    def __init__(self, name):\n'
            '        self.name = name\n'
            '\n'
            'class Post:\n'
            '    def __init__(self, title, author):\n'
            '        self.title = title\n'
            '        self.author = author\n'
        ),
    })

    try:
        # Create task, chat, plan, artifacts
        ctx.create_task("Build a Flask REST API with User and Post models")
        ctx.create_chat(name="Core Application")

        ctx.create_plan(f"""# Task: Build a Flask REST API

### [x] Step: Requirements
<!-- chat-id: done-1 -->
Done

### [x] Step: Technical Specification
<!-- chat-id: done-2 -->
Done

### [x] Step: Planning
<!-- chat-id: done-3 -->
Done

### [>] Step: Core Application
<!-- chat-id: {ctx.chat_id} -->
Build the main application
Files: app.py
Depends-on: models.py (User, Post)

  - [>] Create app.py
  Files: app.py
  Depends-on: models.py (User, Post)
  Create a Flask application that imports User and Post from models.py and defines REST routes.
""")

        ctx.create_artifact('requirements.md', (
            '# Requirements\n'
            '## Functional\n'
            '- Flask REST API with /users and /posts endpoints\n'
            '- User model with name field\n'
            '- Post model with title and author fields\n'
            '## Technical\n'
            '- Python 3, Flask\n'
            '- Import User and Post from models.py\n'
        ))

        ctx.create_artifact('spec.md', (
            '# Technical Specification\n'
            '## Stack\n'
            '- Python 3 + Flask\n'
            '## Files\n'
            '- models.py: User, Post classes (already exists)\n'
            '- app.py: Flask routes, imports from models.py\n'
            '## API\n'
            '- GET /users -> list users\n'
            '- GET /posts -> list posts\n'
        ))

        # Set timeout
        timer = ctx.set_timeout(180)

        # Run main agent
        print("\n  Running main agent...")
        from services.agent_service import AgentService

        events = collect_events(
            AgentService.run_agent_stream(
                ctx.task_id, ctx.chat_id,
                "Create app.py that imports User and Post from models.py and defines Flask routes for /users and /posts",
                cancel_event=ctx.cancel_event,
                stream_state={},
            ),
            timeout=180,
        )
        timer.cancel()

        # ---- Event Log ----
        print(f"\n  Events collected: {len(events)}")
        print("\n  --- Full Event Timeline ---")
        print_event_log(events)
        print("\n  --- Event Summary ---")
        print_event_summary(events)

        # ---- Checks ----
        print("\n  --- Assertions ---")

        # MUST: Agent emitted events
        check("events were emitted", len(events) > 0, f"count={len(events)}")

        # MUST: At least one tool_call event
        tool_calls = find_events(events, 'tool_call')
        check("at least one tool_call event", len(tool_calls) > 0)

        # MUST: WriteFile was called
        write_calls = [e for e in tool_calls if e[1].get('tool') == 'WriteFile']
        check("WriteFile was called", len(write_calls) > 0,
              f"tool_calls={[(e[1].get('tool'), e[1].get('args', {}).get('path')) for e in tool_calls]}")

        # MUST: tool_result events exist
        tool_results = find_events(events, 'tool_result')
        check("tool_result events exist", len(tool_results) > 0)

        # OBSERVE: Were there any warnings?
        warning_events = [e for e in tool_results if e[1].get('isWarning')]
        if warning_events:
            print(f"\n  --- Warnings Fired ({len(warning_events)}) ---")
            for _, data, ts in warning_events:
                print(f"  [{ts:6.1f}s] WARNING: {str(data.get('result', ''))[:200]}")

            # OBSERVE: After warning, did LLM respond?
            last_warning_ts = warning_events[-1][2]
            later_tool_calls = [e for e in tool_calls if e[2] > last_warning_ts]
            observe("LLM made tool calls AFTER warning",
                    len(later_tool_calls) > 0,
                    f"tool_calls after warning: {len(later_tool_calls)}")

            # OBSERVE: Did LLM use EditFile after warning?
            edit_after = [e for e in later_tool_calls if e[1].get('tool') == 'EditFile']
            observe("LLM used EditFile to fix warning",
                    len(edit_after) > 0,
                    "no EditFile after warning")
        else:
            observe("no warnings fired (LLM wrote clean code)", True)

        # CHECK: Final file on disk
        app_path = os.path.join(ctx.workspace_path, 'app.py')
        if os.path.isfile(app_path):
            with open(app_path, 'r', encoding='utf-8') as f:
                final_content = f.read()

            # Syntax validity
            try:
                ast.parse(final_content)
                check("final app.py is valid Python", True)
            except SyntaxError as e:
                check("final app.py is valid Python", False, f"SyntaxError: {e}")

            # Import resolution
            has_user_import = 'from models import' in final_content and 'User' in final_content
            has_post_import = 'from models import' in final_content and 'Post' in final_content
            observe("app.py imports User from models", has_user_import)
            observe("app.py imports Post from models", has_post_import)
            observe("app.py mentions Flask", 'Flask' in final_content or 'flask' in final_content)

            print(f"\n  --- Final app.py ({len(final_content)} chars) ---")
            for i, line in enumerate(final_content.split('\n')[:20], 1):
                print(f"  {i:3d} | {line}")
            if final_content.count('\n') > 20:
                print(f"  ... ({final_content.count(chr(10)) - 20} more lines)")
        else:
            check("app.py was written to disk", False, "file not found")

        # OBSERVE: done event
        done_events = find_events(events, 'done')
        observe("done event emitted", len(done_events) > 0)

        # Summary stats
        print(f"\n  --- Stats ---")
        print(f"  Total events: {len(events)}")
        print(f"  Tool calls: {len(tool_calls)}")
        print(f"  WriteFile calls: {len(write_calls)}")
        print(f"  Warnings: {len(warning_events)}")
        print(f"  Tool results: {len(tool_results)}")

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
