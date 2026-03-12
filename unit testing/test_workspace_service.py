"""Unit tests for backend/services/workspace_service.py"""

import os
import pytest

from services.workspace_service import (
    ignore_copy_dirs,
    ignore_windows_reserved,
    COPY_IGNORE,
    WINDOWS_RESERVED_NAMES,
)


class TestIgnoreCopyDirs:
    def test_ignores_git(self):
        result = ignore_copy_dirs('/some/dir', ['.git', 'src', 'main.py'])
        assert '.git' in result
        assert 'src' not in result
        assert 'main.py' not in result

    def test_ignores_pycache(self):
        result = ignore_copy_dirs('/some/dir', ['__pycache__', 'app.py'])
        assert '__pycache__' in result

    def test_ignores_node_modules(self):
        result = ignore_copy_dirs('/some/dir', ['node_modules', 'index.js'])
        assert 'node_modules' in result

    def test_ignores_venv(self):
        result = ignore_copy_dirs('/some/dir', ['.venv', 'venv', 'app.py'])
        assert '.venv' in result
        assert 'venv' in result

    def test_ignores_windows_reserved(self):
        result = ignore_copy_dirs('/some/dir', ['CON.txt', 'NUL.log', 'app.py'])
        assert 'CON.txt' in result
        assert 'NUL.log' in result
        assert 'app.py' not in result

    def test_all_copy_ignore_items(self):
        files = list(COPY_IGNORE) + ['keep_me.py']
        result = ignore_copy_dirs('/some/dir', files)
        for item in COPY_IGNORE:
            assert item in result
        assert 'keep_me.py' not in result


class TestIgnoreWindowsReserved:
    def test_ignores_con(self):
        result = ignore_windows_reserved('/dir', ['CON', 'app.py'])
        assert 'CON' in result
        assert 'app.py' not in result

    def test_ignores_com_ports(self):
        result = ignore_windows_reserved('/dir', ['COM1.txt', 'COM9.log'])
        assert 'COM1.txt' in result
        assert 'COM9.log' in result

    def test_ignores_lpt_ports(self):
        result = ignore_windows_reserved('/dir', ['LPT1', 'LPT9.bin'])
        assert 'LPT1' in result
        assert 'LPT9.bin' in result

    def test_ignores_venv(self):
        result = ignore_windows_reserved('/dir', ['.venv', 'venv', 'keep.py'])
        assert '.venv' in result
        assert 'venv' in result
        assert 'keep.py' not in result

    def test_case_insensitive(self):
        result = ignore_windows_reserved('/dir', ['con.txt', 'nul.log'])
        assert 'con.txt' in result
        assert 'nul.log' in result

    def test_normal_files_pass(self):
        result = ignore_windows_reserved('/dir', ['main.py', 'config.json', 'readme.md'])
        assert len(result) == 0


class TestWindowsReservedNames:
    def test_all_names_present(self):
        assert 'CON' in WINDOWS_RESERVED_NAMES
        assert 'PRN' in WINDOWS_RESERVED_NAMES
        assert 'AUX' in WINDOWS_RESERVED_NAMES
        assert 'NUL' in WINDOWS_RESERVED_NAMES
        for i in range(1, 10):
            assert f'COM{i}' in WINDOWS_RESERVED_NAMES
            assert f'LPT{i}' in WINDOWS_RESERVED_NAMES
