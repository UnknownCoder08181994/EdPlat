import uuid
import os
from datetime import datetime
from services.storage import StorageService
from config import Config
from utils.logging import _safe_log

class ProjectService:
    @staticmethod
    def list_projects():
        files = StorageService.list_files('projects')
        projects = []
        for f in files:
            data = StorageService.load_json('projects', f)
            if data:
                projects.append(data)
        # Sort by createdAt desc
        projects.sort(key=lambda x: x.get('createdAt', ''), reverse=True)
        return projects

    @staticmethod
    def create_project(name, path):
        project_id = str(uuid.uuid4())
        project = {
            "id": project_id,
            "name": name,
            "path": path,
            "createdAt": datetime.now().isoformat()
        }
        StorageService.save_json('projects', f"{project_id}.json", project)
        return project

    @staticmethod
    def get_project(project_id):
        return StorageService.load_json('projects', f"{project_id}.json")

    @staticmethod
    def delete_project(project_id):
        """Delete project and cascade-delete all its tasks."""
        # Import here to avoid circular import (TaskService imports ProjectService)
        from services.task_service import TaskService

        tasks = TaskService.list_tasks(project_id=project_id)
        for task in tasks:
            TaskService.delete_task(task['id'])

        project_file = os.path.join(Config.STORAGE_DIR, 'projects', f'{project_id}.json')
        if os.path.exists(project_file):
            os.remove(project_file)

        _safe_log(f"[Project] Deleted project {project_id} ({len(tasks)} tasks)")
