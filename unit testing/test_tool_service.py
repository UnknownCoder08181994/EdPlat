"""Unit tests for backend/services/tool_service.py"""

import os
import pytest
from conftest import write_text, read_text


class TestToolService:
    @pytest.fixture
    def ts(self, workspace_dir):
        from services.tool_service import ToolService
        return ToolService(workspace_dir)

    # ── WriteFile ────────────────────────────────────────────────

    def test_write_new_file(self, ts, workspace_dir):
        result = ts.execute_tool('WriteFile', {
            'path': 'hello.py',
            'content': 'print("hello")\n',
        })
        assert 'Successfully' in result
        assert os.path.isfile(os.path.join(workspace_dir, 'hello.py'))

    def test_write_creates_dirs(self, ts, workspace_dir):
        result = ts.execute_tool('WriteFile', {
            'path': 'src/utils/helper.py',
            'content': 'def helper(): pass\n',
        })
        assert 'Successfully' in result
        assert os.path.isfile(os.path.join(workspace_dir, 'src', 'utils', 'helper.py'))

    def test_write_meta_in_result(self, ts):
        result = ts.execute_tool('WriteFile', {
            'path': 'test.py',
            'content': 'x = 1\n',
        })
        assert '[meta:' in result
        assert 'is_new=' in result

    def test_write_overwrite_file(self, ts, workspace_dir):
        ts.execute_tool('WriteFile', {'path': 'app.py', 'content': 'v1\n'})
        result = ts.execute_tool('WriteFile', {'path': 'app.py', 'content': 'v2\n'})
        assert 'Successfully' in result
        content = read_text(os.path.join(workspace_dir, 'app.py'))
        assert content == 'v2\n'

    def test_write_markdown_unescapes_newlines(self, ts, workspace_dir):
        """Markdown files should have literal \\n unescaped to real newlines."""
        ts.execute_tool('WriteFile', {
            'path': 'readme.md',
            'content': 'Line 1\\nLine 2\\nLine 3',
        })
        content = read_text(os.path.join(workspace_dir, 'readme.md'))
        assert '\n' in content
        assert '\\n' not in content

    def test_write_python_preserves_backslash_n(self, ts, workspace_dir):
        """Source code should preserve literal \\n sequences."""
        ts.execute_tool('WriteFile', {
            'path': 'code.py',
            'content': 'x = "hello\\nworld"',
        })
        content = read_text(os.path.join(workspace_dir, 'code.py'))
        # The literal \n should be preserved as two characters
        assert '\\n' in content

    # ── ReadFile ─────────────────────────────────────────────────

    def test_read_file(self, ts, workspace_dir):
        write_text(os.path.join(workspace_dir, 'data.txt'), 'hello world')
        result = ts.execute_tool('ReadFile', {'path': 'data.txt'})
        assert 'hello world' in result

    def test_read_nonexistent(self, ts):
        result = ts.execute_tool('ReadFile', {'path': 'nope.txt'})
        assert 'Error' in result or 'not found' in result.lower()

    # ── EditFile ─────────────────────────────────────────────────

    def test_edit_file(self, ts, workspace_dir):
        write_text(os.path.join(workspace_dir, 'app.py'), 'x = 1\ny = 2\n')
        result = ts.execute_tool('EditFile', {
            'path': 'app.py',
            'old_string': 'x = 1',
            'new_string': 'x = 99',
        })
        assert 'Successfully' in result
        content = read_text(os.path.join(workspace_dir, 'app.py'))
        assert 'x = 99' in content

    def test_edit_file_not_found(self, ts):
        result = ts.execute_tool('EditFile', {
            'path': 'nope.py',
            'old_string': 'x',
            'new_string': 'y',
        })
        assert 'Error' in result or 'not found' in result.lower()

    def test_edit_string_not_found(self, ts, workspace_dir):
        write_text(os.path.join(workspace_dir, 'app.py'), 'x = 1\n')
        result = ts.execute_tool('EditFile', {
            'path': 'app.py',
            'old_string': 'NONEXISTENT STRING',
            'new_string': 'replacement',
        })
        assert 'not found' in result.lower() or 'error' in result.lower()

    def test_edit_markdown_unescapes(self, ts, workspace_dir):
        """EditFile on .md files should unescape \\n."""
        write_text(os.path.join(workspace_dir, 'doc.md'), 'Hello\nWorld\n')
        result = ts.execute_tool('EditFile', {
            'path': 'doc.md',
            'old_string': 'Hello\\nWorld',
            'new_string': 'Hi\\nEarth',
        })
        assert 'Successfully' in result

    def test_edit_python_no_unescape(self, ts, workspace_dir):
        """EditFile on .py should NOT unescape \\n — it's a literal backslash-n."""
        write_text(os.path.join(workspace_dir, 'code.py'), 'msg = "a\\nb"\n')
        result = ts.execute_tool('EditFile', {
            'path': 'code.py',
            'old_string': 'msg = "a\\nb"',
            'new_string': 'msg = "x\\ny"',
        })
        # Should find the match because \\n is NOT unescaped
        assert 'Successfully' in result

    # ── ListFiles ────────────────────────────────────────────────

    def test_list_files(self, ts, workspace_dir):
        write_text(os.path.join(workspace_dir, 'a.py'), '')
        write_text(os.path.join(workspace_dir, 'b.txt'), '')
        result = ts.execute_tool('ListFiles', {'path': '.'})
        assert 'a.py' in result
        assert 'b.txt' in result

    # ── Path validation ──────────────────────────────────────────

    def test_path_escape_blocked(self, ts):
        """Paths trying to escape the workspace should be blocked."""
        result = ts.execute_tool('ReadFile', {'path': '../../etc/passwd'})
        assert 'Error' in result or 'outside' in result.lower() or 'not found' in result.lower()

    # ── Unknown tool ─────────────────────────────────────────────

    def test_unknown_tool(self, ts):
        result = ts.execute_tool('FakeTool', {})
        assert 'Error' in result or 'unknown' in result.lower() or 'not supported' in result.lower()
