import os
import re
import glob
import json
import time
import fnmatch
import subprocess

from services.error_memory import ErrorMemory

# Junk lines commonly left by review agent / bad diffs
_JUNK_LINE_RE = re.compile(
    r'^\*\*\* End of File \*\*\*$'
    r'|^<<<<<<< '
    r'|^=======$'
    r'|^>>>>>>> '
    r'|^diff --git '
    r'|^index [0-9a-f]'
    r'|^@@ .* @@'
)


class ToolService:
    def __init__(self, root_path, current_step_id=None, workspace_path=None, excluded_tools=None):
        self.root_path = os.path.abspath(root_path)
        self.current_step_id = current_step_id
        # workspace_path is the actual workspace root where .venv lives.
        # Falls back to root_path if not specified (e.g. files.py route, implementation steps).
        self.workspace_path = os.path.abspath(workspace_path) if workspace_path else self.root_path
        self.excluded_tools = excluded_tools or set()

    # ── Corrective write-time fixes ──────────────────────────
    _write_corrections_cache = None
    _write_corrections_ts = 0
    _CACHE_TTL = 60  # seconds

    # SDD artifacts should never be auto-corrected
    _SDD_ARTIFACTS = {'requirements.md', 'tech-spec.md', 'implementation-plan.md'}

    @classmethod
    def _load_write_corrections(cls):
        """Load on-write corrective rules from error memory, cached 60s."""
        now = time.time()
        if cls._write_corrections_cache is not None and (now - cls._write_corrections_ts) < cls._CACHE_TTL:
            return cls._write_corrections_cache

        cls._write_corrections_cache = ErrorMemory.get_corrective_fixes(on_write=True)
        cls._write_corrections_ts = now
        return cls._write_corrections_cache

    @staticmethod
    def _apply_write_corrections(content, filename):
        """Apply all matching on-write corrections to file content.

        Returns: (corrected_content, list_of_correction_descriptions)
        Skips SDD artifact files.
        """
        corrections = []

        # Skip SDD artifacts
        if filename.lower() in ToolService._SDD_ARTIFACTS:
            return content, corrections

        all_fixes = ToolService._load_write_corrections()

        for entry, af in all_fixes:
            pattern = af.get('file_pattern', '')
            if not fnmatch.fnmatch(filename, pattern):
                continue

            fix_type = af.get('type', '')
            find_pat = af.get('find', '')
            if not find_pat:
                continue

            original = content

            try:
                if fix_type == 'regex_replace':
                    replace_map = af.get('replace_map')
                    if replace_map:
                        # Per-character replacement using the map
                        def _char_replacer(m):
                            ch = m.group(0)
                            return replace_map.get(ch, ch)
                        content = re.sub(find_pat, _char_replacer, content)
                    else:
                        replace_str = af.get('replace', '')
                        content = re.sub(find_pat, replace_str, content)

                elif fix_type == 'line_remove':
                    line_re = re.compile(find_pat)
                    lines = content.splitlines(True)
                    content = ''.join(line for line in lines if not line_re.match(line.strip()))

            except re.error:
                continue  # invalid regex -- skip silently

            if content != original:
                desc = af.get('description', 'Auto-fix applied')
                corrections.append(desc)
                # Record success back to bandit
                try:
                    ErrorMemory.record_auto_fix(entry.get('id', ''), success=True)
                except Exception:
                    pass

        return content, corrections

    def _validate_path(self, path):
        # Allow paths starting with / if they resolve within root_path
        # But mostly expect relative paths
        if not path:
             return self.root_path

        if os.path.isabs(path):
            abs_path = os.path.abspath(path)
        else:
            abs_path = os.path.abspath(os.path.join(self.root_path, path))

        # Use os.sep suffix to prevent sibling-prefix escapes
        # e.g., root_path="C:\repo\root" must NOT accept "C:\repo\root2\..."
        if not (abs_path == self.root_path or abs_path.startswith(self.root_path + os.sep)):
            raise ValueError(f"Access denied: Path must be within the root directory ({self.root_path})")
        return abs_path

    def _get_relative_path(self, abs_path):
        return os.path.relpath(abs_path, self.root_path)

    @staticmethod
    def _strip_diff_markers(content):
        """Strip stray unified-diff markers (+/-) and junk lines from content.

        The LLM sometimes outputs file content in diff format instead of clean
        source code.  This runs at write-time so corrupted files never reach disk.

        Heuristic: a line starting with + or - is a diff marker if the character
        after it is a space, tab, letter, hash, or common code punctuation.
        This avoids false-positives on legitimate code like ``x = -1`` (the minus
        is mid-line) or ``+= 1`` (the + is an operator, not column 0).
        """
        lines = content.split('\n')
        cleaned = []
        changed = False
        for line in lines:
            stripped = line.rstrip('\r')

            # Drop junk lines entirely
            if stripped and _JUNK_LINE_RE.match(stripped):
                changed = True
                continue

            # Not a candidate
            if not stripped or stripped[0] not in ('+', '-'):
                cleaned.append(line)
                continue

            # Standalone + or - on a line → empty line
            if len(stripped) == 1:
                cleaned.append('')
                changed = True
                continue

            rest = stripped[1:]
            # Skip diff headers like +++ or ---
            if rest.startswith('++') or rest.startswith('--'):
                cleaned.append(line)
                continue

            # Diff marker heuristic: followed by space/tab/letter/hash/code-punct
            if rest[0] in (' ', '\t', '#', '@', '(', ')', '[', ']', '{', '}', '"', "'") or rest[0].isalpha():
                cleaned.append(rest)
                changed = True
            else:
                cleaned.append(line)

        return '\n'.join(cleaned) if changed else content

    def list_files(self, path="."):
        try:
            target_path = self._validate_path(path)
            if not os.path.exists(target_path):
                return f"Error: Path not found: {path}"

            items = []
            for item in os.listdir(target_path):
                # Ignore common garbage
                if item in ['.git', '__pycache__', 'node_modules', '.DS_Store', '.venv', 'venv', '.sentinel']:
                    continue

                full_path = os.path.join(target_path, item)
                is_dir = os.path.isdir(full_path)
                items.append(f"{item}{'/' if is_dir else ''}")

            if not items:
                return "(empty directory)"
            return "\n".join(sorted(items))
        except Exception as e:
            return f"Error listing files: {str(e)}"

    _MAX_READ_SIZE = 500_000  # 500KB max per file read (prevents OOM on huge files)

    def read_file(self, path):
        try:
            target_path = self._validate_path(path)
            if not os.path.isfile(target_path):
                # List available files so the model can self-correct
                available = []
                try:
                    for f in os.listdir(self.root_path):
                        if os.path.isfile(os.path.join(self.root_path, f)):
                            available.append(f)
                except OSError:
                    pass
                hint = ""
                if available:
                    hint = f" Available files: {', '.join(sorted(available)[:15])}"
                return f"Error: File not found: {path}.{hint} Remember: task details and prior artifacts are already in your system prompt — do NOT try to read them again."

            # Check file size before reading to prevent OOM
            try:
                file_size = os.path.getsize(target_path)
                if file_size > self._MAX_READ_SIZE:
                    return f"Error: File too large ({file_size} bytes, max {self._MAX_READ_SIZE}). Use RunCommand with 'head' or 'tail' to read portions."
            except OSError:
                pass

            with open(target_path, 'r', encoding='utf-8') as f:
                content = f.read(self._MAX_READ_SIZE + 1)
            if len(content) > self._MAX_READ_SIZE:
                content = content[:self._MAX_READ_SIZE] + '\n\n...(truncated)'
            return content
        except UnicodeDecodeError:
            return "Error: File appears to be binary."
        except Exception as e:
            return f"Error reading file: {str(e)}"

    # SDD steps can only write markdown artifacts — prevents the 3B model
    # from creating app.py, run_flask.sh, etc. during Requirements/Spec/Planning.
    SDD_STEPS = {'requirements', 'technical-specification', 'planning'}
    SDD_ALLOWED_FILES = {
        'requirements': {'requirements.md'},
        'technical-specification': {'spec.md'},
        'planning': {'implementation-plan.md', 'plan.md'},
    }

    _MAX_FILE_SIZE = 500_000  # 500KB max per file write

    def write_file(self, path, content):
        try:
            # Guard: reject None/missing content
            if content is None:
                return "Error: No content provided for WriteFile."

            # Guard: cap file size to prevent OOM / disk abuse
            if len(content) > self._MAX_FILE_SIZE:
                return f"Error: File content too large ({len(content)} chars, max {self._MAX_FILE_SIZE}). Split into smaller files."

            target_path = self._validate_path(path)
            # Protect plan.md from agent overwrite — Planning step can edit it, others cannot
            rel = os.path.relpath(target_path, self.root_path).replace("\\", "/")
            if rel == "plan.md" or (rel.endswith("plan.md") and ".sentinel/" in rel):
                if self.current_step_id != 'planning':
                    return "Error: Cannot overwrite plan.md — it is managed by the system. Save your output to a different file (e.g., requirements.md, spec.md, implementation-plan.md)."

            # Protect SDD artifacts from implementation overwrites.
            # Implementation steps should NEVER overwrite requirements.md, spec.md,
            # or implementation-plan.md — those are specification artifacts produced
            # by SDD steps and must be preserved.
            PROTECTED_ARTIFACTS = {'requirements.md', 'spec.md', 'implementation-plan.md'}
            if self.current_step_id and self.current_step_id not in self.SDD_STEPS:
                basename = os.path.basename(target_path)
                if basename in PROTECTED_ARTIFACTS and '.sentinel' in rel:
                    return (
                        f"Error: Cannot overwrite {basename} — it is a specification artifact. "
                        f"Implementation steps should only write project code files."
                    )

            # SDD steps: only allow the expected artifact file
            if self.current_step_id and self.current_step_id in self.SDD_STEPS:
                basename = os.path.basename(target_path)
                allowed = self.SDD_ALLOWED_FILES.get(self.current_step_id, set())
                if basename not in allowed:
                    expected = ', '.join(sorted(allowed))
                    return (
                        f"ERROR: WRITE REJECTED. The file '{basename}' is NOT allowed in the '{self.current_step_id}' step. "
                        f"You can ONLY write: {expected}. "
                        f"DO NOT retry writing '{basename}'. Instead, write your output to {expected} and say [STEP_COMPLETE]."
                    )

            # Text-file post-processing (skip binary files)
            BINARY_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.ico', '.woff', '.woff2',
                           '.ttf', '.eot', '.pdf', '.zip', '.tar', '.gz', '.db', '.sqlite'}
            ext = os.path.splitext(target_path)[1].lower()
            if ext not in BINARY_EXTS:
                # For MARKDOWN files only: unescape literal \n and \t sequences.
                # Markdown never legitimately contains literal \n (unlike Python/JS
                # source code). These sequences appear when content arrives via
                # narration rescue or triple-quote fallback paths that skip json.loads.
                # Source code files (.py, .js, etc.) must NOT be unescaped — their
                # \n sequences are legitimate string literals.
                MARKDOWN_EXTS = {'.md', '.markdown', '.txt', '.rst'}
                if ext in MARKDOWN_EXTS:
                    content = content.replace('\\n', '\n')
                    content = content.replace('\\t', '\t')

                # Fix mojibake: LLM outputs UTF-8 bytes misinterpreted as latin-1.
                # Repair sequences like \u00e2\u0080\u0093 → proper ASCII equivalents.
                import re as _re
                def _fix_mojibake(m):
                    try:
                        raw = m.group(0).encode('latin-1').decode('utf-8')
                        _to_ascii = {
                            '\u2011': '-', '\u2010': '-',
                            '\u2013': '-', '\u2014': '--',
                            '\u2018': "'", '\u2019': "'",
                            '\u201c': '"', '\u201d': '"',
                            '\u2026': '...', '\u00a0': ' ', '\u2022': '-',
                        }
                        return _to_ascii.get(raw, raw)
                    except (UnicodeDecodeError, UnicodeEncodeError):
                        return '-'
                content = _re.sub(r'[\u00c0-\u00ef][\u0080-\u00bf]{1,2}', _fix_mojibake, content)

                # Strip stray diff markers from source code files.
                # The LLM sometimes writes content in unified-diff format (+/-
                # prefixed lines) instead of clean source. Clean it at write time
                # so downstream tools never see corrupted files.
                SOURCE_EXTS = {'.py', '.js', '.ts', '.jsx', '.tsx', '.css', '.html',
                               '.json', '.yaml', '.yml', '.toml', '.cfg', '.ini',
                               '.sh', '.bat', '.ps1', '.rb', '.go', '.rs', '.java',
                               '.c', '.cpp', '.h', '.hpp', '.cs', '.swift', '.kt'}
                if ext in SOURCE_EXTS or ext in MARKDOWN_EXTS:
                    content = self._strip_diff_markers(content)

            # Apply error-memory auto-corrections (e.g. Unicode -> ASCII)
            corrections = []
            try:
                content, corrections = ToolService._apply_write_corrections(
                    content, os.path.basename(target_path))
            except Exception:
                pass  # never break writes due to correction failure

            # Read existing file content for diff stats before overwriting
            is_new = not os.path.isfile(target_path)
            old_lines = 0
            if not is_new:
                try:
                    with open(target_path, 'r', encoding='utf-8') as f:
                        old_lines = len(f.readlines())
                except Exception:
                    old_lines = 0

            os.makedirs(os.path.dirname(target_path), exist_ok=True)

            with open(target_path, 'w', encoding='utf-8') as f:
                f.write(content)

            new_lines = len(content.splitlines()) if content else 0
            if is_new:
                added, removed = new_lines, 0
            else:
                # Simple heuristic: lines gained = added, lines lost = removed
                added = max(0, new_lines - old_lines)
                removed = max(0, old_lines - new_lines)
                # If both old and new exist but same count, at least 1 line changed
                if added == 0 and removed == 0 and old_lines > 0:
                    added = 1
                    removed = 1

            meta = f"[meta:is_new={is_new},added={added},removed={removed}]"
            if corrections:
                meta += f"[auto-fixed: {'; '.join(corrections[:3])}]"
            return f"Successfully wrote to {path} {meta}"
        except Exception as e:
            return f"Error writing file: {str(e)}"

    def edit_file(self, path, old_string, new_string):
        """Make a targeted edit to an existing file using string matching.

        Finds old_string in the file and replaces it with new_string.
        The old_string must match exactly once — if not found or found
        multiple times, returns an error so the model can retry.
        """
        try:
            target_path = self._validate_path(path)
            rel = os.path.relpath(target_path, self.root_path).replace("\\", "/")

            # Same protections as write_file
            if rel == "plan.md" or (rel.endswith("plan.md") and ".sentinel/" in rel):
                if self.current_step_id != 'planning':
                    return "Error: Cannot edit plan.md — it is managed by the system."

            PROTECTED_ARTIFACTS = {'requirements.md', 'spec.md', 'implementation-plan.md'}
            if self.current_step_id and self.current_step_id not in self.SDD_STEPS:
                basename = os.path.basename(target_path)
                if basename in PROTECTED_ARTIFACTS and '.sentinel' in rel:
                    return (
                        f"Error: Cannot edit {basename} — it is a specification artifact. "
                        f"Implementation steps should only modify project code files."
                    )

            # File must exist
            if not os.path.isfile(target_path):
                return f"Error: File not found: {path}. Use WriteFile to create new files."

            # Read existing content
            with open(target_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Fix double-escaped newlines in the search/replace strings
            # Only unescape for markdown/text files — source code legitimately
            # contains literal \n sequences (e.g. Python "\\n" strings).
            # Matches the WriteFile gating added 2026-02-16.
            MARKDOWN_EXTS = {'.md', '.markdown', '.txt', '.rst'}
            ext = os.path.splitext(target_path)[1].lower()
            if ext in MARKDOWN_EXTS:
                old_string = old_string.replace('\\n', '\n').replace('\\t', '\t')
                new_string = new_string.replace('\\n', '\n').replace('\\t', '\t')

            # Count occurrences
            count = content.count(old_string)
            if count == 0:
                # Try a more lenient match: strip trailing whitespace from each line
                # in both old_string and content to handle whitespace mismatches
                stripped_old = '\n'.join(line.rstrip() for line in old_string.split('\n'))
                stripped_content = '\n'.join(line.rstrip() for line in content.split('\n'))
                stripped_count = stripped_content.count(stripped_old)
                if stripped_count == 1:
                    # Found with whitespace-lenient match — find the actual position
                    # by matching line-by-line
                    old_lines = old_string.split('\n')
                    content_lines = content.split('\n')
                    for i in range(len(content_lines) - len(old_lines) + 1):
                        match = True
                        for j, old_line in enumerate(old_lines):
                            if content_lines[i + j].rstrip() != old_line.rstrip():
                                match = False
                                break
                        if match:
                            # Replace these lines
                            new_lines = content_lines[:i] + new_string.split('\n') + content_lines[i + len(old_lines):]
                            content = '\n'.join(new_lines)
                            count = 1  # Signal success
                            break
                    if count == 0:
                        return (
                            f"Error: old_string not found in {path}. "
                            f"Make sure you copy the exact text from the file. "
                            f"Use ReadFile to check the current file contents."
                        )
                else:
                    return (
                        f"Error: old_string not found in {path}. "
                        f"Make sure you copy the exact text from the file. "
                        f"Use ReadFile to check the current file contents."
                    )
            elif count > 1:
                return (
                    f"Error: old_string matches {count} locations in {path}. "
                    f"Include more surrounding context in old_string to make it unique."
                )
            else:
                # Exact single match — do the replacement
                content = content.replace(old_string, new_string, 1)

            # Calculate diff stats
            old_line_count = len(old_string.splitlines()) if old_string else 0
            new_line_count = len(new_string.splitlines()) if new_string else 0
            added = max(0, new_line_count - old_line_count)
            removed = max(0, old_line_count - new_line_count)
            if added == 0 and removed == 0:
                added = 1
                removed = 1

            # Write back
            with open(target_path, 'w', encoding='utf-8') as f:
                f.write(content)

            return f"Successfully edited {path} [meta:is_new=False,added={added},removed={removed}]"
        except Exception as e:
            return f"Error editing file: {str(e)}"

    def run_glob(self, pattern):
        try:
            # glob in python doesn't support ** recursively nicely from a base dir unless python 3.10+ with root_dir
            # or we manually walk.
            # Let's use glob with recursive=True

            # Construct search path
            search_path = os.path.join(self.root_path, pattern) if not os.path.isabs(pattern) else pattern

            # Security check is harder with wildcards, so we filter results
            results = []
            # We'll use os.walk and fnmatch for safer relative matching
            for root, dirs, files in os.walk(self.root_path):
                # cleanup ignored dirs
                for ignore in ['.git', 'node_modules', '__pycache__', 'dist', 'build', '.venv', 'venv', '.sentinel']:
                    if ignore in dirs:
                        dirs.remove(ignore)

                rel_root = os.path.relpath(root, self.root_path)
                if rel_root == ".": rel_root = ""

                for name in files:
                    rel_path = os.path.join(rel_root, name).replace("\\", "/")
                    if fnmatch.fnmatch(rel_path, pattern):
                        results.append(rel_path)

            return "\n".join(sorted(results))
        except Exception as e:
            return f"Error running glob: {str(e)}"

    # Commands that should NEVER be run by the agent (destructive / security risk)
    _BLOCKED_CMD_RE = re.compile(
        r'(?:^|\s*(?:&&|\|\||;)\s*)'           # start or after chain operators
        r'(?:'
        r'rm\s+-(?:\w*r\w*f|f\w*r)\s+/'        # rm -rf / (root)
        r'|rmdir\s+/s\b'                        # Windows rmdir /s
        r'|del\s+/(?:s|q)\b'                    # Windows del /s or /q
        r'|format\s+[a-z]:'                     # format C:
        r'|mkfs\b'                              # mkfs
        r'|dd\s+if='                            # dd
        r'|curl\s.*\|\s*(?:sh|bash)\b'          # curl | sh
        r'|wget\s.*\|\s*(?:sh|bash)\b'          # wget | sh
        r'|powershell\s.*-enc'                  # encoded powershell
        r'|shutdown\b|reboot\b'                 # shutdown/reboot
        r'|reg\s+(?:delete|add)\b'              # registry edits
        r'|net\s+(?:user|localgroup)\b'         # user/group management
        r'|chmod\s+777\b'                       # overly permissive chmod
        r')',
        re.IGNORECASE
    )
    _MAX_CMD_LEN = 2000  # Prevent absurdly long commands
    _MAX_OUTPUT_LEN = 50000  # Cap output to prevent OOM

    def run_command(self, command, cwd=None):
        try:
            # Validate command is not empty or too long
            if not command or not command.strip():
                return "Error: No command provided."
            if len(command) > self._MAX_CMD_LEN:
                return f"Error: Command too long ({len(command)} chars, max {self._MAX_CMD_LEN})."

            # Block dangerous commands
            if self._BLOCKED_CMD_RE.search(command):
                return "Error: Command blocked for safety. Destructive or system-level commands are not allowed."

            # Validate cwd if provided
            if cwd:
                working_dir = self._validate_path(cwd)
            else:
                working_dir = self.root_path

            # Prepare environment with workspace venv on PATH so the agent
            # can just type `pip install flask` or `python app.py` and it
            # automatically uses the workspace venv
            env = os.environ.copy()
            venv_scripts = os.path.join(self.workspace_path, '.venv', 'Scripts')
            if os.path.isdir(venv_scripts):
                env['PATH'] = venv_scripts + os.pathsep + env.get('PATH', '')
                env['VIRTUAL_ENV'] = os.path.join(self.workspace_path, '.venv')

            result = subprocess.run(
                command,
                shell=True,
                cwd=working_dir,
                capture_output=True,
                text=True,
                timeout=120,
                env=env
            )

            output = result.stdout
            if result.stderr:
                output += "\nSTDERR:\n" + result.stderr

            if not output:
                output = "(Command executed with no output)"

            # Cap output size to prevent OOM
            if len(output) > self._MAX_OUTPUT_LEN:
                output = output[:self._MAX_OUTPUT_LEN] + f"\n\n...(truncated at {self._MAX_OUTPUT_LEN} chars)"

            return output
        except subprocess.TimeoutExpired:
            return "Error: Command timed out after 120 seconds."
        except Exception as e:
            return f"Error running command: {str(e)}"

    def get_tool_definitions(self, exclude=None):
        exclude = exclude or set()
        all_tools = [
            {
                "name": "ListFiles",
                "description": "List files in a directory. Path is relative to project root.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "The directory path (default: .)"}
                    }
                }
            },
            {
                "name": "ReadFile",
                "description": "Read the contents of a file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "The file path"}
                    },
                    "required": ["path"]
                }
            },
            {
                "name": "WriteFile",
                "description": "Write content to a file. Overwrites existing files.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "The file path"},
                        "content": {"type": "string", "description": "The content to write"}
                    },
                    "required": ["path", "content"]
                }
            },
            {
                "name": "EditFile",
                "description": "Make a targeted edit to an existing file. Finds old_string in the file and replaces it with new_string. The old_string must match exactly once. Use this instead of WriteFile when you only need to change part of a file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "The file path"},
                        "old_string": {"type": "string", "description": "The exact text to find and replace"},
                        "new_string": {"type": "string", "description": "The replacement text"}
                    },
                    "required": ["path", "old_string", "new_string"]
                }
            },
            {
                "name": "Glob",
                "description": "Find files matching a glob pattern (e.g., **/*.py).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "The glob pattern"}
                    },
                    "required": ["pattern"]
                }
            },
            {
                "name": "RunCommand",
                "description": "Run a shell command in the project directory.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "The command to execute"},
                        "cwd": {"type": "string", "description": "Optional relative path to run command in"}
                    },
                    "required": ["command"]
                }
            }
        ]
        return [t for t in all_tools if t['name'] not in exclude]

    def execute_tool(self, name, args):
        # Guard: ensure args is a dict (LLM may produce malformed JSON)
        if not isinstance(args, dict):
            return f"Error: Tool arguments must be a JSON object, got {type(args).__name__}"
        if name in self.excluded_tools:
            return f"Error: Tool '{name}' is not available in this step. Use file tools (ListFiles, ReadFile, WriteFile, Glob) instead."
        try:
            if name == "ListFiles":
                return self.list_files(args.get("path", "."))
            elif name == "ReadFile":
                return self.read_file(args.get("path"))
            elif name == "WriteFile":
                return self.write_file(args.get("path"), args.get("content"))
            elif name == "EditFile":
                return self.edit_file(args.get("path"), args.get("old_string", ""), args.get("new_string", ""))
            elif name == "Glob":
                return self.run_glob(args.get("pattern"))
            elif name == "RunCommand":
                return self.run_command(args.get("command"), args.get("cwd"))
            else:
                return f"Error: Unknown tool {name}"
        except Exception as e:
            return f"Error executing {name}: {str(e)}"
