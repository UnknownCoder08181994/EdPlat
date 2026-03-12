"""Run all isolation tests and report results."""

import subprocess
import sys
import os

TESTS = [
    # Helper function tests
    'test_requirements_scan.py',
    'test_entry_point.py',
    'test_shadowing.py',
    'test_integrity_check.py',
    # Micro-agents (deterministic)
    'test_micro_agents.py',
    # Scoring (pure math)
    'test_reward_scorer.py',
    # Plan engine (parsing + selection)
    'test_plan_engine.py',
    # Agent tests (mocked LLM)
    'test_execution_agent.py',
    'test_recoder_agent.py',
    'test_review_agent.py',
]

test_dir = os.path.dirname(os.path.abspath(__file__))
all_passed = True

print("=" * 70)
print("  ZENFLOW ISOLATION TEST SUITE")
print("=" * 70)

for test_file in TESTS:
    path = os.path.join(test_dir, test_file)
    print(f"\n{'-'*70}")
    print(f"  Running: {test_file}")
    print(f"{'-'*70}")

    try:
        result = subprocess.run(
            [sys.executable, path],
            capture_output=False,
            cwd=test_dir,
            timeout=120,
        )
        if result.returncode != 0:
            all_passed = False
            print(f"\n  >>> {test_file} FAILED (exit code {result.returncode}) <<<")
        else:
            print(f"\n  >>> {test_file} PASSED <<<")
    except subprocess.TimeoutExpired:
        all_passed = False
        print(f"\n  >>> {test_file} TIMED OUT (120s) <<<")

print(f"\n{'='*70}")
if all_passed:
    print("  ALL TESTS PASSED")
else:
    print("  SOME TESTS FAILED")
print(f"{'='*70}")
sys.exit(0 if all_passed else 1)
