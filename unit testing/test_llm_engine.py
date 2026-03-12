"""Unit tests for backend/services/llm_engine.py"""

import pytest
import threading


class TestLLMEngine:
    def test_count_tokens_basic(self):
        from services.llm_engine import LLMEngine
        engine = LLMEngine.__new__(LLMEngine)
        engine._context_size = None
        msgs = [{"role": "user", "content": "Hello world"}]
        count = engine.count_tokens(msgs)
        # "Hello world" = 11 chars, at 3.2 chars/token ~= 3 tokens
        assert count > 0
        assert isinstance(count, int)

    def test_count_tokens_empty(self):
        from services.llm_engine import LLMEngine
        engine = LLMEngine.__new__(LLMEngine)
        engine._context_size = None
        assert engine.count_tokens([]) == 0

    def test_count_tokens_multiple_messages(self):
        from services.llm_engine import LLMEngine
        engine = LLMEngine.__new__(LLMEngine)
        engine._context_size = None
        msgs = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        count = engine.count_tokens(msgs)
        total_chars = sum(len(m['content']) for m in msgs)
        expected = int(total_chars / 3.2)
        assert count == expected

    def test_count_tokens_conservative_ratio(self):
        """3.2 chars/token should be more conservative than 4 chars/token."""
        from services.llm_engine import LLMEngine
        engine = LLMEngine.__new__(LLMEngine)
        engine._context_size = None
        msgs = [{"role": "user", "content": "x" * 320}]
        count = engine.count_tokens(msgs)
        # 320 / 3.2 = 100
        assert count == 100

    def test_context_size_property(self):
        from services.llm_engine import LLMEngine
        engine = LLMEngine.__new__(LLMEngine)
        engine._context_size = None
        assert engine.context_size is None

        engine.set_context_size(32768)
        assert engine.context_size == 32768

    def test_fold_system_into_user(self):
        from services.llm_engine import LLMEngine
        msgs = [
            {"role": "system", "content": "Be helpful."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ]
        result = LLMEngine._fold_system_into_user(msgs)
        # System should be folded into first user message
        assert result[0]['role'] == 'user'
        assert 'Be helpful.' in result[0]['content']
        assert 'Hello' in result[0]['content']
        # No system messages remain
        assert all(m['role'] != 'system' for m in result)

    def test_fold_system_no_system(self):
        from services.llm_engine import LLMEngine
        msgs = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ]
        result = LLMEngine._fold_system_into_user(msgs)
        assert result == msgs

    def test_fold_system_only_system(self):
        from services.llm_engine import LLMEngine
        msgs = [{"role": "system", "content": "Be helpful."}]
        result = LLMEngine._fold_system_into_user(msgs)
        assert result[0]['role'] == 'user'
        assert 'Be helpful.' in result[0]['content']

    def test_think_prefix_constant(self):
        from services.llm_engine import LLMEngine
        assert hasattr(LLMEngine, 'THINK_PREFIX')
        assert isinstance(LLMEngine.THINK_PREFIX, str)
        assert len(LLMEngine.THINK_PREFIX) > 0

    def test_strip_think_tags(self):
        from services.llm_engine import LLMEngine
        engine = LLMEngine.__new__(LLMEngine)
        engine._context_size = None

        # Simple content with no think tags
        tokens = list(engine._strip_think_tags(iter(["Hello ", "world!"])))
        combined = ''.join(t for t in tokens if not t.startswith(LLMEngine.THINK_PREFIX))
        assert combined == "Hello world!"

    def test_strip_think_tags_with_thinking(self):
        from services.llm_engine import LLMEngine
        engine = LLMEngine.__new__(LLMEngine)
        engine._context_size = None

        tokens = list(engine._strip_think_tags(
            iter(["<think>reasoning here</think>visible content"])
        ))
        # Thinking tokens should be prefixed
        think_tokens = [t for t in tokens if t.startswith(LLMEngine.THINK_PREFIX)]
        visible_tokens = [t for t in tokens if not t.startswith(LLMEngine.THINK_PREFIX)]
        assert any('reasoning' in t for t in think_tokens)
        assert 'visible content' in ''.join(visible_tokens)
