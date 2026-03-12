import uuid
import os
import re
import sys
import shutil
import subprocess
from datetime import datetime
from services.storage import StorageService
from services.project_service import ProjectService
from services.workspace_service import WorkspaceService
from services.plan_engine import parse_plan, update_step, StepStatus, STATUS_LABEL_MAP
from config import Config
from prompts.plan_template import build as build_plan_template

class TaskService:
    @staticmethod
    def _enrich_task(task):
        # Add title if missing
        if 'title' not in task and 'details' in task:
            # First line of details or truncated details
            details = task['details']
            title = details.split('\n')[0][:50]
            if len(details) > 50:
                title += "..."
            task['title'] = title

        # Add project name if missing
        if 'projectName' not in task and 'projectId' in task:
            project = ProjectService.get_project(task['projectId'])
            if project:
                task['projectName'] = project['name']
        return task

    @staticmethod
    def list_tasks(project_id=None):
        files = StorageService.list_files('tasks')
        tasks = []
        for f in files:
            data = StorageService.load_json('tasks', f)
            if data:
                if project_id and data.get('projectId') != project_id:
                    continue
                TaskService._enrich_task(data)
                tasks.append(data)
        # Sort by createdAt desc
        tasks.sort(key=lambda x: x.get('createdAt', ''), reverse=True)
        return tasks

    @staticmethod
    def create_task(project_id, workflow_type, details, settings):
        project = ProjectService.get_project(project_id)
        if not project:
            raise ValueError("Project not found")

        task_id = str(uuid.uuid4())
        short_id = task_id[:4]
        branch_name = f"new-task-{short_id}"

        # Setup workspace
        workspace_path, method = WorkspaceService.setup_workspace(project['path'], task_id, branch_name)

        # Initialize plan.md
        # We need to write plan.md into the workspace
        # The prompt says: "Task artifacts_path: .sentinel/tasks/new-task-c8e8"
        # "Files in artifacts folder: .sentinel/tasks/new-task-c8e8\plan.md"
        # So we should create .sentinel/tasks/{task_id}/plan.md in the WORKSPACE.

        artifacts_dir = os.path.join(workspace_path, '.sentinel', 'tasks', task_id)
        os.makedirs(artifacts_dir, exist_ok=True)

        plan_content = build_plan_template(
            details=details,
            complexity=settings.get('complexity', 5),
            workflow_type=workflow_type,
        )
        with open(os.path.join(artifacts_dir, 'plan.md'), 'w', encoding='utf-8') as f:
            f.write(plan_content)

        task = {
            "id": task_id,
            "projectId": project_id,
            "workflowType": workflow_type,
            "details": details,
            "settings": settings,
            "status": "To Do",
            "branch": branch_name,
            "workspacePath": workspace_path,
            "workspaceMethod": method,
            "createdAt": datetime.now().isoformat()
        }

        StorageService.save_json('tasks', f"{task_id}.json", task)
        return task

    @staticmethod
    def _parse_plan(workspace_path, task_id):
        """Parse plan.md into a list of step dicts (delegates to plan_engine)."""
        plan_path = os.path.join(workspace_path, '.sentinel', 'tasks', task_id, 'plan.md')
        plan = parse_plan(plan_path)
        return [s.to_dict() for s in plan.steps]

    @staticmethod
    def update_step_in_plan(workspace_path, task_id, step_id, updates):
        """Update a step in plan.md (delegates to plan_engine).

        updates can include: {status: str, chatId: str}
        """
        plan_path = os.path.join(workspace_path, '.sentinel', 'tasks', task_id, 'plan.md')
        if not os.path.exists(plan_path):
            return False

        # Guard: never overwrite plan.md with empty content (race condition protection)
        try:
            with open(plan_path, 'r', encoding='utf-8') as f:
                content = f.read()
            if not content.strip():
                try:
                    print(f"Warning: plan.md is empty for task {task_id}, skipping update", file=sys.stderr, flush=True)
                except OSError:
                    pass
                return False
        except OSError:
            return False

        plan = parse_plan(plan_path)
        new_status = None
        if 'status' in updates:
            new_status = STATUS_LABEL_MAP.get(updates['status'])

        try:
            update_step(plan, step_id, new_status=new_status, chat_id=updates.get('chatId'))
        except ValueError:
            return False

        return True

    @staticmethod
    def delete_task(task_id):
        """Delete a task and all associated files (workspace, chats, metadata)."""
        task = StorageService.load_json('tasks', f'{task_id}.json')

        if task:
            workspace_path = task.get('workspacePath')
            project_path = task.get('projectPath', '')
            if workspace_path and os.path.exists(workspace_path):
                # Just remove the directory — skip git worktree remove (too slow).
                # Stale worktree refs are cleaned up by `git worktree prune`.
                try:
                    shutil.rmtree(workspace_path, ignore_errors=True)
                except Exception as e:
                    try:
                        print(f"[Task] Failed to delete workspace: {e}", file=sys.stderr, flush=True)
                    except OSError:
                        pass

            # Prune stale git worktree refs
            if project_path and os.path.isdir(project_path):
                try:
                    import subprocess
                    subprocess.run(
                        ['git', 'worktree', 'prune'],
                        cwd=project_path, capture_output=True, timeout=10
                    )
                except Exception:
                    pass

        # Delete chat files
        chat_dir = os.path.join(Config.STORAGE_DIR, 'chats', task_id)
        if os.path.exists(chat_dir):
            shutil.rmtree(chat_dir, ignore_errors=True)

        # Delete task JSON
        task_file = os.path.join(Config.STORAGE_DIR, 'tasks', f'{task_id}.json')
        if os.path.exists(task_file):
            os.remove(task_file)

        try:
            print(f"[Task] Deleted task {task_id}", file=sys.stderr, flush=True)
        except OSError:
            pass

    @staticmethod
    def get_task(task_id):
        task = StorageService.load_json('tasks', f"{task_id}.json")
        if not task:
            return None

        TaskService._enrich_task(task)

        # Enrich with steps from plan.md
        workspace_path = task.get('workspacePath')
        if workspace_path:
            task['steps'] = TaskService._parse_plan(workspace_path, task_id)
        else:
            task['steps'] = []

        # Dynamic file counts — must match what's visible in the file tree.
        # Tree shows: artifact .md files + recursive workspace files
        # (excluding hidden dirs + shallow dirs like .venv/node_modules)
        HIDE = {'.git', '__pycache__', '.DS_Store', 'dist', 'build', '.claude', '.sentinel'}
        SHALLOW = {'.venv', 'venv', 'node_modules'}
        file_count = 0

        # Count artifact .md files (shown in virtual Artifacts folder)
        artifacts_dir = os.path.join(workspace_path, '.sentinel', 'tasks', task_id) if workspace_path else None
        if artifacts_dir and os.path.isdir(artifacts_dir):
            file_count += len([f for f in os.listdir(artifacts_dir)
                               if os.path.isfile(os.path.join(artifacts_dir, f)) and f.endswith('.md')])

        # Count workspace files recursively (matching file tree behavior)
        if workspace_path and os.path.isdir(workspace_path):
            for root, dirs, files in os.walk(workspace_path):
                # Skip hidden and shallow directories
                dirs[:] = [d for d in dirs if d not in HIDE and d not in SHALLOW]
                # Skip hidden filenames that the tree also hides
                file_count += sum(1 for f in files if f not in HIDE)

        task['filesCount'] = file_count

        # commitsCount removed — Commits tab no longer shown in UI

        return task
