"""
Phase-specific prompts for the micro-task orchestrated requirements step.

Three phases, four prompts:
  1. SCOPE      — build_scope_prompt()       → LLM outputs JSON
  2. DEEP DIVE  — build_deep_dive_prompt()   → LLM outputs JSON (medium/complex)
     2b.          build_interface_prompt()    → LLM outputs JSON (complex only)
  3. ASSEMBLE   — build_assemble_prompt()    → LLM calls WriteFile

The orchestrator in agent_service._run_requirements_micro_tasks() calls
these in sequence, validates JSON between phases, and controls depth
based on the complexity rating from Phase 1.
"""

from __future__ import annotations
import json


# ── Phase 1: Scope Analysis ─────────────────────────────────────────

def build_scope_prompt(*, task_details: str) -> str:
    """Phase 1: Analyze the task and output structured JSON.

    The orchestrator validates the JSON and uses `complexity` to decide
    whether Phase 2 runs (medium/complex) or is skipped (simple).
    """
    return (
        "Analyze this task and output a JSON object. "
        "NO markdown, NO commentary, NO explanation. ONLY valid JSON.\n\n"
        f"TASK:\n{task_details}\n\n"
        "Think through (in your thinking, not your output):\n"
        "- What is the user actually building? Single script, multi-module app, or full system?\n"
        "- What are the distinct functional pieces (be specific, not generic)?\n"
        "- What could go wrong or what is ambiguous in the task description?\n\n"
        "Then output ONLY the JSON object below.\n\n"
        "Output this exact JSON structure:\n"
        "{\n"
        '  "complexity": "simple or medium or complex",\n'
        '  "components": ["component1", "component2"],\n'
        '  "risks": ["risk1", "risk2"],\n'
        '  "deliverable_type": "web application or api/service or cli tool or library or automation or other",\n'
        '  "quality_level": "low or medium or high",\n'
        '  "summary": "2-3 sentence summary of what is being built"\n'
        "}\n\n"
        "Rules for complexity:\n"
        '- "simple": 1-2 components, no integrations, straightforward utility\n'
        '- "medium": 3-5 components, some integrations, moderate logic\n'
        '- "complex": 6+ components, multiple integrations, complex data flows\n\n'
        "Rules for components: List the major functional pieces. "
        "Each component = one distinct capability. Be specific — "
        '"Data Processing" not "Backend".\n\n'
        "Rules for risks: What could go wrong? Missing info, ambiguous requirements, "
        "technical challenges.\n\n"
        "Rules for quality_level: "
        '"low" = prototype/MVP, "medium" = standard, "high" = production-ready.\n\n'
        "Output ONLY the JSON object. No other text."
    )


# ── Phase 2: Component Deep-Dive ────────────────────────────────────

def build_deep_dive_prompt(*, task_details: str, scope_data: dict) -> str:
    """Phase 2: Detail requirements per component. Expects JSON output.

    Only called for medium/complex tasks.
    """
    components = scope_data.get('components', [])
    components_str = '\n'.join(f'  - {c}' for c in components)

    return (
        "For each component below, define its requirements and constraints. "
        "Output ONLY valid JSON. NO markdown, NO commentary.\n\n"
        f"TASK:\n{task_details}\n\n"
        f"COMPONENTS (from scope analysis):\n{components_str}\n\n"
        "Think through (in your thinking, not your output):\n"
        "- For each component: what specific behaviors must it support?\n"
        "- What data does each component receive and produce?\n"
        "- What happens when things go wrong for each component?\n\n"
        "Then output ONLY the JSON object below.\n\n"
        "Output this exact JSON structure:\n"
        "{\n"
        '  "components": [\n'
        "    {\n"
        '      "name": "ComponentName",\n'
        '      "requirements": ["req1", "req2"],\n'
        '      "constraints": ["constraint1"],\n'
        '      "inputs": "what data/events this component receives",\n'
        '      "outputs": "what data/events this component produces",\n'
        '      "edge_cases": ["edge case 1"]\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Rules:\n"
        "- Each component gets 2-5 requirements (specific, testable behaviors)\n"
        "- Constraints = limitations, tech choices, performance bounds\n"
        "- Inputs/Outputs = concrete data types, not vague descriptions\n"
        "- Edge cases = what happens when things go wrong\n"
        "- Do NOT invent components not in the list above\n"
        "- Do NOT add generic features (auth, logging) unless the TASK mentions them\n\n"
        "Output ONLY the JSON object. No other text."
    )


# ── Phase 2b: Interface Analysis (complex only) ─────────────────────

def build_interface_prompt(
    *, task_details: str, scope_data: dict, deep_dive_data: dict
) -> str:
    """Phase 2b: Describe interfaces between interacting components.

    Only called for complex tasks.
    """
    components = deep_dive_data.get('components', [])
    comp_names = [c.get('name', '') for c in components if isinstance(c, dict)]

    # Generate pairs
    pairs = []
    for i, a in enumerate(comp_names):
        for b in comp_names[i + 1:]:
            pairs.append(f'  - {a} <-> {b}')
    pairs_str = '\n'.join(pairs) if pairs else '  (none)'

    return (
        "For each pair of components that interact, describe the interface. "
        "Output ONLY valid JSON. NO markdown, NO commentary.\n\n"
        f"TASK:\n{task_details}\n\n"
        f"COMPONENT PAIRS:\n{pairs_str}\n\n"
        "Think through (in your thinking, not your output):\n"
        "- Which components actually need to communicate?\n"
        "- What data format passes between them?\n"
        "- Are there any circular dependencies to avoid?\n\n"
        "Then output ONLY the JSON object below.\n\n"
        "Output this exact JSON structure:\n"
        "{\n"
        '  "interfaces": [\n'
        "    {\n"
        '      "between": ["ComponentA", "ComponentB"],\n'
        '      "description": "How these components communicate",\n'
        '      "data_format": "What data passes between them",\n'
        '      "direction": "A->B or B->A or bidirectional"\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Only include pairs that actually interact. Skip unrelated pairs.\n"
        "Output ONLY the JSON object. No other text."
    )


# ── Phase 3: Assemble requirements.md ───────────────────────────────

def build_assemble_prompt(
    *, task_details: str, scope_data: dict,
    deep_dive_data: dict | None,
    interface_data: dict | None,
    artifact_path: str,
) -> str:
    """Phase 3: Write requirements.md from structured data using WriteFile.

    The structured data from Phases 1-2 is embedded as context so the
    LLM's job is pure assembly — no analysis needed.
    """
    # Build context block from prior phases
    context_parts = []
    context_parts.append(f"SCOPE ANALYSIS:\n{json.dumps(scope_data, indent=2)}")

    if deep_dive_data:
        context_parts.append(
            f"COMPONENT DETAILS:\n{json.dumps(deep_dive_data, indent=2)}"
        )

    if interface_data:
        context_parts.append(
            f"COMPONENT INTERFACES:\n{json.dumps(interface_data, indent=2)}"
        )

    context_block = '\n\n'.join(context_parts)

    quality = scope_data.get('quality_level', 'medium').upper()

    return (
        "Write requirements.md using the structured data below. "
        "Call WriteFile ONCE with the complete content.\n\n"
        f"TASK:\n{task_details}\n\n"
        f"{context_block}\n\n"
        "Think through (in your thinking, not your output):\n"
        "- Review scope data: does the summary match the task?\n"
        "- For each component: are the requirements complete and testable?\n"
        "- What should explicitly be listed as non-goals?\n\n"
        "Then call WriteFile ONCE with the complete requirements.md content.\n\n"
        f"TEMPLATE — fill in every section using the data above. "
        f"No placeholders, no '...':\n\n"
        "# Requirements\n\n"
        "## Overview\n"
        f"6-10 sentences: what is being built, who for, problem/outcome, "
        f"constraints, quality={quality}.\n"
        "Use the summary and components from SCOPE ANALYSIS.\n\n"
        "## Features\n"
        "One block per component. Each feature:\n"
        "### [Component Name]\n"
        "- **What**: 4-8 sentences — behavior, boundaries, edge cases. "
        "Pull from requirements + edge_cases.\n"
        "- **Inputs/Outputs**: From the component's inputs/outputs fields.\n"
        "- **Done when**: One testable statement derived from the requirements.\n\n"
        "## Acceptance Criteria\n"
        "Per feature, 2+ criteria: Given [precondition], when [action], then [result].\n"
        "Derive from requirements and edge_cases. Include at least one error case.\n\n"
        "## Non-Goals\n"
        "List what is NOT being built. Derive from SCOPE ANALYSIS risks and "
        "components NOT listed.\n\n"
        "## Constraints & Assumptions\n"
        "Hard constraints from TASK, then assumptions prefixed 'Assumption:'.\n"
        "Pull from component constraints.\n\n"
        "HARD RULES:\n"
        "1) No code, pseudocode, or code blocks.\n"
        "2) Only create requirements.md — no other files.\n"
        "3) No placeholders. Every section must have real content.\n"
        "4) Every feature must trace to the TASK. Do NOT invent features.\n\n"
        f"SAVE: Call WriteFile ONCE for {artifact_path} with complete content. "
        "Then say [STEP_COMPLETE]."
    )
