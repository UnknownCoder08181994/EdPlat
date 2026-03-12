"""Prompt template for Implementation / dynamic steps from Planning."""

import re

from .context_wiring import build_read_before_write_rules


def build(*, artifacts_path: str, step_id: str, step_name: str,
          step_description: str, parent_name: str, parent_description: str,
          existing_files: list[str] | None = None,
          known_pitfalls: str = '',
          prior_integrity_warning: str = '',
          **_kwargs) -> str:
    """Return the full instruction string for an implementation step."""
    def fp(filename: str) -> str:
        if artifacts_path == ".":
            return filename
        return f"{artifacts_path}/{filename}"

    # For child steps, use parent description if child has none
    effective_description = step_description or ""
    if not effective_description and parent_description:
        effective_description = parent_description

    # ---------- Robust file extraction ----------
    # Accept paths like src/app.py, app/__init__.py, web/ui.tsx, assets/config.json, etc.
    FILE_EXTS = (
        "py", "md", "txt", "json", "yaml", "yml", "toml", "ini", "cfg",
        "html", "css", "js", "ts", "tsx", "csv", "xlsx"
    )

    def _dedupe_keep_order(items):
        seen = set()
        out = []
        for x in items:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out

    owned_files = []
    if effective_description:
        # 1) Match explicit "Files: a.py, b.md" lines (single or multiple)
        # Stops at newline; supports commas and "and"
        files_lines = re.findall(
            r"(?im)^\s*Files?\s*:\s*(.+?)\s*$",
            effective_description
        )
        for line in files_lines:
            # Split on commas or "and"
            parts = re.split(r"\s*,\s*|\s+\band\b\s+", line.strip())
            for p in parts:
                p = p.strip().strip("`").strip()
                if not p:
                    continue
                # Keep only things that look like file paths with known extensions
                if re.search(rf"(?i)\.({'|'.join(FILE_EXTS)})\b", p):
                    owned_files.append(p)

        # 2) Match any file-like tokens anywhere in description (fallback)
        if not owned_files:
            token_files = re.findall(
                rf"(?i)\b[A-Za-z0-9_\-./]+\.({'|'.join(FILE_EXTS)})\b",
                effective_description
            )
            # re.findall above returns only the ext due to capturing group; redo with non-capturing group:
            token_files = re.findall(
                rf"(?i)\b[A-Za-z0-9_\-./]+\.(?:{'|'.join(FILE_EXTS)})\b",
                effective_description
            )
            owned_files.extend(token_files)

        owned_files = _dedupe_keep_order([f.strip() for f in owned_files if f.strip()])

    # ---------- Extract Modifies: metadata ----------
    modifies_files = []
    if effective_description:
        mod_lines = re.findall(
            r"(?im)^\s*Modifies?\s*:\s*(.+?)\s*$",
            effective_description
        )
        for line in mod_lines:
            parts = re.split(r"\s*,\s*|\s+\band\b\s+", line.strip())
            for p in parts:
                p = p.strip().strip("`").strip()
                # Strip parenthetical notes like "(to register_blueprint)"
                p = re.sub(r"\s*\(.*?\)\s*$", "", p).strip()
                if not p:
                    continue
                if re.search(rf"(?i)\.({'|'.join(FILE_EXTS)})\b", p):
                    modifies_files.append(p)
        modifies_files = _dedupe_keep_order([f.strip() for f in modifies_files if f.strip()])

    # For child steps, strip parent prefix to get a valid filename (no "::" which has ":" invalid on Windows)
    clean_step_id = step_id.split("::")[-1] if "::" in step_id else step_id

    # ---------- Build instructions ----------
    instructions = (
        f"STOP — READ THIS FIRST: You are working on step: \"{step_name}\"\n\n"
        "BEFORE WRITING ANY CODE — STUDY THE PRE-LOADED CONTEXT:\n"
        "1) Read the EXISTING CODE FILES pre-loaded above. Know what functions, classes, and imports already exist.\n"
        "2) Read implementation-plan.md to understand THIS step's scope and how it fits the overall project.\n"
        "3) Read spec.md to understand the architecture and technology decisions.\n"
        "4) Read requirements.md to know WHAT this code must accomplish.\n"
        "Only THEN start writing code. Every file you write must integrate with existing code.\n\n"
    )

    # Context block
    if parent_name and not step_description:
        instructions += (
            f"You are implementing part of: {parent_name}\n"
            f"Parent scope:\n{effective_description}\n\n"
            f"YOUR SPECIFIC TASK: {step_name}\n"
            f"Do exactly what the step name describes. The step name IS your instruction.\n\n"
        )
    elif effective_description:
        instructions += f"Step description:\n{effective_description}\n\n"
    else:
        instructions += (
            f"YOUR TASK: {step_name}\n"
            f"Do exactly what the step name describes.\n\n"
        )

    # Prior integrity warnings from previous step (cross-step injection)
    if prior_integrity_warning:
        instructions += prior_integrity_warning

    # Owned files list (best-effort)
    if owned_files:
        instructions += "FILES YOU MUST CREATE:\n"
        for fpath in owned_files:
            instructions += f"  - {fpath}\n"
        instructions += (
            "\nNOTE: This list may be incomplete. You are still REQUIRED to save EVERY file you create or modify.\n\n"
        )

    # Files this step must edit to wire in new code
    if modifies_files:
        instructions += "FILES YOU MUST EDIT (wire new code into these):\n"
        for fpath in modifies_files:
            instructions += f"  - {fpath} — use EditFile to add imports/registrations for your new modules\n"
        instructions += (
            "\nThese files already exist. You MUST EditFile them to register/import new code you create.\n"
            "If you skip this, the new modules will be orphaned and the project will be BROKEN.\n\n"
        )

    # Continuity rules — force the model to build on existing code, not replace it
    continuity_rules = build_read_before_write_rules(existing_files or [])
    if continuity_rules:
        instructions += continuity_rules

    # Special guidance for the User Guide step
    step_name_lower = step_name.lower()
    if 'user guide' in step_name_lower or 'readme' in step_name_lower:
        instructions += (
            "AUDIENCE: COMPLETE BEGINNERS (NON-NEGOTIABLE)\n"
            "The person reading this README has NEVER used a terminal before.\n"
            "Keep it SHORT and PRACTICAL. They just want to run the project.\n"
            "STRUCTURE:\n"
            "1. One sentence: what this project does\n"
            "2. How to run it — numbered steps with EXACT commands to copy-paste:\n"
            "   - Open PowerShell (Windows) or Terminal (Mac)\n"
            "   - Navigate to the project folder\n"
            "   - Run the project (the exact command)\n"
            "3. What the output looks like when it works\n"
            "4. Usage examples with different inputs\n"
            "That's IT. No installation essays. No architecture explanations. No 'clone the repo'.\n"
            "Simple language. Short sentences. Copy-paste commands.\n\n"
        )

    # Thinking guidance
    instructions += (
        "THINKING GUIDANCE:\n"
        "Think through before coding (in your thinking, not your output):\n"
        "- What existing files and functions does this step build on?\n"
        "- What imports will your new code need from previous steps?\n"
        "- What will later steps need to import from your code?\n"
        "- Does every function signature match what callers expect?\n"
        "- Does this step's code reference config files, data files, or templates that must exist on disk?\n"
        "  If so, CREATE those files with working defaults — don't assume the user will create them.\n\n"
    )

    # Known mistakes from error memory
    if known_pitfalls:
        instructions += (
            "KNOWN MISTAKES (AVOID THESE):\n"
            f"{known_pitfalls}\n\n"
        )

    # File saving discipline (this is the core fix)
    instructions += (
        "FILE SAVE DISCIPLINE (NON-NEGOTIABLE):\n"
        "- You MUST use WriteFile for EVERY file you create or modify. No exceptions.\n"
        "- NEVER write code in a markdown code block in your response. Go STRAIGHT to a tool call.\n"
        "- Do NOT show the code first then say 'now let me save it'. The code goes INSIDE the tool call.\n"
        "- Think about what to build → call WriteFile or EditFile immediately. No intermediate code display.\n"
        "- Save IMMEDIATELY after you finish each file. Do NOT batch saves at the end.\n\n"
        "CHOOSING THE RIGHT TOOL:\n"
        "- WriteFile: Use for CREATING NEW files, or when MOST of the file needs to change.\n"
        "- EditFile: Use for MODIFYING A SMALL PART of an existing file (adding a function, fixing a bug, adding imports).\n"
        "  EditFile finds old_string in the file and replaces it with new_string. old_string must match exactly once.\n"
        "  PREFER EditFile over WriteFile when editing existing files — it's safer and preserves the rest of the file.\n\n"
        "WRITEFILE MUST ALWAYS INCLUDE:\n"
        "- 'path': a relative file path (e.g., src/app.py)\n"
        "- 'content': the full file content\n\n"
        "EDITFILE MUST ALWAYS INCLUDE:\n"
        "- 'path': the file to edit\n"
        "- 'old_string': the exact text to find (copy it from the pre-loaded code above)\n"
        "- 'new_string': the replacement text\n\n"
        "Example of CORRECT WriteFile (new file):\n"
        "<tool_code>\n"
        "{\"name\": \"WriteFile\", \"arguments\": {\"path\": \"app.py\", \"content\": \"from flask import Flask\\n\\napp = Flask(__name__)\\n\"}}\n"
        "</tool_code>\n\n"
        "Example of CORRECT EditFile (modify existing file):\n"
        "<tool_code>\n"
        "{\"name\": \"EditFile\", \"arguments\": {\"path\": \"app.py\", \"old_string\": \"app = Flask(__name__)\", \"new_string\": \"app = Flask(__name__)\\n\\n@app.route(\\'/\\')\\ndef index():\\n    return \\'Hello!\\'\"}}\n"
        "</tool_code>\n\n"
    )

    # Workflow (tight, explicit)
    instructions += (
        "BEFORE EACH ACTION — THINK (in your head, not chat):\n"
        "- What files already exist? (check the pre-loaded code above)\n"
        "- What functions/classes from existing files will this code IMPORT?\n"
        "- What functions/classes will this code EXPORT for later steps?\n"
        "- Verify every import name matches an actual definition.\n"
        "- If editing, does your old_string EXACTLY match the file? If unsure, ReadFile first.\n\n"
        "PROJECT COHESION (CRITICAL):\n"
        "You are building ONE runnable project, not isolated files.\n"
        "- Every file you create must integrate with existing files. Use imports, shared data structures, consistent naming.\n"
        "- If this step creates the entry point (main.py, app.py, cli.py), it MUST be runnable: `python main.py` should work.\n"
        "- If this step creates supporting modules, they MUST be importable from the entry point.\n"
        "- Check the pre-loaded code above — wire your new code INTO the existing project structure.\n\n"
        "WIRING CHECKLIST — after creating a new module, you MUST EditFile the entry point:\n"
        "- Flask blueprint → EditFile main.py: add `from X import X_bp` + `app.register_blueprint(X_bp)`\n"
        "- Socket.IO handlers → EditFile main.py: import and call the handler registration function\n"
        "- FastAPI router → EditFile main.py: add `app.include_router(router)`\n"
        "- Express router → EditFile app.js: add `app.use('/path', router)`\n"
        "- New utility module → EditFile the caller: add the import statement\n"
        "If the step description has a Modifies: line, you MUST EditFile those files.\n"
        "If you create a .py file but do NOT import it anywhere, the project is BROKEN.\n\n"
        "IMPORT CONSISTENCY (NON-NEGOTIABLE — #1 cause of broken projects):\n"
        "- If main.py does `from storage import save_task`, then storage.py MUST exist and define `def save_task`.\n"
        "- If you create a file that imports from another file, the imported names MUST MATCH EXACTLY.\n"
        "  WRONG: File A imports `monthly_breakdown` but file B defines `monthly_aggregate`.\n"
        "  RIGHT: File A imports `monthly_aggregate` and file B defines `monthly_aggregate`.\n"
        "- If existing code uses `from module import func_name`, your new code MUST use that exact function name.\n"
        "- FLAT LAYOUT: Keep all .py files at the project root unless the plan explicitly calls for packages.\n"
        "  Root files import each other as: `from storage import func` or `import storage`.\n"
        "- BEFORE saying [STEP_COMPLETE], mentally trace: Can `python main.py` run? Does every import resolve?\n\n"
        "API MATCHING (MUST match constructors, methods, and return types):\n"
        "- When you import a class from an existing file, check its __init__ parameters EXACTLY.\n"
        "  WRONG: Existing class has `__init__(self, config)` but your code calls `ClassName()` with no args.\n"
        "  RIGHT: Your code calls `ClassName(config=my_config)` matching the expected parameters.\n"
        "- When you call a method on an imported object, the method name must match what the class defines.\n"
        "  WRONG: Class defines `fetch_prices()` but your code calls `fetch()` or `get_prices()`.\n"
        "  RIGHT: Your code calls `fetch_prices()` exactly as defined.\n"
        "- When you access a return value, match the actual return type.\n"
        "  WRONG: Function returns a list of dicts, but your code accesses `result.attribute` (attribute access on dict).\n"
        "  RIGHT: Your code accesses `result['key']` for dict returns, `result.attribute` for object returns.\n"
        "- READ the pre-loaded existing code carefully for constructor signatures and method names before coding.\n\n"
        "WORKFLOW (FOLLOW IN ORDER):\n"
        "1) Study the pre-loaded artifacts (implementation-plan.md, spec.md, requirements.md) AND existing code files above.\n"
        "   - Existing code files from previous steps are pre-loaded above. Study them BEFORE writing anything.\n"
        "   - If a file already exists and you need to change part of it, use EditFile (not WriteFile).\n"
        "   - Only use WriteFile for creating NEW files or rewriting files where most content changes.\n"
        "2) Implement ONLY what this step requires. Do NOT add new features.\n"
        "3) As you work, IMMEDIATELY save each change:\n"
        "   - New file → WriteFile\n"
        "   - Modify existing file → EditFile (find old_string, replace with new_string)\n"
        "4) Only use RunCommand for `pip install` when genuinely needed. Do NOT run the app or tests.\n\n"
        "HARD STOP CONDITION:\n"
        "- You may NOT say [STEP_COMPLETE] until EVERY created/modified file has been persisted via WriteFile or EditFile.\n"
        "- Do NOT write a separate summary file. The system tracks file changes automatically.\n\n"
        "FINISH:\n"
        "5) Say [STEP_COMPLETE] immediately after all files are saved. Do NOT do anything else.\n"
    )

    return instructions
