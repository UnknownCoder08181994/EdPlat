"""Core system prompt builder for the Sentinel agent.

Extracted from agent_service.py — assembles the full system prompt
from identity, tool examples, workspace info, step context, tool
definitions, and completion rules.
"""

import json
import os

# SDD steps that produce .md artifacts (not code)
SDD_STEPS = {'requirements', 'technical-specification', 'planning'}


def build_example_block(*, step_id: str | None, compact_mode: bool) -> str:
    """Return the tool-usage example block appropriate for the step type."""
    if compact_mode:
        return (
            '<tool_code>\n'
            '{"name": "WriteFile", "arguments": {"path": "file.md", "content": "content here"}}\n'
            '</tool_code>\n\n'
        )

    if step_id and step_id in SDD_STEPS:
        return (
            "Example — go STRAIGHT to WriteFile:\n"
            "<tool_code>\n"
            '{"name": "WriteFile", "arguments": {"path": "requirements.md", "content": "# Requirements\\n\\n## Overview\\nA command-line task manager that stores tasks locally as JSON...\\n"}}\n'
            "</tool_code>\n\n"
        )

    return (
        "Example — go STRAIGHT to WriteFile:\n"
        "<tool_code>\n"
        '{"name": "WriteFile", "arguments": {"path": "app.py", "content": "from flask import Flask\\n\\napp = Flask(__name__)\\n\\nif __name__ == \\"__main__\\":\\n    app.run(debug=True)\\n"}}\n'
        "</tool_code>\n\n"
        "Example of editing an EXISTING file (use EditFile instead of rewriting the whole file):\n"
        "<tool_code>\n"
        '{"name": "EditFile", "arguments": {"path": "app.py", "old_string": "if __name__ == \\"__main__\\":", "new_string": "@app.route(\\"/hello\\")\\ndef hello():\\n    return \\"Hello, World!\\"\\n\\nif __name__ == \\"__main__\\":"}}\n'
        "</tool_code>\n\n"
        "CRITICAL: Go DIRECTLY to WriteFile/EditFile tool calls.\n"
        "Do NOT write code in a markdown code block first and then save it.\n"
        "Do NOT narrate what you plan to do. Just do it.\n"
        "The code goes INSIDE the tool content, nowhere else.\n\n"
        "WHEN TO USE EACH TOOL:\n"
        "- WriteFile: Creating NEW files, or when most of the file content needs to change.\n"
        "- EditFile: Modifying a SMALL PART of an existing file (adding a function, fixing a bug, adding imports).\n"
        "  EditFile finds old_string in the file and replaces it with new_string. old_string must match exactly once.\n\n"
    )


def build_thinking_instructions(*, compact_mode: bool, example_block: str) -> str:
    """Return the tool-usage instructions section."""
    if compact_mode:
        return (
            "Go straight to tool calls. Use <tool_code> JSON format.\n\n"
            + example_block
        )
    return (
        "## How You Work\n"
        "Go DIRECTLY to tool calls. Do NOT narrate your reasoning in the chat — "
        "your chain-of-thought is captured separately.\n"
        "Do NOT write inner monologue, analysis, or commentary before tool calls.\n"
        "Just call the tool immediately.\n\n"
        "## Thinking Framework\n"
        "Before each action, reason through these (in your head, NOT in chat):\n"
        "- STATE: What files exist? What has this step already produced so far?\n"
        "- GOAL: What specific outcome does this step need?\n"
        "- PLAN: Which files to create/edit, in what order, what depends on what?\n"
        "- EACH FILE: What does it import? What does it export? Does it match existing APIs?\n"
        "- AFTER TOOL: Did it succeed? If error — what went wrong? Try a DIFFERENT approach.\n\n"
        "If a tool returns an Error, STOP and think: Why did it fail? What is the ACTUAL file content? "
        "Do NOT retry the same approach — change your strategy.\n\n"
        + example_block
    )


def build_workspace_section(*, compact_mode: bool, step_id: str | None,
                            workspace_path: str, artifacts_path: str,
                            os_name: str) -> str:
    """Return workspace, venv, and shell environment info."""
    out = ""
    if compact_mode:
        if step_id and step_id in SDD_STEPS:
            out += "File paths are relative. Use just filenames.\n\n"
        else:
            out += f"Workspace: {workspace_path}\n"
            out += f"Artifacts: {artifacts_path}/\n\n"
    else:
        if step_id and step_id in SDD_STEPS:
            out += "## Workspace\nYour working directory contains the task artifacts (plan.md, requirements.md, spec.md, etc.).\n"
            out += "All file paths are relative to this directory. Use just filenames like plan.md, requirements.md.\n\n"
        else:
            out += f"## Workspace\nYour project directory: {workspace_path}\n"
            out += "Build a complete, runnable project here. All files must work together as one cohesive application.\n"
            out += f"Prior step artifacts (specs, plans) are at: {artifacts_path}/\n\n"
            out += (
                "## Python Environment\n"
                "A Python virtual environment is pre-configured at `.venv\\` in the workspace.\n"
                "- Install packages: `pip install <package>` (the venv is already active for commands)\n"
                "- Run Python: `python <script.py>`\n"
                "- ALWAYS use the workspace venv. NEVER install to the global Python.\n\n"
            )
            out += (
                "## Shell Environment\n"
                f"- Operating system: {os_name}\n"
            )
            if os_name == 'Windows':
                out += (
                    "- Commands run via cmd.exe. Use Windows-compatible commands.\n"
                    "- Use `mkdir dirname` (NO -p flag). For nested dirs: `mkdir parent\\child`\n"
                    "- Do NOT use `touch`, `rm -rf`, `export`, `source`, or other Unix commands.\n"
                    "- PREFER using WriteFile tool over RunCommand for creating files — it's more reliable.\n"
                    "- Use forward slashes in Python code paths (they work on Windows too).\n\n"
                )
            else:
                out += "- Standard Unix shell commands are available.\n\n"
    return out


def build_task_section(task_details: str) -> str:
    """Return the ## Task block."""
    return f"## Task\n{task_details}\n\n"


def build_plan_protection(*, compact_mode: bool) -> str:
    """Return plan.md protection rules (skipped in compact mode)."""
    if compact_mode:
        return ""
    return (
        "## Important Rules\n"
        "CRITICAL RULE: NEVER modify or overwrite plan.md. "
        "The plan.md is the workflow state file managed by the system. "
        "Save your step outputs to separate artifact files instead "
        "(e.g., requirements.md, spec.md, implementation-plan.md).\n\n"
    )


def build_step_context(*, step_for_chat: dict, all_steps: list,
                        compact_mode: bool, parent_context: dict | None,
                        step_instructions: str, step_id: str | None,
                        artifact_name: str, existing_files: list[str]) -> str:
    """Return step progress, current step details, existing files, and completion rules."""
    out = ""

    # Flatten root + children for progress display
    flat_steps = []
    for s in all_steps:
        flat_steps.append(s)
        for child in s.get('children', []):
            flat_steps.append(child)

    step_index = next((i for i, s in enumerate(flat_steps) if s['id'] == step_for_chat['id']), 0)
    total_steps = len(flat_steps)

    # Workflow progress overview
    if not compact_mode:
        out += f"## Workflow Progress — Step {step_index + 1} of {total_steps}\n"
        for i, s in enumerate(flat_steps):
            marker = ">>>" if s['id'] == step_for_chat['id'] else "   "
            status_label = "[DONE]" if s['status'] == 'completed' else "[CURRENT]" if s['id'] == step_for_chat['id'] else "[pending]"
            indent = "  " if '::' in s.get('id', '') else ""
            out += f"  {marker} {i + 1}. {indent}{s['name']} {status_label}\n"
        out += "\n"

    # Current step details
    out += f"## Current Step: {step_for_chat['name']}\n"
    if parent_context:
        out += f"Part of: {parent_context['name']}\n"
        out += f"{parent_context['description']}\n\n"
    else:
        out += f"{step_for_chat.get('description', '')}\n\n"

    # Existing workspace files
    if existing_files and not compact_mode:
        out += "## Existing Workspace Files\n"
        out += "These files already exist in the workspace. Their contents are pre-loaded below.\n"
        out += "You can:\n"
        out += "  - Use EditFile to modify specific parts of these files\n"
        out += "  - Use ReadFile to re-read a file if you need to check its current state\n"
        out += "  - Use WriteFile ONLY to create NEW files (not to rewrite existing ones)\n\n"
        for ef in sorted(existing_files):
            out += f"  - {ef}\n"
        out += "\n"

    # Mandatory rules / step instructions
    out += "## MANDATORY RULES — Follow these exactly:\n"
    out += step_instructions

    # Completion instruction
    if step_id and step_id in SDD_STEPS:
        out += (
            f"\n**COMPLETION:** After saving {artifact_name} with WriteFile, "
            f"your VERY NEXT message must end with [STEP_COMPLETE]. "
            f"Do NOT create additional files. Do NOT continue working. "
            f"Do NOT rewrite or re-save {artifact_name} — one WriteFile call is all you get. "
            f"Just say [STEP_COMPLETE] and stop.\n"
        )
    else:
        out += (
            "\n**COMPLETION (REQUIRED):** When ALL files are written and your work is done, "
            "you MUST say [STEP_COMPLETE] as the very last thing in your message. "
            "This signals the system to advance to the next step.\n"
        )

    # Additional rules + completion checklist (skip checklist for SDD steps — step prompt already covers it)
    if not compact_mode:
        out += "\nADDITIONAL RULES:\n"
        out += "- Work autonomously. Do NOT ask the user for confirmation or permission.\n"
        out += "- NEVER modify plan.md — it is managed by the system.\n"
        out += "\n"

        # Only include checklist for implementation steps — SDD step prompts have their own
        if not (step_id and step_id in SDD_STEPS):
            out += "## Completion Checklist (before saying [STEP_COMPLETE]):\n"
            out += f"- [ ] I studied existing code files before writing anything\n"
            out += f"- [ ] I implemented the requirements for '{step_for_chat['name']}'\n"
            out += f"- [ ] I saved ALL code files using WriteFile or EditFile\n"
            out += f"- [ ] Each file has complete, working code (no placeholders)\n"
            out += f"- [ ] My files integrate with existing code (correct imports, shared structures)\n"
            out += f"- [ ] The project has a runnable entry point (e.g. python main.py)\n\n"

    return out


def build_tools_section(*, compact_mode: bool, step_id: str | None,
                        tools_def: list[dict]) -> str:
    """Return the tool definitions and JSON format instructions."""
    out = ""
    if compact_mode:
        out += "## Tools\n"
        for tool in tools_def:
            out += f"- {tool['name']}: {tool['description']}\n"
        out += "\nFormat: <tool_code>{\"name\": \"ToolName\", \"arguments\": {...}}</tool_code>\n"
        out += "Use \\n for newlines, \\\" for quotes in JSON strings.\n\n"
    else:
        out += "## Tools\n"
        for tool in tools_def:
            out += f"- {tool['name']}: {tool['description']} Args: {json.dumps(tool['parameters'])}\n"

        out += "\nTo use a tool, you MUST use this exact XML format with VALID JSON:\n"
        out += "<tool_code>\n"
        out += '{"name": "ToolName", "arguments": {"arg_name": "value"}}\n'
        out += "</tool_code>\n\n"
        out += "CRITICAL JSON RULES:\n"
        out += "- ALL strings use double quotes. The ENTIRE JSON must be on ONE line.\n"
        out += "- Newlines in content: use \\n (backslash-n), NEVER press Enter inside a JSON string.\n"
        out += "- Quotes in content: use \\\" (backslash-quote).\n"
        out += "- NEVER use triple quotes (\"\"\"). NEVER use single quotes.\n\n"

    # Step-appropriate WriteFile example (skip for SDD steps — step prompt has its own)
    if compact_mode:
        pass  # Example already included in compact example_block
    elif step_id and step_id in SDD_STEPS:
        pass  # SDD step prompts include their own WriteFile examples
    else:
        out += "WriteFile with multi-line content (correct):\n"
        out += "<tool_code>\n"
        out += '{"name": "WriteFile", "arguments": {"path": "main.py", "content": "import sys\\n\\ndef main():\\n    print(\\"Hello, world!\\")\\n\\nif __name__ == \\"__main__\\":\\n    main()\\n"}}\n'
        out += "</tool_code>\n\n"
        out += "EditFile to modify part of an existing file (correct):\n"
        out += "<tool_code>\n"
        out += '{"name": "EditFile", "arguments": {"path": "main.py", "old_string": "def main():\\n    print(\\"Hello, world!\\")", "new_string": "def main():\\n    print(\\"Hello, world!\\")\\n    print(\\"Starting app...\\")"}}\n'
        out += "</tool_code>\n\n"

    out += "After the tool result is provided, you will be prompted again.\n"
    return out


def build(*, os_name: str, compact_mode: bool, step_id: str | None,
          workspace_path: str, artifacts_path: str, task_details: str,
          tools_def: list[dict],
          step_for_chat: dict | None = None,
          all_steps: list | None = None,
          parent_context: dict | None = None,
          step_instructions: str = '',
          artifact_name: str = 'output.md',
          existing_files: list[str] | None = None,
          known_pitfalls: str = '') -> str:
    """Assemble the complete system prompt for a Sentinel agent turn.

    This is the single entry point that agent_service calls.
    """
    prompt = f"You are Sentinel, an AI software engineer. You are running locally on {os_name}.\n\n"

    # Thinking / example block
    example_block = build_example_block(step_id=step_id, compact_mode=compact_mode)
    prompt += build_thinking_instructions(compact_mode=compact_mode, example_block=example_block)

    # Workspace, venv, shell
    prompt += build_workspace_section(
        compact_mode=compact_mode, step_id=step_id,
        workspace_path=workspace_path, artifacts_path=artifacts_path,
        os_name=os_name,
    )

    # Task description (skip for SDD steps — the step prompt already includes it)
    if not (step_id and step_id in SDD_STEPS):
        prompt += build_task_section(task_details)

    # Plan.md protection
    prompt += build_plan_protection(compact_mode=compact_mode)

    # Step context (progress, rules, completion)
    if step_for_chat:
        prompt += build_step_context(
            step_for_chat=step_for_chat,
            all_steps=all_steps or [],
            compact_mode=compact_mode,
            parent_context=parent_context,
            step_instructions=step_instructions,
            step_id=step_id,
            artifact_name=artifact_name,
            existing_files=existing_files or [],
        )

    # Tool definitions
    prompt += build_tools_section(
        compact_mode=compact_mode, step_id=step_id,
        tools_def=tools_def,
    )

    # Known pitfalls from error memory
    # Tier 3 (critical) entries are pre-filtered by format_for_prompt to pass
    # through even in compact_mode, so we always inject if there's content.
    if known_pitfalls:
        prompt += known_pitfalls + "\n"

    return prompt
