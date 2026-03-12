"""Unit tests for backend/services/project_service.py"""

import os
import json
import pytest


class TestProjectService:
    @pytest.fixture(autouse=True)
    def setup(self, mock_config):
        """Ensure clean storage for each test."""
        self.storage_dir = mock_config

    def test_create_project(self):
        from services.project_service import ProjectService
        project = ProjectService.create_project('Test Project', '/tmp/test')
        assert project['name'] == 'Test Project'
        assert project['path'] == '/tmp/test'
        assert 'id' in project
        assert 'createdAt' in project

    def test_create_project_persists(self):
        from services.project_service import ProjectService
        project = ProjectService.create_project('Persist Test', '/tmp/persist')
        loaded = ProjectService.get_project(project['id'])
        assert loaded is not None
        assert loaded['name'] == 'Persist Test'

    def test_list_projects_empty(self):
        from services.project_service import ProjectService
        projects = ProjectService.list_projects()
        assert isinstance(projects, list)

    def test_list_projects_returns_created(self):
        from services.project_service import ProjectService
        ProjectService.create_project('P1', '/tmp/p1')
        ProjectService.create_project('P2', '/tmp/p2')
        projects = ProjectService.list_projects()
        names = [p['name'] for p in projects]
        assert 'P1' in names
        assert 'P2' in names

    def test_list_projects_sorted_by_date(self):
        from services.project_service import ProjectService
        p1 = ProjectService.create_project('First', '/tmp/first')
        p2 = ProjectService.create_project('Second', '/tmp/second')
        projects = ProjectService.list_projects()
        # Second should be first (newest first)
        assert projects[0]['name'] == 'Second'

    def test_get_project_nonexistent(self):
        from services.project_service import ProjectService
        result = ProjectService.get_project('nonexistent-id-12345')
        assert result is None

    def test_delete_project(self):
        from services.project_service import ProjectService
        project = ProjectService.create_project('ToDelete', '/tmp/del')
        ProjectService.delete_project(project['id'])
        assert ProjectService.get_project(project['id']) is None
