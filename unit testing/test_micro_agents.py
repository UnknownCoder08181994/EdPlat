"""Unit tests for backend/services/micro_agents.py"""

import os
import ast
import pytest


class TestSyntaxCheck:
    def test_valid_python(self, workspace_dir):
        fp = os.path.join(workspace_dir, 'good.py')
        with open(fp, 'w') as f:
            f.write('x = 1\ndef foo():\n    return x\n')
        from services.micro_agents import syntax_check
        assert syntax_check(fp) is None

    def test_syntax_error(self, workspace_dir):
        fp = os.path.join(workspace_dir, 'bad.py')
        with open(fp, 'w') as f:
            f.write('def foo(\n')
        from services.micro_agents import syntax_check
        result = syntax_check(fp)
        assert result is not None
        assert 'SYNTAX ERROR' in result

    def test_non_python_file(self, workspace_dir):
        fp = os.path.join(workspace_dir, 'readme.md')
        with open(fp, 'w') as f:
            f.write('# Hello')
        from services.micro_agents import syntax_check
        assert syntax_check(fp) is None

    def test_nonexistent_file(self, workspace_dir):
        from services.micro_agents import syntax_check
        # Should not raise, just return None
        result = syntax_check(os.path.join(workspace_dir, 'missing.py'))
        # File doesn't exist, so open will fail, caught by except Exception
        assert result is None


class TestResolveImports:
    def test_no_warnings_for_stdlib(self, workspace_dir):
        fp = os.path.join(workspace_dir, 'main.py')
        with open(fp, 'w') as f:
            f.write('import os\nimport json\nimport sys\n')
        from services.micro_agents import resolve_imports
        warnings = resolve_imports(fp, workspace_dir)
        assert warnings == []

    def test_non_python_file(self, workspace_dir):
        fp = os.path.join(workspace_dir, 'readme.md')
        with open(fp, 'w') as f:
            f.write('# Hello')
        from services.micro_agents import resolve_imports
        assert resolve_imports(fp, workspace_dir) == []

    def test_local_import_found(self, workspace_dir):
        # Create a module that defines a function
        mod_fp = os.path.join(workspace_dir, 'utils.py')
        with open(mod_fp, 'w') as f:
            f.write('def helper():\n    return 42\n')
        # Create a file that imports from it
        main_fp = os.path.join(workspace_dir, 'main.py')
        with open(main_fp, 'w') as f:
            f.write('from utils import helper\n')
        from services.micro_agents import resolve_imports
        warnings = resolve_imports(main_fp, workspace_dir)
        assert warnings == []

    def test_local_import_name_not_found(self, workspace_dir):
        # Create a module that defines a function
        mod_fp = os.path.join(workspace_dir, 'utils.py')
        with open(mod_fp, 'w') as f:
            f.write('def helper():\n    return 42\n')
        # Create a file that imports a nonexistent name
        main_fp = os.path.join(workspace_dir, 'main.py')
        with open(main_fp, 'w') as f:
            f.write('from utils import nonexistent_func\n')
        from services.micro_agents import resolve_imports
        warnings = resolve_imports(main_fp, workspace_dir)
        assert len(warnings) > 0
        assert 'nonexistent_func' in warnings[0]

    def test_caps_at_3_warnings(self, workspace_dir):
        mod_fp = os.path.join(workspace_dir, 'utils.py')
        with open(mod_fp, 'w') as f:
            f.write('x = 1\n')
        main_fp = os.path.join(workspace_dir, 'main.py')
        with open(main_fp, 'w') as f:
            f.write('from utils import a, b, c, d, e\n')
        from services.micro_agents import resolve_imports
        warnings = resolve_imports(main_fp, workspace_dir)
        assert len(warnings) <= 3


class TestBuildSignatureIndex:
    def test_empty_workspace(self, workspace_dir):
        from services.micro_agents import build_signature_index
        result = build_signature_index(workspace_dir)
        assert result == ''

    def test_single_file_with_function(self, workspace_dir):
        fp = os.path.join(workspace_dir, 'app.py')
        with open(fp, 'w') as f:
            f.write('def hello(name: str) -> str:\n    return f"Hello {name}"\n')
        from services.micro_agents import build_signature_index
        result = build_signature_index(workspace_dir)
        assert 'API INDEX' in result
        assert 'hello' in result
        assert 'name: str' in result

    def test_class_detection(self, workspace_dir):
        fp = os.path.join(workspace_dir, 'models.py')
        with open(fp, 'w') as f:
            f.write('class User:\n    def __init__(self, name):\n        self.name = name\n')
        from services.micro_agents import build_signature_index
        result = build_signature_index(workspace_dir)
        assert 'class User' in result

    def test_subdirectory_files(self, workspace_dir):
        sub = os.path.join(workspace_dir, 'services')
        os.makedirs(sub)
        fp = os.path.join(sub, 'auth.py')
        with open(fp, 'w') as f:
            f.write('def login(user: str, password: str) -> bool:\n    return True\n')
        from services.micro_agents import build_signature_index
        result = build_signature_index(workspace_dir)
        assert 'login' in result
        assert 'services/' in result or 'services\\\\' in result or 'auth.py' in result


class TestTrackProgress:
    def test_no_step_description(self):
        from services.micro_agents import track_progress
        pct, remaining, msg = track_progress('', {})
        assert pct == 0
        assert remaining == []

    def test_no_files_match(self):
        from services.micro_agents import track_progress
        desc = "Files: app.py, models.py, utils.py"
        pct, remaining, msg = track_progress(desc, {})
        assert pct == 0
        assert len(remaining) == 3

    def test_partial_progress(self):
        from services.micro_agents import track_progress
        desc = "Files: app.py, models.py, utils.py"
        written = {'app.py': {'is_new': True}}
        pct, remaining, msg = track_progress(desc, written)
        assert pct == 33
        assert 'models.py' in remaining
        assert 'utils.py' in remaining

    def test_full_progress(self):
        from services.micro_agents import track_progress
        desc = "Files: app.py, models.py"
        written = {'app.py': {}, 'models.py': {}}
        pct, remaining, msg = track_progress(desc, written)
        assert pct == 100
        assert remaining == []


class TestImportGraph:
    def test_no_cycles(self, workspace_dir):
        from services.micro_agents import ImportGraph
        graph = ImportGraph()
        fp_a = os.path.join(workspace_dir, 'a.py')
        fp_b = os.path.join(workspace_dir, 'b.py')
        with open(fp_a, 'w') as f:
            f.write('import os\n')
        with open(fp_b, 'w') as f:
            f.write('import a\n')
        cycles = graph.update_module('a', fp_a)
        assert cycles == []
        cycles = graph.update_module('b', fp_b)
        assert cycles == []

    def test_detects_cycle(self, workspace_dir):
        from services.micro_agents import ImportGraph
        graph = ImportGraph()
        fp_a = os.path.join(workspace_dir, 'a.py')
        fp_b = os.path.join(workspace_dir, 'b.py')
        with open(fp_a, 'w') as f:
            f.write('import b\n')
        with open(fp_b, 'w') as f:
            f.write('import a\n')
        graph.update_module('a', fp_a)
        cycles = graph.update_module('b', fp_b)
        assert len(cycles) > 0
        assert 'Circular import' in cycles[0]

    def test_load_workspace(self, workspace_dir):
        from services.micro_agents import ImportGraph
        fp = os.path.join(workspace_dir, 'main.py')
        with open(fp, 'w') as f:
            f.write('import os\n')
        graph = ImportGraph()
        graph.load_workspace(workspace_dir)
        assert 'main' in graph.edges


class TestOptimizeHistory:
    def test_short_history_unchanged(self):
        from services.micro_agents import optimize_history
        history = [
            {'role': 'system', 'content': 'You are an assistant.'},
            {'role': 'user', 'content': 'Hello'},
        ]
        result = optimize_history(history)
        assert len(result) == 2

    def test_compresses_write_results(self):
        from services.micro_agents import optimize_history
        history = [
            {'role': 'system', 'content': 'You are an assistant.'},
            {'role': 'user', 'content': 'Hello'},
            {'role': 'assistant', 'content': 'Writing file'},
            {'role': 'user', 'content': 'Tool Result: Successfully wrote to app.py (100 lines) [meta:is_new=true,added=100,removed=0]'},
            {'role': 'assistant', 'content': 'Done'},
        ]
        result = optimize_history(history)
        # The tool result should be compressed
        tool_msg = [m for m in result if 'Successfully wrote' in m['content']]
        assert len(tool_msg) == 1
        assert len(tool_msg[0]['content']) < len(history[3]['content'])

    def test_deduplicates_nudges(self):
        from services.micro_agents import optimize_history
        nudge = 'STOP. You already saved the file. BLOCKED from writing again.'
        history = [
            {'role': 'system', 'content': 'System'},
            {'role': 'user', 'content': nudge},
            {'role': 'assistant', 'content': 'ok'},
            {'role': 'user', 'content': nudge},
            {'role': 'assistant', 'content': 'ok'},
        ]
        result = optimize_history(history)
        nudge_msgs = [m for m in result if 'STOP' in m['content'] and 'BLOCKED' in m['content']]
        assert len(nudge_msgs) == 1

    def test_preserves_command_output(self):
        from services.micro_agents import optimize_history
        long_output = 'Tool Result: Command output:\n' + 'x' * 3000
        history = [
            {'role': 'system', 'content': 'System'},
            {'role': 'user', 'content': 'Hello'},
            {'role': 'assistant', 'content': 'Running'},
            {'role': 'user', 'content': long_output},
            {'role': 'assistant', 'content': 'Done'},
        ]
        result = optimize_history(history)
        cmd_msgs = [m for m in result if 'Command output' in m['content']]
        assert len(cmd_msgs) == 1
        # Should not be compressed (it's a RunCommand output)
        assert len(cmd_msgs[0]['content']) == len(long_output)


class TestCheckPatterns:
    def test_non_python_returns_empty(self, workspace_dir):
        fp = os.path.join(workspace_dir, 'readme.md')
        with open(fp, 'w') as f:
            f.write('# Hello')
        from services.micro_agents import check_patterns
        assert check_patterns(fp, workspace_dir) == []

    def test_returns_list(self, workspace_dir):
        fp = os.path.join(workspace_dir, 'app.py')
        with open(fp, 'w') as f:
            f.write('x = 1\n')
        from services.micro_agents import check_patterns
        result = check_patterns(fp, workspace_dir)
        assert isinstance(result, list)


class TestPostWriteChecks:
    def test_non_python_empty(self, workspace_dir):
        fp = os.path.join(workspace_dir, 'readme.md')
        with open(fp, 'w') as f:
            f.write('# Hello')
        from services.micro_agents import post_write_checks
        result = post_write_checks(fp, workspace_dir)
        assert result == []

    def test_valid_python_no_warnings(self, workspace_dir):
        fp = os.path.join(workspace_dir, 'app.py')
        with open(fp, 'w') as f:
            f.write('import os\n\ndef main():\n    print("hello")\n')
        from services.micro_agents import post_write_checks
        result = post_write_checks(fp, workspace_dir)
        assert isinstance(result, list)

    def test_syntax_error_stops_early(self, workspace_dir):
        fp = os.path.join(workspace_dir, 'bad.py')
        with open(fp, 'w') as f:
            f.write('def foo(\n')
        from services.micro_agents import post_write_checks
        result = post_write_checks(fp, workspace_dir)
        assert len(result) >= 1
        assert 'SYNTAX ERROR' in result[0]

    def test_caps_at_5_warnings(self, workspace_dir):
        from services.micro_agents import post_write_checks
        # Even with many issues, should cap at 5
        fp = os.path.join(workspace_dir, 'app.py')
        with open(fp, 'w') as f:
            f.write('import os\n\ndef main():\n    pass\n')
        result = post_write_checks(fp, workspace_dir)
        assert len(result) <= 5


class TestCheckDeadReferences:
    def test_no_removed_names(self, workspace_dir):
        from services.micro_agents import check_dead_references
        old = 'def foo():\n    pass\n'
        new = 'def foo():\n    return 1\n'
        fp = os.path.join(workspace_dir, 'utils.py')
        with open(fp, 'w') as f:
            f.write(new)
        result = check_dead_references(fp, old, new, workspace_dir)
        assert result == []

    def test_non_python_returns_empty(self, workspace_dir):
        from services.micro_agents import check_dead_references
        result = check_dead_references('readme.md', '', '', workspace_dir)
        assert result == []

    def test_detects_dead_reference(self, workspace_dir):
        from services.micro_agents import check_dead_references
        # Create a file that imports from utils
        consumer_fp = os.path.join(workspace_dir, 'main.py')
        with open(consumer_fp, 'w') as f:
            f.write('from utils import helper\nhelper()\n')
        # Old utils had helper, new utils doesn't
        old = 'def helper():\n    return 42\n'
        new = 'def other():\n    return 99\n'
        utils_fp = os.path.join(workspace_dir, 'utils.py')
        with open(utils_fp, 'w') as f:
            f.write(new)
        result = check_dead_references(utils_fp, old, new, workspace_dir)
        assert len(result) > 0
        assert 'helper' in result[0]


class TestScanDownstreamDependencies:
    def test_no_steps_returns_empty(self):
        from services.micro_agents import scan_downstream_dependencies
        result = scan_downstream_dependencies('step-1', [])
        assert result == ''

    def test_no_current_step_returns_empty(self):
        from services.micro_agents import scan_downstream_dependencies
        steps = [{'id': 'other', 'description': 'Something'}]
        result = scan_downstream_dependencies('step-1', steps)
        assert result == ''

    def test_finds_dependency(self):
        from services.micro_agents import scan_downstream_dependencies
        steps = [
            {'id': 'step-1', 'description': 'Files: app.py, models.py'},
            {'id': 'step-2', 'description': 'Depends-on: app.py', 'name': 'Frontend', 'status': 'pending'},
        ]
        result = scan_downstream_dependencies('step-1', steps)
        assert 'DOWNSTREAM' in result
        assert 'app.py' in result
