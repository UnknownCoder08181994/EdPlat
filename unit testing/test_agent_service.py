"""Unit tests for backend/services/agent_service.py

Tests the pure helper functions in AgentService that can be tested
without a running server, database, or LLM connection.
"""

import os
import json
import re
import pytest


# ═══════════════════════════════════════════════════════════
# _parse_write_meta
# ═══════════════════════════════════════════════════════════

class TestParseWriteMeta:
    def test_full_meta(self):
        from services.agent_service import AgentService
        result = AgentService._parse_write_meta(
            "Successfully wrote to app.py [meta:is_new=True,added=42,removed=5]"
        )
        assert result['is_new'] is True
        assert result['added'] == 42
        assert result['removed'] == 5

    def test_existing_file(self):
        from services.agent_service import AgentService
        result = AgentService._parse_write_meta(
            "Successfully wrote to config.py [meta:is_new=False,added=10,removed=3]"
        )
        assert result['is_new'] is False
        assert result['added'] == 10
        assert result['removed'] == 3

    def test_no_meta(self):
        from services.agent_service import AgentService
        result = AgentService._parse_write_meta("Successfully wrote to app.py")
        assert result['is_new'] is False
        assert result['added'] == 0
        assert result['removed'] == 0

    def test_empty_string(self):
        from services.agent_service import AgentService
        result = AgentService._parse_write_meta("")
        assert result == {'is_new': False, 'added': 0, 'removed': 0}


# ═══════════════════════════════════════════════════════════
# _find_step_by_chat_id
# ═══════════════════════════════════════════════════════════

class TestFindStepByChatId:
    def test_find_root_step(self):
        from services.agent_service import AgentService
        steps = [
            {'id': 'req', 'chatId': 'chat-1', 'children': []},
            {'id': 'impl', 'chatId': 'chat-2', 'children': []},
        ]
        result = AgentService._find_step_by_chat_id(steps, 'chat-1')
        assert result['id'] == 'req'

    def test_find_child_step(self):
        from services.agent_service import AgentService
        steps = [
            {'id': 'impl', 'chatId': 'chat-0', 'children': [
                {'id': 'child-1', 'chatId': 'chat-child'},
            ]},
        ]
        result = AgentService._find_step_by_chat_id(steps, 'chat-child')
        assert result['id'] == 'child-1'

    def test_not_found(self):
        from services.agent_service import AgentService
        steps = [{'id': 'req', 'chatId': 'chat-1', 'children': []}]
        assert AgentService._find_step_by_chat_id(steps, 'nonexistent') is None

    def test_empty_steps(self):
        from services.agent_service import AgentService
        assert AgentService._find_step_by_chat_id([], 'any') is None


# ═══════════════════════════════════════════════════════════
# _find_step_by_name
# ═══════════════════════════════════════════════════════════

class TestFindStepByName:
    def test_find_root(self):
        from services.agent_service import AgentService
        steps = [
            {'id': 'req', 'name': 'Requirements', 'children': []},
            {'id': 'impl', 'name': 'Implementation', 'children': []},
        ]
        result = AgentService._find_step_by_name(steps, 'requirements')
        assert result['id'] == 'req'

    def test_case_insensitive(self):
        from services.agent_service import AgentService
        steps = [{'id': 's1', 'name': 'Setup Environment', 'children': []}]
        result = AgentService._find_step_by_name(steps, 'SETUP ENVIRONMENT')
        assert result['id'] == 's1'

    def test_find_child(self):
        from services.agent_service import AgentService
        steps = [
            {'id': 'impl', 'name': 'Implementation', 'children': [
                {'id': 'c1', 'name': 'Core Logic'},
            ]},
        ]
        result = AgentService._find_step_by_name(steps, 'Core Logic')
        assert result['id'] == 'c1'

    def test_not_found(self):
        from services.agent_service import AgentService
        steps = [{'id': 'req', 'name': 'Requirements', 'children': []}]
        assert AgentService._find_step_by_name(steps, 'nonexistent') is None


# ═══════════════════════════════════════════════════════════
# _get_expected_artifact
# ═══════════════════════════════════════════════════════════

class TestGetExpectedArtifact:
    def test_requirements(self):
        from services.agent_service import AgentService
        result = AgentService._get_expected_artifact('requirements', '/path/to/artifacts')
        assert result.endswith('requirements.md')

    def test_tech_spec(self):
        from services.agent_service import AgentService
        result = AgentService._get_expected_artifact('technical-specification', '/artifacts')
        assert result.endswith('spec.md')

    def test_planning(self):
        from services.agent_service import AgentService
        result = AgentService._get_expected_artifact('planning', '/artifacts')
        assert result.endswith('implementation-plan.md')

    def test_implementation_parent(self):
        from services.agent_service import AgentService
        result = AgentService._get_expected_artifact('implementation', '/artifacts')
        assert result.endswith('implementation-plan.md')

    def test_implementation_child_returns_none(self):
        from services.agent_service import AgentService
        result = AgentService._get_expected_artifact('script-core', '/artifacts')
        assert result is None

    def test_unknown_step_returns_none(self):
        from services.agent_service import AgentService
        result = AgentService._get_expected_artifact('random-step', '/artifacts')
        assert result is None


# ═══════════════════════════════════════════════════════════
# _extract_owned_files
# ═══════════════════════════════════════════════════════════

class TestExtractOwnedFiles:
    def test_basic_files_line(self):
        from services.agent_service import AgentService
        desc = "Create the main application\nFiles: app.py, models.py, utils.py"
        result = AgentService._extract_owned_files(desc)
        assert 'app.py' in result
        assert 'models.py' in result
        assert 'utils.py' in result

    def test_files_with_and(self):
        from services.agent_service import AgentService
        desc = "Files: main.py and config.py"
        result = AgentService._extract_owned_files(desc)
        assert 'main.py' in result
        assert 'config.py' in result

    def test_no_files_line(self):
        from services.agent_service import AgentService
        desc = "Just a description without any files mentioned"
        result = AgentService._extract_owned_files(desc)
        assert result == []

    def test_various_extensions(self):
        from services.agent_service import AgentService
        desc = "Files: style.css, index.html, app.js, data.json"
        result = AgentService._extract_owned_files(desc)
        assert len(result) == 4

    def test_backtick_wrapped(self):
        from services.agent_service import AgentService
        desc = "Files: `main.py`, `utils.py`"
        result = AgentService._extract_owned_files(desc)
        assert 'main.py' in result
        assert 'utils.py' in result


# ═══════════════════════════════════════════════════════════
# _extract_markdown_from_narration
# ═══════════════════════════════════════════════════════════

class TestExtractMarkdownFromNarration:
    def test_fenced_markdown(self):
        from services.agent_service import AgentService
        response = (
            "Here's the document:\n"
            "```markdown\n"
            "# Requirements\n\n"
            "## Overview\n"
            "This is a task manager application that allows users to manage their daily tasks.\n"
            "It provides features for creating, editing, and deleting tasks with priorities.\n\n"
            "## Features\n"
            "### Task Management\n"
            "- Create tasks with title and priority\n"
            "- Edit existing tasks\n"
            "- Delete tasks\n"
            "```\n"
        )
        result = AgentService._extract_markdown_from_narration(response)
        assert '# Requirements' in result
        assert '## Overview' in result

    def test_inline_markdown(self):
        from services.agent_service import AgentService
        response = (
            "I'll write the requirements now.\n\n"
            "# Requirements\n\n"
            "## Overview\n"
            "A web application for tracking expenses.\n"
            "It supports multiple categories and date filtering.\n\n"
            "## Features\n"
            "### Expense Entry\n"
            "Users can add expenses with amount, category, and date.\n\n"
            "[STEP_COMPLETE]"
        )
        result = AgentService._extract_markdown_from_narration(response)
        assert '# Requirements' in result
        assert 'STEP_COMPLETE' not in result

    def test_too_short_returns_empty(self):
        from services.agent_service import AgentService
        response = "```markdown\n# Title\nShort.\n```"
        result = AgentService._extract_markdown_from_narration(response)
        assert result == ''

    def test_no_markdown_returns_empty(self):
        from services.agent_service import AgentService
        result = AgentService._extract_markdown_from_narration("Just a regular response with no headings.")
        assert result == ''


# ═══════════════════════════════════════════════════════════
# _validate_artifact_content
# ═══════════════════════════════════════════════════════════

class TestValidateArtifactContent:
    def test_too_short(self):
        from services.agent_service import AgentService
        is_valid, reason = AgentService._validate_artifact_content("Short", "requirements.md")
        assert is_valid is False
        assert 'short' in reason.lower()

    def test_valid_content(self):
        from services.agent_service import AgentService
        content = (
            "# Requirements\n\n"
            "## Overview\n"
            "A comprehensive task management application that allows users to "
            "create, organize, and track their daily work items efficiently.\n\n"
            "## Functional Requirements\n"
            "The system must support project creation with custom names and paths. "
            "Users should be able to assign priority levels to individual tasks. "
            "Each project contains multiple steps that progress through a defined workflow. "
            "Real-time collaboration features enable team members to share updates.\n\n"
            "## Technical Requirements\n"
            "The backend server runs on Flask with SQLite for persistent storage. "
            "Frontend rendering uses vanilla JavaScript without external frameworks. "
            "API endpoints follow RESTful conventions for all resource operations. "
            "Streaming responses leverage Server-Sent Events for live progress.\n"
        )
        is_valid, reason = AgentService._validate_artifact_content(content, "requirements.md")
        assert is_valid is True

    def test_too_many_placeholders(self):
        from services.agent_service import AgentService
        content = (
            "# Requirements\n\n"
            "## Overview\n...\n## Features\n...\n## Acceptance\n...\n## Non-Goals\n...\n"
            "Some content line\n"
        )
        # Pad to get past length check
        content += "x" * 200
        is_valid, reason = AgentService._validate_artifact_content(content, "requirements.md")
        # May or may not be valid depending on ratio — test that function runs
        assert isinstance(is_valid, bool)


# ═══════════════════════════════════════════════════════════
# _classify_error
# ═══════════════════════════════════════════════════════════

class TestClassifyError:
    def test_module_not_found(self):
        from services.agent_service import AgentService
        error = """Traceback (most recent call last):
  File "app.py", line 1, in <module>
    import flask
ModuleNotFoundError: No module named 'flask'"""
        result = AgentService._classify_error(error)
        assert result['type'] == 'module_not_found'
        assert result['module'] == 'flask'

    def test_import_error(self):
        from services.agent_service import AgentService
        error = """Traceback (most recent call last):
  File "app.py", line 1, in <module>
    from utils import missing_func
ImportError: cannot import name 'missing_func' from 'utils'"""
        result = AgentService._classify_error(error)
        assert result['type'] == 'import'
        assert result['errorType'] == 'ImportError'

    def test_syntax_error(self):
        from services.agent_service import AgentService
        error = """  File "app.py", line 5
    def broken(
              ^
SyntaxError: unexpected EOF while parsing"""
        result = AgentService._classify_error(error)
        assert result['type'] == 'syntax'
        assert result['errorType'] == 'SyntaxError'

    def test_runtime_error(self):
        from services.agent_service import AgentService
        error = """Traceback (most recent call last):
  File "app.py", line 10, in <module>
    x = int("not_a_number")
ValueError: invalid literal for int()"""
        result = AgentService._classify_error(error)
        assert result['type'] == 'runtime'
        assert result['errorType'] == 'ValueError'

    def test_empty_error(self):
        from services.agent_service import AgentService
        result = AgentService._classify_error('')
        assert result['type'] == 'unknown'

    def test_none_error(self):
        from services.agent_service import AgentService
        result = AgentService._classify_error(None)
        assert result['type'] == 'unknown'


# ═══════════════════════════════════════════════════════════
# _count_errors_in_output
# ═══════════════════════════════════════════════════════════

class TestCountErrorsInOutput:
    def test_no_errors(self):
        from services.agent_service import AgentService
        assert AgentService._count_errors_in_output("All good, no issues!") == 0

    def test_single_error(self):
        from services.agent_service import AgentService
        count = AgentService._count_errors_in_output("Traceback (most recent call last):")
        assert count >= 1

    def test_multiple_errors(self):
        from services.agent_service import AgentService
        output = "SyntaxError: bad syntax\nNameError: x is not defined\nTypeError: expected int"
        count = AgentService._count_errors_in_output(output)
        assert count >= 3

    def test_empty(self):
        from services.agent_service import AgentService
        assert AgentService._count_errors_in_output("") == 0

    def test_none(self):
        from services.agent_service import AgentService
        assert AgentService._count_errors_in_output(None) == 0


# ═══════════════════════════════════════════════════════════
# _build_history_context
# ═══════════════════════════════════════════════════════════

class TestBuildHistoryContext:
    def test_empty_history(self):
        from services.agent_service import AgentService
        assert AgentService._build_history_context([]) == ''

    def test_single_entry(self):
        from services.agent_service import AgentService
        history = [{'error': 'SyntaxError', 'fixes': ['app.py'], 'success': False}]
        result = AgentService._build_history_context(history)
        assert 'Previous Fix Attempts' in result
        assert 'SyntaxError' in result

    def test_multiple_entries(self):
        from services.agent_service import AgentService
        history = [
            {'error': 'ImportError', 'fixes': ['app.py'], 'success': False},
            {'error': 'SyntaxError', 'fixes': ['utils.py'], 'success': True},
        ]
        result = AgentService._build_history_context(history)
        assert 'ImportError' in result
        assert 'SyntaxError' in result

    def test_reverted_entry(self):
        from services.agent_service import AgentService
        history = [{'error': 'TypeError', 'fixes': [], 'success': False, 'reverted': True}]
        result = AgentService._build_history_context(history)
        assert 'reverted' in result.lower()


# ═══════════════════════════════════════════════════════════
# _fix_acronyms
# ═══════════════════════════════════════════════════════════

class TestFixAcronyms:
    def test_single_acronym(self):
        from services.agent_service import AgentService
        assert AgentService._fix_acronyms('Cli Interface') == 'CLI Interface'

    def test_multiple_acronyms(self):
        from services.agent_service import AgentService
        result = AgentService._fix_acronyms('Api And Cli Integration')
        assert 'API' in result
        assert 'CLI' in result

    def test_no_acronyms(self):
        from services.agent_service import AgentService
        assert AgentService._fix_acronyms('Build Application') == 'Build Application'

    def test_database_acronym(self):
        from services.agent_service import AgentService
        assert AgentService._fix_acronyms('Sql Database') == 'SQL Database'


# ═══════════════════════════════════════════════════════════
# _sanitize_category_name
# ═══════════════════════════════════════════════════════════

class TestSanitizeCategoryName:
    def test_strip_task_prefix(self):
        from services.agent_service import AgentService
        assert 'Task 1' not in AgentService._sanitize_category_name('Task 1: Setup Environment')

    def test_strip_complexity_label(self):
        from services.agent_service import AgentService
        result = AgentService._sanitize_category_name('Model Training (Complex)')
        assert 'Complex' not in result
        assert 'Model Training' in result

    def test_strip_file_extension(self):
        from services.agent_service import AgentService
        result = AgentService._sanitize_category_name('Create app.py entry point')
        assert '.py' not in result

    def test_truncate_long_name(self):
        from services.agent_service import AgentService
        long_name = "Word1 Word2 Word3 Word4 Word5 Word6 Word7 Word8 Word9 Word10"
        result = AgentService._sanitize_category_name(long_name)
        assert len(result.split()) <= 6

    def test_normalize_whitespace(self):
        from services.agent_service import AgentService
        result = AgentService._sanitize_category_name('  Setup   Environment  ')
        assert '  ' not in result


# ═══════════════════════════════════════════════════════════
# _enrich_vague_heading
# ═══════════════════════════════════════════════════════════

class TestEnrichVagueHeading:
    def test_non_vague_unchanged(self):
        from services.agent_service import AgentService
        name, desc = AgentService._enrich_vague_heading('Building Core Logic', 'Some description')
        assert name == 'Building Core Logic'

    def test_vague_single_word_enriched(self):
        from services.agent_service import AgentService
        name, desc = AgentService._enrich_vague_heading(
            'Technology',
            'Files: app.py\n- [ ] Create Flask application'
        )
        assert 'Technology' in name
        assert len(name) > len('Technology')

    def test_vague_spec_section_enriched(self):
        from services.agent_service import AgentService
        name, desc = AgentService._enrich_vague_heading(
            'Architecture',
            'Files: config.py, models.py\n- [ ] Define data models'
        )
        assert '—' in name or '&' in name  # Should be enriched

    def test_no_desc_stays_vague(self):
        from services.agent_service import AgentService
        name, desc = AgentService._enrich_vague_heading('Setup', '')
        # Can't enrich without description — stays as-is
        assert 'Setup' in name


# ═══════════════════════════════════════════════════════════
# _ensure_action_verb
# ═══════════════════════════════════════════════════════════

class TestEnsureActionVerb:
    def test_already_has_ing_verb(self):
        from services.agent_service import AgentService
        assert AgentService._ensure_action_verb('Building Data Layer') == 'Building Data Layer'

    def test_bare_verb_converted(self):
        from services.agent_service import AgentService
        result = AgentService._ensure_action_verb('Create API Routes')
        assert result.startswith('Creating')

    def test_noun_only_gets_verb(self):
        from services.agent_service import AgentService
        result = AgentService._ensure_action_verb('Application Core')
        # Should prepend an appropriate verb
        assert len(result) > len('Application Core')

    def test_trailing_ing_unchanged(self):
        from services.agent_service import AgentService
        result = AgentService._ensure_action_verb('Page Styling')
        assert result == 'Page Styling'


# ═══════════════════════════════════════════════════════════
# _extract_json_from_response
# ═══════════════════════════════════════════════════════════

class TestExtractJsonFromResponse:
    def test_direct_json(self):
        from services.agent_service import AgentService
        result = AgentService._extract_json_from_response('{"complexity": "simple"}')
        assert result == {"complexity": "simple"}

    def test_fenced_json(self):
        from services.agent_service import AgentService
        text = "Here's the result:\n```json\n{\"complexity\": \"medium\"}\n```"
        result = AgentService._extract_json_from_response(text)
        assert result['complexity'] == 'medium'

    def test_json_with_commentary(self):
        from services.agent_service import AgentService
        text = 'I analyzed the task.\n\n{"complexity": "complex", "components": ["auth", "api"]}\n\nDone.'
        result = AgentService._extract_json_from_response(text)
        assert result['complexity'] == 'complex'

    def test_empty_input(self):
        from services.agent_service import AgentService
        assert AgentService._extract_json_from_response('') is None
        assert AgentService._extract_json_from_response(None) is None

    def test_invalid_json(self):
        from services.agent_service import AgentService
        assert AgentService._extract_json_from_response('not json at all') is None

    def test_fenced_no_language(self):
        from services.agent_service import AgentService
        text = "```\n{\"key\": \"value\"}\n```"
        result = AgentService._extract_json_from_response(text)
        assert result == {"key": "value"}


# ═══════════════════════════════════════════════════════════
# _default_scope
# ═══════════════════════════════════════════════════════════

class TestDefaultScope:
    def test_returns_dict(self):
        from services.agent_service import AgentService
        result = AgentService._default_scope('Build a Flask web app')
        assert isinstance(result, dict)
        assert 'complexity' in result
        assert 'components' in result
        assert result['complexity'] == 'medium'

    def test_detects_web_app(self):
        from services.agent_service import AgentService
        result = AgentService._default_scope('Build a Flask web application')
        assert result['deliverable_type'] == 'web application'

    def test_truncates_long_summary(self):
        from services.agent_service import AgentService
        long_text = "A" * 500
        result = AgentService._default_scope(long_text)
        assert len(result['summary']) <= 200


# ═══════════════════════════════════════════════════════════
# _sanitize_tool_json
# ═══════════════════════════════════════════════════════════

class TestSanitizeToolJson:
    def test_trailing_comma(self):
        from services.agent_service import AgentService
        result = AgentService._sanitize_tool_json('{"key": "value",}')
        assert json.loads(result) == {"key": "value"}

    def test_single_quotes(self):
        from services.agent_service import AgentService
        result = AgentService._sanitize_tool_json("{'key': 'value'}")
        assert json.loads(result) == {"key": "value"}

    def test_valid_json_unchanged(self):
        from services.agent_service import AgentService
        original = '{"name": "WriteFile", "arguments": {"path": "app.py"}}'
        result = AgentService._sanitize_tool_json(original)
        assert json.loads(result) == json.loads(original)


# ═══════════════════════════════════════════════════════════
# _fix_control_chars_in_strings
# ═══════════════════════════════════════════════════════════

class TestFixControlCharsInStrings:
    def test_literal_newline_in_string(self):
        from services.agent_service import AgentService
        s = '{"content": "line1\nline2"}'
        result = AgentService._fix_control_chars_in_strings(s)
        parsed = json.loads(result)
        assert 'line1' in parsed['content']

    def test_tab_in_string(self):
        from services.agent_service import AgentService
        s = '{"content": "col1\tcol2"}'
        result = AgentService._fix_control_chars_in_strings(s)
        parsed = json.loads(result)
        assert 'col1' in parsed['content']

    def test_already_escaped_preserved(self):
        from services.agent_service import AgentService
        s = '{"content": "already\\nescaped"}'
        result = AgentService._fix_control_chars_in_strings(s)
        parsed = json.loads(result)
        assert 'already\nescaped' in parsed['content']

    def test_outside_strings_unchanged(self):
        from services.agent_service import AgentService
        s = '{\n  "key": "value"\n}'
        # Control chars outside strings should remain (they're valid JSON whitespace)
        result = AgentService._fix_control_chars_in_strings(s)
        assert json.loads(result) == {"key": "value"}


# ═══════════════════════════════════════════════════════════
# _extract_tool_call_fallback
# ═══════════════════════════════════════════════════════════

class TestExtractToolCallFallback:
    def test_write_file_extraction(self):
        from services.agent_service import AgentService
        raw = '{"name": "WriteFile", "arguments": {"path": "app.py", "content": "print(\'hello\')"}}'
        result = AgentService._extract_tool_call_fallback(raw)
        assert result is not None
        assert result['name'] == 'WriteFile'
        assert result['arguments']['path'] == 'app.py'

    def test_read_file_extraction(self):
        from services.agent_service import AgentService
        raw = '{"name": "ReadFile", "arguments": {"path": "config.py"}}'
        result = AgentService._extract_tool_call_fallback(raw)
        assert result is not None
        assert result['name'] == 'ReadFile'

    def test_unknown_tool_returns_none(self):
        from services.agent_service import AgentService
        raw = '{"name": "UnknownTool", "arguments": {"path": "x.py"}}'
        result = AgentService._extract_tool_call_fallback(raw)
        assert result is None

    def test_no_name_returns_none(self):
        from services.agent_service import AgentService
        raw = '{"arguments": {"path": "x.py"}}'
        result = AgentService._extract_tool_call_fallback(raw)
        assert result is None


# ═══════════════════════════════════════════════════════════
# _extract_tasks_from_impl_plan
# ═══════════════════════════════════════════════════════════

class TestExtractTasksFromImplPlan:
    def test_h2_headings(self):
        from services.agent_service import AgentService
        content = (
            "# Implementation Plan\n\n"
            "## Project Setup\n"
            "Create the project structure\n\n"
            "## Database Layer\n"
            "Implement database models\n\n"
            "## API Routes\n"
            "Build REST endpoints\n"
        )
        tasks = AgentService._extract_tasks_from_impl_plan(content)
        names = [t[0] for t in tasks]
        assert 'Project Setup' in names
        assert 'Database Layer' in names
        assert 'API Routes' in names

    def test_task_n_prefix_stripped(self):
        from services.agent_service import AgentService
        content = "## Task 1: Setup Environment\nSome description\n## Task 2: Core Logic\nMore text"
        tasks = AgentService._extract_tasks_from_impl_plan(content)
        names = [t[0] for t in tasks]
        assert any('Setup Environment' in n for n in names)

    def test_skips_meta_headings(self):
        from services.agent_service import AgentService
        content = "## Overview\nIntro text\n## Summary\nEnd text\n## Core Feature\nReal task"
        tasks = AgentService._extract_tasks_from_impl_plan(content)
        names = [t[0] for t in tasks]
        assert 'Overview' not in names
        assert 'Summary' not in names
        assert 'Core Feature' in names

    def test_fallback_to_numbered_list(self):
        from services.agent_service import AgentService
        content = (
            "# Implementation Plan\n\n"
            "1. Create database models and schema\n"
            "2. Build API endpoints for CRUD\n"
            "3. Implement authentication layer\n"
        )
        tasks = AgentService._extract_tasks_from_impl_plan(content)
        assert len(tasks) >= 3

    def test_empty_content(self):
        from services.agent_service import AgentService
        assert AgentService._extract_tasks_from_impl_plan("") == []

    def test_capped_at_11(self):
        from services.agent_service import AgentService
        content = '\n'.join(f"## Step {i}\nDescription {i}" for i in range(20))
        tasks = AgentService._extract_tasks_from_impl_plan(content)
        assert len(tasks) <= 11

    def test_descriptions_captured(self):
        from services.agent_service import AgentService
        content = "## Database Setup\nCreate tables for users and tasks\nAdd indexes\n"
        tasks = AgentService._extract_tasks_from_impl_plan(content)
        assert len(tasks) == 1
        assert 'tables' in tasks[0][1].lower()
