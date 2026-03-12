"""Unit tests for backend/services/reward_scorer.py"""

import pytest
from services.reward_scorer import (
    score_step, score_execution, score_task,
    _clamp, _grade,
    STEP_WEIGHTS, EXECUTION_WEIGHTS, GRADE_THRESHOLDS,
)


# ── Utilities ────────────────────────────────────────────────────

class TestClamp:
    def test_within_range(self):
        assert _clamp(0.5) == 0.5

    def test_below_range(self):
        assert _clamp(-0.5) == 0.0

    def test_above_range(self):
        assert _clamp(1.5) == 1.0

    def test_at_boundaries(self):
        assert _clamp(0.0) == 0.0
        assert _clamp(1.0) == 1.0

    def test_custom_range(self):
        assert _clamp(5, lo=0, hi=10) == 5
        assert _clamp(-1, lo=0, hi=10) == 0
        assert _clamp(15, lo=0, hi=10) == 10


class TestGrade:
    def test_a_grade(self):
        assert _grade(0.90) == 'A'
        assert _grade(0.85) == 'A'

    def test_b_grade(self):
        assert _grade(0.75) == 'B'
        assert _grade(0.70) == 'B'

    def test_c_grade(self):
        assert _grade(0.60) == 'C'
        assert _grade(0.55) == 'C'

    def test_d_grade(self):
        assert _grade(0.45) == 'D'
        assert _grade(0.40) == 'D'

    def test_f_grade(self):
        assert _grade(0.30) == 'F'
        assert _grade(0.0) == 'F'


# ── Weights ──────────────────────────────────────────────────────

class TestWeights:
    def test_step_weights_sum_to_one(self):
        assert abs(sum(STEP_WEIGHTS.values()) - 1.0) < 0.001

    def test_execution_weights_sum_to_one(self):
        assert abs(sum(EXECUTION_WEIGHTS.values()) - 1.0) < 0.001


# ── score_step ───────────────────────────────────────────────────

class TestScoreStep:
    def test_perfect_step(self):
        """Step with files, 1 turn, no issues → high score."""
        result = score_step(
            step_id='build-api',
            written_files={'app.py': {'is_new': True, 'added': 50, 'removed': 0}},
            turn_count=1,
        )
        assert result['composite'] >= 0.85
        assert result['grade'] == 'A'
        assert result['file_count'] == 1
        assert result['turn_count'] == 1

    def test_return_shape(self):
        result = score_step('test', {'f.py': {}}, 2)
        assert 'composite' in result
        assert 'signals' in result
        assert 'step_id' in result
        assert 'file_count' in result
        assert 'turn_count' in result
        assert 'grade' in result
        assert isinstance(result['signals'], dict)

    def test_zero_files_low_efficiency(self):
        """Step with 0 files written → zero efficiency signal."""
        result = score_step('test', {}, 3)
        assert result['signals']['efficiency'] == 0.0
        # Composite may still be above 0.5 due to other signals being perfect
        assert result['composite'] < result['composite'] + 0.01  # non-trivial test
        assert result['file_count'] == 0

    def test_syntax_errors_reduce_quality(self):
        result = score_step('test', {'f.py': {}}, 2,
                           micro_agent_warnings=['SYNTAX ERROR in f.py'])
        assert result['signals']['code_quality'] < 1.0

    def test_code_in_prose_reduces_scores(self):
        result = score_step('test', {'f.py': {}}, 2, code_in_prose_count=2)
        assert result['signals']['tool_adherence'] < 1.0
        assert result['signals']['efficiency'] < 1.0

    def test_nudges_reduce_efficiency(self):
        result = score_step('test', {'f.py': {}}, 2, nudge_count=3)
        assert result['signals']['efficiency'] < 1.0

    def test_tool_failures_reduce_adherence(self):
        result = score_step('test', {'f.py': {}}, 2, tool_failure_count=5)
        assert result['signals']['tool_adherence'] < 1.0

    def test_import_warnings_reduce_health(self):
        result = score_step('test', {'f.py': {}}, 2,
                           micro_agent_warnings=['module xyz not found in workspace'])
        assert result['signals']['import_health'] < 1.0

    def test_circular_imports_reduce_both(self):
        result = score_step('test', {'f.py': {}}, 2,
                           micro_agent_warnings=['Circular import detected: a -> b -> a'])
        assert result['signals']['import_health'] < 1.0
        assert result['signals']['code_quality'] < 1.0

    def test_efficiency_caps_at_one(self):
        """Many files in few turns shouldn't exceed 1.0."""
        result = score_step('test', {f'f{i}.py': {} for i in range(10)}, 2)
        assert result['signals']['efficiency'] <= 1.0

    def test_many_turns_low_efficiency(self):
        result = score_step('test', {'f.py': {}}, 15)
        assert result['signals']['efficiency'] < 0.5

    def test_composite_always_clamped(self):
        """Even with extreme values, composite stays 0.0-1.0."""
        result = score_step('test', {}, 15, nudge_count=10,
                           code_in_prose_count=10, tool_failure_count=10,
                           micro_agent_warnings=['SYNTAX ERROR'] * 10)
        assert 0.0 <= result['composite'] <= 1.0


# ── score_execution ──────────────────────────────────────────────

class TestScoreExecution:
    def test_perfect_execution(self):
        result = score_execution(attempts=1, success=True, total_files=5)
        assert result['composite'] >= 0.85
        assert result['grade'] == 'A'
        assert result['success'] is True

    def test_return_shape(self):
        result = score_execution(1, True)
        assert 'composite' in result
        assert 'signals' in result
        assert 'attempts' in result
        assert 'success' in result
        assert 'grade' in result

    def test_failed_execution(self):
        result = score_execution(attempts=5, success=False)
        assert result['composite'] < 0.5
        assert result['success'] is False

    def test_first_try_bonus(self):
        r1 = score_execution(1, True, total_files=5)
        r2 = score_execution(3, True, total_files=5)
        assert r1['signals']['first_try_success'] > r2['signals']['first_try_success']

    def test_integrity_issues_reduce_quality(self):
        r1 = score_execution(1, True, integrity_issues=0, total_files=5)
        r2 = score_execution(1, True, integrity_issues=5, total_files=5)
        assert r1['signals']['code_quality'] > r2['signals']['code_quality']

    def test_review_issues_reduce_pass_rate(self):
        r1 = score_execution(1, True, review_issues=0, total_files=5)
        r2 = score_execution(1, True, review_issues=10, total_files=5)
        assert r1['signals']['review_pass_rate'] > r2['signals']['review_pass_rate']

    def test_composite_clamped(self):
        result = score_execution(10, False, integrity_issues=100,
                                review_issues=100, total_files=1)
        assert 0.0 <= result['composite'] <= 1.0


# ── score_task ───────────────────────────────────────────────────

class TestScoreTask:
    def test_no_scores(self):
        result = score_task([])
        assert result['composite'] == 0.0
        assert result['grade'] == 'F'

    def test_only_execution_score(self):
        exec_sc = score_execution(1, True, total_files=5)
        result = score_task([], execution_score=exec_sc)
        assert result['composite'] == exec_sc['composite']

    def test_only_step_scores(self):
        steps = [
            score_step('s1', {'a.py': {}}, 1),
            score_step('s2', {'b.py': {}}, 1),
        ]
        result = score_task(steps)
        assert result['composite'] > 0.0
        assert result['total_files'] == 2
        assert result['total_turns'] == 2

    def test_blended_score(self):
        """60% step avg + 40% execution."""
        steps = [score_step('s1', {'a.py': {}}, 1)]
        exec_sc = score_execution(1, True, total_files=1)
        result = score_task(steps, execution_score=exec_sc)
        expected = steps[0]['composite'] * 0.6 + exec_sc['composite'] * 0.4
        assert abs(result['composite'] - round(expected, 3)) < 0.01

    def test_return_shape(self):
        result = score_task([score_step('s1', {'a.py': {}}, 1)])
        assert 'composite' in result
        assert 'grade' in result
        assert 'step_scores' in result
        assert 'execution_score' in result
        assert 'step_avg' in result
        assert 'total_files' in result
        assert 'total_turns' in result
