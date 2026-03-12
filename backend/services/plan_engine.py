"""
plan_engine.py — Core step-processing engine for ZenClone workflow plans.

Pure Python module (no Flask deps). Handles:
  - Parsing plan.md into a structured step tree
  - Deterministic depth-first selection of the next executable step
  - Atomic plan.md updates (bracket token swaps + parent auto-completion)

Step Grammar:
  Root steps (column 0, must contain Step/Phase keyword):
    ### [ ] Step: Requirements
    - [ ] Step: Build API
    ## [>] Phase 2: Design
  Subtasks (indented checkbox under a root):
    - [ ] Create database models
    - [x] Write migration scripts
  Context bullets (indented, no checkbox — not executable):
    - Research caching strategies

State markers:  [ ] pending, [>] in-progress, [x] done, [!] failed, [-] skipped
"""

import os
import re
import sys
import tempfile
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class StepStatus(Enum):
    PENDING = " "
    IN_PROGRESS = ">"
    DONE = "x"
    FAILED = "!"
    SKIPPED = "-"


# Map single characters found in brackets to StepStatus
_CHAR_TO_STATUS = {
    " ": StepStatus.PENDING,
    ">": StepStatus.IN_PROGRESS,
    "x": StepStatus.DONE,
    "X": StepStatus.DONE,
    "!": StepStatus.FAILED,
    "-": StepStatus.SKIPPED,
}

# Map API-facing string labels to StepStatus
STATUS_LABEL_MAP = {
    "pending": StepStatus.PENDING,
    "in_progress": StepStatus.IN_PROGRESS,
    "completed": StepStatus.DONE,
    "failed": StepStatus.FAILED,
    "skipped": StepStatus.SKIPPED,
}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Step:
    id: str                                 # Derived: name.lower().replace(" ", "-")
    name: str                               # Human-readable name
    status: StepStatus
    line_number: int                        # 0-based index in raw_lines
    chat_id: Optional[str] = None
    description: str = ""                   # Body text below the step heading
    parent_id: Optional[str] = None         # None for root steps
    children: List["Step"] = field(default_factory=list)
    depth: int = 0                          # 0 = root, 1+ = subtask
    is_root: bool = True

    @property
    def status_label(self) -> str:
        return {
            StepStatus.PENDING: "pending",
            StepStatus.IN_PROGRESS: "in_progress",
            StepStatus.DONE: "completed",
            StepStatus.FAILED: "failed",
            StepStatus.SKIPPED: "skipped",
        }[self.status]

    def to_dict(self) -> dict:
        """Backward-compatible serialization matching the old _parse_plan shape."""
        d = {
            "id": self.id,
            "name": self.name,
            "status": self.status_label,
            "description": self.description,
            "chatId": self.chat_id,
            "parentId": self.parent_id,
        }
        if self.children:
            d["children"] = [c.to_dict() for c in self.children]
        return d


@dataclass
class PlanState:
    """Immutable-ish snapshot of a parsed plan.md."""
    steps: List[Step]           # Root steps only (children nested inside)
    raw_lines: List[str]        # Original file lines (for update operations)
    file_path: str              # Absolute path to plan.md

    def flat_iter(self):
        """Yield all steps in depth-first file order."""
        for root in self.steps:
            yield root
            yield from self._walk(root)

    @staticmethod
    def _walk(step):
        for child in step.children:
            yield child
            yield from PlanState._walk(child)

    def find_step(self, step_id: str) -> Optional[Step]:
        for s in self.flat_iter():
            if s.id == step_id:
                return s
        return None


@dataclass
class SelectionResult:
    target: Optional[Step] = None
    halted: bool = False
    halt_reason: str = ""
    warnings: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Root step at column 0.  Captures: (status_char) (name_with_keyword)
# Matches:  ### [ ] Step: Requirements   |  - [ ] Step: Build API  |  ## [>] Phase 2: Design
_ROOT_RE = re.compile(
    r'^(?:#{2,6}\s+|-\s+)'       # heading hashes OR list bullet at column 0
    r'\[([ xX\->!])\]\s+'        # [status]
    r'((?:Step|Phase)(?:\s+\d+)?:?\s+.+)$'  # Step/Phase keyword + name
)

# Indented checkbox subtask.  Captures: (indent) (status_char) (name)
_SUBTASK_RE = re.compile(
    r'^(\s+)-\s+\[([ xX\->!])\]\s+(.+)$'
)

# Chat-id HTML comment
_CHATID_RE = re.compile(
    r'<!--\s*chat-id:\s*([a-zA-Z0-9-]+)\s*-->'
)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def _slugify(text: str) -> str:
    """Convert text to a URL-safe slug: lowercase, spaces/special chars to hyphens."""
    slug = text.strip().lower()
    # Replace any non-alphanumeric character (except hyphen) with hyphen
    slug = re.sub(r'[^a-z0-9-]+', '-', slug)
    # Collapse multiple hyphens and strip leading/trailing
    slug = re.sub(r'-{2,}', '-', slug).strip('-')
    return slug


def _derive_id(name: str) -> str:
    """Derive a step ID from its name, matching the existing convention."""
    # Strip the Step/Phase prefix to get the meaningful part
    m = re.match(r'(?:Step|Phase)(?:\s+\d+)?:?\s+(.+)', name)
    if m:
        return _slugify(m.group(1))
    return _slugify(name)


def _char_to_status(ch: str) -> StepStatus:
    return _CHAR_TO_STATUS.get(ch, StepStatus.PENDING)


def parse_plan(file_path: str) -> PlanState:
    """Parse a plan.md file into a PlanState with root steps and nested subtasks."""
    if not os.path.exists(file_path):
        return PlanState(steps=[], raw_lines=[], file_path=file_path)

    with open(file_path, "r", encoding="utf-8") as f:
        raw_lines = f.readlines()

    # Strip trailing newlines from each line but preserve content
    lines = [line.rstrip("\n").rstrip("\r") for line in raw_lines]

    steps: List[Step] = []
    current_root: Optional[Step] = None
    current_step: Optional[Step] = None  # Most recently parsed step (root or subtask)
    description_lines: List[str] = []

    for i, line in enumerate(lines):
        stripped = line.strip()

        # --- Try root step match ---
        root_match = _ROOT_RE.match(line)
        if root_match:
            # Finalize previous step's description
            if current_step is not None:
                current_step.description = "\n".join(description_lines).strip()

            status_char = root_match.group(1)
            full_name = root_match.group(2).strip()
            step_id = _derive_id(full_name)

            current_root = Step(
                id=step_id,
                name=_extract_display_name(full_name),
                status=_char_to_status(status_char),
                line_number=i,
                depth=0,
                is_root=True,
            )
            steps.append(current_root)
            current_step = current_root
            description_lines = []
            continue

        # --- Try subtask match (only when we have a root) ---
        if current_root is not None:
            sub_match = _SUBTASK_RE.match(line)
            if sub_match:
                # Finalize previous step's description
                if current_step is not None and current_step is not current_root:
                    current_step.description = "\n".join(description_lines).strip()
                elif current_step is current_root:
                    current_root.description = "\n".join(description_lines).strip()

                indent = sub_match.group(1)
                status_char = sub_match.group(2)
                child_name = sub_match.group(3).strip()
                child_id = _slugify(child_name)

                # Scope child ID to avoid collisions across parents
                scoped_id = f"{current_root.id}::{child_id}"

                child = Step(
                    id=scoped_id,
                    name=child_name,
                    status=_char_to_status(status_char),
                    line_number=i,
                    parent_id=current_root.id,
                    depth=1,
                    is_root=False,
                )
                current_root.children.append(child)
                current_step = child
                description_lines = []
                continue

        # --- Try chat-id match ---
        chat_match = _CHATID_RE.search(stripped)
        if chat_match and current_step is not None:
            current_step.chat_id = chat_match.group(1)
            continue

        # --- Accumulate description ---
        if current_step is not None:
            description_lines.append(line)

    # Finalize last step
    if current_step is not None:
        current_step.description = "\n".join(description_lines).strip()

    return PlanState(steps=steps, raw_lines=lines, file_path=file_path)


def _extract_display_name(full_name: str) -> str:
    """Extract the human-readable name from 'Step: Requirements' → 'Requirements'."""
    m = re.match(r'(?:Step|Phase)(?:\s+\d+)?:?\s+(.+)', full_name)
    if m:
        return m.group(1).strip()
    return full_name.strip()


# ---------------------------------------------------------------------------
# Selection algorithm
# ---------------------------------------------------------------------------

def select_next(plan: PlanState) -> SelectionResult:
    """Depth-first, file-order selection of the next executable step.

    Rules:
    1. If [>] exists, resume it (multiple [>] → keep first, downgrade rest)
    2. Walk root steps in file order; skip [x] and [-]
    3. If root is [!] → HALT
    4. If root has children → DFS into children for first actionable leaf
    5. If root is childless and [ ] → select it
    """
    warnings = []

    # --- Pass 1: Find and handle [>] in-progress steps ---
    in_progress = [s for s in plan.flat_iter() if s.status == StepStatus.IN_PROGRESS]

    if len(in_progress) > 1:
        for extra in in_progress[1:]:
            warnings.append(
                f"Inconsistent state: downgraded '{extra.name}' from [>] to [ ] "
                f"(multiple in-progress detected, resuming '{in_progress[0].name}')"
            )
            extra.status = StepStatus.PENDING
            logger.warning("Downgraded [>] on '%s' (line %d) to [ ]", extra.name, extra.line_number)
            # Persist the downgrade to disk so it doesn't recur on next select_next call
            try:
                plan = update_step(plan, extra.id, new_status=StepStatus.PENDING)
            except Exception:
                pass  # Non-critical — worst case is a repeat downgrade next call

    if in_progress:
        target = in_progress[0]
        logger.info("Resuming in-progress step: '%s' (line %d)", target.name, target.line_number)
        return SelectionResult(target=target, warnings=warnings)

    # --- Pass 2: DFS file-order search ---
    for root in plan.steps:
        if root.status in (StepStatus.DONE, StepStatus.SKIPPED):
            continue

        if root.status == StepStatus.FAILED:
            reason = f"Step '{root.name}' is marked [!] (failed/blocked)"
            logger.info("HALT: %s", reason)
            return SelectionResult(halted=True, halt_reason=reason, warnings=warnings)

        # Root is pending — check children
        if root.children:
            # Check if all children are terminal (auto-complete case)
            if _all_children_terminal(root):
                # This root should be auto-completed; skip it for selection
                # (auto-completion is handled in update_step)
                continue

            result = _select_from_children(root, warnings)
            if result is not None:
                return result
        else:
            # Leaf root step
            logger.info("Selected root step: '%s' (line %d)", root.name, root.line_number)
            return SelectionResult(target=root, warnings=warnings)

    # All done
    logger.info("All steps complete or skipped")
    return SelectionResult(target=None, warnings=warnings)


def _select_from_children(parent: Step, warnings: list) -> Optional[SelectionResult]:
    """Find first actionable child in file order. Returns None if all children are terminal."""
    for child in parent.children:
        if child.status in (StepStatus.DONE, StepStatus.SKIPPED):
            continue

        if child.status == StepStatus.FAILED:
            reason = f"Subtask '{child.name}' under '{parent.name}' is marked [!] (failed/blocked)"
            logger.info("HALT: %s", reason)
            return SelectionResult(halted=True, halt_reason=reason, warnings=warnings)

        # Pending child — if it has its own children, recurse
        if child.children:
            result = _select_from_children(child, warnings)
            if result is not None:
                return result
            continue

        # Leaf child — this is the target
        logger.info("Selected subtask: '%s' under '%s' (line %d)", child.name, parent.name, child.line_number)
        return SelectionResult(target=child, warnings=warnings)

    return None


def _all_children_terminal(step: Step) -> bool:
    """Check if all children are done or skipped."""
    return all(
        c.status in (StepStatus.DONE, StepStatus.SKIPPED)
        for c in step.children
    )


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

def update_step(plan: PlanState, step_id: str,
                new_status: StepStatus = None,
                chat_id: str = None) -> PlanState:
    """Update a step's bracket token and/or chat-id in plan.md.

    Writes atomically: temp file in same directory + os.replace().
    Returns updated PlanState.
    """
    step = plan.find_step(step_id)
    if step is None:
        raise ValueError(f"Step '{step_id}' not found in plan")

    lines = list(plan.raw_lines)  # Copy for mutation
    changed = False

    # --- Update status bracket ---
    if new_status is not None and new_status != step.status:
        old_line = lines[step.line_number]
        new_line = re.sub(
            r'\[([ xX\->!])\]',
            f'[{new_status.value}]',
            old_line,
            count=1,
        )
        if new_line != old_line:
            lines[step.line_number] = new_line
            logger.info(
                "Updated '%s' (line %d): [%s] → [%s]",
                step.name, step.line_number, step.status.value, new_status.value,
            )
            step.status = new_status
            changed = True

    # --- Update or insert chat-id ---
    if chat_id is not None and chat_id != step.chat_id:
        next_idx = step.line_number + 1
        chat_id_line = f"<!-- chat-id: {chat_id} -->"

        if next_idx < len(lines) and _CHATID_RE.search(lines[next_idx]):
            # Replace existing chat-id
            lines[next_idx] = chat_id_line
        else:
            # Insert new chat-id line after the step heading
            lines.insert(next_idx, chat_id_line)
            # Shift line numbers for all subsequent steps
            for s in plan.flat_iter():
                if s.line_number > step.line_number:
                    s.line_number += 1

        step.chat_id = chat_id
        changed = True

    # --- Parent auto-completion ---
    if new_status in (StepStatus.DONE, StepStatus.SKIPPED) and step.parent_id:
        parent = plan.find_step(step.parent_id)
        if parent and _all_children_terminal(parent):
            old_parent_line = lines[parent.line_number]
            new_parent_line = re.sub(
                r'\[([ xX\->!])\]',
                f'[{StepStatus.DONE.value}]',
                old_parent_line,
                count=1,
            )
            if new_parent_line != old_parent_line:
                lines[parent.line_number] = new_parent_line
                logger.info(
                    "Auto-completed parent '%s' (line %d): all children terminal",
                    parent.name, parent.line_number,
                )
                parent.status = StepStatus.DONE
                changed = True

    # --- Write atomically ---
    if changed:
        _atomic_write(plan.file_path, lines)

    # Return updated plan state
    plan.raw_lines = lines
    return plan


def _atomic_write(file_path: str, lines: List[str]):
    """Write lines to file_path atomically using temp file + os.replace()."""
    dir_name = os.path.dirname(file_path) or "."
    fd = None
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".md.tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            fd = None  # os.fdopen takes ownership
            f.write("\n".join(lines))
            # Ensure newline at end of file if original had one
            if lines and lines[-1] != "":
                pass  # Content ends as-is from join
        # os.replace can fail on Windows if the target is locked by another process
        # (antivirus, editor, etc.) — retry a few times with a short delay
        for _attempt in range(5):
            try:
                os.replace(tmp_path, file_path)
                tmp_path = None
                break
            except PermissionError:
                import time
                time.sleep(0.1)
        else:
            # Final attempt — fall back to direct write if atomic replace keeps failing
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
            tmp_path = None
    except Exception:
        # Clean up temp file on failure
        if fd is not None:
            os.close(fd)
        if tmp_path is not None and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        raise
