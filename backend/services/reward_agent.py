"""Reward Agent — post-task LLM call that generates behavioral lessons.

After a task is scored, the reward agent:
  1. Builds a compact prompt with the task grade, signal breakdown, and step summaries
  2. Calls the LLM (max_tokens=512, temperature=0.3, no tools)
  3. Parses structured output into lessons
  4. Falls back to deterministic lesson generation if LLM fails

Each lesson is recorded into ExperienceMemory for future prompt injection.

Called by: agent_service.py (background thread after task completion)
"""

import re
import traceback

from utils.logging import _safe_log
from prompts import reward as reward_prompt
from services.experience_memory import ExperienceMemory
from services.reward_scorer import score_task


# ── Deterministic Fallback Lessons ────────────────────────────────

def _fallback_lessons(task_score, step_summaries_data=None):
    """Generate lessons deterministically from signal values.

    Used when the LLM call fails or is unavailable.

    Args:
        task_score: Dict from score_task() with composite, signals, step_scores, etc.
        step_summaries_data: Optional list of step summary dicts

    Returns:
        List of {lesson, type, tags, context, reward} dicts.
    """
    lessons = []
    step_scores = task_score.get('step_scores', [])
    exec_score = task_score.get('execution_score')

    # Aggregate signal averages across steps
    signal_avgs = {}
    if step_scores:
        all_signals = {}
        for ss in step_scores:
            for sig_name, sig_val in ss.get('signals', {}).items():
                all_signals.setdefault(sig_name, []).append(sig_val)
        signal_avgs = {k: sum(v) / len(v) for k, v in all_signals.items()}

    # ── Bad signals -> negative lessons ──

    if signal_avgs.get('tool_adherence', 1.0) < 0.5:
        lessons.append({
            'lesson': 'Do NOT write code in chat responses -- always use WriteFile to save code to disk.',
            'type': 'negative',
            'tags': ['implementation', 'tool_usage'],
            'context': 'Low tool_adherence score detected.',
            'reward': signal_avgs.get('tool_adherence', 0.0),
        })

    if signal_avgs.get('code_quality', 1.0) < 0.5:
        lessons.append({
            'lesson': 'Check for syntax errors and missing imports before saying STEP_COMPLETE.',
            'type': 'negative',
            'tags': ['implementation', 'code_quality'],
            'context': 'Low code_quality score detected.',
            'reward': signal_avgs.get('code_quality', 0.0),
        })

    if signal_avgs.get('efficiency', 1.0) < 0.3:
        lessons.append({
            'lesson': 'Create all required files before STEP_COMPLETE instead of spreading them across turns.',
            'type': 'negative',
            'tags': ['implementation', 'efficiency'],
            'context': 'Low efficiency score -- too many turns per file.',
            'reward': signal_avgs.get('efficiency', 0.0),
        })

    if signal_avgs.get('import_health', 1.0) < 0.5:
        lessons.append({
            'lesson': 'Verify every from-import references an actual name in the target module.',
            'type': 'negative',
            'tags': ['implementation', 'imports', 'python'],
            'context': 'Low import_health score detected.',
            'reward': signal_avgs.get('import_health', 0.0),
        })

    # ── Execution-level lessons ──

    if exec_score:
        if not exec_score.get('success', True):
            lessons.append({
                'lesson': 'Test that the project runs with python main.py before marking complete.',
                'type': 'negative',
                'tags': ['implementation', 'testing'],
                'context': 'Execution failed.',
                'reward': 0.0,
            })
        elif exec_score.get('attempts', 1) > 2:
            lessons.append({
                'lesson': 'Aim for first-try execution success by checking imports and entry points.',
                'type': 'negative',
                'tags': ['implementation', 'testing'],
                'context': f"Needed {exec_score.get('attempts')} attempts to run.",
                'reward': 0.3,
            })

        if exec_score.get('signals', {}).get('review_pass_rate', 1.0) < 0.5:
            lessons.append({
                'lesson': 'Read existing files before writing new ones that import from them.',
                'type': 'negative',
                'tags': ['implementation', 'code_quality'],
                'context': 'Many issues found during code review.',
                'reward': exec_score.get('signals', {}).get('review_pass_rate', 0.0),
            })

    # ── Good signals -> positive lessons ──

    if task_score.get('composite', 0) >= 0.85:
        lessons.append({
            'lesson': 'Keep following the current approach -- well-structured code with clean tool usage.',
            'type': 'positive',
            'tags': ['implementation', 'code_quality'],
            'context': f"Task scored {task_score.get('grade', 'A')}.",
            'reward': task_score.get('composite', 0.85),
        })

    if signal_avgs.get('tool_adherence', 0) >= 0.9:
        lessons.append({
            'lesson': 'Good tool usage pattern -- continue using WriteFile for all code output.',
            'type': 'positive',
            'tags': ['tool_usage'],
            'context': 'High tool_adherence score.',
            'reward': signal_avgs.get('tool_adherence', 0.9),
        })

    # Ensure at least 1 lesson
    if not lessons:
        grade = task_score.get('grade', 'C')
        if grade in ('A', 'B'):
            lessons.append({
                'lesson': 'Continue current approach -- code quality and tool usage are solid.',
                'type': 'positive',
                'tags': ['implementation'],
                'context': f'Task scored {grade}.',
                'reward': task_score.get('composite', 0.7),
            })
        else:
            lessons.append({
                'lesson': 'Review step descriptions carefully and create every listed file.',
                'type': 'negative',
                'tags': ['implementation', 'completion'],
                'context': f'Task scored {grade}.',
                'reward': task_score.get('composite', 0.4),
            })

    return lessons[:5]  # Cap at 5


# ── LLM Response Parser ──────────────────────────────────────────

def _parse_lessons(llm_output):
    """Parse structured LESSON lines from LLM output.

    Expected format:
        LESSON: [rule] | TYPE: [positive/negative] | TAGS: [tags]

    Returns:
        List of {lesson, type, tags} dicts.
    """
    lessons = []
    # Match LESSON: ... | TYPE: ... | TAGS: ...
    pattern = r'LESSON:\s*(.+?)\s*\|\s*TYPE:\s*(positive|negative)\s*\|\s*TAGS:\s*(.+?)(?:\n|$)'

    for match in re.finditer(pattern, llm_output, re.IGNORECASE):
        lesson_text = match.group(1).strip().rstrip('|').strip()
        lesson_type = match.group(2).strip().lower()
        tags_raw = match.group(3).strip()
        tags = [t.strip().lower() for t in tags_raw.split(',') if t.strip()]

        if lesson_text and len(lesson_text) > 10:
            lessons.append({
                'lesson': lesson_text[:200],
                'type': lesson_type,
                'tags': tags,
            })

    return lessons


# ── Signal Formatter ──────────────────────────────────────────────

def _format_signal_breakdown(task_score):
    """Format signal values as a compact readable block."""
    lines = []

    # Step-level signals (averaged)
    step_scores = task_score.get('step_scores', [])
    if step_scores:
        signal_avgs = {}
        for ss in step_scores:
            for sig_name, sig_val in ss.get('signals', {}).items():
                signal_avgs.setdefault(sig_name, []).append(sig_val)
        lines.append("Step Signals (averaged):")
        for sig, vals in sorted(signal_avgs.items()):
            avg = sum(vals) / len(vals)
            marker = '+' if avg >= 0.7 else '-' if avg < 0.5 else '~'
            lines.append(f"  {marker} {sig}: {avg:.2f}")

    # Execution signals
    exec_score = task_score.get('execution_score')
    if exec_score:
        lines.append("Execution Signals:")
        for sig, val in sorted(exec_score.get('signals', {}).items()):
            marker = '+' if val >= 0.7 else '-' if val < 0.5 else '~'
            lines.append(f"  {marker} {sig}: {val:.2f}")

    return '\n'.join(lines) if lines else 'No signals available.'


def _format_step_summaries(step_scores):
    """Format step scores as compact summaries."""
    if not step_scores:
        return 'No steps scored.'

    lines = []
    for ss in step_scores:
        step_id = ss.get('step_id', '?')
        grade = ss.get('grade', '?')
        composite = ss.get('composite', 0)
        files = ss.get('file_count', 0)
        turns = ss.get('turn_count', 0)
        lines.append(f"  {step_id}: {grade} ({composite:.2f}) — {files} files in {turns} turns")

    return '\n'.join(lines)


def _format_execution_outcome(task_score):
    """Format execution outcome as a compact summary."""
    exec_score = task_score.get('execution_score')
    if not exec_score:
        return 'No execution data.'

    success = exec_score.get('success', False)
    attempts = exec_score.get('attempts', 0)
    grade = exec_score.get('grade', '?')

    status = 'SUCCESS' if success else 'FAILED'
    return f"Execution: {status} (attempt {attempts}, grade {grade})"


# ── Main Entry Point ──────────────────────────────────────────────

def generate_lessons(llm, task_score, workspace_path='',
                     step_summaries=None, execution_log='',
                     fingerprint=None, task_id=''):
    """Generate behavioral lessons from task outcomes.

    Args:
        llm: LLMEngine instance (for the LLM call)
        task_score: Dict from score_task()
        workspace_path: Path to workspace (for context)
        step_summaries: Optional step summaries data
        execution_log: Execution log text
        fingerprint: Context fingerprint for experience memory
        task_id: Task identifier

    Returns:
        List of recorded lesson dicts.
    """
    grade = task_score.get('grade', 'F')
    composite = task_score.get('composite', 0.0)

    _safe_log(f"[RewardAgent] Generating lessons for task {task_id} "
              f"(grade={grade}, composite={composite:.3f})")

    # Format inputs for the LLM prompt
    signal_breakdown = _format_signal_breakdown(task_score)
    step_summary_text = _format_step_summaries(task_score.get('step_scores', []))
    execution_outcome = _format_execution_outcome(task_score)

    # Get existing lessons to avoid duplicates
    db = ExperienceMemory.load()
    existing_lessons = [e.get('lesson', '') for e in db.get('entries', [])]

    lessons = []
    llm_succeeded = False

    # ── Try LLM call ──
    if llm is not None:
        try:
            system_prompt = reward_prompt.build(
                task_grade=grade,
                composite_score=composite,
                signal_breakdown=signal_breakdown,
                step_summaries=step_summary_text,
                execution_outcome=execution_outcome,
            )

            existing_block = reward_prompt.build_existing_lessons_block(existing_lessons)

            messages = [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content':
                    f"Generate lessons for this task.\n{existing_block}"
                },
            ]

            # Collect streaming response
            response_parts = []
            for token in llm.stream_chat(
                messages, max_new_tokens=512,
                temperature=0.3, read_timeout=60,
            ):
                # Skip thinking tokens
                if token.startswith('\x00THINK:'):
                    continue
                response_parts.append(token)

            full_response = ''.join(response_parts)
            _safe_log(f"[RewardAgent] LLM response ({len(full_response)} chars)")

            parsed = _parse_lessons(full_response)
            if parsed:
                lessons = parsed
                llm_succeeded = True
                _safe_log(f"[RewardAgent] Parsed {len(parsed)} lessons from LLM")
            else:
                _safe_log("[RewardAgent] LLM returned no parseable lessons, using fallback")

        except Exception as e:
            _safe_log(f"[RewardAgent] LLM call failed: {e}")
            _safe_log(f"[RewardAgent] Traceback: {traceback.format_exc()}")

    # ── Fallback: deterministic lessons ──
    if not llm_succeeded:
        lessons = _fallback_lessons(task_score, step_summaries)
        _safe_log(f"[RewardAgent] Using {len(lessons)} fallback lessons")

    # ── Record lessons to ExperienceMemory ──
    recorded = []
    for lesson_data in lessons:
        try:
            reward = lesson_data.get('reward', composite)
            ExperienceMemory.record(
                lesson=lesson_data['lesson'],
                lesson_type=lesson_data.get('type', 'positive'),
                tags=lesson_data.get('tags', ['implementation']),
                context=lesson_data.get('context', ''),
                fingerprint=fingerprint,
                source_task=task_id,
                source_grade=grade,
                reward_score=reward,
            )
            recorded.append(lesson_data)
            _safe_log(f"[RewardAgent] Recorded: {lesson_data['lesson'][:80]}")
        except Exception as e:
            _safe_log(f"[RewardAgent] Failed to record lesson: {e}")

    # ── Update aggregate stats ──
    try:
        ExperienceMemory.update_stats(task_score)
    except Exception as e:
        _safe_log(f"[RewardAgent] Failed to update stats: {e}")

    _safe_log(f"[RewardAgent] Done: {len(recorded)} lessons recorded for task {task_id}")
    return recorded
