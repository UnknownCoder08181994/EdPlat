"""Unit tests for backend/services/storage.py"""

import os
import json
import pytest


class TestStorageService:
    def test_save_and_load(self, mock_config):
        from services.storage import StorageService
        data = {"key": "value", "count": 42}
        StorageService.save_json('projects', 'test.json', data)
        loaded = StorageService.load_json('projects', 'test.json')
        assert loaded == data

    def test_load_nonexistent(self, mock_config):
        from services.storage import StorageService
        result = StorageService.load_json('projects', 'nope.json')
        assert result is None

    def test_load_empty_file(self, mock_config):
        from services.storage import StorageService
        path = os.path.join(mock_config, 'projects', 'empty.json')
        with open(path, 'w') as f:
            f.write('')
        result = StorageService.load_json('projects', 'empty.json')
        assert result is None

    def test_load_corrupt_json(self, mock_config):
        from services.storage import StorageService
        path = os.path.join(mock_config, 'projects', 'bad.json')
        with open(path, 'w') as f:
            f.write('{not valid json!!!')
        result = StorageService.load_json('projects', 'bad.json')
        assert result is None
        # Should have created a .corrupt backup
        assert os.path.isfile(path + '.corrupt')

    def test_list_files(self, mock_config):
        from services.storage import StorageService
        StorageService.save_json('projects', 'a.json', {"id": "a"})
        StorageService.save_json('projects', 'b.json', {"id": "b"})
        files = StorageService.list_files('projects')
        assert 'a.json' in files
        assert 'b.json' in files

    def test_list_files_empty(self, mock_config):
        from services.storage import StorageService
        files = StorageService.list_files('projects')
        assert files == []

    def test_ensure_directories(self, mock_config):
        from services.storage import StorageService
        StorageService.ensure_directories()
        assert os.path.isdir(os.path.join(mock_config, 'projects'))
        assert os.path.isdir(os.path.join(mock_config, 'tasks'))
        assert os.path.isdir(os.path.join(mock_config, 'workspaces'))

    def test_overwrite_existing(self, mock_config):
        from services.storage import StorageService
        StorageService.save_json('projects', 'test.json', {"v": 1})
        StorageService.save_json('projects', 'test.json', {"v": 2})
        loaded = StorageService.load_json('projects', 'test.json')
        assert loaded['v'] == 2

    def test_nested_data(self, mock_config):
        from services.storage import StorageService
        data = {
            "nested": {"a": [1, 2, 3], "b": {"deep": True}},
            "list": ["x", "y"],
        }
        StorageService.save_json('tasks', 'nested.json', data)
        loaded = StorageService.load_json('tasks', 'nested.json')
        assert loaded == data
