"""Deterministic reward scorer for the RL learning system.

Computes a composite score (0.0-1.0) from multiple signals after each
step completion and after task execution. No LLM calls — pure math.

Signals:
  - file_completion: Did the agent write ALL files from the step's Files: list?
  - execution_success: Did the project run without errors?
  - first_try_success: Ran on first execution attempt?
  - code_quality: AST valid, no placeholders, no truncation
  - efficiency: Turns used vs files created ratio
  - tool_adherence: Proper tool usage (WriteFile, no hallucinations)
  - import_health: All imports resolve, no circular deps
  - review_pass_rate: Issues found by review agent (inverse)
"""

from utils.logging import _safe_log


# ── Signal weights — must sum to 1.0 ─────────────────────────────

STEP_WEIGHTS = {
    'file_completion': 0.25,
    'code_quality':    0.25,
    'efficiency':      0.20,
    'tool_adherence':  0.15,
    'import_health':   0.15,
}

EXECUTION_WEIGHTS = {
    'execution_success':  0.40,
    'first_try_success':  0.15,
    'code_quality':       0.20,
    'import_health':      0.10,
    'review_pass_rate':   0.15,
}

# Grade thresholds
GRADE_THRESHOLDS = [
    (0.85, 'A'),
    (0.70, 'B'),
    (0.55, 'C'),
    (0.40, 'D'),
    (0.0,  'F'),
]


def _clamp(value, lo=0.0, hi=1.0):
    """Clamp a value between lo and hi."""
    return max(lo, min(hi, value))


def _grade(score):
    """Convert composite score to letter grade."""
    for threshold, grade in GRADE_THRESHOLDS:
        if score >= threshold:
            return grade
    return 'F'


def score_step(step_id, written_files, turn_count, nudge_count=0,
               code_in_prose_count=0, tool_failure_count=0,
               micro_agent_warnings=None, expected_file_count=0):
    """Score a single step after completion.

    Args:
        step_id: Step identifier
        written_files: dict of path -> metadata for files written
        turn_count: Number of LLM turns used
        nudge_count: Number of nudges fired (stall + artifact)
        code_in_prose_count: Times agent dumped code in prose
        tool_failure_count: Number of tool call failures
        micro_agent_warnings: List of warning strings from post-write checks
        expected_file_count: Number of files listed in the step's Files: line (0 = unknown)

    Returns: {
        'composite': float 0.0-1.0,
        'signals': {signal_name: float 0.0-1.0},
        'step_id': str,
        'file_count': int,
        'turn_count': int,
        'grade': str,
    }
    """
    warnings = micro_agent_warnings or []
    file_count = len(written_files) if written_files else 0

    # ── File Completion ──
    # Ratio of written files to expected files from the step's Files: list.
    # If no expected files specified (SDD steps, etc), default to 1.0.
    if expected_file_count > 0:
        file_completion = min(1.0, file_count / expected_file_count)
    else:
        file_completion = 1.0 if file_count > 0 else 0.5
    file_completion = _clamp(file_completion)

    # ── Code Quality ──
    # Start at 1.0, deduct for each type of warning
    syntax_errors = sum(1 for w in warnings if 'SYNTAX ERROR' in w)
    import_warnings = sum(1 for w in warnings if 'not found in' in w or 'not defined in' in w)
    pattern_notes = sum(1 for w in warnings if w.startswith('\U0001f4dd'))  # memo emoji
    circular_imports = sum(1 for w in warnings if 'Circular import' in w)

    code_quality = 1.0
    code_quality -= syntax_errors * 0.3
    code_quality -= import_warnings * 0.15
    code_quality -= pattern_notes * 0.05
    code_quality -= circular_imports * 0.2
    code_quality = _clamp(code_quality)

    # ── Efficiency ──
    # Ratio of files created to turns used (ideal: 1 file per turn)
    if file_count > 0 and turn_count > 0:
        efficiency = min(1.0, file_count / max(turn_count - 1, 1))
    elif file_count > 0:
        efficiency = 1.0
    else:
        efficiency = 0.0

    # Bonus for clean runs, penalty for confusion
    if file_count > 0 and nudge_count == 0 and code_in_prose_count == 0:
        efficiency = min(1.0, efficiency + 0.2)
    efficiency -= code_in_prose_count * 0.15
    efficiency -= min(nudge_count, 3) * 0.1
    efficiency = _clamp(efficiency)

    # ── Tool Adherence ──
    tool_adherence = 1.0
    tool_adherence -= code_in_prose_count * 0.25
    tool_adherence -= tool_failure_count * 0.1
    tool_adherence = _clamp(tool_adherence)

    # ── Import Health ──
    if file_count > 0:
        import_issues = import_warnings + circular_imports
        import_health = 1.0 - (import_issues / max(file_count, 1))
    else:
        import_health = 1.0
    import_health = _clamp(import_health)

    # ── Composite ──
    signals = {
        'file_completion': round(file_completion, 3),
        'code_quality': round(code_quality, 3),
        'efficiency': round(efficiency, 3),
        'tool_adherence': round(tool_adherence, 3),
        'import_health': round(import_health, 3),
    }

    composite = sum(signals[k] * STEP_WEIGHTS[k] for k in STEP_WEIGHTS)
    composite = round(_clamp(composite), 3)

    return {
        'composite': composite,
        'signals': signals,
        'step_id': step_id,
        'file_count': file_count,
        'turn_count': turn_count,
        'grade': _grade(composite),
    }


def score_execution(attempts, success, integrity_issues=0,
                    review_issues=0, fixes_applied=0, total_files=0):
    """Score the execution phase outcome.

    Args:
        attempts: Number of execution attempts
        success: Whether execution ultimately succeeded
        integrity_issues: Number of integrity check issues
        review_issues: Number of review agent issues
        fixes_applied: Number of fixes applied during execution
        total_files: Total .py files in workspace

    Returns: {
        'composite': float 0.0-1.0,
        'signals': {signal_name: float 0.0-1.0},
        'attempts': int,
        'success': bool,
        'grade': str,
    }
    """
    # ── Execution Success ──
    execution_success = 1.0 if success else 0.0

    # ── First Try Success ──
    if success and attempts == 1:
        first_try = 1.0
    elif success and attempts == 2:
        first_try = 0.5
    elif success:
        first_try = 0.2
    else:
        first_try = 0.0

    # ── Code Quality (post-execution) ──
    max_files = max(total_files, 1)
    code_quality = 1.0 - (integrity_issues / (max_files * 2))
    code_quality = _clamp(code_quality)

    # ── Import Health ──
    import_health = 1.0 - (integrity_issues * 0.15)
    import_health = _clamp(import_health)

    # ── Review Pass Rate ──
    review_pass_rate = 1.0 - (review_issues / max(max_files * 3, 1))
    review_pass_rate = _clamp(review_pass_rate)

    signals = {
        'execution_success': execution_success,
        'first_try_success': round(first_try, 3),
        'code_quality': round(code_quality, 3),
        'import_health': round(import_health, 3),
        'review_pass_rate': round(review_pass_rate, 3),
    }

    composite = sum(signals[k] * EXECUTION_WEIGHTS[k] for k in EXECUTION_WEIGHTS)
    composite = round(_clamp(composite), 3)

    return {
        'composite': composite,
        'signals': signals,
        'attempts': attempts,
        'success': success,
        'grade': _grade(composite),
    }


def score_task(step_scores, execution_score=None):
    """Aggregate step scores + execution score into a final task score.

    Args:
        step_scores: List of score dicts from score_step()
        execution_score: Score dict from score_execution() (optional)

    Returns: {
        'composite': float 0.0-1.0,
        'grade': str,
        'step_scores': list,
        'execution_score': dict or None,
        'step_avg': float,
        'total_files': int,
        'total_turns': int,
    }
    """
    if not step_scores:
        # No steps scored — use execution score only
        if execution_score:
            return {
                'composite': execution_score['composite'],
                'grade': execution_score.get('grade', _grade(execution_score['composite'])),
                'step_scores': [],
                'execution_score': execution_score,
                'step_avg': 0.0,
                'total_files': 0,
                'total_turns': 0,
            }
        return {
            'composite': 0.0,
            'grade': 'F',
            'step_scores': [],
            'execution_score': None,
            'step_avg': 0.0,
            'total_files': 0,
            'total_turns': 0,
        }

    # Average step scores
    step_avg = sum(s['composite'] for s in step_scores) / len(step_scores)
    total_files = sum(s.get('file_count', 0) for s in step_scores)
    total_turns = sum(s.get('turn_count', 0) for s in step_scores)

    # Blend: 60% step average, 40% execution (if available)
    if execution_score:
        composite = (step_avg * 0.6) + (execution_score['composite'] * 0.4)
    else:
        composite = step_avg

    composite = round(_clamp(composite), 3)

    return {
        'composite': composite,
        'grade': _grade(composite),
        'step_scores': step_scores,
        'execution_score': execution_score,
        'step_avg': round(step_avg, 3),
        'total_files': total_files,
        'total_turns': total_turns,
    }
