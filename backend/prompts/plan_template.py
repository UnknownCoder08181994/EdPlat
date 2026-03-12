"""Dynamic plan.md builder.

Generates a task-specific plan.md at task creation time.
The output is the master document that ALL SDD agents read first.
It must remain parseable by plan_engine.parse_plan().
"""

import re


def _derive_title(details: str) -> str:
    """Extract a short title from the first line of task details."""
    first_line = details.strip().split('\n')[0].strip()
    # Strip leading "Build a..." or "Create a..." for cleaner titles
    if len(first_line) > 60:
        return first_line[:57] + "..."
    return first_line


def _complexity_tone(complexity: int) -> str:
    """Map 1-10 complexity to a human-readable approach description."""
    if complexity <= 3:
        return "Simple — keep it minimal, avoid over-engineering"
    elif complexity <= 6:
        return "Moderate — solid implementation, nothing extra"
    elif complexity <= 8:
        return "Thorough — comprehensive but not gold-plated"
    else:
        return "Complex — cover all edge cases and integrations"


def _truncate_details(details: str, max_chars: int = 500) -> str:
    """Truncate task details for plan.md, preserving whole lines."""
    text = details.strip()
    if len(text) <= max_chars:
        return text
    # Find last newline before the limit
    cut = text[:max_chars].rfind('\n')
    if cut < 200:
        cut = max_chars  # no good line break, hard cut
    return text[:cut].strip() + "\n(...full description available in step prompts)"


def _detect_negative_scope(details: str) -> list:
    """Auto-detect things the user did NOT ask for → boundary bullets."""
    text = details.lower()
    boundaries = []
    checks = [
        (r'\b(auth|login|signup|sign.?up|oauth|user.?account|password)\b',
         "authentication or user accounts"),
        (r'\b(database|postgres|mysql|sqlite|mongo|redis|orm|sql)\b',
         "database or persistence layer"),
        (r'\b(api|endpoint|rest|graphql|fastapi|flask.route)\b',
         "API endpoints or web server"),
        (r'\b(docker|kubernetes|ci/?cd|deploy|aws|gcp|azure|heroku)\b',
         "containerization, CI/CD, or cloud deployment"),
        (r'\b(cache|caching|redis|memcache)\b',
         "caching layer"),
        (r'\b(ui|frontend|html|css|react|vue|angular|template)\b',
         "frontend UI or web interface"),
    ]
    for pattern, label in checks:
        if not re.search(pattern, text):
            boundaries.append(label)
    return boundaries[:4]  # max 4 to save tokens


def build(*, details: str, complexity: int = 5,
          workflow_type: str = 'Full SDD workflow') -> str:
    """Generate a dynamic, task-specific plan.md.

    Parameters
    ----------
    details : str
        The raw task description from the user.
    complexity : int
        1-10 complexity rating from the UI slider.
    workflow_type : str
        Workflow name (currently always 'Full SDD workflow').

    Returns
    -------
    str
        Complete plan.md content, parseable by plan_engine.parse_plan().
    """
    title = _derive_title(details)
    tone = _complexity_tone(complexity)
    truncated = _truncate_details(details)
    neg_scope = _detect_negative_scope(details)

    # Build boundaries section
    boundary_lines = "- Implement ONLY what is described in Project Scope\n"
    if neg_scope:
        exclusions = ", ".join(neg_scope)
        boundary_lines += f"- Do NOT add: {exclusions} — unless explicitly requested\n"
    boundary_lines += (
        "- Prefer single-application design unless requirements force otherwise\n"
        "- Do NOT invent features, screens, or capabilities the user did not ask for"
    )

    return f"""\
# {title}
Complexity: {complexity}/10 — {tone}

## Project Scope
{truncated}

## Boundaries
{boundary_lines}

## Agent Rules
- Save ALL code and content via WriteFile or EditFile tool calls — NEVER show code in chat
- Say [STEP_COMPLETE] when your step is done — do not say anything after it
- If your code reads config files, data files, or templates, you MUST create those files too
- NEVER modify plan.md — it is managed by the system
- Work autonomously — do NOT ask the user for confirmation or clarification

---

## Workflow Steps

### [ ] Step: Requirements

Create a Product Requirements Document (PRD) based on the Project Scope above.

1. Read the Project Scope carefully
2. Write requirements for ONLY what the user asked for
3. Do NOT add features the user did not request

Save the PRD to `requirements.md`.

### [ ] Step: Technical Specification

Create a technical specification based on the PRD in `requirements.md`.

Choose appropriate technology and write a detailed spec covering architecture, data models, and APIs.

Save to `spec.md`.

### [ ] Step: Planning

Create a detailed implementation plan based on `spec.md`.

Break down the work into buildable steps with clear file assignments.

Save to `implementation-plan.md`.

### [ ] Step: Implementation

This step will be replaced with the implementation tasks from Planning.
"""
