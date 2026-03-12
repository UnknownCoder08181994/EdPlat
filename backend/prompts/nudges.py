"""Nudge message templates used during the agent loop.

These are injected as user messages when the agent stalls,
duplicates a write, or fails to produce the expected artifact.
"""

import re


def duplicate_write() -> str:
    """Nudge when the agent tries to save the same file twice."""
    return (
        "You already saved the file successfully. Do NOT save it again. "
        "Say [STEP_COMPLETE] now."
    )


def zero_files(*, step_description: str = '') -> str:
    """Nudge when an implementation step says STEP_COMPLETE with 0 written files."""
    file_hint = ''
    if step_description:
        files_match = re.search(r'Files?:\s*(.+)', step_description)
        if files_match:
            file_hint = f" Your step description says you need to create: {files_match.group(1).strip()}"

    return (
        f"You said [STEP_COMPLETE] but you haven't created any files with WriteFile yet.{file_hint}\n"
        f"You MUST use WriteFile to create each application file. Do NOT just write code in your response.\n"
        f"Example:\n<tool_code>\n"
        f'{{"name": "WriteFile", "arguments": {{"path": "app.py", "content": "from flask import Flask\\n\\napp = Flask(__name__)\\n"}}}}\n'
        f"</tool_code>\n"
        f"Create the files now, then say [STEP_COMPLETE] again."
    )


def missing_artifact(*, artifact_name: str) -> str:
    """Nudge when an SDD step says STEP_COMPLETE but the artifact file is missing or low quality."""
    return (
        f"You said [STEP_COMPLETE] but the artifact file '{artifact_name}' "
        f"was not found or has low quality content. You MUST use WriteFile to save "
        f"COMPLETE, REAL content to {artifact_name}. "
        f"Do NOT use '...' placeholders. Write the FULL content now:\n"
        f'<tool_code>\n'
        f'{{"name": "WriteFile", "arguments": {{"path": "{artifact_name}", '
        f'"content": "YOUR COMPLETE CONTENT HERE"}}}}\n'
        f'</tool_code>\n'
        f"Then say [STEP_COMPLETE]."
    )


def stall_sdd(*, target_file: str) -> str:
    """Nudge when an SDD step responds without a tool call."""
    return (
        f"You must save {target_file} using WriteFile. "
        f"Call WriteFile NOW with the COMPLETE content. "
        f'Format: <tool_code>\n'
        f'{{"name": "WriteFile", "arguments": {{"path": "{target_file}", '
        f'"content": "YOUR FULL CONTENT HERE"}}}}\n'
        f'</tool_code>'
    )


def stall_implementation() -> str:
    """Nudge when an implementation step responds without a tool call."""
    return (
        "You stopped without saving any files. You MUST use WriteFile to create files. "
        "Pick ONE file from the plan and create it NOW using WriteFile. "
        'Format: <tool_code>\n'
        '{"name": "WriteFile", "arguments": {"path": "filename.py", "content": "YOUR CODE"}}\n'
        '</tool_code>'
    )


def repeated_tool_failure(*, tool_name: str, path: str, fail_count: int, fuzzy_hint: str = '') -> str:
    """Nudge when the same tool keeps failing on the same file."""
    if tool_name == 'EditFile':
        hint_line = f"\nClosest match found in file: \"{fuzzy_hint}\"\n" if fuzzy_hint else ""
        return (
            f"STOP. EditFile has failed {fail_count} times on '{path}'. "
            f"Your old_string does NOT match the file content.\n{hint_line}"
            f"Do NOT retry the same approach. Instead:\n"
            f"1. Use ReadFile on '{path}' to see its ACTUAL current content.\n"
            f"2. Copy the EXACT text you want to change from the ReadFile output.\n"
            f"3. If you still can't match, use WriteFile to rewrite the entire file.\n"
            f"Do NOT call EditFile on '{path}' again until you have re-read it."
        )
    return (
        f"STOP. {tool_name} has failed {fail_count} times on '{path}'. "
        f"Your approach is not working. Try a different approach or skip this file and move on."
    )


def repeated_tool_failure_hard(*, tool_name: str, path: str, fail_count: int) -> str:
    """Hard redirect after too many repeated failures — abandon this approach."""
    return (
        f"FINAL WARNING. {tool_name} has failed {fail_count} times on '{path}'. "
        f"You MUST stop trying {tool_name} on this file. "
        f"Either use WriteFile to rewrite '{path}' completely, "
        f"or move on to the next file in your plan. Do NOT retry {tool_name} on '{path}'."
    )


# ── Agent Confusion Guardrail Nudges ─────────────────────────────


def code_in_prose(*, language: str = 'python') -> str:
    """Nudge when the agent dumps code blocks in prose instead of using WriteFile."""
    return (
        f"STOP. You are writing {language} code directly in your response instead of using WriteFile. "
        f"Code in your response does NOT save to disk. You MUST use WriteFile to create files.\n"
        f'<tool_code>\n'
        f'{{"name": "WriteFile", "arguments": {{"path": "FILENAME_HERE", "content": "YOUR CODE HERE"}}}}\n'
        f'</tool_code>\n'
        f"Put your code inside WriteFile NOW."
    )


def repetitive_response(*, turn: int) -> str:
    """Nudge when the agent is generating the same response repeatedly."""
    return (
        f"STOP. You are repeating yourself (turn {turn}). "
        f"Your previous responses are almost identical. Do NOT repeat the same text. "
        f"Either:\n"
        f"1. Use a TOOL (WriteFile, ReadFile, EditFile) to make progress.\n"
        f"2. Say [STEP_COMPLETE] if you are finished.\n"
        f"Do something DIFFERENT now."
    )


def runaway_response(*, char_count: int) -> str:
    """Nudge when the agent generates an extremely long response without tool calls."""
    return (
        f"STOP. Your response is {char_count:,} characters with no tool calls. "
        f"You are writing content directly instead of using tools. "
        f"If you need to create a file, use WriteFile. "
        f"If you are done, say [STEP_COMPLETE]. "
        f"Do NOT continue writing prose."
    )


def wrong_step_write(*, step_id: str, path: str, allowed_pattern: str) -> str:
    """Nudge when the agent writes to a file that doesn't belong to this step."""
    return (
        f"BLOCKED: You tried to write '{path}' but this step ({step_id}) "
        f"should only write to {allowed_pattern}. "
        f"Focus on the files assigned to YOUR step. "
        f"If you believe this file is necessary, use the correct file name for your step."
    )


def hallucinated_tool(*, tool_name: str) -> str:
    """Nudge when the agent calls a tool that doesn't exist."""
    return (
        f"Error: '{tool_name}' is not a valid tool. Available tools are: "
        f"WriteFile, ReadFile, EditFile, ListFiles, Glob, RunCommand. "
        f"Use one of these tools instead."
    )


def corrupted_args(*, tool_name: str, issue: str) -> str:
    """Nudge when the agent produces corrupted tool arguments."""
    return (
        f"Error: Your {tool_name} call has invalid arguments: {issue}. "
        f"Fix the arguments and try again. "
        f"Required format:\n"
        f'<tool_code>\n'
        f'{{"name": "{tool_name}", "arguments": {{...}}}}\n'
        f'</tool_code>'
    )


# ── Step Completion Wiring Safeguard Nudges ──────────────────────


def integrity_check_failed(*, issues: list) -> str:
    """Nudge when project integrity check finds issues at step completion."""
    issue_list = '\n'.join(f"  - {issue}" for issue in issues[:5])
    more = f"\n  ...and {len(issues) - 5} more issues" if len(issues) > 5 else ""
    return (
        f"STOP. Your code has integrity issues that must be fixed before this step can complete:\n"
        f"{issue_list}{more}\n\n"
        f"Fix these issues using EditFile or WriteFile, then say [STEP_COMPLETE] again."
    )


def import_smoke_failed(*, failures: list) -> str:
    """Nudge when python import test fails on step's owned files.

    Args:
        failures: list of (file_path, error_message) tuples
    """
    failure_lines = '\n'.join(
        f"  - {path}: {error}" for path, error in failures
    )
    return (
        f"STOP. These files cannot be imported by Python:\n"
        f"{failure_lines}\n\n"
        f"Common causes: missing dependency in requirements.txt, "
        f"importing from a module that doesn't exist, circular imports, "
        f"or referencing a name that wasn't defined.\n"
        f"Fix the import errors using EditFile, then say [STEP_COMPLETE] again."
    )


def modifies_not_edited(*, missing_files: list, step_name: str = '') -> str:
    """Nudge when Modifies: files were not actually edited by the step."""
    file_list = ', '.join(missing_files)
    return (
        f"STOP. Your step description says you must modify: {file_list}\n"
        f"But you did NOT edit {'these files' if len(missing_files) > 1 else 'this file'}. "
        f"New modules are ORPHANED if you don't wire them into the existing project.\n"
        f"Use EditFile to add imports/registrations in {file_list}, "
        f"then say [STEP_COMPLETE] again."
    )


def missing_files(*, written: list, expected: list, remaining: list) -> str:
    """Nudge when the agent says STEP_COMPLETE but hasn't written all files from its Files: list."""
    written_str = ', '.join(written) if written else '(none)'
    remaining_str = ', '.join(remaining)
    return (
        f"STOP. You said [STEP_COMPLETE] but you only wrote {len(written)}/{len(expected)} files.\n"
        f"Written so far: {written_str}\n"
        f"STILL MISSING: {remaining_str}\n\n"
        f"You MUST create the missing files using WriteFile before this step can complete.\n"
        f"Create {remaining[0]} NOW:\n"
        f'<tool_code>\n'
        f'{{"name": "WriteFile", "arguments": {{"path": "{remaining[0]}", '
        f'"content": "YOUR COMPLETE CONTENT HERE"}}}}\n'
        f'</tool_code>\n'
        f"Then create any other missing files, and say [STEP_COMPLETE] again."
    )


def depends_on_not_wired(*, dep_modules: list, step_name: str = '') -> str:
    """Nudge when step depends on modules but doesn't import from them."""
    mod_list = ', '.join(dep_modules)
    return (
        f"WARNING: Your step depends on {mod_list} but none of your files import from "
        f"{'them' if len(dep_modules) > 1 else 'it'}. "
        f"If your code uses functionality from {mod_list}, add the missing imports. "
        f"If you genuinely don't need to import from {'them' if len(dep_modules) > 1 else 'it'}, "
        f"say [STEP_COMPLETE] again to confirm."
    )
