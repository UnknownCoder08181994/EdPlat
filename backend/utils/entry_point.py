"""Shared entry-point detection logic for Python/JS projects.

Used by:
  - routes/files.py  (HTTP endpoint)
  - services/agent_service.py  (execution agent)
"""

import os
import re
import subprocess


# Priority-ordered names we look for at the workspace root.
_ENTRY_POINT_NAMES = [
    'main.py', 'app.py', 'cli.py', 'run.py', 'server.py', 'serve.py',
    'index.js', 'index.ts', 'app.js', 'main.js',
]

# Browser-only APIs that indicate a .js file is NOT runnable with Node.js
_BROWSER_APIS = re.compile(
    r'\b(?:document\.|window\.|navigator\.|'
    r'getElementById|querySelector|querySelectorAll|'
    r'addEventListener\s*\(\s*[\'"](?:DOMContentLoaded|click|submit|load)|'
    r'innerHTML|textContent|classList\.|style\.|'
    r'createElement\(|appendChild\(|removeChild\(|'
    r'localStorage\.|sessionStorage\.|'
    r'fetch\s*\(|XMLHttpRequest|'
    r'alert\(|confirm\(|prompt\()\b'
)

# Node.js-specific patterns that confirm a .js file IS runnable with Node
_NODE_APIS = re.compile(
    r'\b(?:require\s*\(|module\.exports|exports\.|'
    r'process\.(?:argv|env|exit|stdin|stdout)|'
    r'__dirname|__filename|'
    r'const\s+\{[^}]*\}\s*=\s*require|'
    r'import\s+.*\s+from\s+[\'"](?:fs|path|http|https|net|child_process|'
    r'express|koa|fastify|hapi|socket\.io|ws|mysql|pg|mongodb))\b'
)


def _is_browser_js(filepath):
    """Check if a JS file uses browser-only APIs (not runnable with Node.js).

    Returns True if the file appears to be browser JavaScript.
    """
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            source = f.read(8192)
    except Exception:
        return False

    has_browser = bool(_BROWSER_APIS.search(source))
    has_node = bool(_NODE_APIS.search(source))

    # If it has Node patterns, it's Node.js regardless of browser patterns
    if has_node:
        return False
    # If it has browser patterns but no Node patterns, it's browser JS
    return has_browser

# Sample data generators keyed by detected format
_SAMPLE_DATA = {
    'text': (
        '_sample.txt',
        "Hello World!\n"
        "This is a sample text file created automatically for project demo.\n"
        "It contains multiple lines and words to test with.\n"
        "\n"
        "The quick brown fox jumps over the lazy dog.\n"
        "Pack my box with five dozen liquor jugs.\n"
    ),
    'json': (
        '_sample.json',
        '[\n'
        '  {"name": "Alice", "age": 30, "city": "New York"},\n'
        '  {"name": "Bob", "age": 25, "city": "San Francisco"},\n'
        '  {"name": "Charlie", "age": 35, "city": "Chicago"}\n'
        ']\n'
    ),
    'csv': (
        '_sample.csv',
        "name,age,city,score\n"
        "Alice,30,New York,92.5\n"
        "Bob,25,San Francisco,87.3\n"
        "Charlie,35,Chicago,95.1\n"
        "Diana,28,Boston,88.7\n"
    ),
    'numeric': (
        '_sample.txt',
        "42\n17\n85\n3\n56\n91\n24\n68\n10\n73\n"
    ),
}


def _analyze_source(source):
    """Analyze Python source code for patterns. Returns a dict of detections."""
    result = {
        "needsArgs": False, "readsStdin": False, "hasArgparse": False,
        "argHint": None, "description": None, "isServer": False,
        "dataFormat": "text",
    }

    if 'argparse' in source or 'ArgumentParser' in source:
        result["needsArgs"] = True
        result["hasArgparse"] = True
        result["argHint"] = '--help'

    if 'sys.argv' in source and not result["hasArgparse"]:
        result["needsArgs"] = True
        result["argHint"] = 'sample'

    if 'sys.stdin' in source or 'input()' in source:
        result["readsStdin"] = True

    server_patterns = ['Flask(__name__)', 'FastAPI(', 'app.run(', 'uvicorn.run(',
                       'HTTPServer(', 'Django', 'Bottle(']
    for pat in server_patterns:
        if pat in source:
            result["isServer"] = True
            break

    if result["isServer"]:
        port_match = re.search(r'\.run\([^)]*port\s*=\s*(\d{2,5})', source)
        if not port_match:
            port_match = re.search(r'(?:PORT|port|Port)\s*=\s*(\d{2,5})', source)
        if not port_match:
            port_match = re.search(r'port\s*=\s*(\d{2,5})', source)
        if port_match:
            result["serverPort"] = int(port_match.group(1))
        elif 'Flask' in source:
            result["serverPort"] = 5000
        elif 'FastAPI' in source or 'uvicorn' in source:
            result["serverPort"] = 8000
        else:
            result["serverPort"] = 8080

    if 'json' in source.lower() and ('json.load' in source or 'json.loads' in source):
        result["dataFormat"] = 'json'
    elif 'csv' in source.lower() and ('csv.reader' in source or 'csv.DictReader' in source):
        result["dataFormat"] = 'csv'
    elif any(kw in source for kw in ['int(', 'float(', 'decimal', 'Decimal(']):
        if 'split' in source or 'readline' in source:
            result["dataFormat"] = 'numeric'

    doc_match = re.search(r'"""(.*?)"""', source, re.DOTALL)
    if not doc_match:
        doc_match = re.search(r"'''(.*?)'''", source, re.DOTALL)
    if doc_match:
        desc = doc_match.group(1).strip()
        desc_lines = desc.split('\n')
        result["description"] = desc_lines[0].strip()
        for line in desc_lines:
            if 'usage:' in line.lower():
                usage_hint = line.strip()
                if usage_hint:
                    result["description"] = usage_hint
                break

    return result


def _analyze_python_script(filepath):
    """Analyze a Python script and follow local imports (1 level deep)."""
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            source = f.read(8192)
    except Exception:
        return {"needsArgs": False, "readsStdin": False, "hasArgparse": False,
                "argHint": None, "description": None, "isServer": False,
                "dataFormat": "text"}

    result = _analyze_source(source)

    workspace_dir = os.path.dirname(filepath)
    local_imports = re.findall(r'(?:from|import)\s+([a-zA-Z_][a-zA-Z0-9_]*)', source)
    _SKIP_MODS = {'sys', 'os', 'json', 'csv', 'datetime', 'pathlib',
                  'typing', 'collections', 'dataclasses', 're',
                  'math', 'decimal', 'uuid', 'time', 'functools',
                  'itertools', 'io', 'subprocess', 'shutil',
                  'flask', 'flask_socketio', 'fastapi', 'uvicorn',
                  'django', 'bottle', 'requests', 'sqlalchemy'}
    for mod_name in set(local_imports):
        if mod_name in _SKIP_MODS:
            continue
        mod_path = os.path.join(workspace_dir, mod_name + '.py')
        if os.path.isfile(mod_path):
            try:
                with open(mod_path, 'r', encoding='utf-8', errors='replace') as f:
                    mod_source = f.read(8192)
                mod_result = _analyze_source(mod_source)
                if mod_result["hasArgparse"]:
                    result["hasArgparse"] = True
                    result["needsArgs"] = True
                    result["argHint"] = '--help'
                if mod_result["isServer"]:
                    result["isServer"] = True
                if mod_result["readsStdin"]:
                    result["readsStdin"] = True
                if mod_result["needsArgs"] and not result["needsArgs"]:
                    result["needsArgs"] = mod_result["needsArgs"]
                    result["argHint"] = mod_result["argHint"]
                if mod_result["description"] and not result["description"]:
                    result["description"] = mod_result["description"]
                if mod_result["dataFormat"] != 'text' and result["dataFormat"] == 'text':
                    result["dataFormat"] = mod_result["dataFormat"]
                if mod_result.get("serverPort") and not result.get("serverPort"):
                    result["serverPort"] = mod_result["serverPort"]
                if not result.get("serverPort") or result.get("serverPort") in (5000, 8000, 8080):
                    port_const = re.search(r'(?:PORT|port|Port)\s*=\s*(\d{2,5})', mod_source)
                    if port_const:
                        result["serverPort"] = int(port_const.group(1))
            except Exception:
                pass

    return result


def _validate_imports(workspace_path, entry_name):
    """Quick syntax+import validation of the entry point.

    Returns None if OK, or an error string describing the issue.
    """
    full_path = os.path.join(workspace_path, entry_name)
    if not entry_name.endswith('.py'):
        return None

    venv_python = os.path.join(workspace_path, '.venv', 'Scripts', 'python.exe')
    if not os.path.isfile(venv_python):
        venv_python = os.path.join(workspace_path, '.venv', 'bin', 'python')
    python_cmd = venv_python if os.path.isfile(venv_python) else 'python'

    env = os.environ.copy()
    venv_scripts = os.path.join(workspace_path, '.venv', 'Scripts')
    if not os.path.isdir(venv_scripts):
        venv_scripts = os.path.join(workspace_path, '.venv', 'bin')
    if os.path.isdir(venv_scripts):
        env['PATH'] = venv_scripts + os.pathsep + env.get('PATH', '')
        env['VIRTUAL_ENV'] = os.path.join(workspace_path, '.venv')

    try:
        result = subprocess.run(
            [python_cmd, '-c', f'import ast; ast.parse(open(r"{full_path}").read())'],
            capture_output=True, text=True, timeout=10,
            cwd=workspace_path, env=env
        )
        if result.returncode != 0:
            return f"Syntax error in {entry_name}: {result.stderr.strip()}"
    except Exception:
        pass

    module_name = entry_name.replace('.py', '')
    try:
        result = subprocess.run(
            [python_cmd, '-c', f'import {module_name}'],
            capture_output=True, text=True, timeout=15,
            cwd=workspace_path, env=env
        )
        if result.returncode != 0:
            err = result.stderr.strip()
            for line in err.split('\n'):
                if 'ImportError' in line or 'ModuleNotFoundError' in line or 'cannot import' in line:
                    return line.strip()
            if err:
                return err[-300:]
    except Exception:
        pass

    return None


def _ensure_sample_file(workspace_path, data_format='text'):
    """Create a sample input file matching the expected data format."""
    filename, content = _SAMPLE_DATA.get(data_format, _SAMPLE_DATA['text'])
    sample_path = os.path.join(workspace_path, filename)
    if not os.path.isfile(sample_path):
        try:
            with open(sample_path, 'w', encoding='utf-8') as f:
                f.write(content)
        except Exception:
            pass
    return filename


def detect_entry_point(workspace_path):
    """Detect a runnable entry point in the workspace.

    Returns a dict:
      {
        'entryPoint': str|None,
        'command': str|None,
        'installCmd': str|None,
        'hasVenv': bool,
        'needsArgs': bool,
        'readsStdin': bool,
        'hasArgparse': bool,
        'isServer': bool,
        'serverPort': int|None,
        'sampleFile': str|None,
        'dataFormat': str,
        'importError': str|None,
        'description': str|None,
        'argHint': str|None,
      }
    """
    if not workspace_path or not os.path.isdir(workspace_path):
        return {'entryPoint': None, 'command': None, 'installCmd': None}

    # Check for .venv
    venv_path = os.path.join(workspace_path, '.venv')
    has_venv = os.path.isdir(venv_path)

    # Check for requirements.txt
    req_path = os.path.join(workspace_path, 'requirements.txt')
    install_cmd = None
    if os.path.isfile(req_path) and os.path.getsize(req_path) > 0:
        install_cmd = 'pip install -r requirements.txt'

    # Skip dirs when searching subdirectories
    _SKIP_DIRS = {'.git', '__pycache__', 'node_modules', '.venv', 'venv',
                  '.sentinel', '.tox', '.mypy_cache', '.pytest_cache', 'dist', 'build'}

    # 1) Check well-known names in priority order (root level)
    entry_name = None
    is_frontend = False
    for name in _ENTRY_POINT_NAMES:
        full = os.path.join(workspace_path, name)
        if os.path.isfile(full):
            # Skip browser-only JS files — they can't run with Node.js
            if name.endswith(('.js', '.ts')) and _is_browser_js(full):
                is_frontend = True
                continue
            entry_name = name
            break

    # 2) Fallback: any root-level .py with __name__ guard
    if not entry_name:
        try:
            for fname in sorted(os.listdir(workspace_path)):
                if not fname.endswith('.py'):
                    continue
                full = os.path.join(workspace_path, fname)
                if not os.path.isfile(full):
                    continue
                try:
                    with open(full, 'r', encoding='utf-8', errors='replace') as f:
                        head = f.read(4096)
                    if '__name__' in head and '__main__' in head:
                        entry_name = fname
                        break
                except Exception:
                    continue
        except Exception:
            pass

    # 3) Fallback: check well-known names in immediate subdirectories (1 level deep)
    #    e.g. src/app.py, api/main.py, backend/server.py
    if not entry_name:
        try:
            for subdir in sorted(os.listdir(workspace_path)):
                if subdir in _SKIP_DIRS or subdir.startswith('.'):
                    continue
                subdir_path = os.path.join(workspace_path, subdir)
                if not os.path.isdir(subdir_path):
                    continue
                for name in _ENTRY_POINT_NAMES:
                    full = os.path.join(subdir_path, name)
                    if os.path.isfile(full):
                        # Skip browser-only JS files
                        if name.endswith(('.js', '.ts')) and _is_browser_js(full):
                            is_frontend = True
                            continue
                        entry_name = os.path.join(subdir, name).replace('\\', '/')
                        break
                if entry_name:
                    break
        except Exception:
            pass

    # 4) Fallback: any .py with __name__ guard in subdirectories (1 level deep)
    if not entry_name:
        try:
            for subdir in sorted(os.listdir(workspace_path)):
                if subdir in _SKIP_DIRS or subdir.startswith('.'):
                    continue
                subdir_path = os.path.join(workspace_path, subdir)
                if not os.path.isdir(subdir_path):
                    continue
                for fname in sorted(os.listdir(subdir_path)):
                    if not fname.endswith('.py'):
                        continue
                    full = os.path.join(subdir_path, fname)
                    if not os.path.isfile(full):
                        continue
                    try:
                        with open(full, 'r', encoding='utf-8', errors='replace') as f:
                            head = f.read(4096)
                        if '__name__' in head and '__main__' in head:
                            entry_name = os.path.join(subdir, fname).replace('\\', '/')
                            break
                    except Exception:
                        continue
                if entry_name:
                    break
        except Exception:
            pass

    # 5) Fallback: any root-level .py with Flask/FastAPI/server pattern
    if not entry_name:
        try:
            for fname in sorted(os.listdir(workspace_path)):
                if not fname.endswith('.py'):
                    continue
                full = os.path.join(workspace_path, fname)
                if not os.path.isfile(full):
                    continue
                try:
                    with open(full, 'r', encoding='utf-8', errors='replace') as f:
                        head = f.read(4096)
                    server_patterns = ['Flask(__name__)', 'FastAPI(', 'app.run(',
                                       'uvicorn.run(', 'Bottle(']
                    if any(pat in head for pat in server_patterns):
                        entry_name = fname
                        break
                except Exception:
                    continue
        except Exception:
            pass

    # 6) Fallback: check __init__.py in top-level packages for Flask factory / server patterns
    #    Handles the Flask app factory pattern: app/__init__.py with create_app() + Flask(__name__)
    if not entry_name:
        try:
            for subdir in sorted(os.listdir(workspace_path)):
                if subdir in _SKIP_DIRS or subdir.startswith('.'):
                    continue
                subdir_path = os.path.join(workspace_path, subdir)
                if not os.path.isdir(subdir_path):
                    continue
                init_path = os.path.join(subdir_path, '__init__.py')
                if not os.path.isfile(init_path):
                    continue
                try:
                    with open(init_path, 'r', encoding='utf-8', errors='replace') as f:
                        head = f.read(4096)
                    server_patterns = ['Flask(__name__)', 'FastAPI(', 'app.run(',
                                       'uvicorn.run(', 'Bottle(', 'create_app']
                    if any(pat in head for pat in server_patterns):
                        # Flask factory: generate a run.py entry point
                        run_path = os.path.join(workspace_path, 'run.py')
                        if not os.path.isfile(run_path):
                            # Auto-create run.py that imports and runs the app
                            has_create_app = 'create_app' in head
                            if has_create_app:
                                run_code = (
                                    f"from {subdir} import create_app\n\n"
                                    f"app = create_app()\n\n"
                                    f"if __name__ == '__main__':\n"
                                    f"    app.run(debug=True)\n"
                                )
                            else:
                                run_code = (
                                    f"from {subdir} import app\n\n"
                                    f"if __name__ == '__main__':\n"
                                    f"    app.run(debug=True)\n"
                                )
                            try:
                                with open(run_path, 'w', encoding='utf-8') as rf:
                                    rf.write(run_code)
                                entry_name = 'run.py'
                            except Exception:
                                pass
                        else:
                            entry_name = 'run.py'
                        break
                except Exception:
                    continue
        except Exception:
            pass

    if not entry_name:
        # If not already flagged, check for HTML files as a frontend signal
        html_file = None
        if not is_frontend:
            try:
                root_files = os.listdir(workspace_path)
                # Check root for HTML files (prefer index.html)
                html_files = [f for f in root_files
                              if f.endswith('.html') and os.path.isfile(os.path.join(workspace_path, f))]
                if html_files:
                    is_frontend = True
                    html_file = 'index.html' if 'index.html' in html_files else html_files[0]
                else:
                    # Check 1 level deep (e.g., templates/, pages/, public/)
                    for subdir in sorted(root_files):
                        sp = os.path.join(workspace_path, subdir)
                        if os.path.isdir(sp) and subdir not in _SKIP_DIRS and not subdir.startswith('.'):
                            sub_html = [f for f in os.listdir(sp) if f.endswith('.html')]
                            if sub_html:
                                is_frontend = True
                                html_file = os.path.join(subdir, 'index.html').replace('\\', '/') \
                                    if 'index.html' in sub_html \
                                    else os.path.join(subdir, sub_html[0]).replace('\\', '/')
                                break
            except Exception:
                pass

        if is_frontend and html_file:
            # Serve with Python's built-in HTTP server and auto-open the HTML file
            port = 8080
            return {
                'entryPoint': html_file,
                'command': f'python -m http.server {port}',
                'installCmd': install_cmd,
                'hasVenv': has_venv,
                'needsArgs': False,
                'readsStdin': False,
                'hasArgparse': False,
                'description': f'Static site — serving {html_file} at http://localhost:{port}',
                'isServer': True,
                'serverPort': port,
                'sampleFile': None,
                'dataFormat': 'text',
                'importError': None,
                'isFrontend': True,
            }

        result = {'entryPoint': None, 'command': None, 'installCmd': install_cmd}
        if is_frontend:
            result['isFrontend'] = True
        return result

    # Analyze the entry point
    full_path = os.path.join(workspace_path, entry_name)
    analysis = {}
    if entry_name.endswith('.py'):
        analysis = _analyze_python_script(full_path)

    base_cmd = f'python {entry_name}' if entry_name.endswith('.py') else f'node {entry_name}'

    # Build the run command
    command = base_cmd
    sample_file = None
    data_format = analysis.get('dataFormat', 'text')

    if analysis.get('isServer'):
        command = base_cmd
    elif analysis.get('needsArgs') or analysis.get('readsStdin'):
        sample_file = _ensure_sample_file(workspace_path, data_format)
        if analysis.get('hasArgparse'):
            command = f'python {entry_name} --help'
        elif analysis.get('readsStdin') and not analysis.get('needsArgs'):
            command = f'python {entry_name} < {sample_file}'
        else:
            command = f'python {entry_name} {sample_file}'

    # Validate imports
    import_error = _validate_imports(workspace_path, entry_name)

    return {
        'entryPoint': entry_name,
        'command': command,
        'installCmd': install_cmd,
        'hasVenv': has_venv,
        'needsArgs': analysis.get('needsArgs', False),
        'readsStdin': analysis.get('readsStdin', False),
        'argHint': analysis.get('argHint'),
        'hasArgparse': analysis.get('hasArgparse', False),
        'description': analysis.get('description'),
        'isServer': analysis.get('isServer', False),
        'serverPort': analysis.get('serverPort'),
        'sampleFile': sample_file,
        'dataFormat': data_format,
        'importError': import_error,
    }
