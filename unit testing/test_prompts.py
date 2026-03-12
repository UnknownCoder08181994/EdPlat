"""Unit tests for backend/prompts/*.py

Tests that all prompt builder functions:
- Return non-empty strings
- Accept the documented parameters
- Contain expected keywords
"""

import pytest


# ═══════════════════════════════════════════════════════════
# Requirements prompt
# ═══════════════════════════════════════════════════════════

class TestRequirementsPrompt:
    def test_has_match(self):
        from prompts.requirements import _has_match
        assert _has_match("Build a Flask app", r"\bflask\b")
        assert not _has_match("Build a Django app", r"\bflask\b")

    def test_detect_deliverable_type(self):
        from prompts.requirements import _detect_deliverable_type
        assert _detect_deliverable_type("Build a Flask web app") == "web application"
        assert _detect_deliverable_type("Build an API endpoint") == "api/service"
        assert _detect_deliverable_type("Build a CLI tool") == "cli tool / script"
        assert _detect_deliverable_type("Build something vague") == "unspecified"

    def test_detect_quality_level(self):
        from prompts.requirements import _detect_quality_level
        assert _detect_quality_level("Build a production-ready app") == "HIGH"
        assert _detect_quality_level("Build a simple script") == "LOW"
        assert _detect_quality_level("Build a task manager") == "MEDIUM"


# ═══════════════════════════════════════════════════════════
# System prompt
# ═══════════════════════════════════════════════════════════

class TestSystemPrompt:
    def test_build_example_block_compact(self):
        from prompts.system_prompt import build_example_block
        result = build_example_block(step_id=None, compact_mode=True)
        assert 'WriteFile' in result
        assert 'tool_code' in result

    def test_build_example_block_sdd(self):
        from prompts.system_prompt import build_example_block
        result = build_example_block(step_id='requirements', compact_mode=False)
        assert 'WriteFile' in result
        assert 'requirements.md' in result

    def test_build_example_block_implementation(self):
        from prompts.system_prompt import build_example_block
        result = build_example_block(step_id='implementation', compact_mode=False)
        assert 'WriteFile' in result
        assert 'EditFile' in result

    def test_sdd_steps_constant(self):
        from prompts.system_prompt import SDD_STEPS
        assert 'requirements' in SDD_STEPS
        assert 'technical-specification' in SDD_STEPS
        assert 'planning' in SDD_STEPS


# ═══════════════════════════════════════════════════════════
# Nudges
# ═══════════════════════════════════════════════════════════

class TestNudges:
    def test_duplicate_write(self):
        from prompts.nudges import duplicate_write
        result = duplicate_write()
        assert isinstance(result, str)
        assert 'STEP_COMPLETE' in result

    def test_zero_files_no_description(self):
        from prompts.nudges import zero_files
        result = zero_files()
        assert 'WriteFile' in result
        assert 'STEP_COMPLETE' in result

    def test_zero_files_with_description(self):
        from prompts.nudges import zero_files
        result = zero_files(step_description="Files: app.py, models.py")
        assert 'app.py' in result

    def test_missing_artifact(self):
        from prompts.nudges import missing_artifact
        result = missing_artifact(artifact_name='requirements.md')
        assert 'requirements.md' in result
        assert 'WriteFile' in result


# ═══════════════════════════════════════════════════════════
# Handoff
# ═══════════════════════════════════════════════════════════

class TestHandoff:
    def test_generate_handoff_empty(self):
        from prompts.handoff import generate_handoff_note
        result = generate_handoff_note('requirements', '')
        assert result == {}

    def test_generate_handoff_requirements(self):
        from prompts.handoff import generate_handoff_note
        content = "## Overview\nA task manager app.\n## Features\n- Add tasks\n- Remove tasks\n## Constraints\n- Python only\n"
        result = generate_handoff_note('requirements', content)
        assert result.get('step') == 'requirements'

    def test_generate_handoff_unknown_step(self):
        from prompts.handoff import generate_handoff_note
        result = generate_handoff_note('unknown_step', 'some content')
        assert result == {}

    def test_generate_handoff_planning(self):
        from prompts.handoff import generate_handoff_note
        content = "# Implementation Plan\n## Step 1: Setup\nFiles: app.py\n## Step 2: Core\nFiles: models.py\n"
        result = generate_handoff_note('planning', content)
        assert isinstance(result, dict)

    def test_generate_handoff_tech_spec(self):
        from prompts.handoff import generate_handoff_note
        content = "# Technical Specification\n## Architecture\nFlask + SQLite\n## File Structure\n- app.py\n- models.py\n"
        result = generate_handoff_note('technical-specification', content)
        assert isinstance(result, dict)


# ═══════════════════════════════════════════════════════════
# Plan template
# ═══════════════════════════════════════════════════════════

class TestPlanTemplate:
    def test_derive_title_short(self):
        from prompts.plan_template import _derive_title
        assert _derive_title("Build a task manager") == "Build a task manager"

    def test_derive_title_long(self):
        from prompts.plan_template import _derive_title
        long_details = "A" * 100
        title = _derive_title(long_details)
        assert len(title) <= 60

    def test_complexity_tone(self):
        from prompts.plan_template import _complexity_tone
        assert 'Simple' in _complexity_tone(2)
        assert 'Moderate' in _complexity_tone(5)
        assert 'Thorough' in _complexity_tone(7)
        assert 'Complex' in _complexity_tone(9)

    def test_truncate_details(self):
        from prompts.plan_template import _truncate_details
        short = _truncate_details("Short text", max_chars=500)
        assert short == "Short text"
        long = _truncate_details("A\n" * 500, max_chars=100)
        # Truncation adds a suffix like '...(full description available in step prompts)'
        # Just verify it's much shorter than the original
        assert len(long) < len("A\n" * 500)


# ═══════════════════════════════════════════════════════════
# Reward prompt
# ═══════════════════════════════════════════════════════════

class TestRewardPrompt:
    def test_build_returns_string(self):
        from prompts.reward import build
        result = build(
            task_grade='B',
            composite_score=0.75,
            signal_breakdown='code_quality: 0.8\nefficiency: 0.7',
            step_summaries='Step 1: 3 files written',
            execution_outcome='Project ran successfully',
        )
        assert isinstance(result, str)
        assert len(result) > 100

    def test_build_contains_grade(self):
        from prompts.reward import build
        result = build(
            task_grade='A',
            composite_score=0.9,
            signal_breakdown='all good',
            step_summaries='everything worked',
            execution_outcome='success',
        )
        assert 'A' in result
        assert '0.9' in result

    def test_build_contains_format_instructions(self):
        from prompts.reward import build
        result = build(
            task_grade='C',
            composite_score=0.6,
            signal_breakdown='mixed signals',
            step_summaries='some steps',
            execution_outcome='partial',
        )
        assert 'LESSON:' in result
        assert 'TYPE:' in result
        assert 'TAGS:' in result


# ═══════════════════════════════════════════════════════════
# Task reformat
# ═══════════════════════════════════════════════════════════

class TestTaskReformat:
    def test_truly_vague_list(self):
        from prompts.task_reformat import _TRULY_VAGUE
        assert isinstance(_TRULY_VAGUE, list)
        assert len(_TRULY_VAGUE) > 0

    def test_is_vague_truly_empty(self):
        from prompts.task_reformat import is_vague_input
        # Fewer than 3 words = vague
        assert is_vague_input("hi") is True
        assert is_vague_input("do") is True

    def test_is_vague_truly_vague_phrase(self):
        from prompts.task_reformat import is_vague_input
        # Truly vague phrases with < 8 words
        assert is_vague_input("code for me please") is True
        assert is_vague_input("make something cool") is True

    def test_is_vague_short_but_specific(self):
        from prompts.task_reformat import is_vague_input
        # Short but has clear intent -- should NOT be vague
        assert is_vague_input("build a task manager with drag and drop") is False
        assert is_vague_input("create a weather dashboard using flask") is False

    def test_is_vague_detailed_input(self):
        from prompts.task_reformat import is_vague_input
        # Detailed input -- definitely NOT vague
        assert is_vague_input(
            "I want a Flask web app that tracks my gym workouts, "
            "lets me log exercises with sets and reps, and shows "
            "progress charts over time"
        ) is False

    def test_prebuilt_specs_exist(self):
        from prompts.task_reformat import get_prebuilt_spec
        for c in [1, 3, 5, 7, 10]:
            spec = get_prebuilt_spec(complexity=c)
            assert isinstance(spec, str)
            assert len(spec) > 30

    def test_build_returns_four_values(self):
        from prompts.task_reformat import build
        result = build(complexity=5)
        assert isinstance(result, tuple)
        assert len(result) == 4
        system, preamble, shot_input, shot_output = result
        assert isinstance(system, str)
        assert isinstance(preamble, str)
        assert isinstance(shot_input, str)
        assert isinstance(shot_output, str)

    def test_build_basic_tier(self):
        from prompts.task_reformat import build
        system, preamble, shot_input, shot_output = build(complexity=2)
        assert 'BASIC' in preamble
        assert 'function' not in system.lower() or 'signature' not in system.lower()

    def test_build_expert_tier(self):
        from prompts.task_reformat import build
        system, preamble, shot_input, shot_output = build(complexity=9)
        assert 'EXPERT' in preamble

    def test_prebuilt_specs_diverse(self):
        """Prebuilt specs should include web apps, not just CLI scripts."""
        from prompts.task_reformat import _PREBUILT_INTERMEDIATE, _PREBUILT_ADVANCED, _PREBUILT_EXPERT
        all_specs = _PREBUILT_INTERMEDIATE + _PREBUILT_ADVANCED + _PREBUILT_EXPERT
        combined = ' '.join(all_specs).lower()
        # Should have web app variety, not just CLI
        assert 'web' in combined or 'flask' in combined
        assert 'dashboard' in combined or 'interface' in combined


# ═══════════════════════════════════════════════════════════
# Context wiring
# ═══════════════════════════════════════════════════════════

class TestContextWiring:
    def test_build_code_context_empty(self):
        from prompts.context_wiring import build_code_context
        result = build_code_context({})
        assert result == ""

    def test_build_code_context_with_files(self):
        from prompts.context_wiring import build_code_context
        files = {
            'app.py': 'from flask import Flask\napp = Flask(__name__)\n',
            'models.py': 'class User:\n    pass\n',
        }
        result = build_code_context(files)
        assert 'EXISTING CODE FILES' in result
        assert 'app.py' in result
        assert 'models.py' in result

    def test_build_code_context_with_priority(self):
        from prompts.context_wiring import build_code_context
        files = {
            'app.py': 'from flask import Flask\napp = Flask(__name__)\n',
            'models.py': 'class User:\n    pass\n',
        }
        result = build_code_context(files, priority_files=['app.py'])
        assert 'app.py' in result

    def test_code_extensions_constant(self):
        from prompts.context_wiring import CODE_EXTENSIONS
        assert '.py' in CODE_EXTENSIONS
        assert '.js' in CODE_EXTENSIONS
        assert '.html' in CODE_EXTENSIONS


# ═══════════════════════════════════════════════════════════
# Execution prompt
# ═══════════════════════════════════════════════════════════

class TestExecutionPrompt:
    def test_pip_name_map(self):
        from prompts.execution import PIP_NAME_MAP
        assert PIP_NAME_MAP['PIL'] == 'Pillow'
        assert PIP_NAME_MAP['cv2'] == 'opencv-python'
        assert PIP_NAME_MAP['sklearn'] == 'scikit-learn'

    def test_build_diagnose_prompt_basic(self):
        from prompts.execution import build_diagnose_prompt
        result = build_diagnose_prompt(os_name='Windows')
        assert isinstance(result, str)
        assert 'Windows' in result
        assert 'RUNTIME ERROR' in result
        assert 'EditFile' in result

    def test_build_diagnose_prompt_with_spec_context(self):
        from prompts.execution import build_diagnose_prompt
        result = build_diagnose_prompt(
            os_name='Linux',
            spec_context='A Flask REST API for managing users.'
        )
        assert 'Flask REST API' in result
        assert 'Project Specification' in result

    def test_build_diagnose_prompt_with_integrity_issues(self):
        from prompts.execution import build_diagnose_prompt
        result = build_diagnose_prompt(
            os_name='Windows',
            integrity_issues=['Missing __init__.py', 'Broken import in cli.py']
        )
        assert 'Static Analysis' in result
        assert 'Missing __init__.py' in result

    def test_build_diagnose_prompt_with_history(self):
        from prompts.execution import build_diagnose_prompt
        result = build_diagnose_prompt(
            os_name='Windows',
            history_context='Attempt 1: tried adding import, still failed'
        )
        assert 'Previous Fix Attempts' in result
        assert 'Do NOT repeat' in result

    def test_build_diagnose_prompt_with_known_solutions_critical(self):
        from prompts.execution import build_diagnose_prompt
        result = build_diagnose_prompt(
            os_name='Windows',
            known_solutions='CRITICAL REQUIREMENT: Apply this fix first.'
        )
        assert 'CRITICAL' in result
        assert 'FAILURE TO APPLY' in result

    def test_build_diagnose_prompt_with_known_solutions_normal(self):
        from prompts.execution import build_diagnose_prompt
        result = build_diagnose_prompt(
            os_name='Windows',
            known_solutions='Known fix: install missing package.'
        )
        assert 'Try these solutions FIRST' in result

    def test_build_rewrite_prompt_basic(self):
        from prompts.execution import build_rewrite_prompt
        result = build_rewrite_prompt(os_name='Windows')
        assert 'FILE REWRITER' in result
        assert 'WriteFile' in result
        assert 'Windows' in result

    def test_build_rewrite_prompt_with_spec(self):
        from prompts.execution import build_rewrite_prompt
        result = build_rewrite_prompt(
            os_name='Linux',
            spec_context='A CLI tool for parsing CSV files.'
        )
        assert 'Project Specification' in result
        assert 'CLI tool' in result

    def test_build_rewrite_prompt_with_expected_names(self):
        from prompts.execution import build_rewrite_prompt
        result = build_rewrite_prompt(
            os_name='Windows',
            expected_names=['process_data', 'DataLoader', 'Config']
        )
        assert 'Expected Exports' in result
        assert 'process_data' in result
        assert 'DataLoader' in result

    def test_build_rewrite_prompt_with_related_files(self):
        from prompts.execution import build_rewrite_prompt
        result = build_rewrite_prompt(
            os_name='Windows',
            related_files={'main.py': 'from utils import helper\nhelper()'}
        )
        assert 'Related Files' in result
        assert 'main.py' in result

    def test_build_dependency_prompt(self):
        from prompts.execution import build_dependency_prompt
        result = build_dependency_prompt(os_name='Windows')
        assert 'DEPENDENCY FIXER' in result
        assert 'ModuleNotFoundError' in result
        assert 'pip install' in result
        # Should contain the PIP_NAME_MAP entries
        assert 'PIL' in result
        assert 'Pillow' in result

    def test_exec_tool_instructions_constant(self):
        from prompts.execution import _EXEC_TOOL_INSTRUCTIONS
        assert 'EditFile' in _EXEC_TOOL_INSTRUCTIONS
        assert 'WriteFile' in _EXEC_TOOL_INSTRUCTIONS
        assert 'RunCommand' in _EXEC_TOOL_INSTRUCTIONS


# ═══════════════════════════════════════════════════════════
# Review prompts
# ═══════════════════════════════════════════════════════════

class TestReviewPrompt:
    def test_tool_instructions_constant(self):
        from prompts.review import _TOOL_INSTRUCTIONS
        assert 'EditFile' in _TOOL_INSTRUCTIONS
        assert 'WriteFile' in _TOOL_INSTRUCTIONS
        assert 'old_string' in _TOOL_INSTRUCTIONS

    def test_build_api_check_prompt(self):
        from prompts.review import build_api_check_prompt
        result = build_api_check_prompt(os_name='Windows')
        assert isinstance(result, str)
        assert 'API AUDITOR' in result
        assert 'Windows' in result
        assert 'Constructor calls' in result

    def test_build_api_check_prompt_linux(self):
        from prompts.review import build_api_check_prompt
        result = build_api_check_prompt(os_name='Linux')
        assert 'Linux' in result

    def test_build_quality_check_prompt(self):
        from prompts.review import build_quality_check_prompt
        result = build_quality_check_prompt(os_name='Windows')
        assert 'CODE QUALITY REVIEWER' in result
        assert 'Logic bugs' in result
        assert 'Dead code' in result

    def test_build_fix_summary_prompt(self):
        from prompts.review import build_fix_summary_prompt
        result = build_fix_summary_prompt(os_name='Windows')
        assert 'SENIOR CODE REVIEWER' in result
        assert 'Overall Assessment' in result
        assert 'Import Check' in result

    def test_build_legacy(self):
        from prompts.review import build
        result = build(os_name='Windows')
        assert 'MASTER CODE REVIEWER' in result
        assert 'Import & Integration Check' in result
        assert 'API Compatibility Check' in result

    def test_all_review_prompts_contain_tool_instructions(self):
        from prompts.review import (
            build_api_check_prompt, build_quality_check_prompt,
            build_fix_summary_prompt, build
        )
        for builder in [build_api_check_prompt, build_quality_check_prompt,
                        build_fix_summary_prompt, build]:
            result = builder(os_name='Test')
            assert 'tool_code' in result


# ═══════════════════════════════════════════════════════════
# Requirements phases prompts
# ═══════════════════════════════════════════════════════════

class TestRequirementsPhases:
    def test_build_scope_prompt(self):
        from prompts.requirements_phases import build_scope_prompt
        result = build_scope_prompt(task_details='Build a weather dashboard')
        assert isinstance(result, str)
        assert 'weather dashboard' in result
        assert 'JSON' in result
        assert 'complexity' in result

    def test_build_scope_prompt_contains_structure(self):
        from prompts.requirements_phases import build_scope_prompt
        result = build_scope_prompt(task_details='Build a blog')
        assert 'components' in result
        assert 'risks' in result
        assert 'deliverable_type' in result
        assert 'quality_level' in result

    def test_build_deep_dive_prompt(self):
        from prompts.requirements_phases import build_deep_dive_prompt
        scope_data = {
            'components': ['Auth Module', 'API Layer', 'Database'],
            'complexity': 'medium',
        }
        result = build_deep_dive_prompt(
            task_details='Build a user management system',
            scope_data=scope_data,
        )
        assert 'Auth Module' in result
        assert 'API Layer' in result
        assert 'Database' in result
        assert 'requirements' in result.lower()

    def test_build_deep_dive_prompt_empty_components(self):
        from prompts.requirements_phases import build_deep_dive_prompt
        result = build_deep_dive_prompt(
            task_details='Build something',
            scope_data={'components': []},
        )
        assert isinstance(result, str)

    def test_build_interface_prompt(self):
        from prompts.requirements_phases import build_interface_prompt
        scope_data = {'complexity': 'complex'}
        deep_dive_data = {
            'components': [
                {'name': 'Frontend'},
                {'name': 'Backend'},
                {'name': 'Database'},
            ]
        }
        result = build_interface_prompt(
            task_details='Build a full-stack app',
            scope_data=scope_data,
            deep_dive_data=deep_dive_data,
        )
        assert 'Frontend' in result
        assert 'Backend' in result
        assert 'interfaces' in result.lower()

    def test_build_interface_prompt_single_component(self):
        from prompts.requirements_phases import build_interface_prompt
        result = build_interface_prompt(
            task_details='Simple app',
            scope_data={},
            deep_dive_data={'components': [{'name': 'Core'}]},
        )
        # Only one component means no pairs
        assert '(none)' in result

    def test_build_assemble_prompt(self):
        from prompts.requirements_phases import build_assemble_prompt
        scope_data = {
            'complexity': 'medium',
            'components': ['Auth', 'API'],
            'quality_level': 'high',
        }
        result = build_assemble_prompt(
            task_details='Build a user API',
            scope_data=scope_data,
            deep_dive_data={'components': [{'name': 'Auth', 'requirements': ['login']}]},
            interface_data=None,
            artifact_path='.sentinel/tasks/123/requirements.md',
        )
        assert 'requirements.md' in result
        assert 'WriteFile' in result
        assert 'HIGH' in result

    def test_build_assemble_prompt_simple(self):
        from prompts.requirements_phases import build_assemble_prompt
        result = build_assemble_prompt(
            task_details='Build a calculator',
            scope_data={'complexity': 'simple', 'quality_level': 'low'},
            deep_dive_data=None,
            interface_data=None,
            artifact_path='requirements.md',
        )
        assert 'LOW' in result
        assert 'STEP_COMPLETE' in result


# ═══════════════════════════════════════════════════════════
# Reward prompt (additional tests)
# ═══════════════════════════════════════════════════════════

class TestRewardPromptExtended:
    def test_build_existing_lessons_block_empty(self):
        from prompts.reward import build_existing_lessons_block
        result = build_existing_lessons_block([])
        assert result == ''

    def test_build_existing_lessons_block_with_entries(self):
        from prompts.reward import build_existing_lessons_block
        result = build_existing_lessons_block([
            'Always use WriteFile',
            'Check imports before STEP_COMPLETE',
        ])
        assert 'Already Known' in result
        assert 'WriteFile' in result
        assert 'imports' in result

    def test_build_existing_lessons_block_caps_at_15(self):
        from prompts.reward import build_existing_lessons_block
        lessons = [f'Lesson {i}' for i in range(30)]
        result = build_existing_lessons_block(lessons)
        # Should only include first 15
        assert 'Lesson 14' in result
        assert 'Lesson 15' not in result
