"""Unit tests for backend/services/reward_agent.py"""

import pytest


# ═══════════════════════════════════════════════════════════
# _fallback_lessons
# ═══════════════════════════════════════════════════════════

class TestFallbackLessons:
    def test_empty_task_score(self):
        from services.reward_agent import _fallback_lessons
        task_score = {'step_scores': [], 'execution_score': None}
        lessons = _fallback_lessons(task_score)
        assert isinstance(lessons, list)

    def test_bad_tool_adherence(self):
        from services.reward_agent import _fallback_lessons
        task_score = {
            'step_scores': [
                {'signals': {'tool_adherence': 0.3, 'code_quality': 0.9, 'efficiency': 0.8, 'import_health': 0.9}},
            ],
            'execution_score': None,
        }
        lessons = _fallback_lessons(task_score)
        tool_lessons = [l for l in lessons if 'WriteFile' in l.get('lesson', '')]
        assert len(tool_lessons) > 0
        assert tool_lessons[0]['type'] == 'negative'

    def test_bad_code_quality(self):
        from services.reward_agent import _fallback_lessons
        task_score = {
            'step_scores': [
                {'signals': {'tool_adherence': 0.9, 'code_quality': 0.3, 'efficiency': 0.8, 'import_health': 0.9}},
            ],
            'execution_score': None,
        }
        lessons = _fallback_lessons(task_score)
        quality_lessons = [l for l in lessons if 'syntax' in l.get('lesson', '').lower() or 'code_quality' in l.get('context', '')]
        assert len(quality_lessons) > 0

    def test_bad_efficiency(self):
        from services.reward_agent import _fallback_lessons
        task_score = {
            'step_scores': [
                {'signals': {'tool_adherence': 0.9, 'code_quality': 0.9, 'efficiency': 0.2, 'import_health': 0.9}},
            ],
            'execution_score': None,
        }
        lessons = _fallback_lessons(task_score)
        eff_lessons = [l for l in lessons if 'efficiency' in l.get('context', '').lower()]
        assert len(eff_lessons) > 0

    def test_bad_import_health(self):
        from services.reward_agent import _fallback_lessons
        task_score = {
            'step_scores': [
                {'signals': {'tool_adherence': 0.9, 'code_quality': 0.9, 'efficiency': 0.9, 'import_health': 0.3}},
            ],
            'execution_score': None,
        }
        lessons = _fallback_lessons(task_score)
        import_lessons = [l for l in lessons if 'import' in l.get('lesson', '').lower()]
        assert len(import_lessons) > 0

    def test_good_signals_generate_positive(self):
        from services.reward_agent import _fallback_lessons
        task_score = {
            'composite': 0.95,
            'grade': 'A',
            'step_scores': [
                {'signals': {'tool_adherence': 0.95, 'code_quality': 0.95, 'efficiency': 0.95, 'import_health': 0.95}},
            ],
            'execution_score': {
                'success': True,
                'signals': {'execution_success': 1.0, 'first_try_success': 1.0},
            },
        }
        lessons = _fallback_lessons(task_score)
        positive = [l for l in lessons if l.get('type') == 'positive']
        assert len(positive) > 0

    def test_execution_failure_generates_lesson(self):
        from services.reward_agent import _fallback_lessons
        task_score = {
            'step_scores': [
                {'signals': {'tool_adherence': 0.9, 'code_quality': 0.9, 'efficiency': 0.9, 'import_health': 0.9}},
            ],
            'execution_score': {
                'success': False,
                'signals': {'execution_success': 0.0, 'first_try_success': 0.0},
            },
        }
        lessons = _fallback_lessons(task_score)
        exec_lessons = [l for l in lessons if 'execution' in l.get('tags', []) or 'execution' in l.get('context', '').lower()]
        assert len(exec_lessons) > 0

    def test_execution_many_attempts(self):
        from services.reward_agent import _fallback_lessons
        task_score = {
            'step_scores': [
                {'signals': {'tool_adherence': 0.9, 'code_quality': 0.9, 'efficiency': 0.9, 'import_health': 0.9}},
            ],
            'execution_score': {
                'success': True,
                'attempts': 4,
                'signals': {'execution_success': 1.0},
            },
        }
        lessons = _fallback_lessons(task_score)
        attempt_lessons = [l for l in lessons if 'first-try' in l.get('lesson', '').lower() or 'attempts' in l.get('context', '')]
        assert len(attempt_lessons) > 0

    def test_low_review_pass_rate(self):
        from services.reward_agent import _fallback_lessons
        task_score = {
            'step_scores': [
                {'signals': {'tool_adherence': 0.9, 'code_quality': 0.9, 'efficiency': 0.9, 'import_health': 0.9}},
            ],
            'execution_score': {
                'success': True,
                'signals': {'review_pass_rate': 0.3},
            },
        }
        lessons = _fallback_lessons(task_score)
        review_lessons = [l for l in lessons if 'read' in l.get('lesson', '').lower() or 'review' in l.get('context', '').lower()]
        assert len(review_lessons) > 0

    def test_capped_at_5_lessons(self):
        from services.reward_agent import _fallback_lessons
        task_score = {
            'step_scores': [
                {'signals': {'tool_adherence': 0.1, 'code_quality': 0.1, 'efficiency': 0.1, 'import_health': 0.1}},
            ],
            'execution_score': {
                'success': False,
                'signals': {'execution_success': 0.0, 'first_try_success': 0.0, 'review_pass_rate': 0.1},
            },
        }
        lessons = _fallback_lessons(task_score)
        assert len(lessons) <= 5

    def test_lesson_format(self):
        from services.reward_agent import _fallback_lessons
        task_score = {
            'step_scores': [
                {'signals': {'tool_adherence': 0.3, 'code_quality': 0.3, 'efficiency': 0.3, 'import_health': 0.3}},
            ],
            'execution_score': None,
        }
        lessons = _fallback_lessons(task_score)
        for lesson in lessons:
            assert 'lesson' in lesson
            assert 'type' in lesson
            assert 'tags' in lesson
            assert lesson['type'] in ('positive', 'negative')
            assert isinstance(lesson['tags'], list)

    def test_always_at_least_one_lesson(self):
        from services.reward_agent import _fallback_lessons
        # All signals good but no composite/grade — should still get a lesson
        task_score = {
            'step_scores': [
                {'signals': {'tool_adherence': 0.7, 'code_quality': 0.7, 'efficiency': 0.7, 'import_health': 0.7}},
            ],
            'execution_score': None,
        }
        lessons = _fallback_lessons(task_score)
        assert len(lessons) >= 1

    def test_grade_c_or_lower_negative(self):
        from services.reward_agent import _fallback_lessons
        task_score = {
            'composite': 0.4,
            'grade': 'D',
            'step_scores': [
                {'signals': {'tool_adherence': 0.6, 'code_quality': 0.6, 'efficiency': 0.6, 'import_health': 0.6}},
            ],
            'execution_score': None,
        }
        lessons = _fallback_lessons(task_score)
        negatives = [l for l in lessons if l['type'] == 'negative']
        assert len(negatives) >= 1


# ═══════════════════════════════════════════════════════════
# _parse_lessons
# ═══════════════════════════════════════════════════════════

class TestParseLessons:
    def test_parse_single_lesson(self):
        from services.reward_agent import _parse_lessons
        text = "LESSON: Always check imports before completing. | TYPE: positive | TAGS: implementation, imports\n"
        lessons = _parse_lessons(text)
        assert len(lessons) == 1
        assert lessons[0]['type'] == 'positive'
        assert 'imports' in lessons[0]['tags']

    def test_parse_multiple_lessons(self):
        from services.reward_agent import _parse_lessons
        text = (
            "LESSON: Always use WriteFile for code output. | TYPE: positive | TAGS: tool_usage\n"
            "LESSON: Do NOT dump code in chat responses. | TYPE: negative | TAGS: tool_usage, implementation\n"
        )
        lessons = _parse_lessons(text)
        assert len(lessons) == 2
        assert lessons[0]['type'] == 'positive'
        assert lessons[1]['type'] == 'negative'

    def test_parse_empty_input(self):
        from services.reward_agent import _parse_lessons
        assert _parse_lessons("") == []

    def test_parse_no_matching_format(self):
        from services.reward_agent import _parse_lessons
        text = "This is just regular text with no structured lessons."
        assert _parse_lessons(text) == []

    def test_parse_ignores_short_lessons(self):
        from services.reward_agent import _parse_lessons
        text = "LESSON: Short. | TYPE: positive | TAGS: test\n"
        # Lesson text "Short." is <= 10 chars, should be ignored
        lessons = _parse_lessons(text)
        assert len(lessons) == 0

    def test_parse_truncates_long_lessons(self):
        from services.reward_agent import _parse_lessons
        long_text = "A" * 300
        text = f"LESSON: {long_text} | TYPE: positive | TAGS: test\n"
        lessons = _parse_lessons(text)
        if lessons:
            assert len(lessons[0]['lesson']) <= 200

    def test_parse_case_insensitive(self):
        from services.reward_agent import _parse_lessons
        text = "lesson: Always validate inputs carefully. | type: Positive | tags: implementation\n"
        lessons = _parse_lessons(text)
        assert len(lessons) == 1
        assert lessons[0]['type'] == 'positive'

    def test_parse_tags_split_correctly(self):
        from services.reward_agent import _parse_lessons
        text = "LESSON: Test all edge cases carefully. | TYPE: negative | TAGS: testing, code_quality, python\n"
        lessons = _parse_lessons(text)
        assert len(lessons) == 1
        assert 'testing' in lessons[0]['tags']
        assert 'code_quality' in lessons[0]['tags']
        assert 'python' in lessons[0]['tags']

    def test_parse_with_surrounding_text(self):
        from services.reward_agent import _parse_lessons
        text = (
            "Based on the task analysis, here are the lessons:\n\n"
            "LESSON: Always verify constructor signatures match. | TYPE: negative | TAGS: implementation, code_quality\n"
            "\nThis concludes the analysis."
        )
        lessons = _parse_lessons(text)
        assert len(lessons) == 1
        assert 'constructor' in lessons[0]['lesson'].lower()


# ═══════════════════════════════════════════════════════════
# _format_signal_breakdown
# ═══════════════════════════════════════════════════════════

class TestFormatSignalBreakdown:
    def test_empty_scores(self):
        from services.reward_agent import _format_signal_breakdown
        result = _format_signal_breakdown({'step_scores': [], 'execution_score': None})
        assert result == 'No signals available.'

    def test_with_step_signals(self):
        from services.reward_agent import _format_signal_breakdown
        task_score = {
            'step_scores': [
                {'signals': {'code_quality': 0.8, 'efficiency': 0.3}},
            ],
            'execution_score': None,
        }
        result = _format_signal_breakdown(task_score)
        assert 'Step Signals' in result
        assert 'code_quality' in result
        assert 'efficiency' in result

    def test_high_signal_gets_plus(self):
        from services.reward_agent import _format_signal_breakdown
        task_score = {
            'step_scores': [{'signals': {'code_quality': 0.9}}],
            'execution_score': None,
        }
        result = _format_signal_breakdown(task_score)
        assert '+' in result

    def test_low_signal_gets_minus(self):
        from services.reward_agent import _format_signal_breakdown
        task_score = {
            'step_scores': [{'signals': {'efficiency': 0.2}}],
            'execution_score': None,
        }
        result = _format_signal_breakdown(task_score)
        assert '-' in result

    def test_with_execution_signals(self):
        from services.reward_agent import _format_signal_breakdown
        task_score = {
            'step_scores': [],
            'execution_score': {
                'signals': {'execution_success': 1.0, 'first_try_success': 0.0},
            },
        }
        result = _format_signal_breakdown(task_score)
        assert 'Execution Signals' in result

    def test_averaged_across_steps(self):
        from services.reward_agent import _format_signal_breakdown
        task_score = {
            'step_scores': [
                {'signals': {'code_quality': 0.6}},
                {'signals': {'code_quality': 0.8}},
            ],
            'execution_score': None,
        }
        result = _format_signal_breakdown(task_score)
        assert '0.70' in result  # average of 0.6 and 0.8


# ═══════════════════════════════════════════════════════════
# _format_step_summaries
# ═══════════════════════════════════════════════════════════

class TestFormatStepSummaries:
    def test_empty(self):
        from services.reward_agent import _format_step_summaries
        assert _format_step_summaries([]) == 'No steps scored.'

    def test_single_step(self):
        from services.reward_agent import _format_step_summaries
        steps = [{'step_id': 'requirements', 'grade': 'A', 'composite': 0.95, 'file_count': 1, 'turn_count': 3}]
        result = _format_step_summaries(steps)
        assert 'requirements' in result
        assert 'A' in result
        assert '0.95' in result

    def test_multiple_steps(self):
        from services.reward_agent import _format_step_summaries
        steps = [
            {'step_id': 'requirements', 'grade': 'A', 'composite': 0.95, 'file_count': 1, 'turn_count': 3},
            {'step_id': 'implementation', 'grade': 'C', 'composite': 0.55, 'file_count': 5, 'turn_count': 12},
        ]
        result = _format_step_summaries(steps)
        assert 'requirements' in result
        assert 'implementation' in result

    def test_missing_fields_use_defaults(self):
        from services.reward_agent import _format_step_summaries
        steps = [{'step_id': 'test'}]
        result = _format_step_summaries(steps)
        assert 'test' in result
        assert '?' in result  # default grade


# ═══════════════════════════════════════════════════════════
# _format_execution_outcome
# ═══════════════════════════════════════════════════════════

class TestFormatExecutionOutcome:
    def test_no_execution_data(self):
        from services.reward_agent import _format_execution_outcome
        assert _format_execution_outcome({}) == 'No execution data.'

    def test_success(self):
        from services.reward_agent import _format_execution_outcome
        task_score = {
            'execution_score': {
                'success': True,
                'attempts': 1,
                'grade': 'A',
            }
        }
        result = _format_execution_outcome(task_score)
        assert 'SUCCESS' in result
        assert 'attempt 1' in result

    def test_failure(self):
        from services.reward_agent import _format_execution_outcome
        task_score = {
            'execution_score': {
                'success': False,
                'attempts': 3,
                'grade': 'F',
            }
        }
        result = _format_execution_outcome(task_score)
        assert 'FAILED' in result
        assert 'attempt 3' in result


# ═══════════════════════════════════════════════════════════
# generate_lessons (with mocked LLM)
# ═══════════════════════════════════════════════════════════

class TestGenerateLessons:
    def test_fallback_when_llm_none(self, mock_config, monkeypatch):
        """When llm=None, should use fallback lessons and record to ExperienceMemory."""
        from services.reward_agent import generate_lessons
        import services.experience_memory as em_module

        # Patch ExperienceMemory DB_PATH to temp dir
        db_path = os.path.join(mock_config, 'experience_memory.json')
        monkeypatch.setattr(em_module, 'DB_PATH', db_path)

        task_score = {
            'composite': 0.4,
            'grade': 'D',
            'step_scores': [
                {'signals': {'tool_adherence': 0.3, 'code_quality': 0.3, 'efficiency': 0.3, 'import_health': 0.3}},
            ],
            'execution_score': None,
        }
        lessons = generate_lessons(
            llm=None,
            task_score=task_score,
            task_id='test-fallback',
        )
        assert len(lessons) > 0
        for lesson in lessons:
            assert 'lesson' in lesson

    def test_fallback_when_llm_fails(self, mock_config, monkeypatch):
        """When LLM call raises, should gracefully fall back to deterministic lessons."""
        from services.reward_agent import generate_lessons
        import services.experience_memory as em_module

        db_path = os.path.join(mock_config, 'experience_memory.json')
        monkeypatch.setattr(em_module, 'DB_PATH', db_path)

        class FakeLLM:
            def stream_chat(self, *args, **kwargs):
                raise ConnectionError("LLM down")

        task_score = {
            'composite': 0.5,
            'grade': 'C',
            'step_scores': [
                {'signals': {'tool_adherence': 0.7, 'code_quality': 0.7, 'efficiency': 0.7, 'import_health': 0.7}},
            ],
            'execution_score': None,
        }
        lessons = generate_lessons(
            llm=FakeLLM(),
            task_score=task_score,
            task_id='test-fail',
        )
        assert len(lessons) >= 1

    def test_llm_success_parses_lessons(self, mock_config, monkeypatch):
        """When LLM returns valid structured output, lessons are parsed."""
        from services.reward_agent import generate_lessons
        import services.experience_memory as em_module

        db_path = os.path.join(mock_config, 'experience_memory.json')
        monkeypatch.setattr(em_module, 'DB_PATH', db_path)

        class FakeLLM:
            def stream_chat(self, messages, **kwargs):
                yield "LESSON: Always validate inputs before processing data. | TYPE: positive | TAGS: implementation, code_quality\n"
                yield "LESSON: Never dump large code blocks in chat responses. | TYPE: negative | TAGS: tool_usage\n"

        task_score = {
            'composite': 0.8,
            'grade': 'B',
            'step_scores': [
                {'signals': {'tool_adherence': 0.9, 'code_quality': 0.8, 'efficiency': 0.7, 'import_health': 0.9}},
            ],
            'execution_score': None,
        }
        lessons = generate_lessons(
            llm=FakeLLM(),
            task_score=task_score,
            task_id='test-llm-success',
        )
        assert len(lessons) == 2
        assert lessons[0]['type'] == 'positive'
        assert lessons[1]['type'] == 'negative'


import os
