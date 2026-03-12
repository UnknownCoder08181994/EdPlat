"""Isolation test: detect_entry_point()

Tests that entry point detection correctly handles:
  1. Well-known names at root (main.py, app.py, etc.)
  2. __name__ == '__main__' guard detection
  3. Subdirectory entry points (src/app.py, api/main.py)
  4. Flask/FastAPI server pattern detection
  5. Flask factory pattern (app/__init__.py with create_app) — auto-generates run.py
  6. Server detection + port extraction
  7. No entry point -> returns None gracefully
"""

import os
import sys
import shutil
import tempfile

# Add backend to path
BACKEND_DIR = os.path.join(os.path.dirname(__file__), '..', 'backend')
sys.path.insert(0, os.path.abspath(BACKEND_DIR))

import utils.entry_point as _ep_module
from utils.entry_point import detect_entry_point

# Monkeypatch _validate_imports to skip subprocess calls in tests.
# The subprocess calls can hang if the entry point does argparse.parse_args()
# at module level or starts a server.
_ep_module._validate_imports = lambda workspace_path, entry_name: None


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _make_workspace(structure: dict) -> str:
    ws = tempfile.mkdtemp(prefix='zenflow_ep_')
    for rel_path, content in structure.items():
        full = os.path.join(ws, rel_path.replace('/', os.sep))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, 'w', encoding='utf-8') as f:
            f.write(content)
    return ws


passed = 0
failed = 0

def check(name, condition, detail=''):
    global passed, failed
    if condition:
        print(f"  PASS  {name}")
        passed += 1
    else:
        print(f"  FAIL  {name}  {detail}")
        failed += 1


# ═══════════════════════════════════════════════════════════════
# TEST 1: Well-known name at root (main.py)
# ═══════════════════════════════════════════════════════════════
print("\n=== TEST 1: Well-known name at root (main.py) ===")
ws = _make_workspace({
    'main.py': (
        'print("Hello World")\n'
    ),
})
result = detect_entry_point(ws)
check("entryPoint is main.py", result['entryPoint'] == 'main.py', f"got={result['entryPoint']}")
check("command starts with python", result['command'].startswith('python'), f"cmd={result['command']}")
check("isServer is False", result.get('isServer') == False, f"isServer={result.get('isServer')}")
shutil.rmtree(ws)


# ═══════════════════════════════════════════════════════════════
# TEST 2: app.py with Flask server
# ═══════════════════════════════════════════════════════════════
print("\n=== TEST 2: app.py with Flask server ===")
ws = _make_workspace({
    'app.py': (
        'from flask import Flask\n'
        '\n'
        'app = Flask(__name__)\n'
        '\n'
        '@app.route("/")\n'
        'def index():\n'
        '    return "hello"\n'
        '\n'
        'if __name__ == "__main__":\n'
        '    app.run(port=5001)\n'
    ),
    'requirements.txt': 'flask\n',
})
result = detect_entry_point(ws)
check("entryPoint is app.py", result['entryPoint'] == 'app.py', f"got={result['entryPoint']}")
check("isServer is True", result.get('isServer') == True, f"isServer={result.get('isServer')}")
check("serverPort is 5001", result.get('serverPort') == 5001, f"port={result.get('serverPort')}")
check("installCmd exists", result.get('installCmd') is not None, f"installCmd={result.get('installCmd')}")
shutil.rmtree(ws)


# ═══════════════════════════════════════════════════════════════
# TEST 3: __name__ guard in non-standard filename
# ═══════════════════════════════════════════════════════════════
print("\n=== TEST 3: __name__ guard in non-standard filename ===")
ws = _make_workspace({
    'calculator.py': (
        'import sys\n'
        '\n'
        'def calculate(x, y):\n'
        '    return x + y\n'
        '\n'
        'if __name__ == "__main__":\n'
        '    print(calculate(1, 2))\n'
    ),
})
result = detect_entry_point(ws)
check("entryPoint is calculator.py", result['entryPoint'] == 'calculator.py',
      f"got={result['entryPoint']}")
shutil.rmtree(ws)


# ═══════════════════════════════════════════════════════════════
# TEST 4: Subdirectory entry point (src/app.py)
# ═══════════════════════════════════════════════════════════════
print("\n=== TEST 4: Subdirectory entry point (src/app.py) ===")
ws = _make_workspace({
    'src/app.py': (
        'from flask import Flask\n'
        'app = Flask(__name__)\n'
        'app.run()\n'
    ),
    'src/__init__.py': '',
    'README.md': '# Project\n',
})
result = detect_entry_point(ws)
check("entryPoint is src/app.py", result['entryPoint'] == 'src/app.py',
      f"got={result['entryPoint']}")
check("isServer is True", result.get('isServer') == True, f"isServer={result.get('isServer')}")
shutil.rmtree(ws)


# ═══════════════════════════════════════════════════════════════
# TEST 5: Flask factory pattern — app/__init__.py with create_app
# ═══════════════════════════════════════════════════════════════
print("\n=== TEST 5: Flask factory pattern (app/__init__.py + create_app) ===")
ws = _make_workspace({
    'app/__init__.py': (
        'from flask import Flask\n'
        '\n'
        'def create_app(config_name="default"):\n'
        '    app = Flask(__name__)\n'
        '    app.config["SECRET_KEY"] = "dev"\n'
        '\n'
        '    from .routes import main_bp\n'
        '    app.register_blueprint(main_bp)\n'
        '\n'
        '    return app\n'
    ),
    'app/routes/__init__.py': (
        'from flask import Blueprint\n'
        'main_bp = Blueprint("main", __name__)\n'
    ),
    'app/models/__init__.py': '',
    'app/models/user.py': (
        'class User:\n'
        '    pass\n'
    ),
    'requirements.txt': 'flask\n',
})

result = detect_entry_point(ws)
check("entryPoint is run.py", result['entryPoint'] == 'run.py',
      f"got={result['entryPoint']}")
check("run.py was auto-generated", os.path.isfile(os.path.join(ws, 'run.py')),
      "run.py not found!")

# Verify run.py content
if os.path.isfile(os.path.join(ws, 'run.py')):
    with open(os.path.join(ws, 'run.py'), 'r') as f:
        run_content = f.read()
    check("run.py imports create_app", 'from app import create_app' in run_content,
          f"content={run_content}")
    check("run.py calls create_app()", 'create_app()' in run_content,
          f"content={run_content}")
    check("run.py has __name__ guard", "__name__" in run_content,
          f"content={run_content}")
    check("isServer is True", result.get('isServer') == True,
          f"isServer={result.get('isServer')}")

shutil.rmtree(ws)


# ═══════════════════════════════════════════════════════════════
# TEST 6: Flask factory — run.py already exists
# ═══════════════════════════════════════════════════════════════
print("\n=== TEST 6: Flask factory — run.py already exists ===")
ws = _make_workspace({
    'app/__init__.py': (
        'from flask import Flask\n'
        'def create_app():\n'
        '    return Flask(__name__)\n'
    ),
    'run.py': (
        'from app import create_app\n'
        'app = create_app()\n'
        'app.run(debug=True)\n'
    ),
    'requirements.txt': 'flask\n',
})
result = detect_entry_point(ws)
# Should detect run.py (well-known name, step 1) BEFORE even reaching step 6
check("entryPoint is run.py", result['entryPoint'] == 'run.py',
      f"got={result['entryPoint']}")
shutil.rmtree(ws)


# ═══════════════════════════════════════════════════════════════
# TEST 7: FastAPI server detection
# ═══════════════════════════════════════════════════════════════
print("\n=== TEST 7: FastAPI server detection ===")
ws = _make_workspace({
    'main.py': (
        'from fastapi import FastAPI\n'
        'import uvicorn\n'
        '\n'
        'app = FastAPI()\n'
        '\n'
        '@app.get("/")\n'
        'def read_root():\n'
        '    return {"hello": "world"}\n'
        '\n'
        'if __name__ == "__main__":\n'
        '    uvicorn.run(app, host="0.0.0.0", port=8000)\n'
    ),
})
result = detect_entry_point(ws)
check("entryPoint is main.py", result['entryPoint'] == 'main.py',
      f"got={result['entryPoint']}")
check("isServer is True", result.get('isServer') == True, f"isServer={result.get('isServer')}")
check("serverPort is 8000", result.get('serverPort') == 8000, f"port={result.get('serverPort')}")
shutil.rmtree(ws)


# ═══════════════════════════════════════════════════════════════
# TEST 8: No entry point -> graceful None
# ═══════════════════════════════════════════════════════════════
print("\n=== TEST 8: No entry point -> graceful None ===")
ws = _make_workspace({
    'README.md': '# Just a readme\n',
    'data/sample.csv': 'a,b\n1,2\n',
})
result = detect_entry_point(ws)
check("entryPoint is None", result['entryPoint'] is None, f"got={result['entryPoint']}")
check("command is None", result['command'] is None, f"cmd={result['command']}")
shutil.rmtree(ws)


# ═══════════════════════════════════════════════════════════════
# TEST 9: Priority order (app.py beats random_script.py)
# ═══════════════════════════════════════════════════════════════
print("\n=== TEST 9: Priority — app.py beats random_script.py ===")
ws = _make_workspace({
    'app.py': 'print("I am app.py")\n',
    'random_script.py': (
        'if __name__ == "__main__":\n'
        '    print("I am random_script")\n'
    ),
})
result = detect_entry_point(ws)
check("entryPoint is app.py (priority)", result['entryPoint'] == 'app.py',
      f"got={result['entryPoint']}")
shutil.rmtree(ws)


# ═══════════════════════════════════════════════════════════════
# TEST 10: Argparse detection
# ═══════════════════════════════════════════════════════════════
print("\n=== TEST 10: Argparse detection ===")
ws = _make_workspace({
    'main.py': (
        'import argparse\n'
        '\n'
        'parser = argparse.ArgumentParser()\n'
        'parser.add_argument("--input", required=True)\n'
        'args = parser.parse_args()\n'
        'print(args.input)\n'
    ),
})
result = detect_entry_point(ws)
check("hasArgparse is True", result.get('hasArgparse') == True,
      f"hasArgparse={result.get('hasArgparse')}")
check("needsArgs is True", result.get('needsArgs') == True,
      f"needsArgs={result.get('needsArgs')}")
check("command includes --help", '--help' in (result.get('command') or ''),
      f"cmd={result.get('command')}")
shutil.rmtree(ws)


# ═══════════════════════════════════════════════════════════════
# TEST 11: Invalid workspace
# ═══════════════════════════════════════════════════════════════
print("\n=== TEST 11: Invalid workspace ===")
result = detect_entry_point('/nonexistent/path/that/does/not/exist')
check("entryPoint is None for invalid path", result['entryPoint'] is None,
      f"got={result['entryPoint']}")

result2 = detect_entry_point('')
check("entryPoint is None for empty string", result2['entryPoint'] is None,
      f"got={result2['entryPoint']}")


# ═══════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════
print(f"\n{'='*60}")
print(f"EntryPointDetection:  {passed} passed, {failed} failed")
print(f"{'='*60}")
sys.exit(1 if failed > 0 else 0)
