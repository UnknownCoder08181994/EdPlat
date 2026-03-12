"""LLM Activity Logger — captures ALL LLM output for debugging.

Writes a timestamped log of everything the model says and does to:
  storage/llm_logs/{task_id}.log

Each entry is tagged with:
  [THINK]    — thinking/reasoning tokens
  [TOKEN]    — content tokens (accumulated per-turn, not per-token)
  [TURN]     — turn boundaries (start/end)
  [TOOL]     — tool call attempted
  [RESULT]   — tool result returned
  [ERROR]    — errors, aborts, failures
  [META]     — context stats, token budgets
  [RESPONSE] — full accumulated response at end of turn

Usage in agent_service.py:
  from services.llm_logger import LLMLogger

  logger = LLMLogger(task_id)
  logger.turn_start(step_name, turn_number)
  logger.thinking(text)
  logger.token(text)          # accumulates, flushed on turn_end
  logger.tool_call(name, args)
  logger.tool_result(name, result_text)
  logger.response(full_text)  # full response at end of turn
  logger.turn_end(status)
  logger.error(message)
  logger.meta(key, value)
"""

import os
import json
from datetime import datetime

from config import Config
from utils.logging import _safe_log

LOG_DIR = os.path.join(Config.STORAGE_DIR, 'llm_logs')


class LLMLogger:
    """Per-task LLM activity logger. Writes append-only log file."""

    def __init__(self, task_id):
        self.task_id = task_id
        self._path = os.path.join(LOG_DIR, f'{task_id}.log')
        self._ensure_dir()
        self._token_buffer = ''  # Accumulates content tokens within a turn
        self._think_buffer = ''  # Accumulates thinking tokens within a turn
        # Create the file immediately so it's always accessible via API
        self._write('META', f'Logger initialized for task {task_id}')

    def _ensure_dir(self):
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
        except Exception:
            pass

    def _write(self, tag, text):
        """Append a tagged line to the log file."""
        try:
            ts = datetime.now().strftime('%H:%M:%S.%f')[:-3]
            # Collapse multiline to single line for log readability
            compact = text.replace('\n', '\\n').replace('\r', '')
            if len(compact) > 2000:
                compact = compact[:2000] + f'... ({len(text)} chars total)'
            with open(self._path, 'a', encoding='utf-8') as f:
                f.write(f'[{ts}] [{tag}] {compact}\n')
        except Exception as e:
            _safe_log(f'[LLMLogger] Write failed: {e}')

    # ── Turn lifecycle ────────────────────────────────────────

    def turn_start(self, step_name, turn_number, context_tokens=0):
        """Log the start of an LLM generation turn."""
        self._token_buffer = ''
        self._think_buffer = ''
        self._write('TURN', f'=== Turn {turn_number} START | Step: {step_name} | Context: {context_tokens} tokens ===')

    def turn_end(self, status='ok'):
        """Log the end of a turn. Flushes thinking and content buffers."""
        if self._think_buffer:
            self._write('THINK_FULL', self._think_buffer)
            self._think_buffer = ''
        if self._token_buffer:
            self._write('CONTENT', self._token_buffer)
            self._token_buffer = ''
        self._write('TURN', f'=== Turn END | Status: {status} ===')

    # ── Token-level logging ───────────────────────────────────

    def thinking(self, text):
        """Accumulate a thinking/reasoning chunk. Flushed on turn_end."""
        self._think_buffer += text

    def token(self, text):
        """Accumulate a content token. Flushed on turn_end or response()."""
        self._token_buffer += text

    def response(self, full_text):
        """Log the full accumulated response at end of turn."""
        self._token_buffer = ''  # Clear buffer since we're logging the full thing
        self._write('RESPONSE', full_text)

    # ── Tool logging ──────────────────────────────────────────

    def tool_call(self, name, args_summary=''):
        """Log a tool call attempt."""
        self._write('TOOL', f'{name}({args_summary})')

    def tool_result(self, name, result_text):
        """Log a tool result."""
        self._write('RESULT', f'{name} → {result_text}')

    # ── Errors and metadata ───────────────────────────────────

    def error(self, message):
        """Log an error."""
        self._write('ERROR', message)

    def meta(self, key, value):
        """Log a metadata entry (context stats, budgets, etc.)."""
        self._write('META', f'{key}: {value}')

    def abort(self, reason):
        """Log an abort (duplicate write, context overflow, etc.)."""
        self._write('ABORT', reason)

    # ── Step-level events ─────────────────────────────────────

    def step_start(self, step_name, step_id=''):
        """Log the start of an SDD step."""
        self._write('STEP', f'>>> STEP START: {step_name} (id={step_id}) <<<')

    def step_complete(self, step_name, written_files=None):
        """Log step completion with files written."""
        files_str = ', '.join(written_files or [])
        self._write('STEP', f'>>> STEP COMPLETE: {step_name} | Files: {files_str} <<<')

    # ── Execution agent events ────────────────────────────────

    def exec_attempt(self, attempt, command, exit_code):
        """Log an execution attempt."""
        self._write('EXEC', f'Attempt {attempt}: `{command}` → exit {exit_code}')

    def exec_error(self, error_class):
        """Log a classified error."""
        self._write('EXEC', f'Error: {error_class.get("type", "?")} | {error_class.get("message", "")[:200]}')

    def exec_fix(self, fix_type, details):
        """Log a fix applied (deterministic or LLM)."""
        self._write('FIX', f'{fix_type}: {details}')

    # ── Review events ─────────────────────────────────────────

    def review_start(self, pass_name):
        """Log review pass start."""
        self._write('REVIEW', f'Pass: {pass_name} START')

    def review_end(self, pass_name, issues_count=0):
        """Log review pass end."""
        self._write('REVIEW', f'Pass: {pass_name} END | Issues: {issues_count}')
