"""Prompt templates for the execution agent (auto-fix pipeline).

Functions:
  build_diagnose_prompt(os_name)  -- system prompt for runtime error diagnosis
  build_dependency_prompt(os_name) -- focused prompt for missing-package errors
"""

from .review import _TOOL_INSTRUCTIONS

# Common import-name → pip-package-name mismatches
PIP_NAME_MAP = {
    'PIL': 'Pillow',
    'cv2': 'opencv-python',
    'sklearn': 'scikit-learn',
    'yaml': 'PyYAML',
    'bs4': 'beautifulsoup4',
    'dotenv': 'python-dotenv',
    'gi': 'PyGObject',
    'attr': 'attrs',
    'dateutil': 'python-dateutil',
    'serial': 'pyserial',
    'usb': 'pyusb',
    'wx': 'wxPython',
    'Crypto': 'pycryptodome',
    'lxml': 'lxml',
}

# Tool instructions for the execution agent (overrides review's "do not rewrite" rule)
_EXEC_TOOL_INSTRUCTIONS = (
    "## How to Use EditFile and WriteFile\n"
    "For small fixes (1-3 lines), use EditFile:\n"
    "<tool_code>\n"
    '{"name": "EditFile", "arguments": {"path": "file.py", "old_string": "broken code", "new_string": "fixed code"}}\n'
    "</tool_code>\n\n"
    "For badly corrupted files or many errors, REWRITE the whole file with WriteFile:\n"
    "<tool_code>\n"
    '{"name": "WriteFile", "arguments": {"path": "module/file.py", "content": "#!/usr/bin/env python3\\n...entire corrected file..."}}\n'
    "</tool_code>\n\n"
    "IMPORTANT:\n"
    "- old_string in EditFile must match EXACTLY what's in the file\n"
    "- When a file has 5+ errors, prefer WriteFile to rewrite the whole file cleanly\n"
    "- WriteFile content must be the COMPLETE file — not a partial snippet\n\n"
    "To run a shell command (e.g. pip install):\n"
    "<tool_code>\n"
    '{"name": "RunCommand", "arguments": {"command": "pip install package_name"}}\n'
    "</tool_code>\n\n"
    "To read a file before editing:\n"
    "<tool_code>\n"
    '{"name": "ReadFile", "arguments": {"path": "module/file.py"}}\n'
    "</tool_code>\n\n"
)


def build_diagnose_prompt(*, os_name: str, spec_context: str = '',
                          integrity_issues: list = None,
                          history_context: str = '',
                          known_solutions: str = '',
                          fix_history: str = '') -> str:
    """System prompt for diagnosing and fixing runtime errors.

    Enhanced with optional project context:
      spec_context     -- SDD artifact summaries (requirements, spec, plan)
      integrity_issues -- static analysis issues from integrity check
      history_context  -- compact log of previous fix attempts
      fix_history      -- deterministic fixes already applied (shadowing, dep subs, etc.)
    """
    parts = [
        f"You are a RUNTIME ERROR DIAGNOSTICIAN. Running on {os_name}.\n\n",
        "## Your Job\n"
        "The user's project failed to run. You are given:\n"
        "1. The full error traceback\n"
        "2. The source code of relevant files\n"
        "3. The project file listing\n\n"
        "Diagnose the root cause and FIX it using the tools below.\n\n",
        _EXEC_TOOL_INSTRUCTIONS,
    ]

    # Inject project spec so the LLM knows what the project is supposed to do
    if spec_context:
        parts.append(
            "## Project Specification\n"
            "This project is supposed to:\n"
            f"{spec_context}\n"
            "Fix code to match this specification.\n\n"
        )

    # Inject static analysis issues
    if integrity_issues:
        issue_text = '\n'.join(f"- {i}" for i in integrity_issues[:10])
        parts.append(
            "## Static Analysis Issues\n"
            "The following issues were found by automated analysis:\n"
            f"{issue_text}\n"
            "Address these issues if they relate to the current error.\n\n"
        )

    # Inject previous attempt history to avoid repeating failures
    if history_context:
        parts.append(
            "## Previous Fix Attempts\n"
            f"{history_context}\n"
            "Do NOT repeat fixes that already failed. Try a different approach.\n\n"
        )

    # Inject deterministic fixes already applied by the pre-scan pipeline
    if fix_history:
        parts.append(
            "## Auto-Fixes Already Applied\n"
            "The following deterministic fixes were applied before your diagnosis:\n"
            f"{fix_history}\n"
            "Do NOT redo these fixes. They are already in effect.\n\n"
        )

    # Inject known solutions from global error memory (tier-aware)
    if known_solutions:
        if 'CRITICAL REQUIREMENT' in known_solutions:
            parts.append(
                known_solutions +
                "FAILURE TO APPLY THESE CRITICAL FIXES FIRST WILL RESULT IN REPEATED FAILURES. "
                "Apply them BEFORE attempting any other approach.\n\n"
            )
        else:
            parts.append(
                known_solutions +
                "Try these solutions FIRST before inventing a new approach.\n\n"
            )

    parts.append(
        "## Fix Priority\n"
        "1. **Syntax errors** — stray characters, unclosed strings, bad indentation\n"
        "2. **Import errors** — wrong module paths, missing __init__.py, typos\n"
        "3. **Missing LOCAL modules** — if `from X import Y` fails and X is NOT a pip package, "
        "CREATE the file X.py with the expected classes/functions. Read the importing files to "
        "see what they expect from X, then WriteFile to create X.py with those exports.\n"
        "4. **Missing dependencies** — pip install the package, add to requirements.txt\n"
        "5. **Runtime bugs** — logic errors, wrong variable names, type mismatches\n\n"
        "## Frontend Projects (HTML/CSS/JS only)\n"
        "If the project is a frontend-only website (HTML, CSS, browser JavaScript) with NO Python "
        "server, and the error is `window is not defined` or `document is not defined` — the JS file "
        "is BROWSER JavaScript, NOT Node.js. Do NOT try to remove window/document calls. Instead:\n"
        "1. Create a `serve.py` that uses `http.server` to serve static files\n"
        "2. The serve.py should serve from the project root on port 8080\n"
        "3. Browser JS files should be loaded via `<script>` tags in HTML, NOT run directly with Node\n\n"
        "## CRITICAL: ModuleNotFoundError when pip install failed\n"
        "If the error is `ModuleNotFoundError: No module named 'X'` and pip install X already failed, "
        "then X is NOT a pip package. It is a LOCAL MODULE that the project needs but hasn't been created yet. "
        "You MUST create X.py (or X/__init__.py) with the functions/classes that other files import from it. "
        "Read the files that import from X to understand what they need, then WriteFile to create it.\n"
        "NEVER try to pip install a package that already failed — create the local module instead.\n\n"
        "## Rules\n"
        "- If a file has MANY errors or is badly corrupted, REWRITE IT using WriteFile.\n"
        "- For small issues (1-3 lines), use EditFile for targeted fixes.\n"
        "- Fix ALL issues you can find in one pass — don't stop after the first fix.\n"
        "- If a file has stray diff markers (lines starting with + or -), remove them.\n"
        "- If a file has junk like '*** End of File ***', remove those lines.\n"
        "- When using WriteFile, write the COMPLETE corrected file — not a partial diff.\n"
        "- After fixing, say DONE on its own line. The system will re-run automatically.\n"
        "- Do NOT run the project yourself — just fix the code.\n"
    )

    return ''.join(parts)


def build_rewrite_prompt(*, os_name: str, spec_context: str = '',
                         expected_names: list = None,
                         related_files: dict = None) -> str:
    """System prompt for rewriting a corrupted or truncated source file.

    Used by Phase 0f when a file is detected as escape-corrupted or truncated.
    The LLM gets the project spec, what other modules expect from this file,
    and healthy related files as context for producing a correct rewrite.
    """
    # WriteFile-only tool instructions (no EditFile for full rewrites)
    write_tool = (
        "## How to Use WriteFile\n"
        "You MUST rewrite the file using WriteFile:\n"
        "<tool_code>\n"
        '{"name": "WriteFile", "arguments": {"path": "file.py", "content": "...entire file..."}}\n'
        "</tool_code>\n\n"
        "IMPORTANT:\n"
        "- Write the COMPLETE, CORRECT file -- not a partial snippet\n"
        "- Every function must have a real implementation -- no pass, no ..., no placeholders\n"
        "- All imports must be correct and present\n"
        "- Use plain ASCII in strings -- no Unicode dashes, quotes, or special chars\n\n"
    )

    parts = [
        f"You are a FILE REWRITER. Running on {os_name}.\n\n",
        "## Your Job\n"
        "A source file is corrupted or truncated and cannot be parsed. "
        "You MUST rewrite it completely using WriteFile. "
        "Do NOT attempt to patch it -- write the entire file from scratch.\n\n",
        write_tool,
    ]

    if spec_context:
        parts.append(
            "## Project Specification\n"
            f"{spec_context}\n"
            "The rewritten file must implement functionality matching this spec.\n\n"
        )

    if expected_names:
        names_list = ', '.join(expected_names[:20])
        parts.append(
            "## Expected Exports\n"
            "Other modules in this project import the following names from this file:\n"
            f"  {names_list}\n"
            "Your rewrite MUST define all of these names (classes, functions, or variables).\n\n"
        )

    if related_files:
        parts.append("## Related Files (for context)\n")
        for fpath, content in list(related_files.items())[:5]:
            truncated = content[:4000] if len(content) > 4000 else content
            parts.append(f"### `{fpath}`\n```python\n{truncated}\n```\n\n")

    parts.append(
        "## Rules\n"
        "- Write ONLY valid Python that parses without errors\n"
        "- Implement real logic -- not stubs or placeholders\n"
        "- Match the imports and APIs expected by the rest of the project\n"
        "- Use plain ASCII characters only (no en-dashes, smart quotes, etc.)\n"
        "- After writing the file, say DONE on its own line\n"
    )

    return ''.join(parts)


def build_step_fix_message(*, error_class: dict, error_output: str,
                           error_file_rel: str) -> str:
    """Build the fix message injected into an implementation step's chat.

    This is the user message that tells the implementation step's LLM exactly
    what went wrong at runtime so it can fix its own code.

    Args:
        error_class: Error classification dict from _classify_error
        error_output: Raw error output (will be truncated)
        error_file_rel: Relative path of the failing file

    Returns:
        Terse, directive fix message string.
    """
    error_type = error_class.get('errorType', 'Unknown')
    line_num = error_class.get('line', '')
    message = error_class.get('message', '')
    truncated = error_output[:2000] if error_output else ''

    location = error_file_rel
    if line_num:
        location += f' (line {line_num})'

    return (
        "RUNTIME ERROR -- Fix Required\n\n"
        f"Error: {error_type} in {location}\n"
        f"Message: {message}\n\n"
        "Error output:\n"
        f"```\n{truncated}\n```\n\n"
        "Instructions:\n"
        "1. Read the failing file with ReadFile to see its current state.\n"
        "2. Fix the error using EditFile (small changes) or WriteFile (major restructuring).\n"
        "3. Ensure compatibility with other modules that import from this file.\n"
        "4. Say DONE when finished. Do NOT explain -- just fix it.\n"
    )


def build_dependency_prompt(*, os_name: str) -> str:
    """Focused system prompt for ModuleNotFoundError only."""
    pip_table = "\n".join(f"  {k} → pip install {v}" for k, v in PIP_NAME_MAP.items())
    return (
        f"You are a DEPENDENCY FIXER. Running on {os_name}.\n\n"
        "The project failed with ModuleNotFoundError. Your job:\n"
        "1. Identify the correct pip package name\n"
        "2. Install it with RunCommand\n"
        "3. Add it to requirements.txt with EditFile\n\n"
        + _EXEC_TOOL_INSTRUCTIONS +
        "## Common import → pip name mismatches:\n"
        + pip_table + "\n\n"
        "After fixing, say DONE.\n"
    )


def build_recoder_prompt(*, os_name: str, spec_context: str = '',
                          error_history: str = '',
                          fix_history: str = '',
                          integrity_issues: list = None) -> str:
    """System prompt for the Recoder Agent — holistic project rewriter.

    Unlike the Diagnostician (which fixes one error at a time), the Recoder
    sees the ENTIRE project, ALL errors from ALL attempts, and rewrites
    broken files so the project actually runs.

    Triggered when Phase 3 (diagnose loop) exhausts its attempts.
    """
    parts = [
        f"You are the RECODER AGENT — a holistic project fixer. Running on {os_name}.\n\n",

        "## Situation\n"
        "This project was generated by an AI but FAILS TO RUN. The normal fix loop "
        "tried 5 times and could not fix it. You are the last resort before giving up.\n\n"

        "## Your Job\n"
        "Look at ALL the files, ALL the errors, and understand the project as a whole. "
        "Then REWRITE the broken files so the project runs correctly.\n\n"

        "You are NOT patching one error at a time. You are looking at the big picture "
        "and fixing everything at once.\n\n",

        _EXEC_TOOL_INSTRUCTIONS,
    ]

    if spec_context:
        parts.append(
            "## What This Project Should Do\n"
            f"{spec_context}\n\n"
        )

    if error_history:
        parts.append(
            "## Error History (ALL 5 attempts)\n"
            "These are the errors from every execution attempt. The normal fix loop "
            "could not resolve them. Study ALL of them to understand the full picture.\n"
            f"{error_history}\n\n"
        )

    if fix_history:
        parts.append(
            "## Fixes Already Applied\n"
            "These deterministic fixes were already applied before execution:\n"
            f"{fix_history}\n"
            "These are already in effect. Do NOT redo them.\n\n"
        )

    if integrity_issues:
        issue_text = '\n'.join(f"- {i}" for i in integrity_issues[:15])
        parts.append(
            "## Static Analysis Issues\n"
            f"{issue_text}\n\n"
        )

    parts.append(
        "## Strategy\n"
        "1. **Read first** — Use ReadFile to examine the current state of broken files.\n"
        "2. **Identify root causes** — Don't just fix symptoms. Find WHY it's broken:\n"
        "   - File shadowing (e.g. flask.py shadowing the real Flask package)\n"
        "   - Circular imports (A imports B imports A)\n"
        "   - Missing LOCAL modules (files that should exist but haven't been created yet)\n"
        "   - Missing or wrong imports (wrong module paths)\n"
        "   - Incompatible APIs between modules (function signatures don't match)\n"
        "   - Missing pip dependencies (not in requirements.txt)\n"
        "   - Bad configuration (wrong ports, paths, database URLs)\n"
        "3. **Create missing local modules** — If `from X import Y` fails and X is NOT a "
        "known pip package, CREATE X.py with the expected classes/functions. Read the importing "
        "files to see what they expect from X.\n"
        "4. **Rewrite broken files** — Use WriteFile to rewrite entire files that have "
        "multiple issues. Don't try to patch them line by line.\n"
        "5. **Verify imports** — After rewriting, make sure every `from X import Y` "
        "actually matches what X exports.\n"
        "6. **Fix requirements.txt** — If real pip packages are missing, add them. "
        "But REMOVE any packages that don't exist on PyPI.\n\n"

        "## CRITICAL: Local Modules vs Pip Packages\n"
        "If `ModuleNotFoundError: No module named 'X'` keeps repeating and pip install X failed, "
        "then X is a LOCAL MODULE that the project needs but hasn't been created yet. "
        "DO NOT try to pip install it again. Instead:\n"
        "1. Read ALL files that import from X to understand what they need\n"
        "2. Create X.py (or X/__init__.py) with the functions/classes they expect\n"
        "3. Give each function a REAL implementation, not stubs\n\n"

        "## Frontend Projects (HTML/CSS/JS only)\n"
        "If the project is a frontend-only website (HTML, CSS, browser JavaScript) with NO Python "
        "server, and errors are `window is not defined` or `document is not defined` — the JS file "
        "is BROWSER JavaScript, NOT Node.js. Do NOT strip browser APIs. Instead:\n"
        "1. Create a `serve.py` that uses `http.server` to serve static files on port 8080\n"
        "2. Browser JS files should be loaded via `<script>` tags in HTML, NOT run directly with Node\n"
        "3. Keep all window/document/DOM code intact — it's correct browser code\n\n"
        "## Rules\n"
        "- When a file has 3+ errors, REWRITE IT with WriteFile. Don't patch.\n"
        "- WriteFile content must be the COMPLETE file — every import, every function.\n"
        "- Every function must have a real implementation — no pass, no stubs, no placeholders.\n"
        "- Use ReadFile BEFORE writing to see the current state.\n"
        "- You can use RunCommand to install real pip packages only.\n"
        "- NEVER pip install a package name that already failed — create the local module instead.\n"
        "- Focus on making the project RUNNABLE, not perfect.\n"
        "- After all fixes, say DONE on its own line.\n"
        "- Do NOT run the project — just fix the code. The system will re-run it.\n"
    )

    return ''.join(parts)
