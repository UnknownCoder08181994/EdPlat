"""Real-time micro-agents that assist the main agent loop.

These fire deterministically during the agent loop — after file writes,
between turns, at step start, and at step completion. They provide
instant feedback that the LLM agent would otherwise only discover
after execution failures.

Micro-agents:
  1. SyntaxSentinel     — AST-parse .py files after every write
  2. ImportResolver     — Validate cross-module imports after writes
  3. SignatureIndex     — Build function/class manifest at step start
  4. DownstreamScanner  — Extract what future steps need from this step
  5. ProgressTracker    — Track completion % vs expected files
  6. PatternMatcher     — Enforce tech stack conventions
  7. CircularImportDetector — Detect import cycles in real time
  8. DeadReferenceWatchdog  — Detect broken references after edits
  9. ContextBudgetOptimizer — Smart history compression
 10. TestRunnerScout    — Run tests after step completion
"""

import os
import re
import ast
import subprocess
import sys

from utils.logging import _safe_log


# ═══════════════════════════════════════════════════════════════════
# 1. SYNTAX SENTINEL
# ═══════════════════════════════════════════════════════════════════

def syntax_check(file_path):
    """Run ast.parse on a Python file. Returns error string or None.

    Called after every successful WriteFile/EditFile on a .py file.
    Appended to the tool result so the LLM sees the error immediately.
    """
    if not file_path.endswith('.py'):
        return None
    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            source = f.read()
        ast.parse(source, filename=os.path.basename(file_path))
        return None  # No syntax error
    except SyntaxError as e:
        return (
            f"\n⚠ SYNTAX ERROR in {os.path.basename(file_path)} "
            f"line {e.lineno}: {e.msg}"
        )
    except Exception:
        return None  # Don't block on unexpected errors


# ═══════════════════════════════════════════════════════════════════
# 2. IMPORT RESOLVER
# ═══════════════════════════════════════════════════════════════════

def resolve_imports(file_path, workspace_path):
    """Check if a Python file's imports resolve within the workspace.

    Returns a list of warning strings, or empty list if all good.
    Called after every successful WriteFile/EditFile on a .py file.
    """
    if not file_path.endswith('.py'):
        return []

    warnings = []
    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            source = f.read()
        tree = ast.parse(source)
    except (SyntaxError, Exception):
        return []  # Syntax sentinel handles parse errors

    # Collect all local module files in workspace (including subdirectories)
    local_modules = {}  # module_name (dotted) → set of defined names
    SKIP = {'.git', '__pycache__', 'node_modules', '.venv', 'venv', '.sentinel'}
    try:
        for root, dirs, files in os.walk(workspace_path):
            dirs[:] = [d for d in dirs if d not in SKIP]
            for fname in files:
                if fname.endswith('.py'):
                    mod_path = os.path.join(root, fname)
                    # Build dotted module name: services/tool_service.py → services.tool_service
                    rel = os.path.relpath(mod_path, workspace_path)
                    mod_name = rel.replace(os.sep, '.').replace('/', '.')[:-3]  # strip .py
                    # Also register the bare filename (e.g. "tool_service") for simple imports
                    bare_name = fname[:-3]
                    try:
                        with open(mod_path, 'r', encoding='utf-8', errors='replace') as mf:
                            mod_tree = ast.parse(mf.read())
                        names = set()
                        for node in ast.iter_child_nodes(mod_tree):
                            if isinstance(node, ast.FunctionDef):
                                names.add(node.name)
                            elif isinstance(node, ast.AsyncFunctionDef):
                                names.add(node.name)
                            elif isinstance(node, ast.ClassDef):
                                names.add(node.name)
                            elif isinstance(node, ast.Assign):
                                for t in node.targets:
                                    if isinstance(t, ast.Name):
                                        names.add(t.id)
                        local_modules[mod_name] = names
                        # Also register bare name if not already taken
                        if bare_name not in local_modules:
                            local_modules[bare_name] = names
                    except Exception:
                        local_modules[mod_name] = set()
    except Exception:
        return []

    # Python standard library modules (subset — covers common ones)
    STDLIB = {
        '__future__', 'abc', 'argparse', 'ast', 'asyncio', 'base64',
        'collections', 'contextlib', 'copy', 'csv', 'dataclasses',
        'datetime', 'decimal', 'email', 'enum', 'functools', 'glob',
        'hashlib', 'hmac', 'html', 'http', 'importlib', 'inspect',
        'io', 'itertools', 'json', 'logging', 'math', 'multiprocessing',
        'operator', 'os', 'pathlib', 'pickle', 'platform', 'pprint',
        're', 'secrets', 'shutil', 'signal', 'smtplib', 'socket',
        'sqlite3', 'ssl', 'string', 'struct', 'subprocess', 'sys',
        'tempfile', 'textwrap', 'threading', 'time', 'traceback',
        'typing', 'unittest', 'urllib', 'uuid', 'warnings', 'xml',
        'zipfile', 'random',
    }

    current_module = os.path.basename(file_path)[:-3]

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            # from X import Y, Z
            top_module = node.module.split('.')[0]
            if top_module in STDLIB or top_module == current_module:
                continue
            if top_module in local_modules:
                # Check if imported names exist in the module
                for alias in (node.names or []):
                    name = alias.name
                    if name == '*':
                        continue
                    if name not in local_modules[top_module]:
                        # Search other modules for the name
                        found_in = [m for m, names in local_modules.items()
                                    if name in names and m != current_module]
                        if found_in:
                            warnings.append(
                                f"⚠ '{name}' not found in {top_module}.py — "
                                f"did you mean 'from {found_in[0]} import {name}'?"
                            )
                        else:
                            warnings.append(
                                f"⚠ '{name}' not defined in {top_module}.py"
                            )
            # If top_module not in local_modules and not stdlib, it's a third-party
            # package — skip (handled by pip install)

    return warnings[:3]  # Cap at 3 warnings per file


# ═══════════════════════════════════════════════════════════════════
# 3. SIGNATURE INDEX BUILDER
# ═══════════════════════════════════════════════════════════════════

def build_signature_index(workspace_path):
    """Scan workspace .py files and build a compact function/class index.

    Returns a formatted string like:
        === API INDEX ===
        main.py: create_app() → Flask, run_server(port: int)
        models.py: class User(db.Model), class Post(db.Model)
        utils.py: validate_email(email: str) → bool

    Called once at step start, refreshed after file writes.
    """
    SKIP = {'.git', '__pycache__', 'node_modules', '.venv', 'venv', '.sentinel'}
    index = {}

    try:
        all_py_files = []
        for root, dirs, files in os.walk(workspace_path):
            dirs[:] = sorted(d for d in dirs if d not in SKIP)
            for fname in sorted(files):
                if fname.endswith('.py'):
                    all_py_files.append(os.path.join(root, fname))

        for fpath in all_py_files:
            if not os.path.isfile(fpath):
                continue
            # Use relative path as key so subdirectory files are identifiable
            rel_path = os.path.relpath(fpath, workspace_path).replace(os.sep, '/')
            fname = os.path.basename(fpath)

            try:
                with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                    source = f.read(50_000)  # Cap per file
                tree = ast.parse(source)
            except Exception:
                continue

            entries = []
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    args = []
                    for arg in node.args.args:
                        ann = ''
                        if arg.annotation:
                            ann = f': {ast.unparse(arg.annotation)}'
                        args.append(f'{arg.arg}{ann}')
                    ret = ''
                    if node.returns:
                        ret = f' → {ast.unparse(node.returns)}'
                    entries.append(f'{node.name}({", ".join(args)}){ret}')
                elif isinstance(node, ast.ClassDef):
                    bases = ', '.join(ast.unparse(b) for b in node.bases) if node.bases else ''
                    base_str = f'({bases})' if bases else ''
                    # Get class methods
                    methods = []
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            if not item.name.startswith('_') or item.name == '__init__':
                                m_args = []
                                for arg in item.args.args:
                                    if arg.arg == 'self':
                                        continue
                                    ann = ''
                                    if arg.annotation:
                                        ann = f': {ast.unparse(arg.annotation)}'
                                    m_args.append(f'{arg.arg}{ann}')
                                methods.append(f'{item.name}({", ".join(m_args)})')
                    method_str = f' [{", ".join(methods[:5])}]' if methods else ''
                    entries.append(f'class {node.name}{base_str}{method_str}')

            if entries:
                index[rel_path] = entries

    except Exception:
        return ''

    if not index:
        return ''

    parts = ['=== API INDEX (functions & classes in workspace) ===']
    for file_key, entries in index.items():
        parts.append(f'{file_key}: {"; ".join(entries[:8])}')
    parts.append('=== END API INDEX ===')
    return '\n'.join(parts)


# ═══════════════════════════════════════════════════════════════════
# 4. DOWNSTREAM DEPENDENCY SCANNER
# ═══════════════════════════════════════════════════════════════════

def scan_downstream_dependencies(current_step_id, all_steps, written_files_so_far=None):
    """Find what future steps expect from files THIS step creates.

    Scans all remaining (pending) step descriptions for Depends-on:/Modifies:
    references to files in this step's Files: list.

    Returns a formatted string for injection into the system prompt.
    """
    if not all_steps or not current_step_id:
        return ''

    # Find current step and its owned files
    current_step = None
    current_idx = -1
    for i, step in enumerate(all_steps):
        if step.get('id') == current_step_id:
            current_step = step
            current_idx = i
            break

    if not current_step:
        return ''

    current_files = set()
    desc = current_step.get('description', '')
    files_match = re.findall(r'(?im)^\s*Files?\s*:\s*(.+)', desc)
    for line in files_match:
        parts = re.split(r'\s*,\s*|\s+and\s+', line.strip())
        for p in parts:
            p = p.strip().strip('`').strip()
            if p and '.' in p:
                current_files.add(p)
                current_files.add(os.path.basename(p))

    if not current_files:
        return ''

    # Scan future steps for references to our files
    downstream_refs = []
    for step in all_steps[current_idx + 1:]:
        if step.get('status') == 'completed':
            continue
        step_desc = step.get('description', '')
        step_name = step.get('name', step.get('id', ''))
        # Look for Depends-on: or Modifies: references
        dep_lines = re.findall(r'(?im)^\s*(?:Depends[- ]on|Modifies|Imports?)\s*:\s*(.+)', step_desc)
        for dep_line in dep_lines:
            for our_file in current_files:
                if our_file in dep_line:
                    # Extract what they import
                    import_match = re.search(
                        rf'{re.escape(our_file)}\s*\(([^)]+)\)',
                        dep_line
                    )
                    detail = f' ({import_match.group(1)})' if import_match else ''
                    downstream_refs.append(
                        f'  Step "{step_name}" depends on {our_file}{detail}'
                    )

    if not downstream_refs:
        return ''

    return (
        '\n=== DOWNSTREAM DEPENDENCIES ===\n'
        'Future steps will import from files you create. Ensure these exist:\n'
        + '\n'.join(downstream_refs[:10])
        + '\n=== END DOWNSTREAM ===\n'
    )


# ═══════════════════════════════════════════════════════════════════
# 5. PROGRESS TRACKER
# ═══════════════════════════════════════════════════════════════════

def track_progress(step_description, written_files):
    """Compare written files against the step's expected Files: list.

    Returns (percentage: int, remaining: list[str], message: str).
    """
    if not step_description:
        return 0, [], ''

    # Extract expected files from step description
    expected = []
    files_match = re.findall(r'(?im)^\s*Files?\s*:\s*(.+)', step_description)
    for line in files_match:
        parts = re.split(r'\s*,\s*|\s+and\s+', line.strip())
        for p in parts:
            p = p.strip().strip('`').strip()
            if p and '.' in p:
                expected.append(p)

    if not expected:
        return 0, [], ''

    # Check which expected files have been written
    written_basenames = {os.path.basename(w) for w in (written_files or {})}
    done = []
    remaining = []
    for ef in expected:
        ef_base = os.path.basename(ef)
        if ef_base in written_basenames or ef in written_files:
            done.append(ef)
        else:
            remaining.append(ef)

    if not expected:
        return 100, [], ''

    pct = int(100 * len(done) / len(expected))
    msg = f'Progress: {len(done)}/{len(expected)} files done ({pct}%).'
    if remaining:
        msg += f' Remaining: {", ".join(remaining)}'

    return pct, remaining, msg


# ═══════════════════════════════════════════════════════════════════
# 6. PATTERN MATCHER
# ═══════════════════════════════════════════════════════════════════

def check_patterns(file_path, workspace_path):
    """Check if a newly written file matches existing codebase conventions.

    Returns a list of convention notes, or empty list.
    """
    if not file_path.endswith('.py'):
        return []

    notes = []
    basename = os.path.basename(file_path)

    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            new_content = f.read(30_000)
    except Exception:
        return []

    # Scan existing files for conventions
    existing_patterns = {
        'flask_blueprint': False,
        'sqlalchemy': False,
        'raw_sql': False,
        'dataclass': False,
        'type_hints': 0,
        'no_type_hints': 0,
        'docstrings': 0,
        'no_docstrings': 0,
    }

    try:
        for fname in os.listdir(workspace_path):
            if not fname.endswith('.py') or fname == basename:
                continue
            fpath = os.path.join(workspace_path, fname)
            if not os.path.isfile(fpath):
                continue
            try:
                with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read(10_000)
            except Exception:
                continue

            if 'Blueprint(' in content:
                existing_patterns['flask_blueprint'] = True
            if 'sqlalchemy' in content.lower() or 'db.Model' in content or 'Session' in content:
                existing_patterns['sqlalchemy'] = True
            if 'sqlite3.connect' in content or 'cursor.execute' in content:
                existing_patterns['raw_sql'] = True
            if '@dataclass' in content:
                existing_patterns['dataclass'] = True

            # Type hints
            try:
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        has_ann = any(a.annotation for a in node.args.args)
                        if has_ann:
                            existing_patterns['type_hints'] += 1
                        else:
                            existing_patterns['no_type_hints'] += 1
                        # Docstrings
                        if (node.body and isinstance(node.body[0], ast.Expr)
                                and isinstance(node.body[0].value, (ast.Str, ast.Constant))):
                            existing_patterns['docstrings'] += 1
                        else:
                            existing_patterns['no_docstrings'] += 1
            except Exception:
                pass
    except Exception:
        return []

    # Check new file against conventions
    if existing_patterns['sqlalchemy'] and 'sqlite3.connect' in new_content:
        notes.append(
            '📝 Other files use SQLAlchemy ORM. Consider using '
            'Session/db.Model instead of raw sqlite3.'
        )
    if existing_patterns['flask_blueprint'] and 'Flask(' in new_content and 'Blueprint' not in new_content:
        if basename not in ('app.py', 'main.py', '__init__.py'):
            notes.append(
                '📝 Other files use Flask Blueprints. Consider using '
                'Blueprint() for route registration.'
            )
    if existing_patterns['dataclass'] and 'class ' in new_content:
        try:
            tree = ast.parse(new_content)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    has_init = any(
                        isinstance(n, ast.FunctionDef) and n.name == '__init__'
                        for n in node.body
                    )
                    has_decorator = any(
                        (isinstance(d, ast.Name) and d.id == 'dataclass')
                        or (isinstance(d, ast.Attribute) and d.attr == 'dataclass')
                        for d in node.decorator_list
                    )
                    if has_init and not has_decorator and not node.bases:
                        notes.append(
                            f'📝 Other files use @dataclass. Consider '
                            f'using @dataclass for class {node.name}.'
                        )
                        break
        except Exception:
            pass

    return notes[:2]  # Cap at 2 notes


# ═══════════════════════════════════════════════════════════════════
# 7. CIRCULAR IMPORT DETECTOR
# ═══════════════════════════════════════════════════════════════════

class ImportGraph:
    """Maintains a live import graph for cycle detection."""

    def __init__(self):
        self.edges = {}  # module → set(imported_modules)

    def update_module(self, module_name, file_path):
        """Re-parse a module's imports and update the graph.

        Returns list of cycle descriptions, or empty list.
        """
        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                source = f.read()
            tree = ast.parse(source)
        except Exception:
            return []

        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                top = node.module.split('.')[0]
                imports.add(top)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split('.')[0])

        self.edges[module_name] = imports
        return self._detect_cycles(module_name)

    def _detect_cycles(self, start):
        """DFS from start module to detect cycles."""
        visited = set()
        path = []
        cycles = []

        def dfs(node):
            if node in visited:
                return
            if node in path:
                # Found cycle
                cycle_start = path.index(node)
                cycle = path[cycle_start:] + [node]
                cycle_str = ' → '.join(f'{m}.py' for m in cycle)
                cycles.append(f'⚠ Circular import: {cycle_str}')
                return
            if node not in self.edges:
                return

            path.append(node)
            for neighbor in self.edges[node]:
                if neighbor in self.edges:  # Only check local modules
                    dfs(neighbor)
            path.pop()
            visited.add(node)

        dfs(start)
        return cycles[:2]  # Cap at 2 per check

    def load_workspace(self, workspace_path):
        """Pre-load all .py files in workspace into the graph."""
        try:
            for fname in os.listdir(workspace_path):
                if fname.endswith('.py'):
                    mod_name = fname[:-3]
                    fpath = os.path.join(workspace_path, fname)
                    if os.path.isfile(fpath):
                        self.update_module(mod_name, fpath)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════
# 8. DEAD REFERENCE WATCHDOG
# ═══════════════════════════════════════════════════════════════════

def check_dead_references(file_path, old_content, new_content, workspace_path):
    """After an edit, check if removed definitions are still referenced elsewhere.

    Returns list of warning strings.
    """
    if not file_path.endswith('.py'):
        return []

    warnings = []
    basename = os.path.basename(file_path)
    module_name = basename[:-3]

    # Parse old and new to find removed definitions
    old_names = set()
    new_names = set()

    try:
        if old_content:
            old_tree = ast.parse(old_content)
            for node in ast.iter_child_nodes(old_tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    old_names.add(node.name)
                elif isinstance(node, ast.ClassDef):
                    old_names.add(node.name)
    except Exception:
        return []

    try:
        if new_content:
            new_tree = ast.parse(new_content)
            for node in ast.iter_child_nodes(new_tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    new_names.add(node.name)
                elif isinstance(node, ast.ClassDef):
                    new_names.add(node.name)
    except Exception:
        return []

    removed = old_names - new_names
    if not removed:
        return []

    # Check if removed names are imported/referenced in other files
    try:
        for fname in os.listdir(workspace_path):
            if not fname.endswith('.py') or fname == basename:
                continue
            fpath = os.path.join(workspace_path, fname)
            if not os.path.isfile(fpath):
                continue
            try:
                with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
                for name in removed:
                    # Check for import or usage
                    if (f'from {module_name} import' in content and name in content) or \
                       (f'{module_name}.{name}' in content):
                        warnings.append(
                            f'⚠ You removed/renamed \'{name}\' from {basename} '
                            f'but {fname} still references it. Update {fname} too.'
                        )
            except Exception:
                continue
    except Exception:
        pass

    return warnings[:3]


# ═══════════════════════════════════════════════════════════════════
# 9. CONTEXT BUDGET OPTIMIZER
# ═══════════════════════════════════════════════════════════════════

def optimize_history(history, written_files=None):
    """Smart compression of LLM history to preserve what matters.

    Unlike blunt trimming, this:
    - Compresses "Successfully wrote X" tool results to one line
    - Deduplicates repeated nudge messages
    - Strips thinking content from assistant messages
    - Replaces long file content in ReadFile results with summaries

    Returns compressed history list (same format).
    """
    if len(history) <= 4:
        return history

    compressed = []
    seen_nudges = set()

    for i, msg in enumerate(history):
        role = msg['role']
        content = msg['content']

        # Always keep system prompt as-is
        if i == 0 and role == 'system':
            compressed.append(msg)
            continue

        # Compress tool results
        if role == 'user' and content.startswith('Tool Result: Successfully wrote'):
            # Extract just the path and meta
            match = re.search(r'Successfully wrote to (\S+).*?\[meta:(.+?)\]', content)
            if match:
                short = f'Tool Result: Successfully wrote to {match.group(1)} [{match.group(2)}]'
                compressed.append({'role': role, 'content': short})
                continue

        # Compress ReadFile/ListFiles results (file contents in tool results)
        # Only compress read-type results, NOT RunCommand output (stack traces needed)
        if (role == 'user' and content.startswith('Tool Result:') and len(content) > 2000
                and not content.startswith('Tool Result: Command')
                and not content.startswith('Tool Result: Error')):
            # Keep first 500 chars + last 200 chars
            truncated = content[:500] + '\n...(compressed)...\n' + content[-200:]
            compressed.append({'role': role, 'content': truncated})
            continue

        # Deduplicate system nudges
        if role == 'user' and ('STOP.' in content or 'BLOCKED' in content or 'FINAL WARNING' in content):
            nudge_key = content[:80]
            if nudge_key in seen_nudges:
                continue  # Skip duplicate nudge
            seen_nudges.add(nudge_key)

        # Compress assistant messages: strip thinking content
        if role == 'assistant' and len(content) > 3000:
            # Remove fenced code blocks that were already saved via WriteFile
            if written_files:
                # If this response contains code that was already written, summarize
                has_tool_code = '<tool_code>' in content or '<|channel|>' in content
                if has_tool_code:
                    # Keep tool_code blocks, strip the prose around them
                    parts = re.split(r'(<tool_code>.*?</tool_code>)', content, flags=re.DOTALL)
                    kept = []
                    for part in parts:
                        if '<tool_code>' in part:
                            kept.append(part)
                        elif len(part) > 200:
                            kept.append(part[:100] + '...')
                        else:
                            kept.append(part)
                    content = ''.join(kept)
                    compressed.append({'role': role, 'content': content})
                    continue

        compressed.append(msg)

    return compressed


# ═══════════════════════════════════════════════════════════════════
# 10. TEST RUNNER SCOUT
# ═══════════════════════════════════════════════════════════════════

def run_tests(workspace_path, timeout=30):
    """Run pytest/unittest in the workspace after step completion.

    Returns dict: {ran: bool, passed: int, failed: int, errors: list[str], output: str}
    """
    result = {'ran': False, 'passed': 0, 'failed': 0, 'errors': [], 'output': ''}

    # Find test files
    test_files = []
    try:
        for fname in os.listdir(workspace_path):
            if fname.startswith('test_') and fname.endswith('.py'):
                test_files.append(fname)
            elif fname.endswith('_test.py'):
                test_files.append(fname)
        # Also check tests/ directory
        tests_dir = os.path.join(workspace_path, 'tests')
        if os.path.isdir(tests_dir):
            for fname in os.listdir(tests_dir):
                if fname.endswith('.py') and fname.startswith('test_'):
                    test_files.append(os.path.join('tests', fname))
    except Exception:
        return result

    if not test_files:
        return result

    # Find Python executable (prefer workspace .venv)
    venv_python = os.path.join(workspace_path, '.venv', 'Scripts', 'python.exe')
    if not os.path.isfile(venv_python):
        venv_python = os.path.join(workspace_path, '.venv', 'bin', 'python')
    if not os.path.isfile(venv_python):
        venv_python = sys.executable

    try:
        proc = subprocess.run(
            [venv_python, '-m', 'pytest', '--tb=short', '-q', '--no-header'],
            cwd=workspace_path,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = (proc.stdout or '') + '\n' + (proc.stderr or '')
        result['output'] = output[:5000]  # Cap output

        # Detect if pytest itself isn't installed
        if 'No module named pytest' in output:
            return result  # ran stays False — pytest not available

        result['ran'] = True

        # Parse pytest output for pass/fail counts
        # Format: "5 passed, 2 failed in 1.23s"
        summary = re.search(r'(\d+)\s+passed', output)
        if summary:
            result['passed'] = int(summary.group(1))
        fail_match = re.search(r'(\d+)\s+failed', output)
        if fail_match:
            result['failed'] = int(fail_match.group(1))
        error_match = re.search(r'(\d+)\s+error', output)
        if error_match:
            result['failed'] += int(error_match.group(1))

        # Extract failure details
        failures = re.findall(r'FAILED\s+(\S+)', output)
        for f in failures[:5]:
            result['errors'].append(f)

    except subprocess.TimeoutExpired:
        result['ran'] = True
        result['errors'].append(f'Tests timed out after {timeout}s')
    except FileNotFoundError:
        pass  # pytest not installed
    except Exception as e:
        result['errors'].append(str(e))

    return result


# ═══════════════════════════════════════════════════════════════════
# UNIFIED POST-WRITE HOOK
# ═══════════════════════════════════════════════════════════════════

def post_write_checks(file_path, workspace_path, import_graph=None,
                      old_content=None, is_edit=False):
    """Run all post-write micro-agents on a single file.

    Returns a list of warning/note strings to append to the tool result.
    Called after every successful WriteFile/EditFile.
    """
    warnings = []

    abs_path = os.path.join(workspace_path, file_path) if not os.path.isabs(file_path) else file_path

    if not abs_path.endswith('.py'):
        return warnings

    # 1. Syntax Sentinel
    syntax_err = syntax_check(abs_path)
    if syntax_err:
        warnings.append(syntax_err)
        return warnings  # Don't run further checks if syntax is broken

    # 2. Import Resolver
    import_warnings = resolve_imports(abs_path, workspace_path)
    warnings.extend(import_warnings)

    # 6. Pattern Matcher
    pattern_notes = check_patterns(abs_path, workspace_path)
    warnings.extend(pattern_notes)

    # 7. Circular Import Detector
    if import_graph:
        module_name = os.path.basename(abs_path)[:-3]
        cycles = import_graph.update_module(module_name, abs_path)
        warnings.extend(cycles)

    # 8. Dead Reference Watchdog (only for edits)
    if is_edit and old_content:
        try:
            with open(abs_path, 'r', encoding='utf-8', errors='replace') as f:
                new_content = f.read()
            dead_refs = check_dead_references(abs_path, old_content, new_content, workspace_path)
            warnings.extend(dead_refs)
        except Exception:
            pass

    return warnings[:5]  # Cap total warnings per write
