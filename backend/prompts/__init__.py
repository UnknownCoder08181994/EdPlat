"""
Prompt templates for the Sentinel agent pipeline.

All LLM-facing prompts live here:
  - Step-specific instructions (requirements, tech-spec, planning, implementation)
  - Micro-task phase prompts for requirements (requirements_phases)
  - Core system prompt assembly (system_prompt)
  - Code review prompt (review)
  - Mid-loop nudge messages (nudges)
  - Task description reformatter (task_reformat)
  - Context wiring helpers (context_wiring)
"""

from .requirements import build as build_requirements_prompt
from .technical_specification import build as build_technical_specification_prompt
from .planning import build as build_planning_prompt
from .implementation import build as build_implementation_prompt
from .context_wiring import (
    build_code_context, build_read_before_write_rules,
    extract_relevant_criteria, build_completion_ledger,
)
from .handoff import generate_handoff_note, format_handoff_note
from .system_prompt import build as build_system_prompt
from .review import build as build_review_prompt
from .review import build_api_check_prompt, build_quality_check_prompt, build_fix_summary_prompt
from .requirements_phases import (
    build_scope_prompt,
    build_deep_dive_prompt,
    build_interface_prompt,
    build_assemble_prompt,
)
from . import nudges
from .task_reformat import build as build_task_reformat_prompt
from .plan_template import build as build_plan_template
from .execution import build_diagnose_prompt as build_execution_diagnose_prompt
from .execution import build_dependency_prompt as build_execution_dependency_prompt
from .execution import build_recoder_prompt as build_execution_recoder_prompt

__all__ = [
    'build_requirements_prompt',
    'build_technical_specification_prompt',
    'build_planning_prompt',
    'build_implementation_prompt',
    'build_code_context',
    'build_read_before_write_rules',
    'extract_relevant_criteria',
    'build_completion_ledger',
    'generate_handoff_note',
    'format_handoff_note',
    'build_system_prompt',
    'build_review_prompt',
    'build_api_check_prompt',
    'build_quality_check_prompt',
    'build_fix_summary_prompt',
    'build_scope_prompt',
    'build_deep_dive_prompt',
    'build_interface_prompt',
    'build_assemble_prompt',
    'nudges',
    'build_task_reformat_prompt',
    'build_plan_template',
    'build_execution_diagnose_prompt',
    'build_execution_dependency_prompt',
    'build_execution_recoder_prompt',
]
