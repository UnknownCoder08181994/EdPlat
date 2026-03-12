"""Handoff note generation — deterministic extraction from step artifacts.

After each SDD step (requirements, technical-specification, planning) completes,
a compact structured note (200-400 chars) is extracted from the artifact and
stored as a .handoff JSON file. The next step receives this note prepended to
the artifact content, giving it a quick summary of key decisions, scope
boundaries, and flags without re-parsing the full document.

No LLM calls — purely regex-based extraction from known artifact formats.
"""

import re


def generate_handoff_note(step_id: str, artifact_content: str) -> dict:
    """Extract a structured handoff note from a completed step artifact.

    Args:
        step_id: The step that just completed
                 ('requirements', 'technical-specification', 'planning')
        artifact_content: Full text of the artifact file

    Returns:
        dict with keys: step, decisions, scope_out, flags, complexity
        Empty dict if extraction fails.
    """
    if not artifact_content or not artifact_content.strip():
        return {}

    if step_id == 'requirements':
        return _extract_requirements_handoff(artifact_content)
    elif step_id == 'technical-specification':
        return _extract_spec_handoff(artifact_content)
    elif step_id == 'planning':
        return _extract_planning_handoff(artifact_content)
    return {}


def _extract_requirements_handoff(content: str) -> dict:
    """Extract key decisions from requirements.md."""
    note = {'step': 'requirements', 'decisions': [], 'scope_out': [], 'flags': []}

    # Extract features count (## headings that look like features)
    feature_headings = re.findall(
        r'^##\s+(?!Overview|Requirements|Features|Constraints|Out)',
        content, re.MULTILINE | re.IGNORECASE
    )
    if feature_headings:
        note['decisions'].append(f"{len(feature_headings)} features defined")

    # Extract "Out of Scope" or "Exclusions" section content
    oos_match = re.search(
        r'(?:out.of.scope|exclusion|not.included|won.t.build|non.goals?)[:\s]*\n((?:[-*]\s+.+\n?)+)',
        content, re.IGNORECASE
    )
    if oos_match:
        items = re.findall(r'[-*]\s+(.+)', oos_match.group(1))
        note['scope_out'] = [item.strip()[:60] for item in items[:4]]

    # Extract complexity from content
    complexity_match = re.search(
        r'complexity[:\s]*(simple|medium|complex|low|high)',
        content, re.IGNORECASE
    )
    if complexity_match:
        note['complexity'] = complexity_match.group(1).upper()

    # Count acceptance criteria (checkbox items)
    ac_count = len(re.findall(r'[-*]\s+\[[ x]\]', content))
    if ac_count:
        note['decisions'].append(f"{ac_count} acceptance criteria")

    # Count "Done when" items as fallback
    if not ac_count:
        done_items = len(re.findall(r'Done\s+when.*?:(.*?)(?=\n##|\Z)', content, re.DOTALL | re.IGNORECASE))
        if done_items:
            note['flags'].append(f"{done_items} completion conditions")

    return note


def _extract_spec_handoff(content: str) -> dict:
    """Extract key decisions from spec.md."""
    note = {'step': 'technical-specification', 'decisions': [], 'scope_out': [], 'flags': []}

    # Complexity
    complexity_match = re.search(r'Complexity:\s*(SIMPLE|MEDIUM|COMPLEX)', content)
    if complexity_match:
        note['complexity'] = complexity_match.group(1)

    # Technology stack (first 3 items)
    tech_section = re.search(
        r'(?:Technology Stack|Tech Stack)[^\n]*\n((?:[-*]\s+.+\n?)+)',
        content, re.IGNORECASE
    )
    if tech_section:
        # Match **bold** labels or plain text before colon/dash
        techs = re.findall(r'[-*]\s+\*\*(.+?)\*\*|[-*]\s+([A-Za-z0-9_.]+)(?:\s*[-:>])', tech_section.group(1))
        items = [t[0] or t[1] for t in techs if t[0] or t[1]]
        if items:
            note['decisions'].append(f"Stack: {', '.join(items[:3])}")

    # Architecture approach (first sentence)
    approach = re.search(
        r'(?:##\s*Approach)[^\n]*\n(.+?)(?:\n##|\Z)',
        content, re.DOTALL | re.IGNORECASE
    )
    if approach:
        first_line = approach.group(1).strip().split('\n')[0].strip()
        if len(first_line) > 15:
            note['decisions'].append(first_line[:80])

    # File count from backtick references
    file_refs = re.findall(r'`([a-zA-Z0-9_/.-]+\.\w{1,5})`', content)
    unique_files = set(f for f in file_refs if not f.startswith('http'))
    if unique_files:
        note['flags'].append(f"{len(unique_files)} files planned")

    return note


def _extract_planning_handoff(content: str) -> dict:
    """Extract key decisions from implementation-plan.md."""
    note = {'step': 'planning', 'decisions': [], 'scope_out': [], 'flags': []}

    # Count implementation steps (## headings)
    steps = re.findall(r'^##\s+', content, re.MULTILINE)
    if steps:
        note['decisions'].append(f"{len(steps)} implementation steps")

    # Extract entry point info
    entry = re.search(r'Entry\s*point:\s*YES\s*[-—]\s*(.+)', content, re.IGNORECASE)
    if entry:
        note['decisions'].append(f"Entry: {entry.group(1).strip()[:50]}")

    # Extract total file count from Files: lines
    all_files = set()
    for match in re.finditer(r'Files?:\s*(.+)', content):
        parts = re.split(r'\s*,\s*', match.group(1))
        all_files.update(p.strip().strip('`') for p in parts if '.' in p.strip().strip('`'))
    if all_files:
        note['flags'].append(f"{len(all_files)} files total")

    return note


def format_handoff_note(note: dict) -> str:
    """Format a handoff note dict into a compact string for injection into prompts.

    Target: 200-400 characters.
    """
    if not note:
        return ""

    parts = [f"HANDOFF from {note.get('step', 'unknown')}:"]

    if note.get('complexity'):
        parts.append(f"Complexity: {note['complexity']}")

    if note.get('decisions'):
        parts.append("Decisions: " + "; ".join(note['decisions']))

    if note.get('scope_out'):
        parts.append("OUT OF SCOPE: " + "; ".join(note['scope_out']))

    if note.get('flags'):
        parts.append("Flags: " + "; ".join(note['flags']))

    result = " | ".join(parts)
    return result[:400]
