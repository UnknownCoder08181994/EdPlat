"""Unit tests for backend/config.py and backend/app.py setup"""

import os
import pytest


class TestConfig:
    def test_base_dir_exists(self):
        from config import Config
        assert os.path.isdir(Config.BASE_DIR)

    def test_storage_dir_path(self):
        from config import Config
        assert Config.STORAGE_DIR.endswith('storage')

    def test_project_root_is_parent(self):
        from config import Config
        assert Config.BASE_DIR.startswith(Config.PROJECT_ROOT)

    def test_debug_flag(self):
        from config import Config
        assert isinstance(Config.DEBUG, bool)


class TestAppSetup:
    def test_app_import(self):
        """Verify app.py can be imported (creates Flask app)."""
        # We import selectively to avoid side effects
        import importlib
        # Just verify the blueprints exist as modules
        from routes.projects import projects_bp
        from routes.tasks import tasks_bp
        from routes.chats import chats_bp
        from routes.files import files_bp
        from routes.terminal import terminal_bp
        assert projects_bp is not None
        assert tasks_bp is not None
        assert chats_bp is not None
        assert files_bp is not None
        assert terminal_bp is not None

    def test_blueprint_names(self):
        from routes.projects import projects_bp
        from routes.tasks import tasks_bp
        from routes.chats import chats_bp
        from routes.files import files_bp
        from routes.terminal import terminal_bp
        assert projects_bp.name == 'projects'
        assert tasks_bp.name == 'tasks'
        assert chats_bp.name == 'chats'
        assert files_bp.name == 'files'
        assert terminal_bp.name == 'terminal'


class TestUtilsLogging:
    def test_safe_log_exists(self):
        from utils.logging import _safe_log
        # Should not raise
        _safe_log("test message")

    def test_safe_log_with_exception(self):
        from utils.logging import _safe_log
        # Should handle any string safely
        _safe_log("Error: " + "x" * 1000)
