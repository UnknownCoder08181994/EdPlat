"""Unit tests for backend/services/plan_engine.py"""

import os
import pytest
from conftest import write_text, read_text

from services.plan_engine import (
    parse_plan, select_next, update_step,
    StepStatus, STATUS_LABEL_MAP, _slugify, _derive_id,
)


# ── Helpers ──────────────────────────────────────────────────────

def make_plan(tmp_path, content):
    """Write a plan.md and return its path."""
    path = str(tmp_path / 'plan.md')
    write_text(path, content)
    return path


# ── Slugify / ID derivation ─────────────────────────────────────

class TestSlugify:
    def test_simple_name(self):
        assert _slugify("Hello World") == "hello-world"

    def test_special_chars(self):
        assert _slugify("Build API v2.0!") == "build-api-v2-0"

    def test_multiple_hyphens_collapsed(self):
        assert _slugify("a---b") == "a-b"

    def test_leading_trailing_stripped(self):
        assert _slugify("  hello  ") == "hello"


class TestDeriveId:
    def test_step_prefix(self):
        assert _derive_id("Step: Requirements") == "requirements"

    def test_phase_prefix(self):
        assert _derive_id("Phase 2: Design") == "design"

    def test_step_numbered(self):
        assert _derive_id("Step 1: Build API") == "build-api"

    def test_no_prefix(self):
        # Falls back to slugify the whole thing
        assert _derive_id("Just a name") == "just-a-name"


# ── Parser ───────────────────────────────────────────────────────

class TestParsePlan:
    def test_empty_file(self, tmp_path):
        path = make_plan(tmp_path, "")
        plan = parse_plan(path)
        assert len(plan.steps) == 0

    def test_nonexistent_file(self, tmp_path):
        plan = parse_plan(str(tmp_path / 'nope.md'))
        assert len(plan.steps) == 0

    def test_single_root_step(self, tmp_path):
        path = make_plan(tmp_path, "## [ ] Step: Requirements\n")
        plan = parse_plan(path)
        assert len(plan.steps) == 1
        assert plan.steps[0].id == "requirements"
        assert plan.steps[0].status == StepStatus.PENDING
        assert plan.steps[0].name == "Requirements"

    def test_multiple_root_steps(self, tmp_path):
        path = make_plan(tmp_path, (
            "## [ ] Step: Requirements\n"
            "## [>] Step: Technical Specification\n"
            "## [x] Step: Planning\n"
        ))
        plan = parse_plan(path)
        assert len(plan.steps) == 3
        assert plan.steps[0].status == StepStatus.PENDING
        assert plan.steps[1].status == StepStatus.IN_PROGRESS
        assert plan.steps[2].status == StepStatus.DONE

    def test_subtasks_parsed(self, tmp_path):
        path = make_plan(tmp_path, (
            "## [ ] Step: Implementation\n"
            "  - [ ] Create models\n"
            "  - [x] Write routes\n"
        ))
        plan = parse_plan(path)
        assert len(plan.steps) == 1
        root = plan.steps[0]
        assert len(root.children) == 2
        assert root.children[0].name == "Create models"
        assert root.children[0].status == StepStatus.PENDING
        assert root.children[1].name == "Write routes"
        assert root.children[1].status == StepStatus.DONE

    def test_description_captured(self, tmp_path):
        path = make_plan(tmp_path, (
            "## [ ] Step: Requirements\n"
            "This step gathers all user requirements.\n"
            "Focus on acceptance criteria.\n"
        ))
        plan = parse_plan(path)
        assert "gathers all user requirements" in plan.steps[0].description

    def test_chat_id_parsed(self, tmp_path):
        path = make_plan(tmp_path, (
            "## [>] Step: Requirements\n"
            "<!-- chat-id: abc-123 -->\n"
        ))
        plan = parse_plan(path)
        assert plan.steps[0].chat_id == "abc-123"

    def test_failed_step(self, tmp_path):
        path = make_plan(tmp_path, "## [!] Step: Broken\n")
        plan = parse_plan(path)
        assert plan.steps[0].status == StepStatus.FAILED

    def test_skipped_step(self, tmp_path):
        path = make_plan(tmp_path, "## [-] Step: Skipped\n")
        plan = parse_plan(path)
        assert plan.steps[0].status == StepStatus.SKIPPED

    def test_list_bullet_format(self, tmp_path):
        path = make_plan(tmp_path, "- [ ] Step: Requirements\n")
        plan = parse_plan(path)
        assert len(plan.steps) == 1
        assert plan.steps[0].name == "Requirements"

    def test_flat_iter(self, tmp_path):
        path = make_plan(tmp_path, (
            "## [ ] Step: Parent\n"
            "  - [ ] Child A\n"
            "  - [ ] Child B\n"
            "## [ ] Step: Other\n"
        ))
        plan = parse_plan(path)
        all_steps = list(plan.flat_iter())
        assert len(all_steps) == 4

    def test_find_step(self, tmp_path):
        path = make_plan(tmp_path, (
            "## [ ] Step: Requirements\n"
            "## [ ] Step: Planning\n"
        ))
        plan = parse_plan(path)
        found = plan.find_step("planning")
        assert found is not None
        assert found.name == "Planning"

    def test_find_step_not_found(self, tmp_path):
        path = make_plan(tmp_path, "## [ ] Step: Requirements\n")
        plan = parse_plan(path)
        assert plan.find_step("nonexistent") is None


# ── Selection ────────────────────────────────────────────────────

class TestSelectNext:
    def test_selects_first_pending(self, tmp_path):
        path = make_plan(tmp_path, (
            "## [x] Step: Done\n"
            "## [ ] Step: Next\n"
            "## [ ] Step: Later\n"
        ))
        plan = parse_plan(path)
        result = select_next(plan)
        assert result.target is not None
        assert result.target.name == "Next"

    def test_resumes_in_progress(self, tmp_path):
        path = make_plan(tmp_path, (
            "## [x] Step: Done\n"
            "## [>] Step: Current\n"
            "## [ ] Step: Later\n"
        ))
        plan = parse_plan(path)
        result = select_next(plan)
        assert result.target.name == "Current"

    def test_halts_on_failed(self, tmp_path):
        path = make_plan(tmp_path, (
            "## [x] Step: Done\n"
            "## [!] Step: Broken\n"
            "## [ ] Step: Later\n"
        ))
        plan = parse_plan(path)
        result = select_next(plan)
        assert result.halted is True
        assert "Broken" in result.halt_reason

    def test_all_done_returns_none(self, tmp_path):
        path = make_plan(tmp_path, (
            "## [x] Step: Done1\n"
            "## [x] Step: Done2\n"
        ))
        plan = parse_plan(path)
        result = select_next(plan)
        assert result.target is None
        assert not result.halted

    def test_selects_first_pending_child(self, tmp_path):
        path = make_plan(tmp_path, (
            "## [ ] Step: Parent\n"
            "  - [x] Done child\n"
            "  - [ ] Pending child\n"
        ))
        plan = parse_plan(path)
        result = select_next(plan)
        assert result.target is not None
        assert result.target.name == "Pending child"

    def test_skips_done_parent_all_children_done(self, tmp_path):
        path = make_plan(tmp_path, (
            "## [ ] Step: Parent\n"
            "  - [x] Child A\n"
            "  - [x] Child B\n"
            "## [ ] Step: Next\n"
        ))
        plan = parse_plan(path)
        result = select_next(plan)
        assert result.target.name == "Next"

    def test_multiple_in_progress_warnings(self, tmp_path):
        path = make_plan(tmp_path, (
            "## [>] Step: First\n"
            "## [>] Step: Second\n"
        ))
        plan = parse_plan(path)
        result = select_next(plan)
        assert result.target.name == "First"
        assert len(result.warnings) > 0
        assert "downgraded" in result.warnings[0].lower()


# ── Update ───────────────────────────────────────────────────────

class TestUpdateStep:
    def test_update_status(self, tmp_path):
        path = make_plan(tmp_path, "## [ ] Step: Requirements\n")
        plan = parse_plan(path)
        updated = update_step(plan, "requirements", new_status=StepStatus.IN_PROGRESS)
        # Re-read and verify
        plan2 = parse_plan(path)
        assert plan2.steps[0].status == StepStatus.IN_PROGRESS

    def test_update_adds_chat_id(self, tmp_path):
        path = make_plan(tmp_path, "## [>] Step: Requirements\n")
        plan = parse_plan(path)
        updated = update_step(plan, "requirements", chat_id="chat-abc")
        plan2 = parse_plan(path)
        assert plan2.steps[0].chat_id == "chat-abc"

    def test_update_nonexistent_raises(self, tmp_path):
        path = make_plan(tmp_path, "## [ ] Step: Requirements\n")
        plan = parse_plan(path)
        with pytest.raises(ValueError, match="not found"):
            update_step(plan, "nonexistent", new_status=StepStatus.DONE)

    def test_update_marks_done(self, tmp_path):
        path = make_plan(tmp_path, "## [>] Step: Requirements\n")
        plan = parse_plan(path)
        update_step(plan, "requirements", new_status=StepStatus.DONE)
        plan2 = parse_plan(path)
        assert plan2.steps[0].status == StepStatus.DONE


# ── Status maps ──────────────────────────────────────────────────

class TestStatusMaps:
    def test_status_label_map_coverage(self):
        assert STATUS_LABEL_MAP["pending"] == StepStatus.PENDING
        assert STATUS_LABEL_MAP["in_progress"] == StepStatus.IN_PROGRESS
        assert STATUS_LABEL_MAP["completed"] == StepStatus.DONE
        assert STATUS_LABEL_MAP["failed"] == StepStatus.FAILED
        assert STATUS_LABEL_MAP["skipped"] == StepStatus.SKIPPED

    def test_step_to_dict(self, tmp_path):
        path = make_plan(tmp_path, "## [>] Step: Requirements\n")
        plan = parse_plan(path)
        d = plan.steps[0].to_dict()
        assert d['id'] == 'requirements'
        assert d['status'] == 'in_progress'
        assert d['name'] == 'Requirements'
