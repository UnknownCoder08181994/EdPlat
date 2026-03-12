"""Integration Test 05: Nudge Recovery

Tests whether the nudge system fires when the LLM narrates instead of
calling tools, and whether the LLM recovers after the nudge.

This is a probabilistic test -- the LLM may or may not narrate.
Either outcome is valid; we log what actually happens.

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
    print("  TEST 05: Nudge Recovery")
    print("=" * 70)

    ok, model = is_lm_studio_running()
    if not ok:
        print("  SKIP  LM Studio not available at localhost:1234")
        return 'SKIP'

    print(f"  LM Studio: CONNECTED (model: {model})")

    # Very simple task -- if the LLM can't do this with tools, we have a problem
    ctx = TestContext("nudge_recovery")
    ctx.setup({})  # Empty workspace, agent should create hello.py

    try:
        ctx.create_task("Create a simple Python script")
        ctx.create_chat(name="Core Application")

        ctx.create_plan(f"""# Task: Simple Python script

### [x] Step: Requirements
### [x] Step: Technical Specification
### [x] Step: Planning
### [>] Step: Core Application
<!-- chat-id: {ctx.chat_id} -->
Create the script
Files: hello.py

  - [>] Create hello.py
  Files: hello.py
  Create hello.py that prints "Hello World" to the console.
""")

        ctx.create_artifact('requirements.md', '# Requirements\n- Print Hello World\n')
        ctx.create_artifact('spec.md', '# Spec\n- Single file: hello.py\n- Prints "Hello World"\n')

        timer = ctx.set_timeout(120)

        from services.agent_service import AgentService

        print("\n  Running main agent (simple task)...")
        events = collect_events(
            AgentService.run_agent_stream(
                ctx.task_id, ctx.chat_id,
                "Create hello.py that prints Hello World",
                cancel_event=ctx.cancel_event,
                stream_state={},
            ),
            timeout=120,
        )
        timer.cancel()

        print(f"\n  Events collected: {len(events)}")
        print("\n  --- Full Event Timeline ---")
        print_event_log(events)
        print("\n  --- Event Summary ---")
        print_event_summary(events)

        # ---- Analysis ----
        print("\n  --- Nudge Analysis ---")

        tool_calls = find_events(events, 'tool_call')
        tool_results = find_events(events, 'tool_result')
        data_events = find_events(events, 'data')
        done_events = find_events(events, 'done')

        # Count WriteFile calls
        write_calls = [e for e in tool_calls if e[1].get('tool') == 'WriteFile']
        print(f"  WriteFile calls: {len(write_calls)}")

        # Look for nudge-like messages in tool_results
        nudge_keywords = [
            'STOP', 'BLOCKED', 'FINAL WARNING', 'must use WriteFile',
            'You stopped without', 'use the WriteFile tool',
            'write to a file', 'MUST save',
        ]
        nudge_events = []
        for t, d, ts in tool_results:
            result_text = str(d.get('result', ''))
            if any(kw.lower() in result_text.lower() for kw in nudge_keywords):
                nudge_events.append((t, d, ts))

        if nudge_events:
            print(f"\n  NUDGES FIRED: {len(nudge_events)}")
            for _, d, ts in nudge_events:
                print(f"    [{ts:6.1f}s] {str(d.get('result', ''))[:150]}")

            # Did the agent recover after nudges?
            last_nudge_ts = nudge_events[-1][2]
            writes_after_nudge = [e for e in write_calls if e[2] > last_nudge_ts]
            observe("agent recovered after nudge (wrote files)",
                    len(writes_after_nudge) > 0,
                    f"writes after last nudge: {len(writes_after_nudge)}")
        else:
            print("\n  No nudges fired (agent used tools directly)")
            observe("agent used tools without needing nudges", True)

        # Check: Was hello.py actually written?
        hello_path = os.path.join(ctx.workspace_path, 'hello.py')
        file_written = os.path.isfile(hello_path)
        check("hello.py was written to disk", file_written)

        if file_written:
            with open(hello_path, 'r', encoding='utf-8') as f:
                content = f.read()
            observe("hello.py contains print",
                    'print' in content.lower(),
                    f"content: {content[:100]}")
            observe("hello.py mentions Hello",
                    'hello' in content.lower() or 'Hello' in content,
                    f"content: {content[:100]}")

        # Count total turns (data events between tool calls approximate turns)
        # A rough measure: how many times did the LLM respond?
        turns = 0
        in_response = False
        for t, d, ts in events:
            if t == 'data' and not in_response:
                in_response = True
                turns += 1
            elif t in ('tool_call', 'tool_result', 'done'):
                in_response = False

        print(f"\n  --- Stats ---")
        print(f"  LLM turns: ~{turns}")
        print(f"  Tool calls: {len(tool_calls)}")
        print(f"  WriteFile: {len(write_calls)}")
        print(f"  Nudges fired: {len(nudge_events)}")
        print(f"  File written: {file_written}")

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
