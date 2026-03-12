import os
import sys
import subprocess
import shutil
import re
import threading
from config import Config

# Windows reserved device names that cannot be used as file names
WINDOWS_RESERVED_NAMES = {
    'CON', 'PRN', 'AUX', 'NUL',
    'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
    'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'
}

COPY_IGNORE = {
    '.git', '__pycache__', 'node_modules', '.DS_Store',
    '.venv', 'venv', 'dist', 'build', 'storage',
}

def ignore_copy_dirs(directory, files):
    """Ignore heavy/problematic directories and Windows reserved names during file copy."""
    ignored = set()
    for f in files:
        if f in COPY_IGNORE:
            ignored.add(f)
        name_without_ext = os.path.splitext(f)[0].upper()
        if name_without_ext in WINDOWS_RESERVED_NAMES:
            ignored.add(f)
    return ignored

def ignore_windows_reserved(directory, files):
    """Ignore Windows reserved device names and other problematic files."""
    ignored = set()
    for f in files:
        # Check if file name (without extension) is a reserved name
        name_without_ext = os.path.splitext(f)[0].upper()
        if name_without_ext in WINDOWS_RESERVED_NAMES:
            ignored.add(f)
        # Also ignore .venv directories
        if f == '.venv' or f == 'venv':
            ignored.add(f)
    return ignored

class WorkspaceService:
    @staticmethod
    def setup_workspace(project_path, task_id, branch_name):
        """
        Creates an isolated workspace for the task.
        Returns (workspace_path, method_used) immediately.
        Heavy operations (file copy, venv) run in background threads.
        """
        workspace_path = os.path.join(Config.STORAGE_DIR, 'workspaces', task_id)

        is_git = os.path.isdir(os.path.join(project_path, '.git'))

        if is_git:
            try:
                if os.path.exists(workspace_path):
                    pass

                result = subprocess.run(
                    ['git', 'rev-parse', '--verify', branch_name],
                    cwd=project_path,
                    capture_output=True,
                    timeout=30
                )

                if result.returncode != 0:
                    subprocess.run(
                        ['git', 'branch', branch_name, 'main'],
                        cwd=project_path,
                        check=True,
                        capture_output=True,
                        timeout=30
                    )

                if not os.path.exists(workspace_path):
                    subprocess.run(
                        ['git', 'worktree', 'add', workspace_path, branch_name],
                        cwd=project_path,
                        check=True,
                        capture_output=True,
                        timeout=60
                    )

                WorkspaceService._create_venv(workspace_path)
                return workspace_path, "git-worktree"
            except Exception:
                pass  # Fallback to file-copy below

        # Fallback: create empty workspace — agent creates files from scratch
        os.makedirs(workspace_path, exist_ok=True)

        WorkspaceService._create_venv(workspace_path)
        return workspace_path, "empty-workspace"

    @staticmethod
    def _create_venv(workspace_path):
        """Create a Python virtual environment in the workspace for agent use.
        Runs in a background thread to avoid blocking task creation."""
        venv_path = os.path.join(workspace_path, '.venv')
        if os.path.exists(venv_path):
            return  # Already exists
        def _do_create():
            try:
                subprocess.run(
                    [sys.executable, '-m', 'venv', venv_path],
                    check=True,
                    capture_output=True,
                    timeout=120
                )
            except Exception:
                pass  # venv creation is optional; don't let it break task creation
        thread = threading.Thread(target=_do_create, daemon=True)
        thread.start()
