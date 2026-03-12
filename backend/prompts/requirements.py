"""
Prompt template for the REQUIREMENTS step (tuned for GPT-OSS-20B).

Design goals:
- Produces a strong, specific requirements.md (PRD/SRS hybrid).
- Avoids the "generic ecommerce PRD" failure mode.
- Forces correct tool-call shape: ONE WriteFile call, then [STEP_COMPLETE].
- COMPACT: must fit in limited context windows (~8K tokens total).
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple


# ----------------------------
# Small helpers
# ----------------------------

def _has_match(text: str, pattern: str) -> bool:
    """Check if pattern matches anywhere in text."""
    return bool(re.search(pattern, text or "", flags=re.IGNORECASE))


def _detect_deliverable_type(task: str) -> str:
    """Best-effort classification hint."""
    rules = [
        ("web application", r"\b(flask|django|fastapi|web\s*app|website|frontend|react|vue|svelte)\b"),
        ("api/service", r"\b(api|endpoint|rest|graphql|webhook|service)\b"),
        ("cli tool / script", r"\b(cli|command[- ]line|terminal|script|argparse|flags?)\b"),
        ("python package/library", r"\b(package|library|pip|pypi|module)\b"),
        ("automation / bot", r"\b(bot|agent|automation|scraper)\b"),
    ]
    for label, pat in rules:
        if _has_match(task, pat):
            return label
    return "unspecified"


def _detect_quality_level(task: str) -> str:
    """Detect quality expectations from keywords."""
    if _has_match(task, r"\b(advanced|production[- ]ready|robust|enterprise|scalable|high[- ]performance|secure|hardened|reliable)\b"):
        return "HIGH"
    if _has_match(task, r"\b(simple|minimal|quick|basic|prototype|mvp)\b"):
        return "LOW"
    return "MEDIUM"


def _scope_signals(task: str) -> str:
    """Compact scope matrix — just YES/NO per category, no evidence snippets."""
    categories = [
        ("Auth", r"\b(auth|login|signup|user accounts?|rbac|oauth)\b"),
        ("Database", r"\b(database|db|postgres|mysql|sqlite|mongodb|redis|persistent)\b"),
        ("API", r"\b(api|endpoint|rest|graphql|webhook)\b"),
        ("UI", r"\b(ui|frontend|react|vue|dashboard|interface)\b"),
        ("CLI", r"\b(cli|command[- ]line|terminal|argparse)\b"),
        ("Files", r"\b(file|csv|json|yaml|xml)\b"),
        ("Network", r"\b(http|request|fetch|socket)\b"),
        ("Async", r"\b(async|concurrent|parallel|thread)\b"),
        ("Testing", r"\b(test|pytest|unittest)\b"),
        ("Deploy", r"\b(deploy|docker|kubernetes|aws|gcp)\b"),
        ("Logging", r"\b(logging|metrics|monitoring)\b"),
    ]
    lines = []
    for name, pat in categories:
        status = "YES" if _has_match(task, pat) else "no"
        lines.append(f"  {name}: {status}")
    return "\n".join(lines)


# ----------------------------
# Prompt builder
# ----------------------------

def build(*, artifacts_path: str, task_details: str, **_kwargs) -> str:
    """Return the full instruction string for the Requirements step."""

    def fp(filename: str) -> str:
        if artifacts_path == ".":
            return filename
        return f"{artifacts_path}/{filename}"

    path = fp("requirements.md")

    deliverable_type = _detect_deliverable_type(task_details or "")
    quality_level = _detect_quality_level(task_details or "")
    scope_matrix = _scope_signals(task_details or "")

    return f"""
You are in the REQUIREMENTS step.

MISSION: Create requirements.md (PRD/SRS-style) specific to the user's task.
Clear scope, clear behaviors, clear acceptance criteria.

=== USER TASK (SOURCE OF TRUTH) ===
{task_details}
=== END TASK ===

HINTS (auto-detected, defer to USER TASK if wrong):
- Deliverable type: {deliverable_type}
- Quality level: {quality_level}
- Scope scan:
{scope_matrix}
  Categories marked YES are IN SCOPE. Categories marked "no" are OUT OF SCOPE unless clearly implied.
  If quality=HIGH, include error handling, configuration, and reliability as requirements.

HARD RULES:
1) No code, pseudocode, or code blocks.
2) Only create requirements.md — no other files.
3) No placeholders ('...' or 'TBD' everywhere). Be specific.
4) Every feature must trace to the USER TASK. Do NOT invent features.
5) Missing info → capture as Open Question or Assumption.
6) Do NOT add generic SaaS features (user registration, shopping cart, etc.) unless explicitly requested.

WORKFLOW:
A) Go DIRECTLY to WriteFile. Do NOT narrate reasoning — chain-of-thought is captured separately.
B) After WriteFile, say [STEP_COMPLETE] and stop.

REQUIREMENTS.MD FORMAT:

# Requirements

## Overview
6–10 sentences: what is being built, who for, problem/outcome, constraints, quality expectations.

## Features
One block per distinct capability. Each feature:
### [Feature Name]
- **What**: 4–8 sentences — behavior, boundaries, edge cases.
- **Source**: short quote from USER TASK justifying this feature.
- **Inputs/Outputs**: concrete (files, params, requests, responses).
- **Done when**: one testable statement.

## Acceptance Criteria
Per feature, 2+ criteria: Given [precondition], when [action], then [result].
Include at least one edge/error case.

## Non-Goals
List what you are NOT building. Scope categories marked "no" above are candidates.

## Constraints & Assumptions
Hard constraints from USER TASK, then assumptions prefixed 'Assumption:'.

SAVE: Call WriteFile ONCE for {path} with complete content. Then [STEP_COMPLETE].
""".lstrip()
