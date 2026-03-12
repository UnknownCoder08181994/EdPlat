"""Seed demo data on first run.

Called from app.py at startup. Idempotent — checks if data already exists
before creating anything. Creates a demo project and task so the UI has
something to show immediately on first launch.
"""

import os
import uuid
from datetime import datetime
from config import Config
from services.storage import StorageService
from prompts.plan_template import build as build_plan_template


def ensure_seed_data():
    """Create demo project + task if no projects exist yet."""
    StorageService.ensure_directories()

    # Check if any projects already exist
    existing = StorageService.list_files('projects')
    if existing:
        return  # Already seeded or user has created projects

    project_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    short_id = task_id[:4]
    branch_name = f"new-task-{short_id}"

    # Create demo project pointing at the repo root
    project = {
        "id": project_id,
        "name": "Demo Project",
        "path": Config.PROJECT_ROOT,
        "createdAt": datetime.now().isoformat()
    }
    StorageService.save_json('projects', f"{project_id}.json", project)

    # Create workspace directory for the task
    workspace_path = os.path.join(Config.STORAGE_DIR, 'workspaces', task_id)
    os.makedirs(workspace_path, exist_ok=True)

    # Create artifacts directory with plan.md
    artifacts_dir = os.path.join(workspace_path, '.sentinel', 'tasks', task_id)
    os.makedirs(artifacts_dir, exist_ok=True)
    demo_details = "Build a simple REST API for managing a to-do list"
    with open(os.path.join(artifacts_dir, 'plan.md'), 'w', encoding='utf-8') as f:
        f.write(build_plan_template(details=demo_details, complexity=5))

    # Create demo task
    task = {
        "id": task_id,
        "projectId": project_id,
        "workflowType": "Full SDD workflow",
        "details": "Build a simple REST API for managing a to-do list",
        "settings": {
            "autoStart": False,
            "isolatedCopy": False
        },
        "status": "To Do",
        "branch": branch_name,
        "workspacePath": workspace_path,
        "workspaceMethod": "file-copy",
        "createdAt": datetime.now().isoformat()
    }
    StorageService.save_json('tasks', f"{task_id}.json", task)

    try:
        import sys
        print(f"[Seed] Created demo project '{project['name']}' and task '{task['details']}'",
              file=sys.stderr, flush=True)
    except OSError:
        pass
