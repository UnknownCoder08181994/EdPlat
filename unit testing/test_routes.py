"""Unit tests for backend/routes/*.py

Tests route blueprints using Flask test client.
"""

import os
import json
import pytest


@pytest.fixture
def app(mock_config):
    """Create a Flask test app with all route blueprints registered."""
    from flask import Flask
    from flask_cors import CORS
    from config import Config

    app = Flask(__name__,
                template_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), 'backend', 'templates'),
                static_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), 'backend', 'static'))
    app.config.from_object(Config)
    app.config['TESTING'] = True
    CORS(app)

    from routes.projects import projects_bp
    from routes.tasks import tasks_bp
    from routes.chats import chats_bp
    from routes.files import files_bp
    from routes.terminal import terminal_bp
    app.register_blueprint(projects_bp)
    app.register_blueprint(tasks_bp)
    app.register_blueprint(chats_bp)
    app.register_blueprint(files_bp)
    app.register_blueprint(terminal_bp)

    # Register a minimal health endpoint for testing
    @app.route('/api/health')
    def health():
        from flask import jsonify
        return jsonify({"status": "ok"})

    return app


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()


# ═══════════════════════════════════════════════════════════
# Projects Route Tests
# ═══════════════════════════════════════════════════════════

class TestProjectsRoute:
    def test_list_projects_empty(self, client):
        resp = client.get('/api/projects')
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)

    def test_create_project(self, client):
        resp = client.post('/api/projects', json={
            'name': 'Test Project',
            'path': '/tmp/test-project',
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data['name'] == 'Test Project'
        assert 'id' in data

    def test_create_project_missing_fields(self, client):
        resp = client.post('/api/projects', json={'name': 'Incomplete'})
        assert resp.status_code == 400

    def test_list_projects_after_create(self, client):
        client.post('/api/projects', json={'name': 'P1', 'path': '/tmp/p1'})
        resp = client.get('/api/projects')
        data = resp.get_json()
        assert len(data) >= 1
        assert any(p['name'] == 'P1' for p in data)

    def test_delete_project(self, client):
        resp = client.post('/api/projects', json={'name': 'ToDelete', 'path': '/tmp/del'})
        pid = resp.get_json()['id']
        del_resp = client.delete(f'/api/projects/{pid}')
        assert del_resp.status_code == 200


# ═══════════════════════════════════════════════════════════
# Health endpoint
# ═══════════════════════════════════════════════════════════

class TestHealthRoute:
    def test_health(self, client):
        resp = client.get('/api/health')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['status'] == 'ok'


# ═══════════════════════════════════════════════════════════
# Files Route Blueprint Structure
# ═══════════════════════════════════════════════════════════

class TestFilesBlueprintStructure:
    def test_blueprint_exists(self):
        from routes.files import files_bp
        assert files_bp.name == 'files'

    def test_ignore_dirs_constant(self):
        from routes.files import IGNORE_DIRS
        assert '.git' in IGNORE_DIRS
        assert '__pycache__' in IGNORE_DIRS

    def test_shallow_dirs_constant(self):
        from routes.files import SHALLOW_DIRS
        assert '.venv' in SHALLOW_DIRS
        assert 'node_modules' in SHALLOW_DIRS


# ═══════════════════════════════════════════════════════════
# Files Route: _build_tree
# ═══════════════════════════════════════════════════════════

class TestBuildTree:
    def test_build_tree_empty_dir(self, tmp_path):
        from routes.files import _build_tree
        items = _build_tree(str(tmp_path))
        assert items == []

    def test_build_tree_with_files(self, tmp_path):
        from routes.files import _build_tree
        (tmp_path / 'app.py').write_text('print("hello")')
        (tmp_path / 'README.md').write_text('# Hello')
        items = _build_tree(str(tmp_path))
        names = [i['name'] for i in items]
        assert 'app.py' in names
        assert 'README.md' in names

    def test_build_tree_ignores_git(self, tmp_path):
        from routes.files import _build_tree
        (tmp_path / '.git').mkdir()
        (tmp_path / 'app.py').write_text('x')
        items = _build_tree(str(tmp_path))
        names = [i['name'] for i in items]
        assert '.git' not in names
        assert 'app.py' in names

    def test_build_tree_shallow_dirs(self, tmp_path):
        from routes.files import _build_tree
        venv = tmp_path / '.venv'
        venv.mkdir()
        (venv / 'pyvenv.cfg').write_text('home = /usr/bin')
        items = _build_tree(str(tmp_path))
        venv_item = [i for i in items if i['name'] == '.venv']
        assert len(venv_item) == 1
        assert venv_item[0].get('shallow') is True
        assert venv_item[0]['children'] == []

    def test_build_tree_recursive(self, tmp_path):
        from routes.files import _build_tree
        subdir = tmp_path / 'src'
        subdir.mkdir()
        (subdir / 'main.py').write_text('main()')
        items = _build_tree(str(tmp_path))
        src_item = [i for i in items if i['name'] == 'src']
        assert len(src_item) == 1
        assert src_item[0]['type'] == 'directory'
        child_names = [c['name'] for c in src_item[0]['children']]
        assert 'main.py' in child_names

    def test_build_tree_dirs_first(self, tmp_path):
        from routes.files import _build_tree
        (tmp_path / 'zzz_file.txt').write_text('x')
        (tmp_path / 'aaa_dir').mkdir()
        items = _build_tree(str(tmp_path))
        assert items[0]['name'] == 'aaa_dir'
        assert items[0]['type'] == 'directory'

    def test_build_tree_max_depth(self, tmp_path):
        from routes.files import _build_tree
        # Create nested dirs deeper than max_depth
        current = tmp_path
        for i in range(10):
            current = current / f'level{i}'
            current.mkdir()
            (current / 'file.txt').write_text('x')
        items = _build_tree(str(tmp_path), max_depth=2)
        # Should stop recursing after depth 2
        assert isinstance(items, list)


# ═══════════════════════════════════════════════════════════
# Files Route: _analyze_source
# ═══════════════════════════════════════════════════════════

class TestAnalyzeSource:
    def test_detect_argparse(self):
        from routes.files import _analyze_source
        result = _analyze_source("import argparse\nparser = ArgumentParser()")
        assert result['needsArgs'] is True
        assert result['hasArgparse'] is True
        assert result['argHint'] == '--help'

    def test_detect_sys_argv(self):
        from routes.files import _analyze_source
        result = _analyze_source("import sys\nfile = sys.argv[1]")
        assert result['needsArgs'] is True
        assert result['argHint'] == 'sample'

    def test_detect_stdin(self):
        from routes.files import _analyze_source
        result = _analyze_source("data = input()")
        assert result['readsStdin'] is True

    def test_detect_flask_server(self):
        from routes.files import _analyze_source
        result = _analyze_source("from flask import Flask\napp = Flask(__name__)\napp.run(port=8080)")
        assert result['isServer'] is True
        assert result['serverPort'] == 8080

    def test_detect_fastapi_server(self):
        from routes.files import _analyze_source
        result = _analyze_source("from fastapi import FastAPI\napp = FastAPI()")
        assert result['isServer'] is True

    def test_detect_json_data_format(self):
        from routes.files import _analyze_source
        result = _analyze_source("import json\ndata = json.loads(text)")
        assert result['dataFormat'] == 'json'

    def test_detect_csv_data_format(self):
        from routes.files import _analyze_source
        result = _analyze_source("import csv\nreader = csv.reader(f)")
        assert result['dataFormat'] == 'csv'

    def test_plain_script(self):
        from routes.files import _analyze_source
        result = _analyze_source("print('hello world')")
        assert result['needsArgs'] is False
        assert result['readsStdin'] is False
        assert result['isServer'] is False

    def test_docstring_extraction(self):
        from routes.files import _analyze_source
        result = _analyze_source('"""My awesome script for processing data."""\nprint("hi")')
        assert result['description'] is not None


# ═══════════════════════════════════════════════════════════
# Terminal Route Blueprint Structure
# ═══════════════════════════════════════════════════════════

class TestTerminalBlueprintStructure:
    def test_blueprint_exists(self):
        from routes.terminal import terminal_bp
        assert terminal_bp.name == 'terminal'


# ═══════════════════════════════════════════════════════════
# Terminal Route: _build_venv_env
# ═══════════════════════════════════════════════════════════

class TestBuildVenvEnv:
    def test_without_venv(self, tmp_path):
        from routes.terminal import _build_venv_env
        env = _build_venv_env(str(tmp_path))
        assert 'PATH' in env
        # Should not have VIRTUAL_ENV set to this workspace
        assert env.get('VIRTUAL_ENV', '') != str(tmp_path / '.venv')

    def test_with_venv_scripts(self, tmp_path):
        from routes.terminal import _build_venv_env
        # Create .venv/Scripts (Windows-style)
        scripts = tmp_path / '.venv' / 'Scripts'
        scripts.mkdir(parents=True)
        env = _build_venv_env(str(tmp_path))
        assert str(scripts) in env.get('PATH', '')
        assert env.get('VIRTUAL_ENV') == str(tmp_path / '.venv')

    def test_with_venv_bin(self, tmp_path):
        from routes.terminal import _build_venv_env
        # Create .venv/bin (Unix-style)
        bin_dir = tmp_path / '.venv' / 'bin'
        bin_dir.mkdir(parents=True)
        env = _build_venv_env(str(tmp_path))
        assert str(bin_dir) in env.get('PATH', '')


# ═══════════════════════════════════════════════════════════
# Chats Route Blueprint Structure
# ═══════════════════════════════════════════════════════════

class TestChatsBlueprintStructure:
    def test_blueprint_exists(self):
        from routes.chats import chats_bp
        assert chats_bp.name == 'chats'


# ═══════════════════════════════════════════════════════════
# Chats Route: Cancel Registry Functions
# ═══════════════════════════════════════════════════════════

class TestCancelRegistry:
    def test_register_and_get(self):
        import threading
        from routes.chats import _register_cancel_event, _get_cancel_event, _unregister_cancel_event
        event = threading.Event()
        _register_cancel_event('test-chat-1', event)
        retrieved = _get_cancel_event('test-chat-1')
        assert retrieved is event
        _unregister_cancel_event('test-chat-1')

    def test_get_nonexistent(self):
        from routes.chats import _get_cancel_event
        assert _get_cancel_event('nonexistent-chat-xyz') is None

    def test_unregister_cleans_up(self):
        import threading
        from routes.chats import _register_cancel_event, _get_cancel_event, _unregister_cancel_event
        event = threading.Event()
        _register_cancel_event('test-chat-2', event)
        _unregister_cancel_event('test-chat-2')
        assert _get_cancel_event('test-chat-2') is None

    def test_cancel_all_for_task(self):
        import threading
        from routes.chats import _register_cancel_event, _cancel_all_for_task, _unregister_cancel_event
        e1 = threading.Event()
        e2 = threading.Event()
        _register_cancel_event('chat-a', e1, task_id='task-x')
        _register_cancel_event('chat-b', e2, task_id='task-x')
        cancelled = _cancel_all_for_task('task-x')
        assert cancelled == 2
        assert e1.is_set()
        assert e2.is_set()
        # Cleanup
        _unregister_cancel_event('chat-a', task_id='task-x')
        _unregister_cancel_event('chat-b', task_id='task-x')

    def test_cancel_all_for_nonexistent_task(self):
        from routes.chats import _cancel_all_for_task
        cancelled = _cancel_all_for_task('nonexistent-task-xyz')
        assert cancelled == 0


# ═══════════════════════════════════════════════════════════
# Chats Route: Endpoint Tests
# ═══════════════════════════════════════════════════════════

class TestChatsEndpoints:
    def test_list_chats(self, client, mock_config):
        """List chats for a task — should return empty list for new task."""
        resp = client.get('/api/tasks/fake-task-id/chats')
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)

    def test_create_chat(self, client, mock_config):
        resp = client.post('/api/tasks/fake-task-id/chats')
        assert resp.status_code == 201
        data = resp.get_json()
        assert 'id' in data
        assert data['taskId'] == 'fake-task-id'

    def test_add_message_missing_task_id(self, client, mock_config):
        resp = client.post('/api/chats/some-chat-id/messages', json={
            'content': 'Hello',
            'role': 'user',
        })
        assert resp.status_code == 400
        assert 'taskId' in resp.get_json()['error']

    def test_add_message_invalid_role(self, client, mock_config):
        resp = client.post('/api/chats/some-chat-id/messages', json={
            'taskId': 'fake-task',
            'content': 'Hello',
            'role': 'hacker',
        })
        assert resp.status_code == 400
        assert 'Invalid role' in resp.get_json()['error']

    def test_add_message_too_long(self, client, mock_config):
        resp = client.post('/api/chats/some-chat-id/messages', json={
            'taskId': 'fake-task',
            'content': 'x' * 200_000,
            'role': 'user',
        })
        assert resp.status_code == 400
        assert 'too long' in resp.get_json()['error']

    def test_cancel_no_active(self, client, mock_config):
        resp = client.post('/api/chats/no-chat/cancel')
        assert resp.status_code == 200
        assert resp.get_json()['status'] == 'no_active_generation'

    def test_cancel_all_no_active(self, client, mock_config):
        resp = client.post('/api/tasks/no-task/cancel-all')
        assert resp.status_code == 200
        assert resp.get_json()['count'] == 0

    def test_stream_missing_task_id(self, client, mock_config):
        resp = client.get('/api/chats/some-chat/stream')
        assert resp.status_code == 400

    def test_cancel_review_no_active(self, client, mock_config):
        resp = client.post('/api/chats/no-chat/cancel-review')
        assert resp.status_code == 200
        assert resp.get_json()['status'] == 'no_active_review'


# ═══════════════════════════════════════════════════════════
# Tasks Route Endpoint Tests
# ═══════════════════════════════════════════════════════════

class TestTasksEndpoints:
    def test_list_tasks_empty(self, client, mock_config):
        resp = client.get('/api/tasks')
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)

    def test_create_task_missing_fields(self, client, mock_config):
        resp = client.post('/api/tasks', json={'details': 'Build something'})
        assert resp.status_code == 400

    def test_get_task_not_found(self, client, mock_config):
        resp = client.get('/api/tasks/nonexistent-id')
        assert resp.status_code == 404

    def test_delete_task(self, client, mock_config):
        resp = client.delete('/api/tasks/nonexistent-id')
        assert resp.status_code == 200

    def test_batch_delete_no_ids(self, client, mock_config):
        resp = client.post('/api/tasks/batch-delete', json={'taskIds': []})
        assert resp.status_code == 400

    def test_batch_delete_too_many(self, client, mock_config):
        ids = [f'id-{i}' for i in range(150)]
        resp = client.post('/api/tasks/batch-delete', json={'taskIds': ids})
        assert resp.status_code == 400

    def test_batch_delete_invalid_format(self, client, mock_config):
        resp = client.post('/api/tasks/batch-delete', json={'taskIds': [123, '../../etc']})
        data = resp.get_json()
        # Invalid formats should produce errors
        assert len(data.get('errors', [])) > 0

    def test_pause_task_nonexistent(self, client, mock_config):
        resp = client.post('/api/tasks/nonexistent/pause')
        assert resp.status_code == 200
        assert resp.get_json()['status'] == 'ok'

    def test_update_task_not_found(self, client, mock_config):
        resp = client.patch('/api/tasks/nonexistent', json={'status': 'Completed'})
        assert resp.status_code == 404

    def test_update_task_invalid_status(self, client, mock_config):
        from services.storage import StorageService
        StorageService.save_json('tasks', 'test-upd.json', {
            'id': 'test-upd', 'status': 'Pending',
        })
        resp = client.patch('/api/tasks/test-upd', json={'status': 'InvalidStatus'})
        assert resp.status_code == 400

    def test_cleanup_invalid_max_age(self, client, mock_config):
        resp = client.post('/api/tasks/cleanup', json={'maxAgeDays': -1})
        assert resp.status_code == 400

    def test_cleanup_default(self, client, mock_config):
        resp = client.post('/api/tasks/cleanup', json={})
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'cleaned' in data

    def test_reformat_task_missing_details(self, client, mock_config):
        resp = client.post('/api/reformat-task', json={'details': ''})
        assert resp.status_code == 400

    def test_reformat_task_too_long(self, client, mock_config):
        resp = client.post('/api/reformat-task', json={'details': 'x' * 20_000})
        assert resp.status_code == 400

    def test_next_step_not_found(self, client, mock_config):
        resp = client.get('/api/tasks/nonexistent/next-step')
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════
# Tasks Route Blueprint Structure
# ═══════════════════════════════════════════════════════════

class TestTasksBlueprintStructure:
    def test_blueprint_exists(self):
        from routes.tasks import tasks_bp
        assert tasks_bp.name == 'tasks'


# ═══════════════════════════════════════════════════════════
# Terminal Route: Process Registry
# ═══════════════════════════════════════════════════════════

class TestTerminalProcessRegistry:
    def test_register_and_get(self):
        import threading
        from routes.terminal import _register_process, _get_process, _unregister_process

        class FakeProcess:
            pass

        proc = FakeProcess()
        cancel = threading.Event()
        _register_process('sess-1', proc, cancel)
        entry = _get_process('sess-1')
        assert entry is not None
        assert entry['process'] is proc
        assert entry['cancel_event'] is cancel
        _unregister_process('sess-1')

    def test_get_nonexistent(self):
        from routes.terminal import _get_process
        assert _get_process('nonexistent-session') is None

    def test_unregister_cleans_up(self):
        import threading
        from routes.terminal import _register_process, _get_process, _unregister_process

        class FakeProcess:
            pass

        _register_process('sess-2', FakeProcess(), threading.Event())
        _unregister_process('sess-2')
        assert _get_process('sess-2') is None


# ═══════════════════════════════════════════════════════════
# Terminal Route Endpoint Tests
# ═══════════════════════════════════════════════════════════

class TestTerminalEndpoints:
    def test_stream_no_workspace(self, client, mock_config):
        resp = client.post('/api/tasks/nonexistent/terminal/stream',
                           json={'command': 'echo hello'})
        assert resp.status_code == 404

    def test_stream_no_command(self, client, mock_config):
        # Need a task with a workspace
        from services.storage import StorageService
        ws = os.path.join(mock_config, 'workspaces', 'test-ws')
        os.makedirs(ws, exist_ok=True)
        StorageService.save_json('tasks', 'term-task.json', {
            'id': 'term-task', 'workspacePath': ws,
        })
        resp = client.post('/api/tasks/term-task/terminal/stream', json={'command': ''})
        assert resp.status_code == 400

    def test_stream_command_too_long(self, client, mock_config):
        from services.storage import StorageService
        ws = os.path.join(mock_config, 'workspaces', 'test-ws2')
        os.makedirs(ws, exist_ok=True)
        StorageService.save_json('tasks', 'term-task2.json', {
            'id': 'term-task2', 'workspacePath': ws,
        })
        resp = client.post('/api/tasks/term-task2/terminal/stream',
                           json={'command': 'x' * 3000})
        assert resp.status_code == 400

    def test_kill_nonexistent(self, client, mock_config):
        resp = client.post('/api/terminal/nonexistent-session/kill')
        assert resp.status_code == 404

    def test_cancel_execution_no_active(self, client, mock_config):
        resp = client.post('/api/tasks/nonexistent/execute/cancel')
        assert resp.status_code == 200
        assert resp.get_json()['status'] == 'no_active_execution'
