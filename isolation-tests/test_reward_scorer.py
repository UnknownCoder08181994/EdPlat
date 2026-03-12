"""Isolation test: Reward Scorer (reward_scorer.py)

Tests all 3 scoring functions - pure math, no mocks needed:
  1. score_step      - Per-step quality scoring
  2. score_execution - Execution phase scoring
  3. score_task      - Aggregate task scoring
  4. Grade thresholds
  5. Edge cases
"""

import os
import sys

BACKEND_DIR = os.path.join(os.path.dirname(__file__), '..', 'backend')
sys.path.insert(0, os.path.abspath(BACKEND_DIR))

# Stub only the logging utility
import types
fake_utils = types.ModuleType('utils')
fake_logging = types.ModuleType('utils.logging')
fake_logging._safe_log = lambda *a, **kw: None
fake_utils.logging = fake_logging
sys.modules['utils'] = fake_utils
sys.modules['utils.logging'] = fake_logging

from services.reward_scorer import (
    score_step,
    score_execution,
    score_task,
    _grade,
    _clamp,
    STEP_WEIGHTS,
    EXECUTION_WEIGHTS,
)


# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------

passed = 0
failed = 0

def check(name, condition, detail=''):
    global passed, failed
    if condition:
        print(f"  PASS  {name}")
        passed += 1
    else:
        print(f"  FAIL  {name}  {detail}")
        failed += 1


# ===============================================================
# TEST 1: _clamp and _grade helpers
# ===============================================================
print("\n=== TEST 1: Helpers (_clamp, _grade) ===")

check("clamp normal", _clamp(0.5) == 0.5)
check("clamp below 0", _clamp(-0.5) == 0.0)
check("clamp above 1", _clamp(1.5) == 1.0)
check("clamp at boundary", _clamp(0.0) == 0.0)
check("clamp at boundary hi", _clamp(1.0) == 1.0)

check("grade A", _grade(0.90) == 'A')
check("grade A boundary", _grade(0.85) == 'A')
check("grade B", _grade(0.75) == 'B')
check("grade B boundary", _grade(0.70) == 'B')
check("grade C", _grade(0.60) == 'C')
check("grade C boundary", _grade(0.55) == 'C')
check("grade D", _grade(0.45) == 'D')
check("grade D boundary", _grade(0.40) == 'D')
check("grade F", _grade(0.30) == 'F')
check("grade F zero", _grade(0.0) == 'F')


# ===============================================================
# TEST 2: score_step - perfect run
# ===============================================================
print("\n=== TEST 2: score_step - perfect run ===")

result = score_step(
    step_id='implementation',
    written_files={'app.py': {}, 'models.py': {}},
    turn_count=3,
    nudge_count=0,
    code_in_prose_count=0,
    tool_failure_count=0,
    micro_agent_warnings=[],
)

check("returns dict", isinstance(result, dict))
check("has composite", 'composite' in result)
check("has signals", 'signals' in result)
check("has grade", 'grade' in result)
check("has step_id", result['step_id'] == 'implementation')
check("has file_count", result['file_count'] == 2)
check("has turn_count", result['turn_count'] == 3)
check("composite is float", isinstance(result['composite'], float))
check("composite in [0, 1]", 0.0 <= result['composite'] <= 1.0)
check("perfect run gets A", result['grade'] == 'A', f"grade={result['grade']}, score={result['composite']}")

# All signal weights sum to 1
check("step weights sum to 1", abs(sum(STEP_WEIGHTS.values()) - 1.0) < 0.001)


# ===============================================================
# TEST 3: score_step - with warnings
# ===============================================================
print("\n=== TEST 3: score_step - with warnings ===")

result = score_step(
    step_id='test-step',
    written_files={'app.py': {}},
    turn_count=2,
    micro_agent_warnings=[
        '\n!! SYNTAX ERROR in app.py line 5: invalid syntax',
        "!! 'foo' not found in models.py",
    ],
)

check("syntax error reduces code_quality",
      result['signals']['code_quality'] < 1.0,
      f"cq={result['signals']['code_quality']}")
check("import warning reduces import_health",
      result['signals']['import_health'] < 1.0,
      f"ih={result['signals']['import_health']}")
check("score lower than perfect", result['composite'] < 0.95,
      f"score={result['composite']}")


# ===============================================================
# TEST 4: score_step - with nudges and failures
# ===============================================================
print("\n=== TEST 4: score_step - nudges and failures ===")

result = score_step(
    step_id='messy',
    written_files={'app.py': {}},
    turn_count=10,
    nudge_count=3,
    code_in_prose_count=2,
    tool_failure_count=3,
)

check("nudges reduce efficiency",
      result['signals']['efficiency'] < 0.5,
      f"eff={result['signals']['efficiency']}")
check("code_in_prose reduces tool_adherence",
      result['signals']['tool_adherence'] < 1.0,
      f"ta={result['signals']['tool_adherence']}")
check("code_in_prose reduces efficiency",
      result['signals']['efficiency'] < 0.5,
      f"eff={result['signals']['efficiency']}")
check("overall grade reflects problems",
      result['grade'] in ('C', 'D', 'F'),
      f"grade={result['grade']}, score={result['composite']}")


# ===============================================================
# TEST 5: score_step - zero files
# ===============================================================
print("\n=== TEST 5: score_step - zero files ===")

result = score_step(
    step_id='empty',
    written_files={},
    turn_count=5,
)

check("zero files -> efficiency=0", result['signals']['efficiency'] == 0.0)
check("zero files -> file_count=0", result['file_count'] == 0)


# ===============================================================
# TEST 6: score_step - circular imports
# ===============================================================
print("\n=== TEST 6: score_step - circular imports ===")

result = score_step(
    step_id='circular',
    written_files={'a.py': {}, 'b.py': {}},
    turn_count=3,
    micro_agent_warnings=[
        '!! Circular import: a.py -> b.py -> a.py',
    ],
)

check("circular import reduces code_quality",
      result['signals']['code_quality'] < 1.0,
      f"cq={result['signals']['code_quality']}")
check("circular import reduces import_health",
      result['signals']['import_health'] < 1.0,
      f"ih={result['signals']['import_health']}")


# ===============================================================
# TEST 7: score_execution - success on first try
# ===============================================================
print("\n=== TEST 7: score_execution - first try success ===")

result = score_execution(
    attempts=1,
    success=True,
    integrity_issues=0,
    review_issues=0,
    fixes_applied=0,
    total_files=5,
)

check("execution_success=1.0", result['signals']['execution_success'] == 1.0)
check("first_try_success=1.0", result['signals']['first_try_success'] == 1.0)
check("grade is A", result['grade'] == 'A', f"grade={result['grade']}, score={result['composite']}")
check("has attempts", result['attempts'] == 1)
check("success is True", result['success'] == True)

# Execution weights sum to 1
check("execution weights sum to 1", abs(sum(EXECUTION_WEIGHTS.values()) - 1.0) < 0.001)


# ===============================================================
# TEST 8: score_execution - success on second try
# ===============================================================
print("\n=== TEST 8: score_execution - second try ===")

result = score_execution(
    attempts=2,
    success=True,
    integrity_issues=1,
    review_issues=2,
    total_files=5,
)

check("first_try=0.5 for 2 attempts", result['signals']['first_try_success'] == 0.5)
check("lower than first-try score", result['composite'] < 1.0)


# ===============================================================
# TEST 9: score_execution - failure
# ===============================================================
print("\n=== TEST 9: score_execution - failure ===")

result = score_execution(
    attempts=5,
    success=False,
    integrity_issues=3,
    review_issues=5,
    total_files=5,
)

check("execution_success=0", result['signals']['execution_success'] == 0.0)
check("first_try=0", result['signals']['first_try_success'] == 0.0)
check("low grade", result['grade'] in ('D', 'F'), f"grade={result['grade']}")


# ===============================================================
# TEST 10: score_execution - many integrity issues
# ===============================================================
print("\n=== TEST 10: score_execution - integrity issues ===")

result = score_execution(
    attempts=1,
    success=True,
    integrity_issues=10,
    review_issues=0,
    total_files=5,
)

check("integrity issues reduce code_quality",
      result['signals']['code_quality'] < 1.0,
      f"cq={result['signals']['code_quality']}")
check("integrity issues reduce import_health",
      result['signals']['import_health'] < 1.0,
      f"ih={result['signals']['import_health']}")


# ===============================================================
# TEST 11: score_task - blended scoring
# ===============================================================
print("\n=== TEST 11: score_task - blended scoring ===")

step_scores = [
    score_step('s1', {'a.py': {}}, 2),
    score_step('s2', {'b.py': {}, 'c.py': {}}, 3),
]
exec_score = score_execution(1, True, 0, 0, 0, 3)

result = score_task(step_scores, exec_score)

check("has composite", 'composite' in result)
check("has grade", 'grade' in result)
check("has step_avg", 'step_avg' in result)
check("has total_files", 'total_files' in result)
check("has total_turns", 'total_turns' in result)
check("composite in [0,1]", 0.0 <= result['composite'] <= 1.0)
check("total_files=3", result['total_files'] == 3)
check("total_turns=5", result['total_turns'] == 5)
check("step_scores preserved", len(result['step_scores']) == 2)
check("execution_score preserved", result['execution_score'] is not None)

# Verify 60/40 blend
expected = step_scores[0]['composite'] + step_scores[1]['composite']
step_avg = expected / 2
blended = (step_avg * 0.6) + (exec_score['composite'] * 0.4)
check("60/40 blend correct", abs(result['composite'] - round(_clamp(blended), 3)) < 0.01,
      f"expected={round(blended, 3)}, got={result['composite']}")


# ===============================================================
# TEST 12: score_task - no execution score
# ===============================================================
print("\n=== TEST 12: score_task - without execution ===")

step_scores = [
    score_step('s1', {'a.py': {}}, 2),
]
result = score_task(step_scores, None)

check("without exec -> composite equals step_avg",
      abs(result['composite'] - result['step_avg']) < 0.01,
      f"composite={result['composite']}, avg={result['step_avg']}")
check("execution_score is None", result['execution_score'] is None)


# ===============================================================
# TEST 13: score_task - no steps
# ===============================================================
print("\n=== TEST 13: score_task - no steps ===")

exec_score = score_execution(1, True)
result = score_task([], exec_score)

check("no steps -> uses execution score",
      result['composite'] == exec_score['composite'],
      f"got={result['composite']}, exec={exec_score['composite']}")

result2 = score_task([], None)
check("no steps no exec -> composite=0", result2['composite'] == 0.0)
check("no steps no exec -> grade=F", result2['grade'] == 'F')


# ===============================================================
# TEST 14: Edge cases
# ===============================================================
print("\n=== TEST 14: Edge cases ===")

# Very large turn count
result = score_step('edge', {'a.py': {}}, turn_count=100)
check("large turn count -> low efficiency", result['signals']['efficiency'] < 0.3,
      f"eff={result['signals']['efficiency']}")

# score_step with None written_files
result = score_step('null', None, turn_count=5)
check("None written_files -> file_count=0", result['file_count'] == 0)

# score_execution with 0 total_files (avoid division by zero)
result = score_execution(1, True, 0, 0, 0, 0)
check("0 total_files -> no crash", result['composite'] >= 0)

# Very many warnings
many_warnings = ['\n!! SYNTAX ERROR in x.py line 1: bad'] * 10
result = score_step('many', {'a.py': {}}, 2, micro_agent_warnings=many_warnings)
check("many warnings -> clamped at 0", result['signals']['code_quality'] == 0.0)


# ===============================================================
# Summary
# ===============================================================
print(f"\n{'='*60}")
print(f"RewardScorer:  {passed} passed, {failed} failed")
print(f"{'='*60}")
sys.exit(1 if failed > 0 else 0)
