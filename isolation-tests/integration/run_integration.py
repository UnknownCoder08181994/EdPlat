"""Run all integration tests sequentially.

These tests use the REAL LLM (LM Studio at localhost:1234) and create
real workspaces with real files. They must run sequentially because
they share the LLM.

Usage:
    python isolation-tests/integration/run_integration.py [test_number]

    test_number: optional, 1-6. If provided, runs only that test.
"""

import subprocess
import sys
import os
import time

TESTS = [
    ('01', 'test_int_01_write_warning_loop.py', 'Main Agent: Write -> Warning -> Fix'),
    ('02', 'test_int_02_execution_diagnose.py', 'Execution Agent: Error -> Diagnose -> Fix'),
    ('03', 'test_int_03_review_pipeline.py', 'Review Agent: 4-Pass Pipeline'),
    ('04', 'test_int_04_cross_agent_handoff.py', 'Cross-Agent Handoff'),
    ('05', 'test_int_05_nudge_recovery.py', 'Nudge Recovery'),
    ('06', 'test_int_06_snapshot_revert.py', 'Snapshot/Revert Safety'),
    ('07', 'test_int_07_hard_execution.py', 'HARD Execution: Multi-file + Recoder'),
]

test_dir = os.path.dirname(os.path.abspath(__file__))


def check_lm_studio():
    """Check if LM Studio is running."""
    try:
        import requests
        resp = requests.get('http://localhost:1234/v1/models', timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            models = data.get('data', [])
            if models:
                return True, models[0].get('id', 'unknown')
        return False, ''
    except Exception:
        return False, ''


def main():
    # Parse args
    filter_test = None
    if len(sys.argv) > 1:
        try:
            filter_test = int(sys.argv[1])
        except ValueError:
            print(f"Usage: {sys.argv[0]} [test_number 1-6]")
            sys.exit(1)

    print("=" * 70)
    print("  ZENFLOW INTEGRATION TEST SUITE")
    print("  Tests use REAL LLM at localhost:1234")
    print("=" * 70)

    # Check LM Studio
    ok, model = check_lm_studio()
    if ok:
        print(f"\n  LM Studio: CONNECTED (model: {model})")
    else:
        print(f"\n  LM Studio: NOT AVAILABLE at localhost:1234")
        print("  Start LM Studio with a model loaded, then re-run.")
        print("  Tests that require LLM will be SKIPPED.")

    results = {}
    total_start = time.time()

    tests_to_run = TESTS
    if filter_test:
        tests_to_run = [(n, f, d) for n, f, d in TESTS if int(n) == filter_test]
        if not tests_to_run:
            print(f"\n  No test found with number {filter_test}")
            sys.exit(1)

    for num, test_file, description in tests_to_run:
        print(f"\n{'='*70}")
        print(f"  Running: Test {num} - {description}")
        print(f"{'='*70}")

        path = os.path.join(test_dir, test_file)
        test_start = time.time()

        try:
            result = subprocess.run(
                [sys.executable, path],
                capture_output=False,
                cwd=test_dir,
                timeout=600,  # 10 min max per test
            )
            elapsed = time.time() - test_start

            if result.returncode == 0:
                results[num] = ('PASS', elapsed)
                print(f"\n  >>> Test {num} PASSED ({elapsed:.0f}s) <<<")
            else:
                results[num] = ('FAIL', elapsed)
                print(f"\n  >>> Test {num} FAILED ({elapsed:.0f}s, exit code {result.returncode}) <<<")

        except subprocess.TimeoutExpired:
            elapsed = time.time() - test_start
            results[num] = ('TIMEOUT', elapsed)
            print(f"\n  >>> Test {num} TIMED OUT ({elapsed:.0f}s) <<<")

    total_elapsed = time.time() - total_start

    # Summary
    print(f"\n{'='*70}")
    print(f"  INTEGRATION TEST RESULTS")
    print(f"{'='*70}")
    for num, test_file, description in tests_to_run:
        if num in results:
            status, elapsed = results[num]
            print(f"  Test {num}: {status:8s}  ({elapsed:5.0f}s)  {description}")

    pass_count = sum(1 for s, _ in results.values() if s == 'PASS')
    fail_count = sum(1 for s, _ in results.values() if s == 'FAIL')
    timeout_count = sum(1 for s, _ in results.values() if s == 'TIMEOUT')

    print(f"\n  Total: {pass_count} passed, {fail_count} failed, {timeout_count} timed out")
    print(f"  Time: {total_elapsed:.0f}s ({total_elapsed/60:.1f} minutes)")
    print(f"{'='*70}")

    sys.exit(0 if fail_count == 0 and timeout_count == 0 else 1)


if __name__ == '__main__':
    main()
