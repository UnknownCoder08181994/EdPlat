"""Shared test fixtures for the zenflow-rebuild unit tests.

Adds the backend directory to sys.path so all imports work,
and provides common fixtures for temp directories, mock LLM, etc.
"""

import os
import sys
import json
import shutil
import tempfile
import pytest

# Add backend to sys.path so we can import backend modules directly
BACKEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'backend')
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


@pytest.fixture
def tmp_dir(tmp_path):
    """Provide a temporary directory that auto-cleans."""
    return str(tmp_path)


@pytest.fixture
def storage_dir(tmp_path):
    """Provide a temporary storage directory with standard subdirs."""
    sd = str(tmp_path / 'storage')
    os.makedirs(os.path.join(sd, 'projects'), exist_ok=True)
    os.makedirs(os.path.join(sd, 'tasks'), exist_ok=True)
    os.makedirs(os.path.join(sd, 'workspaces'), exist_ok=True)
    os.makedirs(os.path.join(sd, 'llm_logs'), exist_ok=True)
    return sd


@pytest.fixture
def workspace_dir(tmp_path):
    """Provide a temporary workspace directory."""
    ws = str(tmp_path / 'workspace')
    os.makedirs(ws, exist_ok=True)
    return ws


@pytest.fixture
def plan_file(tmp_path):
    """Provide a temporary plan.md file path (not yet created)."""
    return str(tmp_path / 'plan.md')


@pytest.fixture
def mock_config(tmp_path, monkeypatch):
    """Monkey-patch Config to use temp directories."""
    import config
    sd = str(tmp_path / 'storage')
    os.makedirs(os.path.join(sd, 'projects'), exist_ok=True)
    os.makedirs(os.path.join(sd, 'tasks'), exist_ok=True)
    os.makedirs(os.path.join(sd, 'workspaces'), exist_ok=True)
    os.makedirs(os.path.join(sd, 'llm_logs'), exist_ok=True)

    monkeypatch.setattr(config.Config, 'STORAGE_DIR', sd)
    monkeypatch.setattr(config.Config, 'BASE_DIR', BACKEND_DIR)
    monkeypatch.setattr(config.Config, 'PROJECT_ROOT', os.path.dirname(BACKEND_DIR))
    return sd


def write_json(path, data):
    """Helper to write a JSON file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)


def read_json(path):
    """Helper to read a JSON file."""
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def write_text(path, content):
    """Helper to write a text file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


def read_text(path):
    """Helper to read a text file."""
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()
