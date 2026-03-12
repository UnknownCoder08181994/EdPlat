"""Prompt template for the Technical Specification step."""

import re


def _detect_minimum_complexity(task_details: str) -> str | None:
    """Detect complexity keywords in the task to set a hard floor.

    Returns 'MEDIUM', 'COMPLEX', or None (let model decide).
    """
    text = task_details.lower()

    complex_patterns = [
        r'\bproduction\b', r'\benterprise\b', r'\bscalable\b',
        r'\bmicroservice', r'\bdistributed\b', r'\breal.?time\b',
    ]
    for pat in complex_patterns:
        if re.search(pat, text):
            return 'COMPLEX'

    medium_patterns = [
        r'\badvanced\b', r'\bcomplex\b', r'\bfull.?featured\b',
        r'\bdashboard\b', r'\bweb\s*app\b', r'\bapi\b', r'\brest\b',
        r'\bdatabase\b', r'\bvisuali[sz]', r'\bchart\b', r'\bgraph\b',
        r'\bmulti.?page\b', r'\bauthenticat', r'\bframework\b',
    ]
    for pat in medium_patterns:
        if re.search(pat, text):
            return 'MEDIUM'

    return None


def _map_complexity_label(complexity: int) -> str:
    """Map 1-10 user rating to the SIMPLE/MEDIUM/COMPLEX label."""
    if complexity <= 3:
        return 'SIMPLE'
    elif complexity <= 7:
        return 'MEDIUM'
    else:
        return 'COMPLEX'


def build(*, artifacts_path: str, task_details: str, complexity: int = 5, **_kwargs) -> str:
    """Return the full instruction string for the Technical Specification step."""
    def fp(filename):
        if artifacts_path == ".":
            return filename
        return f"{artifacts_path}/{filename}"

    # Use the user's explicit complexity rating — don't let the model override it
    user_complexity = _map_complexity_label(complexity)
    # Keyword detection can only bump UP, never down
    min_complexity = _detect_minimum_complexity(task_details)
    rank = {'SIMPLE': 0, 'MEDIUM': 1, 'COMPLEX': 2}
    final_complexity = user_complexity if rank.get(user_complexity, 0) >= rank.get(min_complexity or 'SIMPLE', 0) else min_complexity

    complexity_override = (
        f"\n*** USER-SELECTED COMPLEXITY: {final_complexity} (rated {complexity}/10) ***\n"
        f"The user explicitly set the complexity to {complexity}/10. "
        f"You MUST classify as {final_complexity}. Do NOT override the user's rating.\n\n"
    )

    return f"""
You are in the TECHNICAL SPECIFICATION step. Your output: a technical blueprint saved as spec.md.

CONTEXT: requirements.md is pre-loaded above. It defines WHAT to build.
Your job: define HOW to build it — the simplest architecture that satisfies all requirements.

BEFORE WRITING ANYTHING — STUDY requirements.md (pre-loaded above):
- Read EVERY requirement and acceptance criterion listed in requirements.md.
- Your spec MUST cover HOW to implement each requirement. If a requirement has no matching spec element, your spec is INCOMPLETE.
- Trace each spec section back to a requirement. If you can't, the section doesn't belong.

================================================================
THE USER'S TASK — SOURCE OF TRUTH
================================================================
{task_details}
================================================================

HARD RULES:
- Do NOT write code, pseudocode, or code blocks.
- Do NOT create any file except spec.md.
- requirements.md is already pre-loaded above — do NOT call ReadFile on it.

================================================================
SCOPE CHECK
================================================================
For every spec element, ask: "Is this required by requirements.md or THE USER'S TASK?"
- DO NOT design microservices — use a SINGLE application unless requirements force otherwise.
- No auth, no database (unless required), no API (unless required), no deployment config.
- If you cannot trace a spec element to a requirement, it does not belong.
{complexity_override}
================================================================
THINKING GUIDANCE
================================================================
Think through before writing (in your thinking, not your output):
- What is the simplest architecture that satisfies ALL requirements?
- What technology choices are forced by the task vs. what is flexible?
- What are the key workflows and how does data flow through them?
- What could break? What error handling is essential?

================================================================
COMPLEXITY ASSESSMENT
================================================================
The user rated this project {complexity}/10. Use this classification:

Complexity: {final_complexity}

Definitions for reference:
SIMPLE: Single script/program, no persistence, no external integrations, straight-through logic.
MEDIUM: Multiple modules/files, may include file-based persistence, some data modeling.
COMPLEX: Multiple subsystems, complex workflows, heavy state, multiple integrations.

Do NOT override the user's rating. Write {final_complexity} in the spec.

================================================================
OUTPUT FORMAT — spec.md
================================================================
Write a clear, implementation-ready spec. Focus on DECISIONS and REASONING,
not just structure. Each section should show WHY, not just WHAT.

# Technical Specification

## Complexity
Complexity: {final_complexity}
3-5 justification bullets explaining why this rating fits.

## Approach
5-10 sentences: architecture summary, key design decisions, and the reasoning
behind them. Explicitly call out trade-offs you considered.

## Technology Stack
Only what's needed. For each choice, briefly note WHY.
Mark unspecified choices as "Assumption: ..."

## Architecture & File Structure
List each file with its responsibility. Keep it minimal.
For SIMPLE: bullet list of components/functions.
For MEDIUM+: component breakdown with data flow description.

## Key Workflows
For each major feature from requirements:
Inputs → Processing steps → Outputs
Include error cases only where needed for correctness.

## Data & State
What data exists, where it lives (in-memory vs file), its lifecycle.
If no persistence required: "No persistent storage; state is in-memory only."

## Error Handling
Validation rules, failure modes, error message style.
Only what's needed for correctness — no security hardening unless required.

## Verification Plan
Short mapping: requirement → how to verify it works.
5-10 bullets for SIMPLE tasks.

## Scope Self-Audit
- [ ] No code or pseudocode included
- [ ] Only one file created: spec.md
- [ ] Every component is necessary for requirements
- [ ] No auth/login unless requirements include it
- [ ] No database unless requirements include persistence
- [ ] No API unless requirements include an API
- [ ] No microservices; single-application design
- [ ] No deployment/CI/CD content

================================================================
SAVE AND FINISH
================================================================
1) Save to: {fp('spec.md')} using WriteFile
2) Say [STEP_COMPLETE] immediately after saving.

CRITICAL — GO STRAIGHT TO WRITEFILE:
- Do NOT narrate your reasoning in the chat — your chain-of-thought is captured separately.
- Do NOT write out the spec as text and then call WriteFile with "..." placeholders.
- The WriteFile `content` field must contain the COMPLETE, FULL spec text.
- Put ALL real content inside the WriteFile content field.
- Use \\n for newlines inside the JSON content string. Do NOT use actual line breaks inside JSON.

WRITE ONCE ONLY — save the file exactly once, then stop.
Do NOT rewrite, revise, or re-save. The first save is the final save.
""".lstrip()
