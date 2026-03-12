"""Prompt fragment for continuity between implementation steps.

The 3B model treats each implementation sub-step as isolated work.
It does not read existing workspace files before writing its own.
This causes each step to overwrite the previous step's output with
a fresh, disconnected version.

This module provides:
  1. build_code_context()  — formats existing code files into a prompt
     block that gets pre-seeded into the conversation, so the model
     SEES the current codebase before it writes anything.
  2. build_read_before_write_rules() — hard rules injected into the
     implementation prompt forcing the model to build ON TOP of
     existing code, not replace it.
  3. extract_relevant_criteria() — cross-references step description
     with requirements.md to find acceptance criteria for THIS step.
  4. build_completion_ledger() — compact summary of what prior
     implementation steps produced (files, line counts).
"""

import os
import re
import json as _json

# File extensions to treat as "code files" worth seeding
CODE_EXTENSIONS = {
    '.py', '.js', '.ts', '.tsx', '.jsx', '.css', '.html',
    '.json', '.yaml', '.yml', '.toml', '.ini', '.cfg',
    '.sh', '.bat', '.sql', '.csv',
}

# Max characters per individual file when seeding (prevent blowing context)
# With EditFile, the model doesn't need to reproduce entire files — it just
# needs enough context to find the right old_string to match. So we can
# afford to show more of each file.
MAX_FILE_CHARS = 3000

# Priority files (from Depends-on/Modifies) get more context room
MAX_FILE_CHARS_PRIORITY = 4000
MAX_FILE_CHARS_REGULAR = 2000

# Max total characters for all code files combined
MAX_TOTAL_CHARS = 10000


def build_code_context(file_contents: dict[str, str],
                       priority_files: list[str] | None = None) -> str:
    """Format existing workspace code files into a readable context block.

    Args:
        file_contents: dict mapping relative file paths to their content.
                       e.g. {"main.py": "import argparse\\n...", "core.py": "def create..."}
        priority_files: Optional list of file paths to show first with higher
                       char limit. These are files from Depends-on:/Modifies: metadata.

    Returns:
        A formatted string showing all existing code, ready to inject as a
        seeded user message. Returns empty string if no files.
    """
    if not file_contents:
        return ""

    parts = [
        "Here are the EXISTING CODE FILES in the workspace that previous steps have already created.",
        "You MUST build on top of this code. Do NOT rewrite these files from scratch.",
        "When you need to modify an existing file, use EditFile to make targeted changes instead of rewriting the whole file with WriteFile.",
        ""
    ]

    # Build normalized set of priority file names for matching
    normalized_priority = set()
    if priority_files:
        for pf in priority_files:
            normalized_priority.add(pf.replace('\\', '/'))
            normalized_priority.add(pf.replace('/', '\\'))
            normalized_priority.add(os.path.basename(pf))

    # Partition into priority and regular files
    priority_items = []
    regular_items = []
    for filepath, content in sorted(file_contents.items()):
        norm_path = filepath.replace('\\', '/')
        basename = os.path.basename(filepath)
        if normalized_priority and (norm_path in normalized_priority or basename in normalized_priority):
            priority_items.append((filepath, content))
        else:
            regular_items.append((filepath, content))

    total_chars = 0

    # Show priority files first with higher limit
    if priority_items:
        parts.append("=== FILES THIS STEP DEPENDS ON (read carefully) ===")
        for filepath, content in priority_items:
            if total_chars >= MAX_TOTAL_CHARS:
                parts.append(f"\n--- {filepath} ---")
                parts.append("(skipped — context budget reached)")
                continue
            truncated = content[:MAX_FILE_CHARS_PRIORITY]
            if len(content) > MAX_FILE_CHARS_PRIORITY:
                truncated += "\n...(truncated)"
            parts.append(f"\n--- {filepath} ---")
            parts.append(truncated)
            total_chars += len(truncated)
        parts.append("\n=== OTHER PROJECT FILES ===")

    # Show regular files with standard (or reduced) limit
    for filepath, content in regular_items:
        if total_chars >= MAX_TOTAL_CHARS:
            parts.append(f"\n--- {filepath} ---")
            parts.append("(skipped — context budget reached)")
            continue
        limit = MAX_FILE_CHARS_REGULAR if priority_items else MAX_FILE_CHARS
        truncated = content[:limit]
        if len(content) > limit:
            truncated += "\n...(truncated)"
        parts.append(f"\n--- {filepath} ---")
        parts.append(truncated)
        total_chars += len(truncated)

    return "\n".join(parts)


def build_read_before_write_rules(existing_files: list[str]) -> str:
    """Return hard rules that force the model to integrate with existing code.

    These rules are injected into the implementation prompt BEFORE the
    workflow steps, so the model sees them early.

    Args:
        existing_files: list of relative file paths that already exist.
                        e.g. ["main.py", "core.py"]

    Returns:
        A prompt fragment with continuity rules. Empty string if no files exist.
    """
    if not existing_files:
        return ""

    file_list = "\n".join(f"  - {f}" for f in sorted(existing_files))

    return (
        "CONTINUITY RULES (CRITICAL — READ CAREFULLY):\n"
        "Previous steps have ALREADY created these files:\n"
        f"{file_list}\n\n"
        "You are NOT starting from scratch. You are CONTINUING the work.\n"
        "Rules:\n"
        "- The code from previous steps has been pre-loaded above. READ IT CAREFULLY.\n"
        "- PREFER EditFile over WriteFile when modifying existing files.\n"
        "  EditFile lets you change a specific part of a file without rewriting everything.\n"
        "  Just specify old_string (the exact text to find) and new_string (what to replace it with).\n"
        "- Only use WriteFile for existing files when MOST of the content needs to change.\n"
        "- Do NOT rewrite a file from scratch unless the existing code is fundamentally wrong.\n"
        "- Do NOT duplicate code that already exists (e.g., do not add argparse twice).\n"
        "- If core.py already has function stubs, use EditFile to FILL IN the function bodies with real logic.\n"
        "- Import from existing modules instead of redefining functions.\n\n"
        "THINK BEFORE YOU EDIT:\n"
        "Before each EditFile or WriteFile, ask yourself:\n"
        '  "Does this file already exist? If yes, I should use EditFile to change just the part I need."\n'
        '  "What exact text do I need to find? I can copy it from the pre-loaded code above."\n'
        '  "Does another file already define this function/class? Should I import instead?"\n\n'
    )


def extract_relevant_criteria(step_description: str, requirements_content: str) -> str:
    """Extract acceptance criteria from requirements.md relevant to this step.

    Cross-references the step's Files: list and description keywords against
    requirements.md section headings and content. Returns a focused block
    of only the criteria relevant to this step.

    Args:
        step_description: The full step description (includes Files:, Modifies:, etc.)
        requirements_content: Full text of requirements.md

    Returns:
        Formatted string of relevant criteria, or empty string if none found.
        Target: 200-600 chars.
    """
    if not step_description or not requirements_content:
        return ""

    # Extract keywords from step description
    files_match = re.search(r'Files?:\s*(.+)', step_description)
    file_names = set()
    if files_match:
        parts = re.split(r'\s*,\s*', files_match.group(1))
        for p in parts:
            name = p.strip().strip('`')
            if '.' in name:
                file_names.add(name.lower())
                # Also add the stem (e.g., "cli_script" from "cli_script.py")
                stem = name.rsplit('.', 1)[0].rsplit('/', 1)[-1]
                file_names.add(stem.lower())

    # Extract key terms from description (nouns/verbs, excluding boilerplate)
    STOP_WORDS = {'the', 'and', 'for', 'this', 'that', 'with', 'from', 'step',
                  'create', 'build', 'add', 'set', 'use', 'file', 'files',
                  'notes', 'depends', 'modifies', 'entry', 'point', 'none',
                  'new', 'will', 'each', 'all', 'into', 'also', 'should'}
    words = re.findall(r'\b[a-zA-Z]{3,}\b', step_description.lower())
    keywords = {w for w in words if w not in STOP_WORDS}
    keywords.update(file_names)

    if not keywords:
        return ""

    # Parse requirements.md into sections (split on ## headings)
    sections = re.split(r'(?=^##\s+)', requirements_content, flags=re.MULTILINE)

    relevant_criteria = []
    for section in sections:
        if not section.strip():
            continue
        section_lower = section.lower()

        # Score how many keywords match this section
        matches = sum(1 for kw in keywords if kw in section_lower)
        if matches >= 2:  # At least 2 keyword matches
            # Extract acceptance criteria (checkbox items or bullet items)
            criteria = re.findall(r'[-*]\s+\[[ x]\]\s+(.+)', section)
            if not criteria:
                # Try plain bullet items under "Done when" or "Acceptance"
                criteria = re.findall(r'[-*]\s+(.{15,})', section)
            if criteria:
                heading = section.split('\n')[0].strip()
                relevant_criteria.append((heading, criteria, matches))

    if not relevant_criteria:
        return ""

    # Sort by relevance (match count) and take top sections
    relevant_criteria.sort(key=lambda x: x[2], reverse=True)

    parts = ["RELEVANT ACCEPTANCE CRITERIA FOR THIS STEP:"]
    char_count = 0
    for heading, criteria, _score in relevant_criteria[:3]:
        section_text = f"\n{heading}\n"
        for c in criteria[:5]:  # Max 5 criteria per section
            line = f"  - [ ] {c}\n"
            if char_count + len(section_text) + len(line) > 600:
                break
            section_text += line
        parts.append(section_text)
        char_count += len(section_text)
        if char_count > 500:
            break

    return ''.join(parts)


def build_completion_ledger(all_steps: list, current_step_id: str,
                            task_id: str, chats_dir: str) -> str:
    """Build a compact completion ledger showing what each prior step produced.

    Reads structured summary data from completed steps' chat JSON files.

    Format:
    COMPLETED STEPS:
      1. Build CLI Script -> cli_script.py (new, 85 lines)
      2. Setting Up Environment -> requirements.txt (new, 3 lines)
    [CURRENT] 3. Writing Unit Tests
      4. Creating User Guide [pending]

    Args:
        all_steps: List of all steps (may contain children nested)
        current_step_id: ID of the currently executing step
        task_id: Task ID for loading chat data
        chats_dir: Path to the chats directory

    Returns:
        Formatted ledger string. Target: 300-800 chars.
        Empty string if no implementation steps exist.
    """
    # Flatten steps (root + children)
    flat = []
    for s in all_steps:
        flat.append(s)
        for child in s.get('children', []):
            flat.append(child)

    # Skip SDD steps — only show implementation steps
    SDD_IDS = {'requirements', 'technical-specification', 'planning', 'implementation'}

    lines = ["COMPLETED STEPS:"]
    step_num = 0
    found_current = False

    for step in flat:
        sid = step.get('id', '')
        if sid in SDD_IDS:
            continue

        step_num += 1
        name = step.get('name', sid)
        status = step.get('status', 'pending')

        if sid == current_step_id:
            lines.append(f"[CURRENT] {step_num}. {name}")
            found_current = True
            continue

        if found_current:
            # Steps after current — show as pending
            lines.append(f"  {step_num}. {name} [pending]")
            continue

        if status in ('completed', 'done'):
            # Try to extract file list from chat's structured summary
            file_info = _extract_step_files(step, task_id, chats_dir)
            if file_info:
                lines.append(f"  {step_num}. {name} -> {file_info}")
            else:
                lines.append(f"  {step_num}. {name} [done]")
        elif status == 'failed':
            lines.append(f"  {step_num}. {name} [FAILED]")
        else:
            lines.append(f"  {step_num}. {name} [pending]")

    if step_num == 0:
        return ""

    return '\n'.join(lines)


def _extract_step_files(step: dict, task_id: str, chats_dir: str) -> str:
    """Extract file list from a completed step's chat summary message.

    Returns compact string like: "cli.py (new, 85 lines), utils.py (+15 -3)"
    """
    chat_id = step.get('chatId')
    if not chat_id:
        return ""

    chat_path = os.path.join(chats_dir, task_id, f"{chat_id}.json")
    if not os.path.exists(chat_path):
        return ""

    try:
        with open(chat_path, 'r', encoding='utf-8') as f:
            chat = _json.load(f)
    except Exception:
        return ""

    # Find the summary message (has is_summary=True and structured data)
    for msg in reversed(chat.get('messages', [])):
        if msg.get('is_summary') and msg.get('structured'):
            structured = msg['structured']
            files = structured.get('files', [])
            if files:
                parts = []
                for fd in files[:4]:  # Limit to 4 files for space
                    name = fd.get('name', '')
                    if fd.get('isNew'):
                        added = fd.get('added', 0)
                        parts.append(f"{name} (new, {added} lines)")
                    else:
                        added = fd.get('added', 0)
                        removed = fd.get('removed', 0)
                        parts.append(f"{name} (+{added} -{removed})")
                if len(files) > 4:
                    parts.append(f"+{len(files) - 4} more")
                return ', '.join(parts)
    return ""
