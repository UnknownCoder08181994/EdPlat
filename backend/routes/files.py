import os
from flask import Blueprint, request, jsonify
from services.task_service import TaskService
from services.tool_service import ToolService

files_bp = Blueprint('files', __name__)

# Directories to completely hide from file tree (internal / irrelevant)
IGNORE_DIRS = {'.git', '__pycache__', '.DS_Store', 'dist', 'build', '.claude', '.sentinel'}
# Directories to show as a leaf folder (visible but contents not listed)
SHALLOW_DIRS = {'.venv', 'venv', 'node_modules'}

def get_tool_service(task_id):
    task = TaskService.get_task(task_id)
    if not task:
        raise ValueError("Task not found")

    workspace_path = task.get('workspacePath')
    if not workspace_path:
        raise ValueError("Task has no workspace")

    # Always scope to workspace root — readFile/writeFile work for both
    # artifact paths (.sentinel/tasks/{id}/requirements.md) and workspace files (app.py)
    return ToolService(workspace_path)


def _build_tree(dir_path, rel_prefix=".", depth=0, max_depth=5):
    """Recursively build a file tree structure from a directory."""
    if depth > max_depth:
        return []

    items = []
    try:
        entries = sorted(os.listdir(dir_path))
    except (PermissionError, OSError):
        return []

    # Cap entries per directory to prevent extreme cases (e.g., node_modules leaked)
    if len(entries) > 500:
        entries = entries[:500]

    for entry in entries:
        if entry in IGNORE_DIRS:
            continue

        full_path = os.path.join(dir_path, entry)
        rel_path = os.path.join(rel_prefix, entry).replace("\\", "/")

        # Skip symlinks to prevent infinite recursion from circular links
        if os.path.islink(full_path):
            continue

        if os.path.isdir(full_path):
            if entry in SHALLOW_DIRS:
                # Show the folder but don't recurse into it
                items.append({
                    "name": entry,
                    "path": rel_path,
                    "type": "directory",
                    "children": [],
                    "shallow": True
                })
            else:
                children = _build_tree(full_path, rel_path, depth + 1, max_depth)
                items.append({
                    "name": entry,
                    "path": rel_path,
                    "type": "directory",
                    "children": children
                })
        else:
            items.append({
                "name": entry,
                "path": rel_path,
                "type": "file"
            })

    # Sort: directories first, then files, alphabetically within each group
    items.sort(key=lambda x: (x['type'] != 'directory', x['name'].lower()))
    return items


@files_bp.route('/api/tasks/<task_id>/file-tree', methods=['GET'])
def file_tree(task_id):
    """Return a recursive file tree of the task's workspace.

    Includes SDD artifacts (plan.md, requirements.md, spec.md, etc.)
    as a virtual 'Artifacts' folder at the top, even though they live
    inside .sentinel/ which is otherwise hidden.
    """
    try:
        task = TaskService.get_task(task_id)
        if not task:
            return jsonify({"error": "Task not found"}), 404

        workspace_path = task.get('workspacePath')
        if not workspace_path or not os.path.isdir(workspace_path):
            return jsonify({"error": "Workspace not found"}), 404

        children = _build_tree(workspace_path, ".", depth=0, max_depth=5)

        # ── Inject SDD artifacts as a virtual "Artifacts" folder ──
        # These files live in .sentinel/tasks/{task_id}/ but users need
        # to see plan.md, requirements.md, spec.md, implementation-plan.md
        artifacts_dir = os.path.join(workspace_path, '.sentinel', 'tasks', task_id)
        if os.path.isdir(artifacts_dir):
            artifact_files = []
            for fname in sorted(os.listdir(artifacts_dir)):
                fpath = os.path.join(artifacts_dir, fname)
                if os.path.isfile(fpath) and fname.endswith('.md'):
                    # Use the real path relative to workspace so the file reader works
                    rel_path = os.path.join('.sentinel', 'tasks', task_id, fname).replace('\\', '/')
                    artifact_files.append({
                        "name": fname,
                        "path": rel_path,
                        "type": "file"
                    })
            if artifact_files:
                artifacts_folder = {
                    "name": "Artifacts",
                    "path": os.path.join('.sentinel', 'tasks', task_id).replace('\\', '/'),
                    "type": "directory",
                    "children": artifact_files,
                    "virtual": True,  # Flag for frontend styling
                }
                # Insert at the top of the tree
                children.insert(0, artifacts_folder)

        tree = {
            "name": os.path.basename(workspace_path),
            "path": ".",
            "type": "directory",
            "children": children
        }

        return jsonify(tree)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@files_bp.route('/api/tasks/<task_id>/files', methods=['GET'])
def list_files(task_id):
    try:
        path = request.args.get('path', '.')
        tool_service = get_tool_service(task_id)

        # Structured data for the UI (name, type, path)
        target_path = tool_service._validate_path(path)

        items = []
        if os.path.exists(target_path) and os.path.isdir(target_path):
            for item in os.listdir(target_path):
                if item in IGNORE_DIRS:
                    continue

                full_path = os.path.join(target_path, item)
                is_dir = os.path.isdir(full_path)
                items.append({
                    "name": item,
                    "path": os.path.join(path, item).replace("\\", "/"),
                    "type": "directory" if is_dir else "file"
                })

        # Sort directories first, then files
        items.sort(key=lambda x: (x['type'] != 'directory', x['name']))

        return jsonify(items)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@files_bp.route('/api/tasks/<task_id>/file', methods=['GET'])
def read_file(task_id):
    try:
        path = request.args.get('path')
        if not path:
            return jsonify({"error": "Path is required"}), 400

        tool_service = get_tool_service(task_id)
        content = tool_service.read_file(path)

        # ToolService returns "Error: ..." string on failure.
        # Check for specific ToolService error prefixes to avoid misclassifying
        # real file content that happens to start with "Error:".
        if content.startswith("Error: File not found:") or content.startswith("Error: File appears to be binary") or content.startswith("Error reading file:"):
            return jsonify({"error": content}), 400

        return jsonify({"content": content})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@files_bp.route('/api/tasks/<task_id>/file', methods=['POST'])
def write_file(task_id):
    try:
        data = request.json
        path = data.get('path')
        content = data.get('content')

        if not path or content is None:
            return jsonify({"error": "Path and content are required"}), 400

        tool_service = get_tool_service(task_id)
        result = tool_service.write_file(path, content)

        if result.startswith("Error:"):
            return jsonify({"error": result}), 400

        return jsonify({"message": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── Entry‐point detection ──────────────────────────────────
# Priority-ordered names we look for at the workspace root.
_ENTRY_POINT_NAMES = [
    'main.py', 'app.py', 'cli.py', 'run.py', 'server.py',
    'index.js', 'index.ts', 'app.js',
]

import re as _re

def _analyze_source(source):
    """Analyze Python source code for patterns. Returns a dict of detections."""
    result = {
        "needsArgs": False, "readsStdin": False, "hasArgparse": False,
        "argHint": None, "description": None, "isServer": False,
        "dataFormat": "text",
    }

    # Detect argparse usage → has --help built in
    if 'argparse' in source or 'ArgumentParser' in source:
        result["needsArgs"] = True
        result["hasArgparse"] = True
        result["argHint"] = '--help'

    # Detect sys.argv usage (CLI expecting positional args, no built-in --help)
    if 'sys.argv' in source and not result["hasArgparse"]:
        result["needsArgs"] = True
        result["argHint"] = 'sample'

    # Detect stdin reading (blocks if no input piped)
    if 'sys.stdin' in source or 'input()' in source:
        result["readsStdin"] = True

    # Detect web server patterns
    server_patterns = ['Flask(__name__)', 'FastAPI(', 'app.run(', 'uvicorn.run(',
                       'HTTPServer(', 'Django', 'Bottle(']
    for pat in server_patterns:
        if pat in source:
            result["isServer"] = True
            break

    # Detect server port number
    if result["isServer"]:
        # First check for explicit port= in app.run(port=XXXX) or similar
        port_match = _re.search(r'\.run\([^)]*port\s*=\s*(\d{2,5})', source)
        if not port_match:
            # Check for PORT = XXXX style constants (common in config files)
            port_match = _re.search(r'(?:PORT|port|Port)\s*=\s*(\d{2,5})', source)
        if not port_match:
            # Generic port= anywhere
            port_match = _re.search(r'port\s*=\s*(\d{2,5})', source)
        if port_match:
            result["serverPort"] = int(port_match.group(1))
        elif 'Flask' in source:
            result["serverPort"] = 5000
        elif 'FastAPI' in source or 'uvicorn' in source:
            result["serverPort"] = 8000
        else:
            result["serverPort"] = 8080

    # Detect what data format the script expects
    if 'json' in source.lower() and ('json.load' in source or 'json.loads' in source):
        result["dataFormat"] = 'json'
    elif 'csv' in source.lower() and ('csv.reader' in source or 'csv.DictReader' in source):
        result["dataFormat"] = 'csv'
    elif any(kw in source for kw in ['int(', 'float(', 'decimal', 'Decimal(']):
        if 'split' in source or 'readline' in source:
            result["dataFormat"] = 'numeric'

    # Extract docstring for description
    doc_match = _re.search(r'"""(.*?)"""', source, _re.DOTALL)
    if not doc_match:
        doc_match = _re.search(r"'''(.*?)'''", source, _re.DOTALL)
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
    """Analyze a Python script to determine how to run it.

    Also follows local imports (up to 1 level deep) so that a thin main.py
    that does `from cli import main` still detects argparse in cli.py.

    Returns a dict with:
      - needsArgs, readsStdin, hasArgparse, argHint, description,
        isServer, dataFormat
    """
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            source = f.read(8192)
    except Exception:
        return {"needsArgs": False, "readsStdin": False, "hasArgparse": False,
                "argHint": None, "description": None, "isServer": False,
                "dataFormat": "text"}

    result = _analyze_source(source)

    # Follow local imports (up to 1 level deep) and merge their analysis.
    # This catches thin entry points: main.py → from cli import main → cli.py has argparse
    # Also catches port config: main.py → from config import Config → config.py has PORT = 8080
    workspace_dir = os.path.dirname(filepath)
    # Find local imports: `from X import ...` or `import X`
    local_imports = _re.findall(r'(?:from|import)\s+([a-zA-Z_][a-zA-Z0-9_]*)', source)
    for mod_name in set(local_imports):
        # Skip stdlib/known packages
        if mod_name in ('sys', 'os', 'json', 'csv', 'datetime', 'pathlib',
                        'typing', 'collections', 'dataclasses', 're',
                        'math', 'decimal', 'uuid', 'time', 'functools',
                        'itertools', 'io', 'subprocess', 'shutil',
                        'flask', 'flask_socketio', 'fastapi', 'uvicorn',
                        'django', 'bottle', 'requests', 'sqlalchemy'):
            continue
        mod_path = os.path.join(workspace_dir, mod_name + '.py')
        if os.path.isfile(mod_path):
            try:
                with open(mod_path, 'r', encoding='utf-8', errors='replace') as f:
                    mod_source = f.read(8192)
                mod_result = _analyze_source(mod_source)
                # Merge: if the imported module has argparse, the project has argparse
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
                # Merge server port from imported config modules
                # e.g. config.py has PORT = 8080 or port = 8080
                if mod_result.get("serverPort") and not result.get("serverPort"):
                    result["serverPort"] = mod_result["serverPort"]
                # Also scan for PORT = XXXX style config constants (not caught by _analyze_source)
                if not result.get("serverPort") or result.get("serverPort") in (5000, 8000, 8080):
                    port_const = _re.search(r'(?:PORT|port|Port)\s*=\s*(\d{2,5})', mod_source)
                    if port_const:
                        result["serverPort"] = int(port_const.group(1))
            except Exception:
                pass

    return result


@files_bp.route('/api/tasks/<task_id>/entry-point', methods=['GET'])
def detect_entry_point(task_id):
    """Scan the workspace for a runnable entry‐point file.

    Delegates to the shared utility in utils/entry_point.py.
    """
    try:
        from utils.entry_point import detect_entry_point as _detect_ep

        task = TaskService.get_task(task_id)
        if not task:
            return jsonify({"error": "Task not found"}), 404
        workspace = task.get('workspacePath')
        if not workspace or not os.path.isdir(workspace):
            return jsonify({"entryPoint": None, "command": None, "installCmd": None})

        result = _detect_ep(workspace)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@files_bp.route('/api/tasks/<task_id>/command', methods=['POST'])
def run_command(task_id):
    try:
        data = request.json
        command = data.get('command')
        cwd = data.get('cwd')

        if not command:
            return jsonify({"error": "Command is required"}), 400

        tool_service = get_tool_service(task_id)
        output = tool_service.run_command(command, cwd)

        return jsonify({"output": output})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
