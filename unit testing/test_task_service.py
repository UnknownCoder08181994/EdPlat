"""Unit tests for backend/services/task_service.py"""

import os
import json
import pytest


class TestEnrichTask:
    def test_adds_title_from_details(self):
        from services.task_service import TaskService
        task = {'details': 'Build a web scraper for news sites'}
        result = TaskService._enrich_task(task)
        assert 'title' in result
        assert result['title'].startswith('Build a web scraper')

    def test_title_truncated_at_50(self):
        from services.task_service import TaskService
        task = {'details': 'A' * 100}
        result = TaskService._enrich_task(task)
        assert len(result['title']) <= 53  # 50 chars + "..."

    def test_title_not_overwritten(self):
        from services.task_service import TaskService
        task = {'title': 'Existing Title', 'details': 'Other stuff'}
        result = TaskService._enrich_task(task)
        assert result['title'] == 'Existing Title'

    def test_multiline_details_uses_first_line(self):
        from services.task_service import TaskService
        task = {'details': 'First line\nSecond line\nThird line'}
        result = TaskService._enrich_task(task)
        assert 'First line' in result['title']
        assert 'Second line' not in result['title']

    def test_no_details_no_title_added(self):
        from services.task_service import TaskService
        task = {'id': 'test-123'}
        result = TaskService._enrich_task(task)
        assert 'title' not in result


class TestListTasks:
    @pytest.fixture(autouse=True)
    def setup(self, mock_config):
        self.storage_dir = mock_config

    def test_empty_list(self):
        from services.task_service import TaskService
        tasks = TaskService.list_tasks()
        assert isinstance(tasks, list)

    def test_list_with_filter(self):
        from services.storage import StorageService
        from services.task_service import TaskService
        # Create two tasks with different project IDs
        StorageService.save_json('tasks', 't1.json', {
            'id': 't1', 'projectId': 'p1', 'createdAt': '2024-01-01',
        })
        StorageService.save_json('tasks', 't2.json', {
            'id': 't2', 'projectId': 'p2', 'createdAt': '2024-01-02',
        })
        tasks = TaskService.list_tasks(project_id='p1')
        assert len(tasks) == 1
        assert tasks[0]['id'] == 't1'

    def test_list_sorted_by_date_desc(self):
        from services.storage import StorageService
        from services.task_service import TaskService
        StorageService.save_json('tasks', 'old.json', {
            'id': 'old', 'createdAt': '2024-01-01',
        })
        StorageService.save_json('tasks', 'new.json', {
            'id': 'new', 'createdAt': '2024-06-01',
        })
        tasks = TaskService.list_tasks()
        assert tasks[0]['id'] == 'new'


class TestParsePlan:
    def test_parse_plan_basic(self, tmp_path):
        from services.task_service import TaskService
        # Create a minimal plan.md
        task_id = 'test-task-id'
        plan_dir = tmp_path / '.sentinel' / 'tasks' / task_id
        plan_dir.mkdir(parents=True)
        plan_path = plan_dir / 'plan.md'
        plan_path.write_text(
            "# Plan\n\n"
            "## Steps\n\n"
            "- [ ] Requirements {#requirements}\n"
            "  Description: Gather requirements\n"
            "- [ ] Implementation {#implementation}\n"
            "  Description: Build the app\n"
        )
        steps = TaskService._parse_plan(str(tmp_path), task_id)
        assert isinstance(steps, list)

    def test_parse_plan_missing_file(self, tmp_path):
        from services.task_service import TaskService
        # Should handle missing plan.md gracefully (plan_engine may raise or return empty)
        task_id = 'nonexistent'
        plan_dir = tmp_path / '.sentinel' / 'tasks' / task_id
        plan_dir.mkdir(parents=True)
        # The plan file doesn't exist, parse_plan should handle it
        try:
            steps = TaskService._parse_plan(str(tmp_path), task_id)
            assert isinstance(steps, list)
        except (FileNotFoundError, OSError):
            pass  # Expected if plan_engine raises on missing file


class TestUpdateStepInPlan:
    def test_update_nonexistent_returns_false(self, tmp_path):
        from services.task_service import TaskService
        result = TaskService.update_step_in_plan(
            str(tmp_path), 'no-task', 'no-step', {'status': 'completed'}
        )
        assert result is False

    def test_update_empty_plan_returns_false(self, tmp_path):
        from services.task_service import TaskService
        task_id = 'test-task'
        plan_dir = tmp_path / '.sentinel' / 'tasks' / task_id
        plan_dir.mkdir(parents=True)
        plan_path = plan_dir / 'plan.md'
        plan_path.write_text('')  # Empty plan
        result = TaskService.update_step_in_plan(
            str(tmp_path), task_id, 'some-step', {'status': 'in_progress'}
        )
        assert result is False


class TestDeleteTask:
    @pytest.fixture(autouse=True)
    def setup(self, mock_config):
        self.storage_dir = mock_config

    def test_delete_nonexistent_task(self):
        from services.task_service import TaskService
        # Should not raise even if task doesn't exist
        TaskService.delete_task('nonexistent-id-12345')

    def test_delete_removes_json(self):
        from services.storage import StorageService
        from services.task_service import TaskService
        StorageService.save_json('tasks', 'to-delete.json', {
            'id': 'to-delete', 'projectId': 'p1',
        })
        TaskService.delete_task('to-delete')
        task_file = os.path.join(self.storage_dir, 'tasks', 'to-delete.json')
        assert not os.path.exists(task_file)


class TestGetTask:
    @pytest.fixture(autouse=True)
    def setup(self, mock_config):
        self.storage_dir = mock_config

    def test_get_nonexistent_returns_none(self):
        from services.task_service import TaskService
        assert TaskService.get_task('nonexistent') is None

    def test_get_task_enriches(self):
        from services.storage import StorageService
        from services.task_service import TaskService
        # Create a task with a workspace
        ws_path = os.path.join(self.storage_dir, 'workspaces', 'test-ws')
        os.makedirs(ws_path, exist_ok=True)
        # Create artifacts dir
        art_dir = os.path.join(ws_path, '.sentinel', 'tasks', 'enriched')
        os.makedirs(art_dir, exist_ok=True)
        # Write plan.md so _parse_plan doesn't fail
        with open(os.path.join(art_dir, 'plan.md'), 'w') as f:
            f.write("# Plan\n## Steps\n- [ ] Requirements {#requirements}\n")

        StorageService.save_json('tasks', 'enriched.json', {
            'id': 'enriched',
            'details': 'Build a thing',
            'workspacePath': ws_path,
        })
        task = TaskService.get_task('enriched')
        assert task is not None
        assert 'title' in task
        assert 'filesCount' in task
        assert 'steps' in task
