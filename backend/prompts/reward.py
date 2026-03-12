"""Prompt template for the Reward Agent.

The reward agent runs after each task to extract short, actionable
behavioral lessons from the task outcome. It converts numeric scores
and signal breakdowns into terse rules the agent can follow next time.

Called by: reward_agent.py
Format: LESSON: [rule] | TYPE: [positive/negative] | TAGS: [comma-separated]
"""


def build(*, task_grade: str, composite_score: float,
          signal_breakdown: str, step_summaries: str,
          execution_outcome: str) -> str:
    """Build the system prompt for the reward agent LLM call.

    Args:
        task_grade: Letter grade (A/B/C/D/F)
        composite_score: Overall score 0.0-1.0
        signal_breakdown: Formatted string of signal names + values
        step_summaries: Short summary of each step's outcome
        execution_outcome: What happened when the project was executed

    Returns:
        System prompt string for the reward agent.
    """
    return (
        "You are a CODE QUALITY ANALYST. Your job: extract SHORT behavioral rules "
        "from a task's outcomes.\n\n"
        "## Input\n"
        f"Task Grade: {task_grade} ({composite_score})\n"
        f"Signal Breakdown:\n{signal_breakdown}\n\n"
        f"Step Summaries:\n{step_summaries}\n\n"
        f"Execution Outcome:\n{execution_outcome}\n\n"
        "## Your Job\n"
        "Generate 3-5 SHORT behavioral rules. Each rule is ONE sentence in "
        "imperative mood (a command).\n\n"
        "Rules for GOOD signals (>= 0.7): what to KEEP doing.\n"
        "Rules for BAD signals (< 0.5): what to CHANGE.\n\n"
        "## Format (EXACTLY)\n"
        "LESSON: [one-sentence rule] | TYPE: [positive or negative] | TAGS: [comma-separated tags]\n\n"
        "Valid tags: implementation, planning, tool_usage, code_quality, python, "
        "flask, imports, testing, efficiency, architecture\n\n"
        "## Examples\n"
        "LESSON: Always check that imported names exist in the target module before STEP_COMPLETE. "
        "| TYPE: positive | TAGS: implementation, imports\n"
        "LESSON: Do NOT dump code in chat responses -- use WriteFile instead. "
        "| TYPE: negative | TAGS: tool_usage, implementation\n"
        "LESSON: Create requirements.txt in the same step as Python files that need third-party packages. "
        "| TYPE: positive | TAGS: implementation, python\n\n"
        "## Rules\n"
        "- ONE sentence per lesson. No fluff.\n"
        "- Imperative mood (commands): 'Do X', 'Always Y', 'Never Z'.\n"
        "- Be SPECIFIC -- reference the signal that triggered it.\n"
        "- If task scored A, generate 1-2 positive reinforcement rules max.\n"
        "- If task scored D/F, generate 4-5 rules covering each bad signal.\n"
        "- Do NOT repeat lessons that are already known (shown below).\n"
    )


def build_existing_lessons_block(existing_lessons: list[str]) -> str:
    """Format existing lessons so the reward agent avoids duplicates.

    Args:
        existing_lessons: List of lesson text strings already in memory.

    Returns:
        Formatted string to append to the user message.
    """
    if not existing_lessons:
        return ''
    block = "\n## Already Known (do NOT repeat these):\n"
    for lesson in existing_lessons[:15]:  # Cap to avoid prompt bloat
        block += f"- {lesson}\n"
    return block
