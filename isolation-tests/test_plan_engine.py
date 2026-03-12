"""Isolation test: Plan Engine (plan_engine.py)

Tests:
  1. parse_plan   - Parse plan.md into PlanState with steps/subtasks
  2. select_next  - DFS selection of next executable step
  3. update_step  - Bracket token swap + parent auto-completion
  4. Edge cases   - Empty plan, missing file, multiple in-progress, etc.
"""

import os
import sys
import shutil
import tempfile

BACKEND_DIR = os.path.join(os.path.dirname(__file__), '..', 'backend')
sys.path.insert(0, os.path.abspath(BACKEND_DIR))

from services.plan_engine import (
    parse_plan,
    select_next,
    update_step,
    StepStatus,
    PlanState,
    Step,
    SelectionResult,
)


# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------

def _write_plan(content):
    """Write a plan.md to a temp file and return the path."""
    fd, path = tempfile.mkstemp(suffix='.md', prefix='zenflow_plan_')
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(content)
    return path


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
# TEST 1: Basic plan parsing
# ===============================================================
print("\n=== TEST 1: Basic plan parsing ===")

plan_text = """# Project Plan

### [ ] Step: Requirements
Gather all requirements from the user.

### [ ] Step: Technical Specification
Write the technical spec.

### [x] Step: Planning
Create the implementation plan.
"""

path = _write_plan(plan_text)
plan = parse_plan(path)

check("3 root steps parsed", len(plan.steps) == 3, f"count={len(plan.steps)}")
check("first step is Requirements", plan.steps[0].name == 'Requirements', f"name={plan.steps[0].name}")
check("first step is pending", plan.steps[0].status == StepStatus.PENDING)
check("third step is done", plan.steps[2].status == StepStatus.DONE)
check("step IDs are slugified", plan.steps[0].id == 'requirements', f"id={plan.steps[0].id}")
check("raw_lines captured", len(plan.raw_lines) > 0)
check("file_path stored", plan.file_path == path)
os.unlink(path)


# ===============================================================
# TEST 2: Plan with subtasks
# ===============================================================
print("\n=== TEST 2: Plan with subtasks ===")

plan_text = """# Implementation Plan

### [ ] Step: Implementation
Build the application

  - [ ] Create database models
  - [x] Write migration scripts
  - [ ] Create API endpoints

### [ ] Step: Testing
Run tests
"""

path = _write_plan(plan_text)
plan = parse_plan(path)

check("2 root steps", len(plan.steps) == 2, f"count={len(plan.steps)}")
check("first root has 3 children", len(plan.steps[0].children) == 3,
      f"children={len(plan.steps[0].children)}")
check("child 1 is pending", plan.steps[0].children[0].status == StepStatus.PENDING)
check("child 2 is done", plan.steps[0].children[1].status == StepStatus.DONE)
check("child parent_id set", plan.steps[0].children[0].parent_id == plan.steps[0].id,
      f"parent_id={plan.steps[0].children[0].parent_id}")
check("child is_root=False", plan.steps[0].children[0].is_root == False)
check("child depth=1", plan.steps[0].children[0].depth == 1)
check("child ID is scoped", '::' in plan.steps[0].children[0].id,
      f"id={plan.steps[0].children[0].id}")
os.unlink(path)


# ===============================================================
# TEST 3: Step with chat-id
# ===============================================================
print("\n=== TEST 3: Chat-id parsing ===")

plan_text = """### [>] Step: Requirements
<!-- chat-id: abc-123 -->
Gather requirements

### [ ] Step: Technical Specification
Write spec
"""

path = _write_plan(plan_text)
plan = parse_plan(path)

check("chat_id parsed", plan.steps[0].chat_id == 'abc-123', f"chat_id={plan.steps[0].chat_id}")
check("step without chat_id is None", plan.steps[1].chat_id is None)
check("in-progress status parsed", plan.steps[0].status == StepStatus.IN_PROGRESS)
os.unlink(path)


# ===============================================================
# TEST 4: select_next - basic DFS
# ===============================================================
print("\n=== TEST 4: select_next - basic DFS ===")

plan_text = """### [x] Step: Requirements
Done

### [ ] Step: Technical Specification
Pending

### [ ] Step: Planning
Pending
"""

path = _write_plan(plan_text)
plan = parse_plan(path)
result = select_next(plan)

check("selects first pending step", result.target is not None)
check("selected Tech Spec", result.target.name == 'Technical Specification',
      f"name={result.target.name if result.target else None}")
check("not halted", result.halted == False)
os.unlink(path)


# ===============================================================
# TEST 5: select_next - resumes in-progress
# ===============================================================
print("\n=== TEST 5: select_next - resumes in-progress ===")

plan_text = """### [x] Step: Requirements
Done

### [>] Step: Technical Specification
In progress

### [ ] Step: Planning
Pending
"""

path = _write_plan(plan_text)
plan = parse_plan(path)
result = select_next(plan)

check("resumes in-progress step", result.target is not None)
check("resumed Tech Spec", result.target.name == 'Technical Specification',
      f"name={result.target.name if result.target else None}")
os.unlink(path)


# ===============================================================
# TEST 6: select_next - DFS into children
# ===============================================================
print("\n=== TEST 6: select_next - DFS into children ===")

plan_text = """### [ ] Step: Implementation
Build the app

  - [x] Create models
  - [ ] Create routes
  - [ ] Create tests
"""

path = _write_plan(plan_text)
plan = parse_plan(path)
result = select_next(plan)

check("DFS selects first pending child", result.target is not None)
check("selected Create routes", result.target.name == 'Create routes',
      f"name={result.target.name if result.target else None}")
os.unlink(path)


# ===============================================================
# TEST 7: select_next - halt on failed step
# ===============================================================
print("\n=== TEST 7: select_next - halt on failed ===")

plan_text = """### [x] Step: Requirements
Done

### [!] Step: Technical Specification
Failed

### [ ] Step: Planning
Pending
"""

path = _write_plan(plan_text)
plan = parse_plan(path)
result = select_next(plan)

check("halted on failed step", result.halted == True)
check("halt reason mentions step", 'Technical Specification' in result.halt_reason,
      f"reason={result.halt_reason}")
check("no target when halted", result.target is None)
os.unlink(path)


# ===============================================================
# TEST 8: select_next - all done
# ===============================================================
print("\n=== TEST 8: select_next - all steps done ===")

plan_text = """### [x] Step: Requirements
Done

### [x] Step: Technical Specification
Done

### [x] Step: Planning
Done
"""

path = _write_plan(plan_text)
plan = parse_plan(path)
result = select_next(plan)

check("no target when all done", result.target is None)
check("not halted when all done", result.halted == False)
os.unlink(path)


# ===============================================================
# TEST 9: select_next - multiple in-progress (downgrade)
# ===============================================================
print("\n=== TEST 9: select_next - multiple in-progress ===")

plan_text = """### [>] Step: Requirements
First

### [>] Step: Technical Specification
Second

### [ ] Step: Planning
Pending
"""

path = _write_plan(plan_text)
plan = parse_plan(path)
result = select_next(plan)

check("selects first in-progress", result.target is not None)
check("selected Requirements", result.target.name == 'Requirements',
      f"name={result.target.name if result.target else None}")
check("emits warning about multiple in-progress", len(result.warnings) > 0,
      f"warnings={result.warnings}")
os.unlink(path)


# ===============================================================
# TEST 10: select_next - skipped steps bypassed
# ===============================================================
print("\n=== TEST 10: select_next - skipped steps ===")

plan_text = """### [-] Step: Requirements
Skipped

### [ ] Step: Technical Specification
Pending
"""

path = _write_plan(plan_text)
plan = parse_plan(path)
result = select_next(plan)

check("skips skipped step", result.target is not None)
check("selected Tech Spec (not skipped)", result.target.name == 'Technical Specification',
      f"name={result.target.name if result.target else None}")
os.unlink(path)


# ===============================================================
# TEST 11: update_step - status change
# ===============================================================
print("\n=== TEST 11: update_step - status change ===")

plan_text = """### [ ] Step: Requirements
Pending
"""

path = _write_plan(plan_text)
plan = parse_plan(path)
updated = update_step(plan, 'requirements', new_status=StepStatus.IN_PROGRESS)

check("status updated in memory", updated.steps[0].status == StepStatus.IN_PROGRESS)

# Re-read from disk to verify persistence
plan2 = parse_plan(path)
check("status persisted to disk", plan2.steps[0].status == StepStatus.IN_PROGRESS)
os.unlink(path)


# ===============================================================
# TEST 12: update_step - chat_id insertion
# ===============================================================
print("\n=== TEST 12: update_step - chat_id ===")

plan_text = """### [>] Step: Requirements
Working on it
"""

path = _write_plan(plan_text)
plan = parse_plan(path)
updated = update_step(plan, 'requirements', chat_id='my-chat-123')

check("chat_id set in memory", updated.steps[0].chat_id == 'my-chat-123')

plan2 = parse_plan(path)
check("chat_id persisted to disk", plan2.steps[0].chat_id == 'my-chat-123')
os.unlink(path)


# ===============================================================
# TEST 13: update_step - parent auto-completion
# ===============================================================
print("\n=== TEST 13: update_step - parent auto-completion ===")

plan_text = """### [ ] Step: Implementation
Build

  - [x] Create models
  - [ ] Create routes
"""

path = _write_plan(plan_text)
plan = parse_plan(path)

# Find the "Create routes" child step
child = plan.steps[0].children[1]
check("child found", child.name == 'Create routes', f"name={child.name}")

# Mark the last pending child as done
updated = update_step(plan, child.id, new_status=StepStatus.DONE)

# Parent should auto-complete since all children are now terminal
check("parent auto-completed", updated.steps[0].status == StepStatus.DONE,
      f"parent_status={updated.steps[0].status}")

plan2 = parse_plan(path)
check("parent auto-completion persisted", plan2.steps[0].status == StepStatus.DONE)
os.unlink(path)


# ===============================================================
# TEST 14: update_step - nonexistent step raises
# ===============================================================
print("\n=== TEST 14: update_step - nonexistent step ===")

plan_text = """### [ ] Step: Requirements
Pending
"""

path = _write_plan(plan_text)
plan = parse_plan(path)
try:
    update_step(plan, 'nonexistent', new_status=StepStatus.DONE)
    check("raises on nonexistent step", False, "no exception raised")
except ValueError as e:
    check("raises ValueError on nonexistent step", True)
os.unlink(path)


# ===============================================================
# TEST 15: Empty / missing plan
# ===============================================================
print("\n=== TEST 15: Empty / missing plan ===")

# Missing file
plan = parse_plan('/nonexistent/plan.md')
check("missing file -> empty steps", len(plan.steps) == 0)
check("missing file -> empty raw_lines", len(plan.raw_lines) == 0)

# Empty file
path = _write_plan("")
plan = parse_plan(path)
check("empty file -> empty steps", len(plan.steps) == 0)
os.unlink(path)


# ===============================================================
# TEST 16: flat_iter and find_step
# ===============================================================
print("\n=== TEST 16: flat_iter and find_step ===")

plan_text = """### [ ] Step: Implementation
Build

  - [ ] Create models
  - [ ] Create routes

### [ ] Step: Testing
Test
"""

path = _write_plan(plan_text)
plan = parse_plan(path)

all_steps = list(plan.flat_iter())
check("flat_iter yields all steps", len(all_steps) == 4, f"count={len(all_steps)}")
check("flat_iter includes root + children", any(s.name == 'Create models' for s in all_steps))

found = plan.find_step('implementation')
check("find_step by ID works", found is not None and found.name == 'Implementation',
      f"found={found}")
check("find_step returns None for missing", plan.find_step('nope') is None)
os.unlink(path)


# ===============================================================
# TEST 17: Step.to_dict serialization
# ===============================================================
print("\n=== TEST 17: Step.to_dict ===")

plan_text = """### [>] Step: Requirements
<!-- chat-id: abc-123 -->
Gather requirements

  - [x] Interview users
"""

path = _write_plan(plan_text)
plan = parse_plan(path)

d = plan.steps[0].to_dict()
check("to_dict has id", d['id'] == 'requirements')
check("to_dict has name", d['name'] == 'Requirements')
check("to_dict has status=in_progress", d['status'] == 'in_progress')
check("to_dict has chatId", d['chatId'] == 'abc-123')
check("to_dict has children list", 'children' in d and len(d['children']) == 1)
check("child to_dict has status=completed", d['children'][0]['status'] == 'completed')
os.unlink(path)


# ===============================================================
# TEST 18: Heading formats (### and - bullet)
# ===============================================================
print("\n=== TEST 18: Different heading formats ===")

plan_text = """## [ ] Phase 1: Design
Design the system

- [ ] Step: Build API
Create the API

### [ ] Step: Testing
Test everything
"""

path = _write_plan(plan_text)
plan = parse_plan(path)

check("## Phase format parsed", any(s.name == 'Design' for s in plan.steps),
      f"names={[s.name for s in plan.steps]}")
check("- Step bullet format parsed", any(s.name == 'Build API' for s in plan.steps),
      f"names={[s.name for s in plan.steps]}")
check("### Step format parsed", any(s.name == 'Testing' for s in plan.steps),
      f"names={[s.name for s in plan.steps]}")
os.unlink(path)


# ===============================================================
# TEST 19: Description capture
# ===============================================================
print("\n=== TEST 19: Step description capture ===")

plan_text = """### [ ] Step: Implementation
Build the backend
Files: app.py, models.py
Depends-on: requirements.md

  - [ ] Create database
  Database setup with SQLAlchemy
"""

path = _write_plan(plan_text)
plan = parse_plan(path)

desc = plan.steps[0].description
check("root description captured", 'Build the backend' in desc, f"desc={desc[:100]}")
check("Files: line in description", 'Files:' in desc, f"desc={desc[:100]}")

child_desc = plan.steps[0].children[0].description
check("child description captured", 'SQLAlchemy' in child_desc, f"child_desc={child_desc[:100]}")
os.unlink(path)


# ===============================================================
# TEST 20: Auto-complete does NOT fire when children not all terminal
# ===============================================================
print("\n=== TEST 20: No auto-complete with pending children ===")

plan_text = """### [ ] Step: Implementation
Build

  - [x] Create models
  - [ ] Create routes
  - [ ] Create tests
"""

path = _write_plan(plan_text)
plan = parse_plan(path)

# Mark only one child as done (not all)
child = plan.steps[0].children[1]  # Create routes
updated = update_step(plan, child.id, new_status=StepStatus.DONE)

check("parent NOT auto-completed", updated.steps[0].status == StepStatus.PENDING,
      f"parent_status={updated.steps[0].status}")
os.unlink(path)


# ===============================================================
# Summary
# ===============================================================
print(f"\n{'='*60}")
print(f"PlanEngine:  {passed} passed, {failed} failed")
print(f"{'='*60}")
sys.exit(1 if failed > 0 else 0)
