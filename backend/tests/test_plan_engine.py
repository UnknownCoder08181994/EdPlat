"""
Tests for plan_engine.py — the core step-processing engine.

6 tests total:
  Tests 1-3: Debug tests (core parsing, status markers, atomic writes)
  Tests 4-6: New feature tests (subtasks, mixed indentation, recovery)
"""

import os
import sys
import tempfile
import unittest

# Add backend/ to path so we can import services.plan_engine
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from services.plan_engine import (
    StepStatus, Step, PlanState, SelectionResult,
    parse_plan, select_next, update_step,
    _derive_id, _atomic_write,
)


def _write_plan(content: str, tmpdir: str) -> str:
    """Write content to a plan.md in tmpdir, return the file path."""
    path = os.path.join(tmpdir, 'plan.md')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    return path


# ─────────────────────────────────────────────────────────────────────
# Test 1 (Debug): Root steps only — basic parsing + selection
# ─────────────────────────────────────────────────────────────────────

class TestRootStepsBasic(unittest.TestCase):
    """Parse the default SDD template, verify 4 root steps, correct
    line numbers, status, selection order, and update-then-reselect."""

    PLAN = """\
# Full SDD workflow

---

## Workflow Steps

### [ ] Step: Requirements

Create a PRD based on the feature description.

Save the PRD to `requirements.md`.

### [ ] Step: Technical Specification

Create a technical specification.

### [ ] Step: Planning

Create a detailed implementation plan.

### [ ] Step: Implementation

Execute the tasks.
"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.plan_path = _write_plan(self.PLAN, self.tmpdir)

    def test_parse_four_root_steps(self):
        plan = parse_plan(self.plan_path)
        self.assertEqual(len(plan.steps), 4)
        names = [s.name for s in plan.steps]
        self.assertEqual(names, ['Requirements', 'Technical Specification', 'Planning', 'Implementation'])

    def test_all_pending(self):
        plan = parse_plan(self.plan_path)
        for step in plan.steps:
            self.assertEqual(step.status, StepStatus.PENDING)

    def test_correct_line_numbers(self):
        plan = parse_plan(self.plan_path)
        # Each ### [ ] Step: line has a known position
        for step in plan.steps:
            line_content = plan.raw_lines[step.line_number]
            self.assertIn(step.name, line_content)

    def test_no_children(self):
        plan = parse_plan(self.plan_path)
        for step in plan.steps:
            self.assertEqual(step.children, [])

    def test_select_first(self):
        plan = parse_plan(self.plan_path)
        result = select_next(plan)
        self.assertIsNotNone(result.target)
        self.assertEqual(result.target.name, 'Requirements')
        self.assertFalse(result.halted)

    def test_update_first_then_select_second(self):
        plan = parse_plan(self.plan_path)
        plan = update_step(plan, 'requirements', new_status=StepStatus.DONE)

        # Re-parse from disk to verify persistence
        plan2 = parse_plan(self.plan_path)
        self.assertEqual(plan2.steps[0].status, StepStatus.DONE)

        result = select_next(plan2)
        self.assertIsNotNone(result.target)
        self.assertEqual(result.target.name, 'Technical Specification')

    def test_all_done_returns_none(self):
        plan = parse_plan(self.plan_path)
        for step in plan.steps:
            plan = update_step(plan, step.id, new_status=StepStatus.DONE)

        plan2 = parse_plan(self.plan_path)
        result = select_next(plan2)
        self.assertIsNone(result.target)
        self.assertFalse(result.halted)

    def test_description_captured(self):
        plan = parse_plan(self.plan_path)
        self.assertIn('PRD', plan.steps[0].description)

    def test_step_ids_derived(self):
        plan = parse_plan(self.plan_path)
        ids = [s.id for s in plan.steps]
        self.assertEqual(ids, ['requirements', 'technical-specification', 'planning', 'implementation'])

    def test_to_dict_backward_compatible(self):
        plan = parse_plan(self.plan_path)
        d = plan.steps[0].to_dict()
        self.assertIn('id', d)
        self.assertIn('name', d)
        self.assertIn('status', d)
        self.assertIn('description', d)
        self.assertIn('chatId', d)
        self.assertNotIn('children', d)  # No children → no key


# ─────────────────────────────────────────────────────────────────────
# Test 2 (Debug): Heading variants and status markers
# ─────────────────────────────────────────────────────────────────────

class TestHeadingVariantsAndStatusMarkers(unittest.TestCase):
    """Plan with different heading levels and all 5 status markers."""

    PLAN = """\
# Workflow

## [x] Step: Setup
Already done.

### [>] Step: Build
In progress.

#### [ ] Step: Test
Not started.

## [!] Step: Deploy
Blocked on infra.

### [-] Step: Cleanup
Skipped intentionally.
"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.plan_path = _write_plan(self.PLAN, self.tmpdir)

    def test_parse_all_heading_levels(self):
        plan = parse_plan(self.plan_path)
        self.assertEqual(len(plan.steps), 5)

    def test_status_markers(self):
        plan = parse_plan(self.plan_path)
        statuses = [s.status for s in plan.steps]
        self.assertEqual(statuses, [
            StepStatus.DONE,
            StepStatus.IN_PROGRESS,
            StepStatus.PENDING,
            StepStatus.FAILED,
            StepStatus.SKIPPED,
        ])

    def test_in_progress_resume(self):
        """[>] should be selected as resume target."""
        plan = parse_plan(self.plan_path)
        result = select_next(plan)
        self.assertIsNotNone(result.target)
        self.assertEqual(result.target.name, 'Build')

    def test_failed_halts_when_next(self):
        """If [>] is completed, the next pending step should be selected.
        But [!] Deploy comes before [ ] Test in file order? No — Test comes before Deploy.
        Let's re-check: Setup(done), Build(>), Test(pending), Deploy(!), Cleanup(skipped).
        After Build completes, Test is next. After Test completes, Deploy halts."""
        plan = parse_plan(self.plan_path)
        plan = update_step(plan, 'build', new_status=StepStatus.DONE)
        plan = update_step(plan, 'test', new_status=StepStatus.DONE)

        plan2 = parse_plan(self.plan_path)
        result = select_next(plan2)
        self.assertTrue(result.halted)
        self.assertIn('Deploy', result.halt_reason)

    def test_status_label_mapping(self):
        plan = parse_plan(self.plan_path)
        labels = [s.status_label for s in plan.steps]
        self.assertEqual(labels, ['completed', 'in_progress', 'pending', 'failed', 'skipped'])


# ─────────────────────────────────────────────────────────────────────
# Test 3 (Debug): Atomic write and idempotent re-runs
# ─────────────────────────────────────────────────────────────────────

class TestAtomicWriteAndIdempotency(unittest.TestCase):
    """Verify file writes are atomic and re-running doesn't corrupt."""

    PLAN = """\
# Workflow

### [ ] Step: Alpha
Description of Alpha.

### [ ] Step: Beta
Description of Beta.
"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.plan_path = _write_plan(self.PLAN, self.tmpdir)

    def test_update_only_changes_bracket(self):
        """Only the bracket token should change; all other text preserved."""
        plan = parse_plan(self.plan_path)

        # Read original file
        with open(self.plan_path, 'r', encoding='utf-8') as f:
            original = f.read()

        plan = update_step(plan, 'alpha', new_status=StepStatus.DONE)

        with open(self.plan_path, 'r', encoding='utf-8') as f:
            updated = f.read()

        # The only change should be [ ] → [x] on the Alpha line
        self.assertIn('### [x] Step: Alpha', updated)
        self.assertIn('### [ ] Step: Beta', updated)
        self.assertIn('Description of Alpha.', updated)
        self.assertIn('Description of Beta.', updated)

    def test_idempotent_double_update(self):
        """Updating to the same status twice should produce identical files."""
        plan = parse_plan(self.plan_path)
        plan = update_step(plan, 'alpha', new_status=StepStatus.DONE)

        with open(self.plan_path, 'r', encoding='utf-8') as f:
            after_first = f.read()

        plan = parse_plan(self.plan_path)
        plan = update_step(plan, 'alpha', new_status=StepStatus.DONE)

        with open(self.plan_path, 'r', encoding='utf-8') as f:
            after_second = f.read()

        self.assertEqual(after_first, after_second)

    def test_no_temp_files_remain(self):
        """After update, no .md.tmp files should exist in the directory."""
        plan = parse_plan(self.plan_path)
        plan = update_step(plan, 'alpha', new_status=StepStatus.DONE)

        tmp_files = [f for f in os.listdir(self.tmpdir) if f.endswith('.tmp')]
        self.assertEqual(tmp_files, [])

    def test_chat_id_insertion(self):
        """Inserting a chat-id should add a comment line after the step."""
        plan = parse_plan(self.plan_path)
        plan = update_step(plan, 'alpha', chat_id='aaaa-bbbb-cccc-dddd')

        with open(self.plan_path, 'r', encoding='utf-8') as f:
            content = f.read()

        self.assertIn('<!-- chat-id: aaaa-bbbb-cccc-dddd -->', content)

        # Re-parse and verify
        plan2 = parse_plan(self.plan_path)
        self.assertEqual(plan2.steps[0].chat_id, 'aaaa-bbbb-cccc-dddd')

    def test_chat_id_update_replaces_existing(self):
        """Updating chat-id should replace, not duplicate."""
        plan = parse_plan(self.plan_path)
        plan = update_step(plan, 'alpha', chat_id='aaaa-bbbb-cccc-dddd')
        plan = parse_plan(self.plan_path)
        plan = update_step(plan, 'alpha', chat_id='1111-2222-3333-4444')

        with open(self.plan_path, 'r', encoding='utf-8') as f:
            content = f.read()

        self.assertNotIn('aaaa-bbbb-cccc-dddd', content)
        self.assertIn('1111-2222-3333-4444', content)
        # Only one chat-id line
        self.assertEqual(content.count('<!-- chat-id:'), 1)

    def test_file_not_found_returns_empty(self):
        """Parsing a nonexistent file returns empty PlanState."""
        plan = parse_plan(os.path.join(self.tmpdir, 'nonexistent.md'))
        self.assertEqual(plan.steps, [])

    def test_update_nonexistent_step_raises(self):
        """Updating a step that doesn't exist should raise ValueError."""
        plan = parse_plan(self.plan_path)
        with self.assertRaises(ValueError):
            update_step(plan, 'nonexistent-step', new_status=StepStatus.DONE)


# ─────────────────────────────────────────────────────────────────────
# Test 4 (New): Nested checkbox subtasks
# ─────────────────────────────────────────────────────────────────────

class TestNestedSubtasks(unittest.TestCase):
    """Root step with 3 indented checkbox children. Verify hierarchy,
    selection of children first, and parent auto-completion."""

    PLAN = """\
# Workflow

### [ ] Step: Build API
  - [ ] Define REST endpoints
  - [ ] Design database schema
  - [ ] Write OpenAPI specification

### [ ] Step: Testing
Run the tests.
"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.plan_path = _write_plan(self.PLAN, self.tmpdir)

    def test_parse_root_with_children(self):
        plan = parse_plan(self.plan_path)
        self.assertEqual(len(plan.steps), 2)
        self.assertEqual(len(plan.steps[0].children), 3)
        self.assertEqual(len(plan.steps[1].children), 0)

    def test_child_names(self):
        plan = parse_plan(self.plan_path)
        names = [c.name for c in plan.steps[0].children]
        self.assertEqual(names, ['Define REST endpoints', 'Design database schema', 'Write OpenAPI specification'])

    def test_child_parent_ids(self):
        plan = parse_plan(self.plan_path)
        for child in plan.steps[0].children:
            self.assertEqual(child.parent_id, 'build-api')

    def test_child_ids_scoped(self):
        plan = parse_plan(self.plan_path)
        ids = [c.id for c in plan.steps[0].children]
        self.assertEqual(ids, [
            'build-api::define-rest-endpoints',
            'build-api::design-database-schema',
            'build-api::write-openapi-specification',
        ])

    def test_select_first_child(self):
        """When root has children, selection should pick first child, not root."""
        plan = parse_plan(self.plan_path)
        result = select_next(plan)
        self.assertIsNotNone(result.target)
        self.assertEqual(result.target.name, 'Define REST endpoints')
        self.assertFalse(result.target.is_root)

    def test_mark_children_then_parent_auto_completes(self):
        plan = parse_plan(self.plan_path)

        # Mark all 3 children done
        for child in plan.steps[0].children:
            plan = update_step(plan, child.id, new_status=StepStatus.DONE)

        # Re-parse to check persistence
        plan2 = parse_plan(self.plan_path)
        # Parent should be auto-completed
        self.assertEqual(plan2.steps[0].status, StepStatus.DONE)

    def test_mixed_done_and_skipped_children(self):
        """Parent auto-completes when all children are [x] or [-]."""
        plan = parse_plan(self.plan_path)
        children = plan.steps[0].children
        plan = update_step(plan, children[0].id, new_status=StepStatus.DONE)
        plan = update_step(plan, children[1].id, new_status=StepStatus.SKIPPED)
        plan = update_step(plan, children[2].id, new_status=StepStatus.DONE)

        plan2 = parse_plan(self.plan_path)
        self.assertEqual(plan2.steps[0].status, StepStatus.DONE)

    def test_after_parent_done_select_next_root(self):
        """After parent auto-completes, next selection is the next root step."""
        plan = parse_plan(self.plan_path)
        for child in plan.steps[0].children:
            plan = update_step(plan, child.id, new_status=StepStatus.DONE)

        plan2 = parse_plan(self.plan_path)
        result = select_next(plan2)
        self.assertIsNotNone(result.target)
        self.assertEqual(result.target.name, 'Testing')

    def test_to_dict_includes_children(self):
        plan = parse_plan(self.plan_path)
        d = plan.steps[0].to_dict()
        self.assertIn('children', d)
        self.assertEqual(len(d['children']), 3)
        self.assertEqual(d['children'][0]['id'], 'build-api::define-rest-endpoints')


# ─────────────────────────────────────────────────────────────────────
# Test 5 (New): Mixed indentation and context bullets
# ─────────────────────────────────────────────────────────────────────

class TestMixedIndentationAndContextBullets(unittest.TestCase):
    """Verify that context bullets (no checkbox) are NOT parsed as
    executable steps, and various indent levels work."""

    PLAN = """\
# Workflow

### [ ] Step: Design
  - [ ] Create wireframes
  - Review existing designs (context only)
  - [ ] Write user stories
    - Some nested note about user stories
  - [ ] Finalize mockups

### [ ] Step: Build
\t- [ ] Set up project
  - [ ] Write code
"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.plan_path = _write_plan(self.PLAN, self.tmpdir)

    def test_context_bullets_not_parsed_as_steps(self):
        """Non-checkbox bullets should not become children."""
        plan = parse_plan(self.plan_path)
        design = plan.steps[0]
        child_names = [c.name for c in design.children]
        # "Review existing designs" has no checkbox → not a child
        # "Some nested note" has no checkbox → not a child
        self.assertNotIn('Review existing designs (context only)', child_names)
        self.assertNotIn('Some nested note about user stories', child_names)

    def test_checkbox_children_parsed(self):
        plan = parse_plan(self.plan_path)
        design = plan.steps[0]
        child_names = [c.name for c in design.children]
        self.assertIn('Create wireframes', child_names)
        self.assertIn('Write user stories', child_names)
        self.assertIn('Finalize mockups', child_names)
        self.assertEqual(len(design.children), 3)

    def test_tab_indented_subtask(self):
        """Tab-indented subtasks should be parsed correctly."""
        plan = parse_plan(self.plan_path)
        build = plan.steps[1]
        self.assertEqual(len(build.children), 2)
        self.assertEqual(build.children[0].name, 'Set up project')

    def test_selection_skips_context(self):
        """Selection should pick first checkbox child, ignoring context bullets."""
        plan = parse_plan(self.plan_path)
        result = select_next(plan)
        self.assertEqual(result.target.name, 'Create wireframes')

    def test_two_root_steps(self):
        plan = parse_plan(self.plan_path)
        self.assertEqual(len(plan.steps), 2)
        self.assertEqual(plan.steps[0].name, 'Design')
        self.assertEqual(plan.steps[1].name, 'Build')


# ─────────────────────────────────────────────────────────────────────
# Test 6 (New): Multiple [>] recovery + parent [!] blocking
# ─────────────────────────────────────────────────────────────────────

class TestMultipleInProgressAndFailedBlocking(unittest.TestCase):
    """Test recovery from inconsistent state (multiple [>]) and
    parent blocking when a child is [!]."""

    PLAN_MULTIPLE_IP = """\
# Workflow

### [>] Step: First
In progress from crashed run.

### [>] Step: Second
Also in progress (inconsistent).

### [ ] Step: Third
Waiting.
"""

    PLAN_FAILED_CHILD = """\
# Workflow

### [ ] Step: Build
  - [x] Set up scaffold
  - [!] Write API layer
  - [ ] Add auth middleware

### [ ] Step: Deploy
Waiting.
"""

    PLAN_SKIPPED_ALLOWS_COMPLETION = """\
# Workflow

### [ ] Step: Build
  - [x] Set up scaffold
  - [-] Optional cleanup
  - [x] Write main code
"""

    def test_multiple_in_progress_resumes_first(self):
        tmpdir = tempfile.mkdtemp()
        path = _write_plan(self.PLAN_MULTIPLE_IP, tmpdir)
        plan = parse_plan(path)
        result = select_next(plan)

        self.assertIsNotNone(result.target)
        self.assertEqual(result.target.name, 'First')

    def test_multiple_in_progress_downgrades_rest(self):
        tmpdir = tempfile.mkdtemp()
        path = _write_plan(self.PLAN_MULTIPLE_IP, tmpdir)
        plan = parse_plan(path)
        result = select_next(plan)

        # Warnings should mention downgrade
        self.assertTrue(len(result.warnings) > 0)
        self.assertIn('Second', result.warnings[0])
        self.assertIn('downgraded', result.warnings[0].lower())

        # The second step should have been downgraded in memory
        self.assertEqual(plan.steps[1].status, StepStatus.PENDING)

    def test_failed_child_halts(self):
        tmpdir = tempfile.mkdtemp()
        path = _write_plan(self.PLAN_FAILED_CHILD, tmpdir)
        plan = parse_plan(path)
        result = select_next(plan)

        # [!] child should cause halt
        self.assertTrue(result.halted)
        self.assertIn('Write API layer', result.halt_reason)

    def test_failed_child_prevents_parent_completion(self):
        """Even if some children are done, a [!] child prevents parent auto-completion."""
        tmpdir = tempfile.mkdtemp()
        path = _write_plan(self.PLAN_FAILED_CHILD, tmpdir)
        plan = parse_plan(path)

        # Parent should NOT be auto-completed
        self.assertNotEqual(plan.steps[0].status, StepStatus.DONE)

    def test_skipped_children_allow_parent_completion(self):
        tmpdir = tempfile.mkdtemp()
        path = _write_plan(self.PLAN_SKIPPED_ALLOWS_COMPLETION, tmpdir)
        plan = parse_plan(path)

        # All children are [x] or [-], so parent should auto-complete on next update
        # But auto-completion happens when a child transitions. Let's trigger it:
        # The scaffold is already [x] and cleanup [-] and main [x], so we need to
        # check if select_next sees this root as "all children terminal"
        result = select_next(plan)
        # All children done/skipped → root should be skipped by selection
        # select_next should return None (all complete)
        self.assertIsNone(result.target)

    def test_derive_id_function(self):
        """Test the _derive_id helper."""
        self.assertEqual(_derive_id('Step: Requirements'), 'requirements')
        self.assertEqual(_derive_id('Phase 2: Design'), 'design')
        self.assertEqual(_derive_id('Step: Build API'), 'build-api')


# ─────────────────────────────────────────────────────────────────────
# Additional edge case: heading-style with list-style root
# ─────────────────────────────────────────────────────────────────────

class TestListStyleRoot(unittest.TestCase):
    """Verify that `- [ ] Step: Title` at column 0 is parsed as a root."""

    PLAN = """\
# Workflow

- [ ] Step: Alpha
First root step.

- [x] Step: Beta
Second root step, already done.
"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.plan_path = _write_plan(self.PLAN, self.tmpdir)

    def test_list_style_root_parsed(self):
        plan = parse_plan(self.plan_path)
        self.assertEqual(len(plan.steps), 2)
        self.assertEqual(plan.steps[0].name, 'Alpha')
        self.assertEqual(plan.steps[1].name, 'Beta')

    def test_list_style_root_status(self):
        plan = parse_plan(self.plan_path)
        self.assertEqual(plan.steps[0].status, StepStatus.PENDING)
        self.assertEqual(plan.steps[1].status, StepStatus.DONE)

    def test_select_skips_done(self):
        plan = parse_plan(self.plan_path)
        # Make Alpha done too
        plan = update_step(plan, 'alpha', new_status=StepStatus.DONE)
        plan2 = parse_plan(self.plan_path)
        result = select_next(plan2)
        self.assertIsNone(result.target)  # Both done


# ─────────────────────────────────────────────────────────────────────
# Debug Round 2: Edge cases found during review
# ─────────────────────────────────────────────────────────────────────

class TestDebugRound2RealPlanBackwardCompat(unittest.TestCase):
    """Parse a real plan.md from the existing system to verify backward compat."""

    REAL_PLAN = """\
# Full SDD workflow

---

## Workflow Steps

### [x] Step: Requirements
<!-- chat-id: 85df7db0-d381-4355-b409-d6971462b1f2 -->

Create a Product Requirements Document (PRD) based on the feature description.

1. Analyze the task description to understand what needs to be built
2. Identify requirements, user stories, and acceptance criteria
3. Ask the user for clarifications on aspects that significantly impact scope or user experience
4. Make reasonable decisions for minor details based on context and conventions
5. If user can't clarify, make a decision, state the assumption, and continue

Save the PRD to `requirements.md`.

### [x] Step: Technical Specification
<!-- chat-id: 6e694606-95d2-40a7-af30-afb558295175 -->

Create a technical specification based on the PRD in `requirements.md`.

1. Review the requirements document and design the technical architecture
2. Define the implementation approach

Save to `spec.md` with:
- Technical context (language, frameworks, dependencies)
- Implementation approach and architecture decisions
- Source code structure (directories, modules, files to create)
- Data model / API / interface changes
- Delivery phases (incremental, testable milestones)
- Verification approach using project lint/test commands

### [x] Step: Planning
<!-- chat-id: 3545faa9-9d61-4d33-a5fc-b296b4e84a2d -->

Create a detailed implementation plan based on `spec.md`.

1. Break down the work into concrete tasks
2. Each task should reference relevant contracts and include verification steps
3. Replace the Implementation step below with the planned tasks

Rule of thumb for step size: each step should represent a coherent unit of work.

Save to `implementation-plan.md`.

### [x] Step: Implementation
<!-- chat-id: 1ab49c57-b10e-48eb-9ef7-b89551be0296 -->

This step should be replaced with detailed implementation tasks from the Planning step.

If Planning didn't replace this step, execute the tasks in `implementation-plan.md`.
"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.plan_path = _write_plan(self.REAL_PLAN, self.tmpdir)

    def test_parse_four_steps_all_done(self):
        plan = parse_plan(self.plan_path)
        self.assertEqual(len(plan.steps), 4)
        for step in plan.steps:
            self.assertEqual(step.status, StepStatus.DONE)

    def test_chat_ids_preserved(self):
        plan = parse_plan(self.plan_path)
        self.assertEqual(plan.steps[0].chat_id, '85df7db0-d381-4355-b409-d6971462b1f2')
        self.assertEqual(plan.steps[1].chat_id, '6e694606-95d2-40a7-af30-afb558295175')
        self.assertEqual(plan.steps[2].chat_id, '3545faa9-9d61-4d33-a5fc-b296b4e84a2d')
        self.assertEqual(plan.steps[3].chat_id, '1ab49c57-b10e-48eb-9ef7-b89551be0296')

    def test_step_ids_match_old_convention(self):
        plan = parse_plan(self.plan_path)
        ids = [s.id for s in plan.steps]
        self.assertEqual(ids, ['requirements', 'technical-specification', 'planning', 'implementation'])

    def test_select_none_all_done(self):
        plan = parse_plan(self.plan_path)
        result = select_next(plan)
        self.assertIsNone(result.target)
        self.assertFalse(result.halted)

    def test_to_dict_matches_old_format(self):
        """The to_dict output should match the old _parse_plan dict shape."""
        plan = parse_plan(self.plan_path)
        d = plan.steps[0].to_dict()
        self.assertEqual(d['id'], 'requirements')
        self.assertEqual(d['name'], 'Requirements')
        self.assertEqual(d['status'], 'completed')
        self.assertEqual(d['chatId'], '85df7db0-d381-4355-b409-d6971462b1f2')
        self.assertIn('PRD', d['description'])


class TestDebugRound2ChatIdLineShifting(unittest.TestCase):
    """When a chat-id is inserted (not replaced), subsequent line numbers
    must be shifted correctly for future updates."""

    PLAN = """\
# Workflow

### [ ] Step: First
Description of first.

### [ ] Step: Second
Description of second.
"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.plan_path = _write_plan(self.PLAN, self.tmpdir)

    def test_insert_chat_id_then_update_later_step(self):
        """Insert chat-id on first step, then update second step status."""
        plan = parse_plan(self.plan_path)
        plan = update_step(plan, 'first', chat_id='aaaa-1111-2222-3333')
        # Now line numbers have shifted — update second step
        plan = update_step(plan, 'second', new_status=StepStatus.IN_PROGRESS)

        # Re-parse to verify
        plan2 = parse_plan(self.plan_path)
        self.assertEqual(plan2.steps[0].chat_id, 'aaaa-1111-2222-3333')
        self.assertEqual(plan2.steps[1].status, StepStatus.IN_PROGRESS)

    def test_insert_chat_id_and_status_simultaneously(self):
        """Set both chat-id and status in one update call."""
        plan = parse_plan(self.plan_path)
        plan = update_step(plan, 'first',
                          new_status=StepStatus.IN_PROGRESS,
                          chat_id='bbbb-4444-5555-6666')

        plan2 = parse_plan(self.plan_path)
        self.assertEqual(plan2.steps[0].status, StepStatus.IN_PROGRESS)
        self.assertEqual(plan2.steps[0].chat_id, 'bbbb-4444-5555-6666')
        # Second step should be unaffected
        self.assertEqual(plan2.steps[1].status, StepStatus.PENDING)


class TestDebugRound2PhaseKeyword(unittest.TestCase):
    """Verify Phase keyword with numbering works correctly."""

    PLAN = """\
# Workflow

### [ ] Phase 1: Setup Environment
Set up the dev environment.

### [ ] Phase 2: Build Features
Build all the features.

### [x] Step: Final Review
Review everything.
"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.plan_path = _write_plan(self.PLAN, self.tmpdir)

    def test_phase_keyword_parsed(self):
        plan = parse_plan(self.plan_path)
        self.assertEqual(len(plan.steps), 3)
        self.assertEqual(plan.steps[0].name, 'Setup Environment')
        self.assertEqual(plan.steps[1].name, 'Build Features')

    def test_phase_ids_derived(self):
        plan = parse_plan(self.plan_path)
        self.assertEqual(plan.steps[0].id, 'setup-environment')
        self.assertEqual(plan.steps[1].id, 'build-features')

    def test_mixed_phase_and_step(self):
        plan = parse_plan(self.plan_path)
        self.assertEqual(plan.steps[2].name, 'Final Review')
        self.assertEqual(plan.steps[2].status, StepStatus.DONE)

    def test_select_first_phase(self):
        plan = parse_plan(self.plan_path)
        result = select_next(plan)
        self.assertEqual(result.target.name, 'Setup Environment')

    def test_non_keyword_checkbox_ignored(self):
        """A checkbox at column 0 WITHOUT Step/Phase keyword should NOT be a root."""
        plan_content = """\
# Workflow

- [ ] This is just a random checkbox
- [ ] Step: Real Step
"""
        path = _write_plan(plan_content, self.tmpdir)
        plan = parse_plan(path)
        # Only "Real Step" should be parsed, not "This is just a random checkbox"
        self.assertEqual(len(plan.steps), 1)
        self.assertEqual(plan.steps[0].name, 'Real Step')


# ─────────────────────────────────────────────────────────────────────
# Debug Round 3: Production stress tests
# ─────────────────────────────────────────────────────────────────────

class TestDebugRound3SequentialUpdates(unittest.TestCase):
    """Simulate rapid sequential updates — like the backend processing
    multiple step completions in quick succession."""

    PLAN = """\
# Workflow

### [ ] Step: Alpha
  - [ ] Sub A1
  - [ ] Sub A2
  - [ ] Sub A3

### [ ] Step: Beta
  - [ ] Sub B1
  - [ ] Sub B2

### [ ] Step: Gamma
Final step.
"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.plan_path = _write_plan(self.PLAN, self.tmpdir)

    def test_complete_all_subtasks_and_roots_sequentially(self):
        """Walk through the entire plan completing every subtask."""
        plan = parse_plan(self.plan_path)

        # Complete all Alpha subtasks
        for child in plan.steps[0].children:
            plan = update_step(plan, child.id, new_status=StepStatus.DONE)

        # Alpha should be auto-completed
        plan = parse_plan(self.plan_path)
        self.assertEqual(plan.steps[0].status, StepStatus.DONE)

        # Complete all Beta subtasks
        for child in plan.steps[1].children:
            plan = update_step(plan, child.id, new_status=StepStatus.DONE)

        plan = parse_plan(self.plan_path)
        self.assertEqual(plan.steps[1].status, StepStatus.DONE)

        # Complete Gamma (no subtasks)
        plan = update_step(plan, 'gamma', new_status=StepStatus.DONE)

        plan = parse_plan(self.plan_path)
        self.assertEqual(plan.steps[2].status, StepStatus.DONE)

        # Everything done
        result = select_next(plan)
        self.assertIsNone(result.target)

    def test_select_next_advances_correctly(self):
        """select_next should return the correct step at each stage."""
        plan = parse_plan(self.plan_path)

        # Should start with first subtask of Alpha
        result = select_next(plan)
        self.assertEqual(result.target.name, 'Sub A1')

        # Complete A1, select A2
        plan = update_step(plan, 'alpha::sub-a1', new_status=StepStatus.DONE)
        plan = parse_plan(self.plan_path)
        result = select_next(plan)
        self.assertEqual(result.target.name, 'Sub A2')

        # Complete A2, select A3
        plan = update_step(plan, 'alpha::sub-a2', new_status=StepStatus.DONE)
        plan = parse_plan(self.plan_path)
        result = select_next(plan)
        self.assertEqual(result.target.name, 'Sub A3')

        # Complete A3 → Alpha auto-completes → select B1
        plan = update_step(plan, 'alpha::sub-a3', new_status=StepStatus.DONE)
        plan = parse_plan(self.plan_path)
        result = select_next(plan)
        self.assertEqual(result.target.name, 'Sub B1')

    def test_chat_id_on_multiple_steps(self):
        """Assign chat-ids to multiple steps and verify all persist."""
        plan = parse_plan(self.plan_path)
        plan = update_step(plan, 'alpha', chat_id='aaaa-0000-1111-2222')
        plan = update_step(plan, 'alpha::sub-a1', chat_id='bbbb-0000-1111-2222')
        plan = update_step(plan, 'beta', chat_id='cccc-0000-1111-2222')

        plan2 = parse_plan(self.plan_path)
        self.assertEqual(plan2.steps[0].chat_id, 'aaaa-0000-1111-2222')
        self.assertEqual(plan2.steps[0].children[0].chat_id, 'bbbb-0000-1111-2222')
        self.assertEqual(plan2.steps[1].chat_id, 'cccc-0000-1111-2222')


class TestDebugRound3CRLFLineEndings(unittest.TestCase):
    """Windows files often have \\r\\n line endings. The parser must handle them."""

    def test_crlf_plan_parses(self):
        plan_content = "# Workflow\r\n\r\n### [ ] Step: Alpha\r\nDescription.\r\n\r\n### [x] Step: Beta\r\nDone.\r\n"
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, 'plan.md')
        # Write in binary to preserve \r\n
        with open(path, 'wb') as f:
            f.write(plan_content.encode('utf-8'))

        plan = parse_plan(path)
        self.assertEqual(len(plan.steps), 2)
        self.assertEqual(plan.steps[0].name, 'Alpha')
        self.assertEqual(plan.steps[1].status, StepStatus.DONE)

    def test_crlf_update_preserves_formatting(self):
        plan_content = "# Workflow\r\n\r\n### [ ] Step: Alpha\r\nDescription.\r\n"
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, 'plan.md')
        with open(path, 'wb') as f:
            f.write(plan_content.encode('utf-8'))

        plan = parse_plan(path)
        plan = update_step(plan, 'alpha', new_status=StepStatus.DONE)

        plan2 = parse_plan(path)
        self.assertEqual(plan2.steps[0].status, StepStatus.DONE)
        self.assertEqual(plan2.steps[0].name, 'Alpha')


class TestDebugRound3EmptyAndMinimalPlans(unittest.TestCase):
    """Edge cases: empty files, plans with no steps, plans with only headers."""

    def test_empty_file(self):
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, 'plan.md')
        with open(path, 'w', encoding='utf-8') as f:
            f.write('')

        plan = parse_plan(path)
        self.assertEqual(plan.steps, [])
        result = select_next(plan)
        self.assertIsNone(result.target)

    def test_headers_only_no_steps(self):
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, 'plan.md')
        with open(path, 'w', encoding='utf-8') as f:
            f.write('# Workflow\n\n## Heading\n\nSome text.\n')

        plan = parse_plan(path)
        self.assertEqual(plan.steps, [])

    def test_single_step_plan(self):
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, 'plan.md')
        with open(path, 'w', encoding='utf-8') as f:
            f.write('### [ ] Step: Only One\n')

        plan = parse_plan(path)
        self.assertEqual(len(plan.steps), 1)
        result = select_next(plan)
        self.assertEqual(result.target.name, 'Only One')

    def test_plan_with_trailing_whitespace(self):
        """Steps with trailing whitespace in names should be trimmed."""
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, 'plan.md')
        with open(path, 'w', encoding='utf-8') as f:
            f.write('### [ ] Step: Has Trailing Space   \n')

        plan = parse_plan(path)
        self.assertEqual(len(plan.steps), 1)
        self.assertEqual(plan.steps[0].name, 'Has Trailing Space')

    def test_flat_iter_includes_all(self):
        """flat_iter should yield roots and all nested children."""
        plan_content = """\
# Workflow

### [ ] Step: Root
  - [ ] Child 1
  - [ ] Child 2
"""
        tmpdir = tempfile.mkdtemp()
        path = _write_plan(plan_content, tmpdir)
        plan = parse_plan(path)

        all_steps = list(plan.flat_iter())
        self.assertEqual(len(all_steps), 3)
        self.assertEqual(all_steps[0].name, 'Root')
        self.assertEqual(all_steps[1].name, 'Child 1')
        self.assertEqual(all_steps[2].name, 'Child 2')

    def test_find_step_by_scoped_id(self):
        """find_step should work with scoped child IDs."""
        plan_content = """\
# Workflow

### [ ] Step: Parent
  - [ ] Do thing
"""
        tmpdir = tempfile.mkdtemp()
        path = _write_plan(plan_content, tmpdir)
        plan = parse_plan(path)

        step = plan.find_step('parent::do-thing')
        self.assertIsNotNone(step)
        self.assertEqual(step.name, 'Do thing')

        # Root should also be findable
        root = plan.find_step('parent')
        self.assertIsNotNone(root)
        self.assertEqual(root.name, 'Parent')


if __name__ == '__main__':
    unittest.main()
