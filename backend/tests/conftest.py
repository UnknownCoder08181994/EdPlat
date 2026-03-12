"""
Shared test fixtures for zenflow-rebuild API tests.

Creates a test Flask app by importing blueprints directly (bypasses CUDA gate in app.py),
uses tempfile for isolated storage, and provides helper fixtures for common operations.
"""

import os
import sys
import json
import uuid
import shutil
import tempfile
import threading
from datetime import datetime

import pytest

# Add backend/ to path so we can import services, routes, etc.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from flask import Flask
from flask_cors import CORS
from config import Config

# ── Test App Factory ──────────────────────────────────────────────────

def create_test_app(storage_dir):
    """Create a Flask test app with blueprints registered, bypassing CUDA gate."""
    # Patch Config.STORAGE_DIR before importing anything that uses it
    Config.STORAGE_DIR = storage_dir

    from routes.projects import projects_bp
    from routes.tasks import tasks_bp
    from routes.chats import chats_bp
    from routes.files import files_bp

    app = Flask(__name__,
                template_folder=os.path.join(os.path.dirname(__file__), '..', 'templates'),
                static_folder=os.path.join(os.path.dirname(__file__), '..', 'static'),
                static_url_path='/static')
    app.config['TESTING'] = True
    app.config['STORAGE_DIR'] = storage_dir
    CORS(app)

    # Register blueprints
    app.register_blueprint(projects_bp)
    app.register_blueprint(tasks_bp)
    app.register_blueprint(chats_bp)
    app.register_blueprint(files_bp)

    # Health endpoint
    from flask import jsonify
    @app.route('/api/health')
    def health():
        return jsonify({"status": "ok", "message": "Sentinel Clone Backend Running"})

    @app.route('/favicon.ico')
    def favicon():
        return '', 204

    # Global error handler
    @app.errorhandler(Exception)
    def handle_exception(e):
        import traceback
        try:
            traceback.print_exc()
        except OSError:
            pass
        return jsonify({"error": str(e), "type": type(e).__name__}), 500

    return app


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def storage_dir(tmp_path):
    """Create isolated temp storage directory for each test."""
    sd = str(tmp_path / "storage")
    os.makedirs(os.path.join(sd, 'projects'), exist_ok=True)
    os.makedirs(os.path.join(sd, 'tasks'), exist_ok=True)
    os.makedirs(os.path.join(sd, 'chats'), exist_ok=True)
    os.makedirs(os.path.join(sd, 'workspaces'), exist_ok=True)
    # Patch Config
    Config.STORAGE_DIR = sd
    yield sd


@pytest.fixture
def app(storage_dir):
    """Create a test Flask app with isolated storage."""
    application = create_test_app(storage_dir)
    yield application


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()


@pytest.fixture
def workspace_dir(storage_dir):
    """Create a temp workspace directory for file operation tests."""
    ws = os.path.join(storage_dir, 'workspaces', 'test-workspace')
    os.makedirs(ws, exist_ok=True)
    return ws


# ── Helper Functions ──────────────────────────────────────────────────

def make_project(client, name="Test Project", path="C:\\fake\\project"):
    """Create a project via API, return the JSON response."""
    resp = client.post('/api/projects', json={"name": name, "path": path})
    return resp.get_json()


def make_task(client, project_id, details="Build a test app", settings=None):
    """Create a task via API.

    NOTE: This requires WorkspaceService which creates real directories.
    For tests that don't need a real workspace, use make_task_direct().
    """
    data = {
        "projectId": project_id,
        "details": details,
        "settings": settings or {}
    }
    resp = client.post('/api/tasks', json=data)
    return resp.get_json()


def make_task_direct(storage_dir, project_id, details="Build a test app", task_id=None):
    """Create a task directly in storage (bypasses WorkspaceService).

    Creates a minimal task JSON + workspace dir + plan.md so tests
    can work without git or real workspace setup.
    """
    task_id = task_id or str(uuid.uuid4())
    workspace_path = os.path.join(storage_dir, 'workspaces', task_id)
    os.makedirs(workspace_path, exist_ok=True)

    # Create plan.md
    artifacts_dir = os.path.join(workspace_path, '.sentinel', 'tasks', task_id)
    os.makedirs(artifacts_dir, exist_ok=True)
    plan_content = """# Full SDD workflow

---

## Workflow Steps

### [ ] Step: Requirements

Create a PRD based on the feature description.

Save the PRD to `requirements.md`.

### [ ] Step: Technical Specification

Create a technical specification.

### [ ] Step: Planning

Create a detailed implementation plan.

### [ ] Step: Implementation

Execute the tasks.
"""
    with open(os.path.join(artifacts_dir, 'plan.md'), 'w', encoding='utf-8') as f:
        f.write(plan_content)

    task = {
        "id": task_id,
        "projectId": project_id,
        "workflowType": "Full SDD workflow",
        "details": details,
        "settings": {},
        "status": "To Do",
        "branch": f"new-task-{task_id[:4]}",
        "workspacePath": workspace_path,
        "workspaceMethod": "file-copy",
        "createdAt": datetime.now().isoformat()
    }

    task_path = os.path.join(storage_dir, 'tasks', f'{task_id}.json')
    with open(task_path, 'w', encoding='utf-8') as f:
        json.dump(task, f, indent=2)

    return task


def make_chat_direct(storage_dir, task_id, chat_id=None, name="Test Chat", messages=None):
    """Create a chat directly in storage."""
    chat_id = chat_id or str(uuid.uuid4())
    chat_dir = os.path.join(storage_dir, 'chats', task_id)
    os.makedirs(chat_dir, exist_ok=True)

    chat = {
        "id": chat_id,
        "taskId": task_id,
        "name": name,
        "createdAt": datetime.now().isoformat(),
        "messages": messages or [],
        "status": "active"
    }

    chat_path = os.path.join(chat_dir, f'{chat_id}.json')
    with open(chat_path, 'w', encoding='utf-8') as f:
        json.dump(chat, f, indent=2)

    return chat


def make_project_direct(storage_dir, name="Test Project", path="C:\\fake\\project", project_id=None):
    """Create a project directly in storage."""
    project_id = project_id or str(uuid.uuid4())
    project = {
        "id": project_id,
        "name": name,
        "path": path,
        "createdAt": datetime.now().isoformat()
    }
    project_path = os.path.join(storage_dir, 'projects', f'{project_id}.json')
    with open(project_path, 'w', encoding='utf-8') as f:
        json.dump(project, f, indent=2)
    return project
