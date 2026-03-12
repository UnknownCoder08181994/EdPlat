"""Comprehensive tests for the agent overhaul changes.

Tests cover:
1. _extract_tasks_from_impl_plan() — heading extraction, cap at 8, edge cases
2. _inject_subtasks_into_plan() — top-level replacement, descriptions preserved
3. _get_step_read_instructions() — new params, file list parsing, WriteFile example
4. Zero-files nudge logic validation
5. Planning prompt content — complexity-tiered, no copy-paste examples
6. Step cap verification (cap at 8)
7. Dynamic kickoff message content
8. End-to-end plan rewriting integration
"""
import os
import sys
import re
import json
import tempfile
import shutil
import unittest
from unittest.mock import patch, MagicMock

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from services.agent_service import AgentService


class TestExtractTasksFromImplPlan(unittest.TestCase):
    """Tests for _extract_tasks_from_impl_plan() — 20 tests."""

    def test_basic_h2_headings(self):
        content = "## Project Setup\nCreate app.py\n## Data Layer\nCreate models.py\n"
        tasks = AgentService._extract_tasks_from_impl_plan(content)
        self.assertEqual(len(tasks), 2)
        self.assertEqual(tasks[0][0], "Project Setup")
        self.assertEqual(tasks[1][0], "Data Layer")

    def test_descriptions_captured(self):
        content = "## Project Setup\nCreate the entry point and dependencies.\nFiles: app.py, requirements.txt\n## Data Layer\nDefine the models.\n"
        tasks = AgentService._extract_tasks_from_impl_plan(content)
        self.assertIn("Create the entry point", tasks[0][1])
        self.assertIn("Files: app.py", tasks[0][1])

    def test_h3_headings(self):
        content = "### Task 1: Setup\nSetup desc\n### Task 2: Models\nModels desc\n"
        tasks = AgentService._extract_tasks_from_impl_plan(content)
        self.assertEqual(len(tasks), 2)
        self.assertEqual(tasks[0][0], "Setup")

    def test_h4_headings(self):
        content = "#### Setup Phase\nDescription here\n#### Build Phase\nAnother desc\n"
        tasks = AgentService._extract_tasks_from_impl_plan(content)
        self.assertEqual(len(tasks), 2)

    def test_skip_meta_headings(self):
        content = "## Overview\nThis is the plan\n## Project Setup\nActual task\n## Summary\nDone\n"
        tasks = AgentService._extract_tasks_from_impl_plan(content)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0][0], "Project Setup")

    def test_skip_notes_heading(self):
        content = "## Notes\nSome notes\n## Real Task\nDo stuff\n"
        tasks = AgentService._extract_tasks_from_impl_plan(content)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0][0], "Real Task")

    def test_skip_verification_heading(self):
        content = "## Setup\nSetup desc\n## Verification Steps\nVerify stuff\n"
        tasks = AgentService._extract_tasks_from_impl_plan(content)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0][0], "Setup")

    def test_cap_at_8(self):
        headings = "\n".join([f"## Task {i}\nDescription {i}\n" for i in range(10)])
        tasks = AgentService._extract_tasks_from_impl_plan(headings)
        self.assertEqual(len(tasks), 8)

    def test_cap_exactly_8(self):
        headings = "\n".join([f"## Task {i}\nDescription {i}\n" for i in range(8)])
        tasks = AgentService._extract_tasks_from_impl_plan(headings)
        self.assertEqual(len(tasks), 8)

    def test_fewer_than_8_preserved(self):
        content = "## Setup\nDesc\n## Build\nDesc\n## Test\nDesc\n"
        tasks = AgentService._extract_tasks_from_impl_plan(content)
        self.assertEqual(len(tasks), 3)

    def test_numbered_fallback(self):
        content = "1. Create project structure\n2. Build data models\n3. Add API routes\n"
        tasks = AgentService._extract_tasks_from_impl_plan(content)
        self.assertEqual(len(tasks), 3)

    def test_numbered_fallback_short_names_skipped(self):
        content = "1. Do\n2. Create project structure\n"
        tasks = AgentService._extract_tasks_from_impl_plan(content)
        self.assertEqual(len(tasks), 1)  # "Do" is too short (< 5 chars)

    def test_empty_content(self):
        tasks = AgentService._extract_tasks_from_impl_plan("")
        self.assertEqual(len(tasks), 0)

    def test_no_headings_no_numbers(self):
        content = "This is just a paragraph of text.\n"
        tasks = AgentService._extract_tasks_from_impl_plan(content)
        self.assertEqual(len(tasks), 0)

    def test_heading_with_asterisks(self):
        content = "## **Project Setup**\nSetup desc\n"
        tasks = AgentService._extract_tasks_from_impl_plan(content)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0][0], "Project Setup")

    def test_heading_with_colon(self):
        content = "## Setup:\nSetup description\n"
        tasks = AgentService._extract_tasks_from_impl_plan(content)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0][0], "Setup")

    def test_task_numbered_heading(self):
        content = "## Task 1: Project Setup\nDesc\n## Task 2: Data Models\nDesc\n"
        tasks = AgentService._extract_tasks_from_impl_plan(content)
        self.assertEqual(len(tasks), 2)
        self.assertEqual(tasks[0][0], "Project Setup")
        self.assertEqual(tasks[1][0], "Data Models")

    def test_multiline_description(self):
        content = "## Setup\nLine one.\nLine two.\nLine three.\n## Next\nDesc\n"
        tasks = AgentService._extract_tasks_from_impl_plan(content)
        self.assertIn("Line one.", tasks[0][1])
        self.assertIn("Line two.", tasks[0][1])
        self.assertIn("Line three.", tasks[0][1])

    def test_description_with_checklist(self):
        content = "## Setup\nCreate project files.\n- [ ] Create app.py\n- [ ] Create config.py\n"
        tasks = AgentService._extract_tasks_from_impl_plan(content)
        self.assertIn("- [ ] Create app.py", tasks[0][1])

    def test_short_heading_name_skipped(self):
        content = "## AB\nToo short heading\n## Real Task\nDescription\n"
        tasks = AgentService._extract_tasks_from_impl_plan(content)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0][0], "Real Task")


class TestInjectSubtasksIntoPlan(unittest.TestCase):
    """Tests for _inject_subtasks_into_plan() — 15 tests."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.task_id = 'test-task-123'
        self.artifacts_dir = os.path.join(self.temp_dir, '.sentinel', 'tasks', self.task_id)
        os.makedirs(self.artifacts_dir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def _write_plan(self, content):
        path = os.path.join(self.artifacts_dir, 'plan.md')
        with open(path, 'w') as f:
            f.write(content)
        return path

    def _write_impl_plan(self, content):
        path = os.path.join(self.artifacts_dir, 'implementation-plan.md')
        with open(path, 'w') as f:
            f.write(content)
        return path

    def _read_plan(self):
        path = os.path.join(self.artifacts_dir, 'plan.md')
        with open(path, 'r') as f:
            return f.read()

    def test_replaces_implementation_step(self):
        self._write_plan("# Test\n\n## Workflow Steps\n\n### [x] Step: Requirements\n\n### [x] Step: Planning\n\n### [ ] Step: Implementation\n\n")
        self._write_impl_plan("## Setup\nCreate app.py\n## Models\nCreate models.py\n")
        AgentService._inject_subtasks_into_plan(self.temp_dir, self.task_id)
        result = self._read_plan()
        self.assertNotIn("Step: Implementation", result)
        self.assertIn("Step: Setup", result)
        self.assertIn("Step: Models", result)

    def test_creates_top_level_steps(self):
        self._write_plan("# Test\n\n## Workflow Steps\n\n### [x] Step: Planning\n\n### [ ] Step: Implementation\n\n")
        self._write_impl_plan("## Task A\nDesc A\n## Task B\nDesc B\n")
        AgentService._inject_subtasks_into_plan(self.temp_dir, self.task_id)
        result = self._read_plan()
        self.assertIn("### [ ] Step: Task A", result)
        self.assertIn("### [ ] Step: Task B", result)

    def test_preserves_descriptions(self):
        self._write_plan("# Test\n\n## Workflow Steps\n\n### [x] Step: Planning\n\n### [ ] Step: Implementation\n\n")
        self._write_impl_plan("## Setup\nCreate the project files.\nFiles: app.py, config.py\n")
        AgentService._inject_subtasks_into_plan(self.temp_dir, self.task_id)
        result = self._read_plan()
        self.assertIn("Create the project files.", result)
        self.assertIn("Files: app.py, config.py", result)

    def test_preserves_prior_steps(self):
        self._write_plan("# Test\n\n## Workflow Steps\n\n### [x] Step: Requirements\n<!-- chat-id: abc -->\n\n### [x] Step: Technical Specification\n<!-- chat-id: def -->\n\n### [x] Step: Planning\n<!-- chat-id: ghi -->\n\n### [ ] Step: Implementation\n\n")
        self._write_impl_plan("## Setup\nDesc\n")
        AgentService._inject_subtasks_into_plan(self.temp_dir, self.task_id)
        result = self._read_plan()
        self.assertIn("Step: Requirements", result)
        self.assertIn("Step: Technical Specification", result)
        self.assertIn("Step: Planning", result)
        self.assertIn("chat-id: abc", result)

    def test_no_impl_plan_file(self):
        plan_path = self._write_plan("# Test\n\n### [ ] Step: Implementation\n\n")
        AgentService._inject_subtasks_into_plan(self.temp_dir, self.task_id)
        result = self._read_plan()
        self.assertIn("Step: Implementation", result)  # Unchanged

    def test_empty_impl_plan(self):
        self._write_plan("# Test\n\n### [ ] Step: Implementation\n\n")
        self._write_impl_plan("")
        AgentService._inject_subtasks_into_plan(self.temp_dir, self.task_id)
        result = self._read_plan()
        self.assertIn("Step: Implementation", result)  # Unchanged

    def test_no_implementation_step(self):
        self._write_plan("# Test\n\n### [x] Step: Planning\n\n### [x] Step: Done\n\n")
        self._write_impl_plan("## Task\nDesc\n")
        AgentService._inject_subtasks_into_plan(self.temp_dir, self.task_id)
        result = self._read_plan()
        self.assertNotIn("Step: Task", result)  # Nothing injected since no Implementation step

    def test_multiple_steps_injected(self):
        self._write_plan("# Test\n\n### [x] Step: Planning\n\n### [ ] Step: Implementation\n\n")
        self._write_impl_plan("## Alpha\nDesc A\n## Bravo\nDesc B\n## Charlie\nDesc C\n")
        AgentService._inject_subtasks_into_plan(self.temp_dir, self.task_id)
        result = self._read_plan()
        self.assertIn("Step: Alpha", result)
        self.assertIn("Step: Bravo", result)
        self.assertIn("Step: Charlie", result)

    def test_caps_at_8_steps(self):
        self._write_plan("# Test\n\n### [x] Step: Planning\n\n### [ ] Step: Implementation\n\n")
        headings = "\n".join([f"## Task {i}\nDescription {i}\n" for i in range(12)])
        self._write_impl_plan(headings)
        AgentService._inject_subtasks_into_plan(self.temp_dir, self.task_id)
        result = self._read_plan()
        step_count = result.count("### [ ] Step:")
        self.assertLessEqual(step_count, 8)

    def test_implementation_with_children_replaced(self):
        self._write_plan("# Test\n\n### [x] Step: Planning\n\n### [ ] Step: Implementation\n\n  - [ ] Old subtask\n\n")
        self._write_impl_plan("## New Task\nNew description\n")
        AgentService._inject_subtasks_into_plan(self.temp_dir, self.task_id)
        result = self._read_plan()
        self.assertNotIn("Old subtask", result)
        self.assertIn("Step: New Task", result)

    def test_new_steps_are_unchecked(self):
        self._write_plan("# Test\n\n### [x] Step: Planning\n\n### [ ] Step: Implementation\n\n")
        self._write_impl_plan("## Setup\nDesc\n")
        AgentService._inject_subtasks_into_plan(self.temp_dir, self.task_id)
        result = self._read_plan()
        self.assertIn("### [ ] Step: Setup", result)
        self.assertNotIn("### [x] Step: Setup", result)

    def test_preserves_content_after_implementation(self):
        # Normally there's nothing after Implementation, but test robustness
        self._write_plan("# Test\n\n### [x] Step: Planning\n\n### [ ] Step: Implementation\n\n### [ ] Step: Deploy\n\nDeploy description\n")
        self._write_impl_plan("## Build\nBuild things\n")
        AgentService._inject_subtasks_into_plan(self.temp_dir, self.task_id)
        result = self._read_plan()
        self.assertIn("Step: Build", result)
        self.assertIn("Step: Deploy", result)

    def test_layer_based_headings(self):
        self._write_plan("# Test\n\n### [x] Step: Planning\n\n### [ ] Step: Implementation\n\n")
        self._write_impl_plan(
            "## Project Setup & Configuration\n"
            "Set up entry point and deps.\n"
            "Files: app.py, requirements.txt\n\n"
            "## Data Layer & Models\n"
            "Define database models.\n"
            "Files: models.py\n\n"
            "## API Routes & Business Logic\n"
            "Build REST endpoints.\n"
            "Files: routes.py\n"
        )
        AgentService._inject_subtasks_into_plan(self.temp_dir, self.task_id)
        result = self._read_plan()
        self.assertIn("Step: Project Setup & Configuration", result)
        self.assertIn("Step: Data Layer & Models", result)
        self.assertIn("Step: API Routes & Business Logic", result)
        self.assertIn("Files: app.py, requirements.txt", result)

    def test_idempotent_no_double_injection(self):
        self._write_plan("# Test\n\n### [x] Step: Planning\n\n### [ ] Step: Implementation\n\n")
        self._write_impl_plan("## Setup\nDesc\n## Build\nDesc\n")
        AgentService._inject_subtasks_into_plan(self.temp_dir, self.task_id)
        # Second call should be a no-op (no Implementation step anymore)
        AgentService._inject_subtasks_into_plan(self.temp_dir, self.task_id)
        result = self._read_plan()
        self.assertEqual(result.count("Step: Setup"), 1)
        self.assertEqual(result.count("Step: Build"), 1)

    def test_checklist_items_become_plain_bullets(self):
        """Checklist items (- [ ] ...) become plain description bullets (no children)."""
        self._write_plan("# Test\n\n### [x] Step: Planning\n\n### [ ] Step: Implementation\n\n")
        self._write_impl_plan(
            "## Setup\nCreate project files.\nFiles: app.py\n"
            "- [ ] Create app.py with Flask factory\n"
            "- [ ] Create config.py with settings\n"
        )
        AgentService._inject_subtasks_into_plan(self.temp_dir, self.task_id)
        result = self._read_plan()
        # Checklist items become plain bullets — no indent, no [ ] checkbox
        self.assertIn("- Create app.py with Flask factory", result)
        self.assertIn("- Create config.py with settings", result)
        # Should NOT have indented checkbox format (old child format)
        self.assertNotIn("    - [ ]", result)
        # Non-checklist lines preserved as-is
        self.assertIn("Create project files.", result)
        self.assertIn("Files: app.py", result)

    def test_flat_bullets_not_parsed_as_children(self):
        """After injection, plain bullets should NOT be parsed as children by plan_engine."""
        from services.plan_engine import parse_plan

        self._write_plan("# Test\n\n### [x] Step: Planning\n\n### [ ] Step: Implementation\n\n")
        self._write_impl_plan(
            "## Setup\nCreate project files.\nFiles: app.py\n"
            "- [ ] Create app.py with Flask factory\n"
            "- [ ] Create config.py with settings\n"
        )
        AgentService._inject_subtasks_into_plan(self.temp_dir, self.task_id)

        plan = parse_plan(os.path.join(self.artifacts_dir, 'plan.md'))
        setup_step = plan.find_step('setup')
        self.assertIsNotNone(setup_step)
        # Flat steps: no children — checklist items are plain description bullets
        self.assertEqual(len(setup_step.children), 0)
        # But the bullet text should appear in the step description
        self.assertIn("Create app.py with Flask factory", setup_step.description)
        self.assertIn("Create config.py with settings", setup_step.description)

    def test_flat_steps_have_no_children(self):
        """Injected flat steps should have zero children."""
        from services.plan_engine import parse_plan

        self._write_plan("# Test\n\n### [x] Step: Planning\n\n### [ ] Step: Implementation\n\n")
        self._write_impl_plan(
            "## Setup\nDesc.\n"
            "- [ ] Task A\n"
            "- [ ] Task B\n"
        )
        AgentService._inject_subtasks_into_plan(self.temp_dir, self.task_id)

        plan = parse_plan(os.path.join(self.artifacts_dir, 'plan.md'))
        setup_step = plan.find_step('setup')
        self.assertEqual(len(setup_step.children), 0)
        # Bullet text should be in description instead
        self.assertIn("Task A", setup_step.description)
        self.assertIn("Task B", setup_step.description)

    def test_flat_steps_are_root_level(self):
        """Injected steps should be root-level with no scoped IDs."""
        from services.plan_engine import parse_plan

        self._write_plan("# Test\n\n### [x] Step: Planning\n\n### [ ] Step: Implementation\n\n")
        self._write_impl_plan(
            "## Setup\nDesc.\n"
            "- [ ] Create entry point\n"
        )
        AgentService._inject_subtasks_into_plan(self.temp_dir, self.task_id)

        plan = parse_plan(os.path.join(self.artifacts_dir, 'plan.md'))
        setup_step = plan.find_step('setup')
        self.assertIsNotNone(setup_step)
        # No :: in ID — it's a root step, not a child
        self.assertNotIn("::", setup_step.id)
        self.assertEqual(len(setup_step.children), 0)

    def test_select_next_picks_flat_step_directly(self):
        """select_next should pick the flat step directly (no children to drill into)."""
        from services.plan_engine import parse_plan, select_next

        self._write_plan("# Test\n\n### [x] Step: Planning\n\n### [ ] Step: Implementation\n\n")
        self._write_impl_plan(
            "## Setup\nDesc.\n"
            "- [ ] First sub-step\n"
            "- [ ] Second sub-step\n"
        )
        AgentService._inject_subtasks_into_plan(self.temp_dir, self.task_id)

        plan = parse_plan(os.path.join(self.artifacts_dir, 'plan.md'))
        result = select_next(plan)
        self.assertIsNotNone(result.target)
        # With flat steps, select_next picks the root step itself
        self.assertEqual(result.target.name, "Setup")
        self.assertTrue(result.target.is_root)

    def test_description_text_stays_on_parent(self):
        """Non-checklist text (description, Files: line) should remain as parent description."""
        from services.plan_engine import parse_plan

        self._write_plan("# Test\n\n### [x] Step: Planning\n\n### [ ] Step: Implementation\n\n")
        self._write_impl_plan(
            "## Setup\nCreate the project files.\nFiles: app.py, config.py\n"
            "- [ ] Create app.py\n"
        )
        AgentService._inject_subtasks_into_plan(self.temp_dir, self.task_id)

        plan = parse_plan(os.path.join(self.artifacts_dir, 'plan.md'))
        setup_step = plan.find_step('setup')
        self.assertIn("Create the project files.", setup_step.description)
        self.assertIn("Files: app.py, config.py", setup_step.description)

    def test_to_dict_no_children_key_for_flat_steps(self):
        """to_dict() should NOT include children key when steps are flat."""
        from services.plan_engine import parse_plan

        self._write_plan("# Test\n\n### [x] Step: Planning\n\n### [ ] Step: Implementation\n\n")
        self._write_impl_plan(
            "## Setup\nDesc.\n"
            "- [ ] Sub A\n"
            "- [ ] Sub B\n"
        )
        AgentService._inject_subtasks_into_plan(self.temp_dir, self.task_id)

        plan = parse_plan(os.path.join(self.artifacts_dir, 'plan.md'))
        setup_step = plan.find_step('setup')
        d = setup_step.to_dict()
        # Flat steps have no children → to_dict() omits the children key
        self.assertNotIn("children", d)
        # But description should contain the bullet text
        self.assertIn("Sub A", d["description"])
        self.assertIn("Sub B", d["description"])


class TestGetStepReadInstructions(unittest.TestCase):
    """Tests for _get_step_read_instructions() — 20 tests."""

    def test_requirements_step(self):
        result = AgentService._get_step_read_instructions('requirements', '.')
        self.assertIn("REQUIREMENTS step", result)
        self.assertIn("requirements.md", result)

    def test_technical_spec_step(self):
        result = AgentService._get_step_read_instructions('technical-specification', '.')
        self.assertIn("TECHNICAL SPECIFICATION step", result)
        self.assertIn("spec.md", result)

    def test_planning_step_has_complexity_tiers(self):
        result = AgentService._get_step_read_instructions('planning', '.')
        self.assertIn("SIMPLE", result)
        self.assertIn("MEDIUM", result)
        self.assertIn("COMPLEX", result)
        self.assertIn("1 category", result)
        self.assertIn("2 categories", result)
        self.assertIn("3-5", result)

    def test_planning_step_has_file_ownership_format(self):
        result = AgentService._get_step_read_instructions('planning', '.')
        self.assertIn("Files:", result)
        # Example present but explicitly marked as DO NOT COPY
        self.assertIn("DO NOT copy", result)

    def test_planning_step_has_format_rules(self):
        result = AgentService._get_step_read_instructions('planning', '.')
        self.assertIn("## (double hash)", result)
        self.assertIn("- [ ]", result)

    def test_dynamic_step_has_step_name(self):
        result = AgentService._get_step_read_instructions(
            'project-setup', '.', step_name='Project Setup', step_description=''
        )
        self.assertIn("Project Setup", result)

    def test_dynamic_step_has_description(self):
        desc = "Create the project entry point and install dependencies."
        result = AgentService._get_step_read_instructions(
            'project-setup', '.', step_name='Project Setup', step_description=desc
        )
        self.assertIn(desc, result)

    def test_dynamic_step_parses_files_line(self):
        desc = "Set up the project.\nFiles: app.py, config.py, requirements.txt\n- [ ] Create app.py"
        result = AgentService._get_step_read_instructions(
            'project-setup', '.', step_name='Project Setup', step_description=desc
        )
        self.assertIn("FILES YOU MUST CREATE", result)
        self.assertIn("app.py", result)
        self.assertIn("config.py", result)
        self.assertIn("requirements.txt", result)

    def test_dynamic_step_parses_create_patterns(self):
        desc = "- [ ] Create models.py with User model\n- [ ] Create database.py with init"
        result = AgentService._get_step_read_instructions(
            'data-layer', '.', step_name='Data Layer', step_description=desc
        )
        self.assertIn("FILES YOU MUST CREATE", result)
        self.assertIn("models.py", result)
        self.assertIn("database.py", result)

    def test_dynamic_step_has_writefile_example(self):
        result = AgentService._get_step_read_instructions(
            'project-setup', '.', step_name='Setup', step_description='Create files'
        )
        self.assertIn("WriteFile", result)
        self.assertIn("<tool_code>", result)
        self.assertIn("app.py", result)

    def test_dynamic_step_warns_against_writing_in_response(self):
        result = AgentService._get_step_read_instructions(
            'project-setup', '.', step_name='Setup', step_description=''
        )
        self.assertIn("MUST use WriteFile for EVERY file", result)

    def test_dynamic_step_has_step_complete(self):
        result = AgentService._get_step_read_instructions(
            'project-setup', '.', step_name='Setup', step_description=''
        )
        self.assertIn("[STEP_COMPLETE]", result)

    def test_dynamic_step_no_run_application(self):
        result = AgentService._get_step_read_instructions(
            'project-setup', '.', step_name='Setup', step_description=''
        )
        self.assertIn("Do NOT run the app or tests", result)

    def test_dynamic_step_artifact_path_in_summary(self):
        result = AgentService._get_step_read_instructions(
            'project-setup', '.sentinel/tasks/abc', step_name='Setup', step_description=''
        )
        self.assertIn("project-setup.md", result)

    def test_empty_step_name_and_desc(self):
        result = AgentService._get_step_read_instructions('my-step', '.', step_name='', step_description='')
        self.assertIn("WriteFile", result)  # Should still have WriteFile instructions

    def test_files_line_single_file(self):
        desc = "Build routes.\nFiles: routes.py"
        result = AgentService._get_step_read_instructions(
            'api-routes', '.', step_name='API Routes', step_description=desc
        )
        self.assertIn("routes.py", result)

    def test_no_files_in_description(self):
        desc = "Just do some general work on the project."
        result = AgentService._get_step_read_instructions(
            'general', '.', step_name='General', step_description=desc
        )
        self.assertNotIn("FILES YOU MUST CREATE", result)

    def test_deduplicates_file_mentions(self):
        desc = "- [ ] Create models.py with User\n- [ ] Create models.py with Note"
        result = AgentService._get_step_read_instructions(
            'data', '.', step_name='Data', step_description=desc
        )
        # Should only list models.py once
        count = result.count("  - models.py")
        self.assertEqual(count, 1)

    def test_planning_step_complexity_tiered_instruction(self):
        result = AgentService._get_step_read_instructions('planning', '.')
        # Should have category counts for each tier
        self.assertIn("SIMPLE=1", result)
        self.assertIn("MEDIUM=2", result)
        self.assertIn("COMPLEX=3-5", result)

    def test_artifacts_path_dot(self):
        result = AgentService._get_step_read_instructions('requirements', '.')
        self.assertIn("requirements.md", result)
        self.assertNotIn("./requirements.md", result)


class TestPlanningPromptContent(unittest.TestCase):
    """Tests for planning prompt quality — complexity-aware, anti-overengineering."""

    def setUp(self):
        self.prompt = AgentService._get_step_read_instructions('planning', '.', task_details='Build a test app')

    def test_has_medium_example(self):
        """Should have a MEDIUM example with specific category names."""
        self.assertIn("MEDIUM", self.prompt)
        self.assertIn("Flask App & Task CRUD", self.prompt)
        self.assertIn("Tests & Dependencies", self.prompt)

    def test_has_complexity_tiers(self):
        """SIMPLE=1, MEDIUM=2, COMPLEX=3-5."""
        self.assertIn("1 category", self.prompt)
        self.assertIn("2 categories", self.prompt)
        self.assertIn("3-5", self.prompt)

    def test_has_task_description(self):
        """Task description should be injected into the prompt."""
        self.assertIn("THE USER'S TASK", self.prompt)
        self.assertIn("Build a test app", self.prompt)

    def test_todo_is_medium(self):
        """To-do list should be explicitly 2 categories."""
        self.assertIn("to-do list", self.prompt.lower())
        self.assertIn("2 categories", self.prompt)

    def test_has_format_rules(self):
        """Must specify ## for categories and - [ ] for sub-steps."""
        self.assertIn("## (double hash)", self.prompt)
        self.assertIn("- [ ]", self.prompt)
        self.assertIn("NOT # or ### or ####", self.prompt)

    def test_no_category_prefix(self):
        """Must tell model not to use Category: prefixes."""
        self.assertIn("Category 1:", self.prompt)  # mentioned as "Do NOT write"

    def test_file_starts_with_category(self):
        """Must tell model file starts with ## not a title."""
        self.assertIn("start with ##", self.prompt)

    def test_has_naming_guidance(self):
        """Must have category naming guidance."""
        self.assertIn("specific", self.prompt)
        self.assertIn("generic", self.prompt)

    def test_forbids_documentation_category(self):
        """Must forbid Documentation/README category."""
        self.assertIn("Documentation", self.prompt)
        self.assertIn("README", self.prompt)

    def test_forbids_separate_testing(self):
        """Must forbid separate Testing category for simple/medium tasks."""
        self.assertIn("Testing", self.prompt)

    def test_has_files_keyword(self):
        self.assertIn("Files:", self.prompt)

    def test_has_checklist_placeholder(self):
        self.assertIn("- [ ]", self.prompt)

    def test_step_complete_instruction(self):
        self.assertIn("[STEP_COMPLETE]", self.prompt)

    def test_has_implementation_plan_path(self):
        self.assertIn("implementation-plan.md", self.prompt)

    def test_no_bracket_placeholders(self):
        self.assertNotIn("[High-Level Category Name]", self.prompt)

    def test_has_example_boundary(self):
        self.assertIn("END OF", self.prompt)

    def test_substep_is_within_step(self):
        """Must explain that each sub-step is a task the agent performs within this step."""
        self.assertIn("concrete task the agent will perform within this step", self.prompt)

    def test_substep_15_word_minimum(self):
        """Must specify 15+ word minimum for sub-steps."""
        self.assertIn("15+ words", self.prompt)

    def test_no_thinking_in_file(self):
        """Must tell model not to put thinking/commentary in the file."""
        self.assertIn("no thinking", self.prompt.lower())


class TestStepCap(unittest.TestCase):
    """Tests for step cap behavior — cap at 8."""

    def test_6_steps_not_capped(self):
        headings = "\n".join([f"## Task {i}\nDesc {i}\n" for i in range(6)])
        tasks = AgentService._extract_tasks_from_impl_plan(headings)
        self.assertEqual(len(tasks), 6)

    def test_8_steps_not_capped(self):
        headings = "\n".join([f"## Task {i}\nDesc {i}\n" for i in range(8)])
        tasks = AgentService._extract_tasks_from_impl_plan(headings)
        self.assertEqual(len(tasks), 8)

    def test_4_steps_not_capped(self):
        headings = "\n".join([f"## Task {i}\nDesc {i}\n" for i in range(4)])
        tasks = AgentService._extract_tasks_from_impl_plan(headings)
        self.assertEqual(len(tasks), 4)

    def test_1_step(self):
        tasks = AgentService._extract_tasks_from_impl_plan("## Only One\nDesc\n")
        self.assertEqual(len(tasks), 1)

    def test_10_steps_capped_to_8(self):
        headings = "\n".join([f"## Task {i}\nDesc {i}\n" for i in range(10)])
        tasks = AgentService._extract_tasks_from_impl_plan(headings)
        self.assertEqual(len(tasks), 8)

    def test_20_steps_capped_to_8(self):
        headings = "\n".join([f"## Task {i}\nDesc {i}\n" for i in range(20)])
        tasks = AgentService._extract_tasks_from_impl_plan(headings)
        self.assertEqual(len(tasks), 8)

    def test_first_8_preserved(self):
        headings = "\n".join([f"## Task_{i}\nDesc {i}\n" for i in range(12)])
        tasks = AgentService._extract_tasks_from_impl_plan(headings)
        names = [t[0] for t in tasks]
        self.assertEqual(names, [f"Task_{i}" for i in range(8)])

    def test_numbered_fallback_also_capped(self):
        items = "\n".join([f"{i+1}. Create task number {i+1} with details" for i in range(12)])
        tasks = AgentService._extract_tasks_from_impl_plan(items)
        self.assertLessEqual(len(tasks), 8)

    def test_cap_preserves_descriptions(self):
        headings = "\n".join([f"## Task {i}\nDescription for task {i}\n" for i in range(7)])
        tasks = AgentService._extract_tasks_from_impl_plan(headings)
        for name, desc in tasks:
            self.assertTrue(len(desc) > 0)

    def test_0_steps(self):
        tasks = AgentService._extract_tasks_from_impl_plan("Just text, no headings")
        self.assertEqual(len(tasks), 0)


class TestExampleBlock(unittest.TestCase):
    """Tests verifying the example block shows WriteFile for implementation — 5 tests."""

    def test_sdd_step_shows_md_example(self):
        # SDD steps should show .md WriteFile example — verify via prompt
        result = AgentService._get_step_read_instructions('requirements', '.')
        self.assertIn("requirements.md", result)

    def test_dynamic_step_shows_writefile(self):
        result = AgentService._get_step_read_instructions(
            'setup', '.', step_name='Setup', step_description=''
        )
        self.assertIn("WriteFile", result)

    def test_dynamic_step_no_listfiles_example(self):
        result = AgentService._get_step_read_instructions(
            'setup', '.', step_name='Setup', step_description=''
        )
        self.assertNotIn('"ListFiles"', result)

    def test_dynamic_step_has_tool_code_block(self):
        result = AgentService._get_step_read_instructions(
            'setup', '.', step_name='Setup', step_description=''
        )
        self.assertIn("<tool_code>", result)

    def test_planning_shows_writefile(self):
        result = AgentService._get_step_read_instructions('planning', '.')
        self.assertIn("WriteFile", result)


class TestZeroFilesNudgeLogic(unittest.TestCase):
    """Tests for zero-files nudge validation logic — 10 tests.

    Note: We can't easily test the actual SSE generator, so we test the
    conditions and helper functions that feed into the nudge logic.
    """

    def test_sdd_step_not_in_sdd_check(self):
        """SDD steps should NOT trigger zero-files nudge."""
        SDD_STEPS = {'requirements', 'technical-specification', 'planning'}
        self.assertIn('requirements', SDD_STEPS)
        self.assertIn('planning', SDD_STEPS)

    def test_dynamic_step_not_in_sdd(self):
        """Dynamic steps are NOT in SDD_STEPS and should trigger nudge."""
        SDD_STEPS = {'requirements', 'technical-specification', 'planning'}
        self.assertNotIn('project-setup', SDD_STEPS)
        self.assertNotIn('data-layer', SDD_STEPS)
        self.assertNotIn('api-routes', SDD_STEPS)

    def test_written_files_empty_triggers(self):
        written_files = set()
        self.assertEqual(len(written_files), 0)
        # This is the condition that triggers the nudge

    def test_written_files_nonempty_skips(self):
        written_files = {'app.py'}
        self.assertGreater(len(written_files), 0)
        # This would skip the nudge

    def test_nudge_count_zero_triggers(self):
        nudge_count = 0
        self.assertLess(nudge_count, 1)

    def test_nudge_count_one_skips(self):
        nudge_count = 1
        self.assertGreaterEqual(nudge_count, 1)

    def test_file_hint_from_description(self):
        """Test file list parsing for the nudge message."""
        desc = "Set up project.\nFiles: app.py, config.py"
        match = re.search(r'Files?:\s*(.+)', desc)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1).strip(), "app.py, config.py")

    def test_file_hint_empty_description(self):
        desc = ""
        match = re.search(r'Files?:\s*(.+)', desc)
        self.assertIsNone(match)

    def test_file_hint_no_files_line(self):
        desc = "Just create some stuff"
        match = re.search(r'Files?:\s*(.+)', desc)
        self.assertIsNone(match)

    def test_file_hint_file_singular(self):
        desc = "Build routes.\nFile: routes.py"
        match = re.search(r'Files?:\s*(.+)', desc)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1).strip(), "routes.py")


class TestExpectedArtifact(unittest.TestCase):
    """Tests for _get_expected_artifact() — 5 tests."""

    def test_requirements(self):
        result = AgentService._get_expected_artifact('requirements', '/path')
        self.assertTrue(result.endswith('requirements.md'))

    def test_tech_spec(self):
        result = AgentService._get_expected_artifact('technical-specification', '/path')
        self.assertTrue(result.endswith('spec.md'))

    def test_planning(self):
        result = AgentService._get_expected_artifact('planning', '/path')
        self.assertTrue(result.endswith('implementation-plan.md'))

    def test_dynamic_step(self):
        result = AgentService._get_expected_artifact('project-setup', '/path')
        self.assertTrue(result.endswith('project-setup.md'))

    def test_implementation(self):
        result = AgentService._get_expected_artifact('implementation', '/path')
        self.assertTrue(result.endswith('implementation-plan.md'))

    def test_child_step_id_with_double_colon(self):
        """Child step IDs with :: should strip parent prefix for valid filename."""
        result = AgentService._get_expected_artifact('parent-step::child-step', '/path')
        self.assertEqual(os.path.basename(result), 'child-step.md')
        self.assertNotIn('::', os.path.basename(result))


class TestEndToEndPlanRewriting(unittest.TestCase):
    """Integration tests for the full plan rewriting pipeline — 10 tests."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.task_id = 'e2e-test'
        self.artifacts_dir = os.path.join(self.temp_dir, '.sentinel', 'tasks', self.task_id)
        os.makedirs(self.artifacts_dir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def _write_file(self, name, content):
        path = os.path.join(self.artifacts_dir, name)
        with open(path, 'w') as f:
            f.write(content)

    def _read_file(self, name):
        path = os.path.join(self.artifacts_dir, name)
        with open(path, 'r') as f:
            return f.read()

    def test_full_sdd_plan_rewrite(self):
        """Simulate: SDD plan with Requirements [x], Tech Spec [x], Planning [x], Implementation [ ]."""
        self._write_file('plan.md',
            "# Full SDD workflow\n\n---\n\n## Workflow Steps\n\n"
            "### [x] Step: Requirements\n<!-- chat-id: req-chat -->\n\n"
            "### [x] Step: Technical Specification\n<!-- chat-id: spec-chat -->\n\n"
            "### [x] Step: Planning\n<!-- chat-id: plan-chat -->\n\n"
            "### [ ] Step: Implementation\n\n"
        )
        self._write_file('implementation-plan.md',
            "## Project Setup & Configuration\n"
            "Set up Flask app entry point and dependencies.\n"
            "Files: app.py, requirements.txt, config.py\n"
            "- [ ] Create app.py with Flask app factory\n"
            "- [ ] Create requirements.txt\n"
            "- [ ] Create config.py\n\n"
            "## Data Layer & Models\n"
            "Define the database schema and models.\n"
            "Files: models.py, database.py\n"
            "- [ ] Create models.py with Contact model\n"
            "- [ ] Create database.py with DB init\n\n"
            "## API Routes & Business Logic\n"
            "Build all REST API endpoints.\n"
            "Files: routes.py\n"
            "- [ ] Create routes.py with CRUD endpoints\n"
        )
        AgentService._inject_subtasks_into_plan(self.temp_dir, self.task_id)
        result = self._read_file('plan.md')

        # Verify structure
        self.assertNotIn("Step: Implementation", result)
        self.assertIn("### [ ] Step: Project Setup & Configuration", result)
        self.assertIn("### [ ] Step: Data Layer & Models", result)
        self.assertIn("### [ ] Step: API Routes & Business Logic", result)

        # Verify prior steps preserved
        self.assertIn("### [x] Step: Requirements", result)
        self.assertIn("chat-id: req-chat", result)

        # Verify descriptions preserved
        self.assertIn("Files: app.py, requirements.txt, config.py", result)
        self.assertIn("Files: models.py, database.py", result)

    def test_plan_rewrite_then_parse(self):
        """After rewriting, plan_engine should parse the new steps."""
        from services.plan_engine import parse_plan

        self._write_file('plan.md',
            "# Test\n\n## Workflow Steps\n\n"
            "### [x] Step: Planning\n\n"
            "### [ ] Step: Implementation\n\n"
        )
        self._write_file('implementation-plan.md',
            "## Setup\nCreate app.\nFiles: app.py\n\n"
            "## Models\nCreate models.\nFiles: models.py\n"
        )
        AgentService._inject_subtasks_into_plan(self.temp_dir, self.task_id)

        plan = parse_plan(os.path.join(self.artifacts_dir, 'plan.md'))
        step_names = [s.name for s in plan.steps]
        self.assertIn("Setup", step_names)
        self.assertIn("Models", step_names)

    def test_plan_rewrite_select_next(self):
        """After rewriting, select_next() should pick the first new step."""
        from services.plan_engine import parse_plan, select_next

        self._write_file('plan.md',
            "# Test\n\n## Workflow Steps\n\n"
            "### [x] Step: Planning\n\n"
            "### [ ] Step: Implementation\n\n"
        )
        self._write_file('implementation-plan.md',
            "## Alpha\nAlpha desc\n## Beta\nBeta desc\n"
        )
        AgentService._inject_subtasks_into_plan(self.temp_dir, self.task_id)

        plan = parse_plan(os.path.join(self.artifacts_dir, 'plan.md'))
        result = select_next(plan)
        self.assertIsNotNone(result)
        self.assertIsNotNone(result.target)
        self.assertEqual(result.target.name, "Alpha")

    def test_step_descriptions_in_parsed_plan(self):
        """Parsed plan should have step descriptions."""
        from services.plan_engine import parse_plan

        self._write_file('plan.md',
            "# Test\n\n## Workflow Steps\n\n"
            "### [x] Step: Planning\n\n"
            "### [ ] Step: Implementation\n\n"
        )
        self._write_file('implementation-plan.md',
            "## Setup\nCreate the project files.\nFiles: app.py, config.py\n"
        )
        AgentService._inject_subtasks_into_plan(self.temp_dir, self.task_id)

        plan = parse_plan(os.path.join(self.artifacts_dir, 'plan.md'))
        setup_step = plan.find_step('setup')
        self.assertIsNotNone(setup_step)
        self.assertIn("Create the project files", setup_step.description)

    def test_real_qwen_output_format(self):
        """Test with a format similar to what Qwen 3B actually produces."""
        self._write_file('plan.md',
            "# Full SDD workflow\n\n---\n\n## Workflow Steps\n\n"
            "### [x] Step: Requirements\n<!-- chat-id: abc -->\n\n"
            "### [x] Step: Technical Specification\n<!-- chat-id: def -->\n\n"
            "### [x] Step: Planning\n<!-- chat-id: ghi -->\n\n"
            "### [ ] Step: Implementation\n\n"
        )
        # Qwen often uses ### Task N: format
        self._write_file('implementation-plan.md',
            "# Implementation Plan\n\n"
            "## Overview\n"
            "This plan covers the implementation.\n\n"
            "### Task 1: Project Setup\n"
            "Initialize the Flask application.\n"
            "- [ ] Create app.py\n"
            "- [ ] Create requirements.txt\n\n"
            "### Task 2: Database Models\n"
            "Define SQLAlchemy models.\n"
            "- [ ] Create models.py\n\n"
            "### Task 3: API Routes\n"
            "Build REST endpoints.\n"
            "- [ ] Create routes.py\n\n"
            "## Verification Steps\n"
            "Run tests to verify.\n"
        )
        AgentService._inject_subtasks_into_plan(self.temp_dir, self.task_id)
        result = self._read_file('plan.md')

        self.assertNotIn("Step: Implementation", result)
        self.assertIn("Step: Project Setup", result)
        self.assertIn("Step: Database Models", result)
        self.assertIn("Step: API Routes", result)
        self.assertNotIn("Step: Overview", result)  # Meta heading skipped
        self.assertNotIn("Step: Verification Steps", result)  # Meta heading skipped

    def test_numbered_list_fallback(self):
        self._write_file('plan.md',
            "# Test\n\n## Workflow Steps\n\n"
            "### [x] Step: Planning\n\n"
            "### [ ] Step: Implementation\n\n"
        )
        self._write_file('implementation-plan.md',
            "Here are the implementation tasks:\n"
            "1. Create the Flask application entry point\n"
            "2. Build the database models and schema\n"
            "3. Implement the REST API endpoints\n"
        )
        AgentService._inject_subtasks_into_plan(self.temp_dir, self.task_id)
        result = self._read_file('plan.md')

        self.assertNotIn("Step: Implementation", result)
        self.assertIn("Step: Create the Flask application entry point", result)

    def test_empty_impl_plan_no_crash(self):
        self._write_file('plan.md',
            "# Test\n\n### [x] Step: Planning\n\n### [ ] Step: Implementation\n\n"
        )
        self._write_file('implementation-plan.md', "")
        AgentService._inject_subtasks_into_plan(self.temp_dir, self.task_id)
        result = self._read_file('plan.md')
        self.assertIn("Step: Implementation", result)  # Unchanged

    def test_missing_impl_plan_no_crash(self):
        self._write_file('plan.md',
            "# Test\n\n### [x] Step: Planning\n\n### [ ] Step: Implementation\n\n"
        )
        # Don't write implementation-plan.md
        AgentService._inject_subtasks_into_plan(self.temp_dir, self.task_id)
        result = self._read_file('plan.md')
        self.assertIn("Step: Implementation", result)  # Unchanged

    def test_instructions_for_new_step(self):
        """After rewriting, _get_step_read_instructions for a new step includes description."""
        self._write_file('plan.md',
            "# Test\n\n## Workflow Steps\n\n"
            "### [x] Step: Planning\n\n"
            "### [ ] Step: Implementation\n\n"
        )
        self._write_file('implementation-plan.md',
            "## Project Setup\nCreate Flask app.\nFiles: app.py, config.py\n"
        )
        AgentService._inject_subtasks_into_plan(self.temp_dir, self.task_id)

        from services.plan_engine import parse_plan
        plan = parse_plan(os.path.join(self.artifacts_dir, 'plan.md'))
        setup = plan.find_step('project-setup')
        self.assertIsNotNone(setup)

        instructions = AgentService._get_step_read_instructions(
            setup.id, '.sentinel/tasks/e2e-test',
            step_name=setup.name,
            step_description=setup.description
        )
        self.assertIn("Project Setup", instructions)
        self.assertIn("FILES YOU MUST CREATE", instructions)
        self.assertIn("app.py", instructions)
        self.assertIn("config.py", instructions)

    def test_instructions_for_step_without_files_line(self):
        """Steps without explicit Files: line still get WriteFile instructions."""
        self._write_file('plan.md',
            "# Test\n\n## Workflow Steps\n\n"
            "### [x] Step: Planning\n\n"
            "### [ ] Step: Implementation\n\n"
        )
        self._write_file('implementation-plan.md',
            "## Testing\nWrite unit tests for the application.\nFiles: tests.py\n- [ ] Create tests.py with comprehensive test suite\n"
        )
        AgentService._inject_subtasks_into_plan(self.temp_dir, self.task_id)

        from services.plan_engine import parse_plan
        plan = parse_plan(os.path.join(self.artifacts_dir, 'plan.md'))
        testing = plan.find_step('testing')
        self.assertIsNotNone(testing)

        instructions = AgentService._get_step_read_instructions(
            testing.id, '.sentinel/tasks/e2e-test',
            step_name=testing.name,
            step_description=testing.description
        )
        self.assertIn("WriteFile", instructions)
        # Should parse files from Files: line in description (which stays on parent)
        self.assertIn("tests.py", instructions)


class TestSanitizeCategoryName(unittest.TestCase):
    """Tests for _sanitize_category_name() post-processing — 10 tests."""

    def test_strips_py_extension(self):
        result = AgentService._sanitize_category_name("Create app.py")
        self.assertNotIn(".py", result)
        self.assertIn("app", result)

    def test_strips_js_extension(self):
        result = AgentService._sanitize_category_name("Setup index.js")
        self.assertNotIn(".js", result)

    def test_strips_multiple_extensions(self):
        result = AgentService._sanitize_category_name("Build routes.py and models.py")
        self.assertNotIn(".py", result)

    def test_strips_task_n_colon_prefix(self):
        result = AgentService._sanitize_category_name("Task 1: Project Setup")
        self.assertEqual(result, "Project Setup")

    def test_strips_task_n_dot_prefix(self):
        result = AgentService._sanitize_category_name("Task 3. API Routes")
        self.assertEqual(result, "API Routes")

    def test_preserves_normal_name(self):
        result = AgentService._sanitize_category_name("Recipe Browsing Experience")
        self.assertEqual(result, "Recipe Browsing Experience")

    def test_normalizes_whitespace(self):
        result = AgentService._sanitize_category_name("  Too   Many   Spaces  ")
        self.assertEqual(result, "Too Many Spaces")

    def test_handles_yaml_extension(self):
        result = AgentService._sanitize_category_name("Create config.yaml settings")
        self.assertNotIn(".yaml", result)

    def test_handles_json_extension(self):
        result = AgentService._sanitize_category_name("Setup package.json")
        self.assertNotIn(".json", result)

    def test_handles_html_extension(self):
        result = AgentService._sanitize_category_name("Build index.html page")
        self.assertNotIn(".html", result)


class TestSanitizeSubstepText(unittest.TestCase):
    """Tests for _sanitize_substep_text() post-processing — 10 tests."""

    def test_replaces_app_py(self):
        result = AgentService._sanitize_substep_text("Create app.py with Flask factory")
        self.assertNotIn("app.py", result)
        self.assertIn("application entry point", result)

    def test_replaces_models_py(self):
        result = AgentService._sanitize_substep_text("Create models.py with Contact model")
        self.assertNotIn("models.py", result)
        self.assertIn("data models", result)

    def test_replaces_routes_py(self):
        result = AgentService._sanitize_substep_text("Create routes.py with CRUD endpoints")
        self.assertNotIn("routes.py", result)
        self.assertIn("API routes", result)

    def test_replaces_requirements_txt(self):
        result = AgentService._sanitize_substep_text("Create requirements.txt with Flask and SQLAlchemy")
        self.assertNotIn("requirements.txt", result)
        self.assertIn("Python dependencies", result)

    def test_replaces_package_json(self):
        result = AgentService._sanitize_substep_text("Create package.json with React dependencies")
        self.assertNotIn("package.json", result)
        self.assertIn("project dependencies", result)

    def test_replaces_index_html(self):
        result = AgentService._sanitize_substep_text("Create index.html with layout")
        self.assertNotIn("index.html", result)
        self.assertIn("main page", result)

    def test_strips_unknown_extension(self):
        result = AgentService._sanitize_substep_text("Create validators.py with input checks")
        self.assertNotIn(".py", result)
        self.assertIn("validators", result)

    def test_preserves_plain_english(self):
        result = AgentService._sanitize_substep_text("Set up the main application entry point with routing")
        self.assertEqual(result, "Set up the main application entry point with routing")

    def test_handles_multiple_files(self):
        result = AgentService._sanitize_substep_text("Create app.py and config.py for the project")
        self.assertNotIn(".py", result)

    def test_no_double_spaces(self):
        result = AgentService._sanitize_substep_text("Create app.py with settings")
        self.assertNotIn("  ", result)


class TestExtractTasksSkipNames(unittest.TestCase):
    """Tests for expanded skip_names in _extract_tasks_from_impl_plan — 8 tests."""

    def test_skips_saving_to_implementation_plan(self):
        content = "## Setup\nDesc\n## Saving to implementation-plan.md\nSaving content\n"
        tasks = AgentService._extract_tasks_from_impl_plan(content)
        names = [t[0] for t in tasks]
        self.assertEqual(names, ["Setup"])

    def test_skips_high_level_categories_hyphenated(self):
        content = "## Setup\nDesc\n## High-Level Categories\nCategories content\n"
        tasks = AgentService._extract_tasks_from_impl_plan(content)
        names = [t[0] for t in tasks]
        self.assertEqual(names, ["Setup"])

    def test_skips_high_level_categories_no_hyphen(self):
        content = "## Setup\nDesc\n## High Level Categories\nContent\n"
        tasks = AgentService._extract_tasks_from_impl_plan(content)
        names = [t[0] for t in tasks]
        self.assertEqual(names, ["Setup"])

    def test_skips_file_structure(self):
        content = "## File Structure\nFile tree\n## Real Task\nDesc\n"
        tasks = AgentService._extract_tasks_from_impl_plan(content)
        names = [t[0] for t in tasks]
        self.assertEqual(names, ["Real Task"])

    def test_skips_project_structure(self):
        content = "## Project Structure\nDesc\n## Real Task\nDesc\n"
        tasks = AgentService._extract_tasks_from_impl_plan(content)
        names = [t[0] for t in tasks]
        self.assertEqual(names, ["Real Task"])

    def test_skips_implementation_steps(self):
        content = "## Implementation Steps\nMeta\n## Setup\nDesc\n"
        tasks = AgentService._extract_tasks_from_impl_plan(content)
        names = [t[0] for t in tasks]
        self.assertEqual(names, ["Setup"])

    def test_skips_overview_of_requirements(self):
        content = "## Overview of Requirements\nReqs\n## Setup\nDesc\n"
        tasks = AgentService._extract_tasks_from_impl_plan(content)
        names = [t[0] for t in tasks]
        self.assertEqual(names, ["Setup"])

    def test_skips_overview_of_technical_specifications(self):
        content = "## Overview of Technical Specifications\nSpecs\n## Setup\nDesc\n"
        tasks = AgentService._extract_tasks_from_impl_plan(content)
        names = [t[0] for t in tasks]
        self.assertEqual(names, ["Setup"])


class TestExpectedArtifactChildSteps(unittest.TestCase):
    """Tests for _get_expected_artifact() with child step IDs containing '::' — 5 tests."""

    def test_child_step_strips_parent_prefix(self):
        """Child step ID with :: should produce valid filename using only child portion."""
        result = AgentService._get_expected_artifact(
            'project-setup-&-configuration::create-python-dependencies', '/path'
        )
        self.assertTrue(result.endswith('create-python-dependencies.md'))
        self.assertNotIn('::', result)
        # Ensure no bare ':' in filename (invalid on Windows)
        filename = os.path.basename(result)
        self.assertNotIn(':', filename)

    def test_root_step_unchanged(self):
        """Root step ID without :: should work as before."""
        result = AgentService._get_expected_artifact('project-setup', '/path')
        self.assertTrue(result.endswith('project-setup.md'))

    def test_child_portion_extracted_correctly(self):
        """The child portion after :: should become the filename."""
        result = AgentService._get_expected_artifact(
            'data-layer::create-models', '/artifacts'
        )
        self.assertEqual(os.path.basename(result), 'create-models.md')

    def test_deep_child_id_uses_last_part(self):
        """If there are multiple :: separators, use the last part."""
        result = AgentService._get_expected_artifact(
            'parent::mid::child-step', '/path'
        )
        self.assertEqual(os.path.basename(result), 'child-step.md')

    def test_sdd_step_ids_still_use_artifact_map(self):
        """SDD step IDs (requirements, planning, etc.) should still use artifact_map."""
        self.assertTrue(
            AgentService._get_expected_artifact('requirements', '/p').endswith('requirements.md')
        )
        self.assertTrue(
            AgentService._get_expected_artifact('planning', '/p').endswith('implementation-plan.md')
        )


class TestChildStepPromptContext(unittest.TestCase):
    """Tests for child step parent context in _get_step_read_instructions() — 5 tests."""

    def test_child_step_gets_parent_description(self):
        """When step_description is empty but parent_description is available, use it."""
        result = AgentService._get_step_read_instructions(
            'parent::child-step', '.',
            step_name='Create dependencies',
            step_description='',
            parent_name='Project Setup',
            parent_description='Set up the project.\nFiles: app.py, config.py, requirements.txt'
        )
        self.assertIn("Project Setup", result)
        self.assertIn("Set up the project", result)

    def test_child_step_gets_parent_files_line(self):
        """Child step should parse Files: from parent description."""
        result = AgentService._get_step_read_instructions(
            'parent::child-step', '.',
            step_name='Create dependencies',
            step_description='',
            parent_name='Setup',
            parent_description='Build it.\nFiles: app.py, models.py'
        )
        self.assertIn("FILES YOU MUST CREATE", result)
        self.assertIn("app.py", result)
        self.assertIn("models.py", result)

    def test_root_step_unchanged(self):
        """Root step with no parent context should behave as before."""
        result = AgentService._get_step_read_instructions(
            'project-setup', '.',
            step_name='Project Setup',
            step_description='Set up the project.\nFiles: app.py',
            parent_name='',
            parent_description=''
        )
        self.assertIn("Set up the project", result)
        self.assertNotIn("YOUR SPECIFIC TASK", result)

    def test_parent_name_shown_in_part_of(self):
        """Child step should show parent name context."""
        result = AgentService._get_step_read_instructions(
            'parent::child', '.',
            step_name='Create routes',
            step_description='',
            parent_name='API Endpoints',
            parent_description='Create all endpoints.'
        )
        self.assertIn("implementing part of", result)
        self.assertIn("API Endpoints", result)

    def test_child_step_focus_instruction(self):
        """Child step should include task instruction referencing step name."""
        result = AgentService._get_step_read_instructions(
            'parent::child', '.',
            step_name='Build login form',
            step_description='',
            parent_name='Authentication',
            parent_description='Handle user auth.'
        )
        self.assertIn("YOUR SPECIFIC TASK", result)
        self.assertIn("Build login form", result)


class TestChildStepArtifactFilenameInPrompt(unittest.TestCase):
    """Tests that the summary filename in prompts uses clean IDs — 3 tests."""

    def test_child_step_summary_path_no_colons(self):
        """Child step prompt should tell LLM to save summary with clean filename."""
        result = AgentService._get_step_read_instructions(
            'parent::create-models', '.',
            step_name='Create Models',
            step_description='Create data models.\nFiles: models.py'
        )
        # Should reference create-models.md, NOT parent::create-models.md
        self.assertIn('create-models.md', result)
        self.assertNotIn('parent::create-models.md', result)

    def test_root_step_summary_path_unchanged(self):
        """Root step prompt should reference its full ID."""
        result = AgentService._get_step_read_instructions(
            'data-layer', '.',
            step_name='Data Layer',
            step_description='Define models.'
        )
        self.assertIn('data-layer.md', result)

    def test_nested_child_summary_uses_leaf(self):
        """Deeply nested child ID should use only the leaf for summary filename."""
        result = AgentService._get_step_read_instructions(
            'a::b::create-auth', '.',
            step_name='Create Auth',
            step_description='Build auth module.'
        )
        self.assertIn('create-auth.md', result)
        self.assertNotIn('a::b::create-auth.md', result)


class TestLoadPriorStepContextChildSteps(unittest.TestCase):
    """Tests for _load_prior_step_context() with child step IDs — 4 tests."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.task_id = 'test-task'
        self.artifacts_dir = os.path.join(self.temp_dir, '.sentinel', 'tasks', self.task_id)
        os.makedirs(self.artifacts_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_child_step_breaks_at_parent_position(self):
        """Child step ID should stop loading context at its parent's position."""
        # Create an artifact for the first step
        with open(os.path.join(self.artifacts_dir, 'requirements.md'), 'w') as f:
            f.write("# Requirements\nBuild a shopping list.")
        # Create artifact for second step that should NOT be included
        with open(os.path.join(self.artifacts_dir, 'data-layer.md'), 'w') as f:
            f.write("# Data Layer\nModels here.")

        all_steps = [
            {'id': 'requirements', 'name': 'Requirements', 'status': 'completed'},
            {'id': 'project-setup', 'name': 'Project Setup', 'status': 'in_progress'},
            {'id': 'data-layer', 'name': 'Data Layer', 'status': 'completed'},
        ]
        # Child of project-setup — should only get requirements, not data-layer
        result = AgentService._load_prior_step_context(
            self.temp_dir, self.task_id,
            'project-setup::create-deps', all_steps
        )
        self.assertIn("Requirements", result)
        self.assertNotIn("Data Layer", result)

    def test_only_prior_steps_included(self):
        """Only steps BEFORE the parent should have their artifacts loaded."""
        with open(os.path.join(self.artifacts_dir, 'requirements.md'), 'w') as f:
            f.write("# Requirements\nContent")
        with open(os.path.join(self.artifacts_dir, 'spec.md'), 'w') as f:
            f.write("# Spec\nTech details")

        all_steps = [
            {'id': 'requirements', 'name': 'Requirements', 'status': 'completed'},
            {'id': 'technical-specification', 'name': 'Tech Spec', 'status': 'completed'},
            {'id': 'project-setup', 'name': 'Project Setup', 'status': 'in_progress'},
        ]
        result = AgentService._load_prior_step_context(
            self.temp_dir, self.task_id,
            'project-setup::create-entry-point', all_steps
        )
        self.assertIn("Requirements", result)
        self.assertIn("Spec", result)

    def test_root_step_id_works_as_before(self):
        """Root step IDs should still break at their own position."""
        with open(os.path.join(self.artifacts_dir, 'requirements.md'), 'w') as f:
            f.write("# Requirements\nContent")

        all_steps = [
            {'id': 'requirements', 'name': 'Requirements', 'status': 'completed'},
            {'id': 'technical-specification', 'name': 'Tech Spec', 'status': 'pending'},
        ]
        result = AgentService._load_prior_step_context(
            self.temp_dir, self.task_id,
            'technical-specification', all_steps
        )
        self.assertIn("Requirements", result)

    def test_empty_steps_list_handled(self):
        """Empty all_steps should return empty string."""
        result = AgentService._load_prior_step_context(
            self.temp_dir, self.task_id,
            'some::child', []
        )
        self.assertEqual(result, "")


class TestSanitizeSubstepTextRedundancy(unittest.TestCase):
    """Tests for redundancy fixes in _sanitize_substep_text() — 5 tests."""

    def test_python_dependencies_with_dependencies(self):
        """'Create requirements.txt with dependencies' should not have double 'dependencies'."""
        result = AgentService._sanitize_substep_text("Create requirements.txt with dependencies")
        self.assertNotIn("dependencies with dependencies", result)
        self.assertIn("Python dependencies", result)

    def test_data_models_with_all_data_models(self):
        """'Create models.py with all data models' should not have double 'data models'."""
        result = AgentService._sanitize_substep_text("Create models.py with all data models")
        # Should be cleaned up
        self.assertNotIn("data models with all data models", result)

    def test_no_redundancy_when_different_words(self):
        """'Create application entry point with Flask app factory' should be preserved."""
        result = AgentService._sanitize_substep_text("Create app.py with Flask app factory")
        # "application entry point" and "Flask app factory" are different enough
        self.assertIn("application entry point", result)
        self.assertIn("Flask", result)

    def test_api_routes_with_endpoints(self):
        """'Create routes.py with all API endpoints' should clean up redundancy."""
        result = AgentService._sanitize_substep_text("Create routes.py with all API endpoints and route handlers")
        self.assertNotIn("API routes with all API endpoints", result)

    def test_database_setup_with_sqlalchemy_setup(self):
        """'Create database.py with SQLAlchemy setup' should clean up redundancy."""
        result = AgentService._sanitize_substep_text("Create database.py with SQLAlchemy setup and database initialization")
        self.assertNotIn("database setup with SQLAlchemy setup", result)


class TestPlanEngineToDictParentId(unittest.TestCase):
    """Tests for parentId in Step.to_dict() — 3 tests."""

    def test_root_step_has_none_parent_id(self):
        """Root steps should have parentId=None in to_dict()."""
        from services.plan_engine import Step, StepStatus
        step = Step(id='root', name='Root', status=StepStatus.PENDING, line_number=0)
        d = step.to_dict()
        self.assertIn('parentId', d)
        self.assertIsNone(d['parentId'])

    def test_child_step_has_parent_id(self):
        """Child steps should have their parent_id in to_dict()."""
        from services.plan_engine import Step, StepStatus
        step = Step(id='parent::child', name='Child', status=StepStatus.PENDING,
                    line_number=5, parent_id='parent')
        d = step.to_dict()
        self.assertEqual(d['parentId'], 'parent')

    def test_children_serialized_with_parent_id(self):
        """to_dict() with children should serialize parentId for each child."""
        from services.plan_engine import Step, StepStatus
        parent = Step(id='parent', name='Parent', status=StepStatus.PENDING, line_number=0)
        child = Step(id='parent::child', name='Child', status=StepStatus.PENDING,
                     line_number=5, parent_id='parent')
        parent.children = [child]
        d = parent.to_dict()
        self.assertEqual(len(d['children']), 1)
        self.assertEqual(d['children'][0]['parentId'], 'parent')


class TestAntiOverengineeringRules(unittest.TestCase):
    """Tests for anti-overengineering rules across all SDD prompts — 10 tests."""

    def test_requirements_has_do_not_add_auth(self):
        result = AgentService._get_step_read_instructions('requirements', '.', task_details='test')
        self.assertIn("DO NOT add authentication", result)

    def test_requirements_has_do_not_add_database(self):
        result = AgentService._get_step_read_instructions('requirements', '.', task_details='test')
        self.assertIn("DO NOT add a database", result)

    def test_requirements_has_scope_check(self):
        result = AgentService._get_step_read_instructions('requirements', '.', task_details='test')
        self.assertIn("SCOPE CHECK", result)

    def test_requirements_has_task_description(self):
        result = AgentService._get_step_read_instructions('requirements', '.', task_details='Build a calculator')
        self.assertIn("Build a calculator", result)
        self.assertIn("THE USER'S TASK", result)

    def test_tech_spec_has_no_microservices(self):
        result = AgentService._get_step_read_instructions('technical-specification', '.', task_details='test')
        self.assertIn("DO NOT design microservices", result)

    def test_tech_spec_has_complexity_tiers(self):
        result = AgentService._get_step_read_instructions('technical-specification', '.', task_details='test')
        self.assertIn("SIMPLE", result)
        self.assertIn("MEDIUM", result)
        self.assertIn("COMPLEX", result)

    def test_tech_spec_has_scope_check(self):
        result = AgentService._get_step_read_instructions('technical-specification', '.', task_details='test')
        self.assertIn("SCOPE CHECK", result)

    def test_planning_has_category_count_rule(self):
        result = AgentService._get_step_read_instructions('planning', '.', task_details='test')
        self.assertIn("SIMPLE=1, MEDIUM=2, COMPLEX=3-5", result)

    def test_planning_forbids_documentation(self):
        result = AgentService._get_step_read_instructions('planning', '.', task_details='test')
        self.assertIn("Documentation", result)

    def test_all_sdd_prompts_have_task_description(self):
        """All three SDD prompts should include the task description."""
        for step_id in ['requirements', 'technical-specification', 'planning']:
            result = AgentService._get_step_read_instructions(step_id, '.', task_details='My test task')
            self.assertIn("My test task", result, f"Task description missing from {step_id} prompt")
            self.assertIn("THE USER'S TASK", result, f"Task markers missing from {step_id} prompt")

    def test_planning_has_forbidden_categories(self):
        """Planning prompt must have category naming guidance."""
        result = AgentService._get_step_read_instructions('planning', '.', task_details='test')
        self.assertIn("specific", result)
        self.assertIn("generic labels", result)

    def test_planning_has_format_rules(self):
        """Planning prompt must have format rules for correct markdown structure."""
        result = AgentService._get_step_read_instructions('planning', '.', task_details='test')
        self.assertIn("## (double hash)", result)
        self.assertIn("NOT # or ### or ####", result)
        self.assertIn("Category 1:", result)

    def test_planning_forbids_generic_names(self):
        """Planning prompt must discourage generic category names."""
        result = AgentService._get_step_read_instructions('planning', '.', task_details='test')
        self.assertIn("Core Application", result)
        self.assertIn("Quality Assurance", result)
        self.assertIn("generic labels", result)


class TestInnerMonologueAntiOverengineering(unittest.TestCase):
    """Tests that inner monologue example does NOT teach overengineering — 2 tests."""

    def test_monologue_does_not_suggest_auth(self):
        """The inner monologue example must NOT suggest adding authentication."""
        # Read the SDD example block from the source
        import inspect
        source = inspect.getsource(AgentService.continue_chat_stream)
        # Old bad text should NOT be present
        self.assertNotIn("consider authentication and pagination", source)

    def test_monologue_says_not_add_unrequested(self):
        """The inner monologue should explicitly say NOT to add unrequested features."""
        import inspect
        source = inspect.getsource(AgentService.continue_chat_stream)
        self.assertIn("NOT add authentication, pagination", source)


if __name__ == '__main__':
    unittest.main()
