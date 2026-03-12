"""Unit tests for backend/services/llm_logger.py"""

import os
import pytest


class TestLLMLogger:
    @pytest.fixture
    def logger(self, mock_config, monkeypatch):
        """Create an LLMLogger that writes to the temp storage dir."""
        import services.llm_logger as llm_logger_module
        log_dir = os.path.join(mock_config, 'llm_logs')
        os.makedirs(log_dir, exist_ok=True)
        monkeypatch.setattr(llm_logger_module, 'LOG_DIR', log_dir)
        from services.llm_logger import LLMLogger
        return LLMLogger('test-task-123')

    def _log_path(self, mock_config):
        return os.path.join(mock_config, 'llm_logs', 'test-task-123.log')

    def test_creates_log_file(self, logger, mock_config):
        assert os.path.isfile(self._log_path(mock_config))

    def test_init_writes_meta(self, logger, mock_config):
        with open(self._log_path(mock_config), 'r') as f:
            content = f.read()
        assert '[META]' in content
        assert 'Logger initialized' in content

    def test_turn_start(self, logger, mock_config):
        logger.turn_start('requirements', 1, context_tokens=5000)
        with open(self._log_path(mock_config), 'r') as f:
            content = f.read()
        assert '[TURN]' in content
        assert 'Turn 1 START' in content
        assert 'requirements' in content

    def test_turn_end_flushes_buffers(self, logger, mock_config):
        logger.turn_start('test', 1)
        logger.thinking('some reasoning')
        logger.token('some content')
        logger.turn_end('ok')
        with open(self._log_path(mock_config), 'r') as f:
            content = f.read()
        assert '[THINK_FULL]' in content
        assert '[CONTENT]' in content
        assert 'Turn END' in content
        assert 'Status: ok' in content

    def test_thinking_accumulates(self, logger):
        logger.thinking('part1 ')
        logger.thinking('part2')
        assert logger._think_buffer == 'part1 part2'

    def test_token_accumulates(self, logger):
        logger.token('a')
        logger.token('b')
        assert logger._token_buffer == 'ab'

    def test_response_clears_buffer(self, logger):
        logger.token('stuff')
        logger.response('full response text')
        assert logger._token_buffer == ''

    def test_tool_call(self, logger, mock_config):
        logger.tool_call('WriteFile', 'path=app.py')
        with open(self._log_path(mock_config), 'r') as f:
            content = f.read()
        assert '[TOOL]' in content
        assert 'WriteFile' in content

    def test_tool_result(self, logger, mock_config):
        logger.tool_result('WriteFile', 'Successfully wrote to app.py')
        with open(self._log_path(mock_config), 'r') as f:
            content = f.read()
        assert '[RESULT]' in content

    def test_error(self, logger, mock_config):
        logger.error('Something broke')
        with open(self._log_path(mock_config), 'r') as f:
            content = f.read()
        assert '[ERROR]' in content
        assert 'Something broke' in content

    def test_abort(self, logger, mock_config):
        logger.abort('Runaway response')
        with open(self._log_path(mock_config), 'r') as f:
            content = f.read()
        assert '[ABORT]' in content

    def test_meta(self, logger, mock_config):
        logger.meta('budget', '5000 tokens')
        with open(self._log_path(mock_config), 'r') as f:
            content = f.read()
        assert 'budget: 5000 tokens' in content

    def test_long_text_truncated(self, logger, mock_config):
        logger.error('x' * 5000)
        with open(self._log_path(mock_config), 'r') as f:
            content = f.read()
        # Should be truncated with char count
        assert 'chars total' in content

    def test_step_start(self, logger, mock_config):
        logger.step_start('Requirements', step_id='requirements')
        with open(self._log_path(mock_config), 'r') as f:
            content = f.read()
        assert '[STEP]' in content
        assert 'STEP START' in content

    def test_step_complete(self, logger, mock_config):
        logger.step_complete('Requirements', written_files=['requirements.md'])
        with open(self._log_path(mock_config), 'r') as f:
            content = f.read()
        assert 'STEP COMPLETE' in content
        assert 'requirements.md' in content

    def test_review_events(self, logger, mock_config):
        logger.review_start('api_check')
        logger.review_end('api_check', issues_count=3)
        with open(self._log_path(mock_config), 'r') as f:
            content = f.read()
        assert '[REVIEW]' in content
        assert 'api_check START' in content
        assert 'Issues: 3' in content
