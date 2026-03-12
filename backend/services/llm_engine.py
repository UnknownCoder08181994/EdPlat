"""LLM engine — talks to LM Studio via OpenAI-compatible HTTP API.

Connects to a local LM Studio server running DeepSeek-R1-Distill-Qwen-7B
at http://localhost:1234/v1/chat/completions.

Interface:
- get_llm_engine() -> singleton LLMEngine
- engine.stream_chat(messages, max_new_tokens, temperature, cancel_event) -> generator[str]
- engine.count_tokens(messages) -> int
- LLMEngine.force_cancel() -> class method
"""

import json
import time
import threading
import logging
import requests

log = logging.getLogger(__name__)

# Module-level cancel event for force_cancel()
_global_cancel_event = threading.Event()

# Singleton instance
_engine_instance = None
_engine_lock = threading.Lock()

# LM Studio API configuration
_API_BASE = "http://localhost:1234/v1"
_CHAT_URL = f"{_API_BASE}/chat/completions"
_MODELS_URL = f"{_API_BASE}/models"


def get_llm_engine():
    """Return the singleton LLMEngine instance."""
    global _engine_instance
    if _engine_instance is None:
        with _engine_lock:
            if _engine_instance is None:
                _engine_instance = LLMEngine()
    return _engine_instance


class LLMEngine:
    """LLM engine that calls LM Studio's OpenAI-compatible API."""

    def __init__(self):
        self._cancel_event = None
        self._ready = False
        self._model_id = None
        self._gen_lock = threading.Lock()
        self._context_size = None  # Model's n_ctx, learned from errors

        self._connect()

    @property
    def context_size(self):
        """Return the model's known context window size, or None if unknown."""
        return self._context_size

    def set_context_size(self, n_ctx):
        """Set the model's context size (learned from n_ctx errors)."""
        self._context_size = n_ctx
        print(f"[LLM] Model context size: {n_ctx} tokens", flush=True)

    def _connect(self):
        """Verify LM Studio is reachable and discover the model ID."""
        try:
            resp = requests.get(_MODELS_URL, timeout=5)
            resp.raise_for_status()
            data = resp.json()
            models = data.get("data", [])
            # Filter out embedding models — only use chat/completion models
            chat_models = [m for m in models if 'embed' not in m.get('id', '').lower()]
            if chat_models:
                self._model_id = chat_models[0]["id"]
            elif models:
                self._model_id = models[0]["id"]
            else:
                self._model_id = "DeepSeek-R1-Distill-Qwen-7B"
            print(f"[LLM] Connected to LM Studio — model: {self._model_id}", flush=True)

            # Try to detect context window size
            # 1. Check model metadata for context_length field
            chosen = next((m for m in models if m.get('id') == self._model_id), None)
            if chosen:
                ctx = (chosen.get('context_length')
                       or chosen.get('max_context_length')
                       or chosen.get('max_model_len'))
                if ctx and isinstance(ctx, int):
                    self._context_size = ctx

            # 2. Heuristic from model name for common models
            if self._context_size is None:
                model_lower = self._model_id.lower()
                if any(tag in model_lower for tag in ['-1b', '-1.5b', '-3b', '-7b', '-8b',
                                                       '/1b', '/1.5b', '/3b', '/7b', '/8b']):
                    self._context_size = 4096  # Conservative default for small models
                elif any(tag in model_lower for tag in ['-14b', '-20b', '-22b', '-32b', '-70b',
                                                         '/14b', '/20b', '/22b', '/32b', '/70b',
                                                         'gpt-oss']):
                    self._context_size = 32768  # LM Studio typically uses large context windows

            if self._context_size:
                print(f"[LLM] Context size: {self._context_size} tokens", flush=True)

            self._ready = True
        except Exception as e:
            print(f"[LLM] WARNING: LM Studio not reachable at {_API_BASE}: {e}", flush=True)
            print("[LLM] Will retry on first request. Make sure LM Studio is running.", flush=True)
            # Set ready anyway — we'll get errors on actual calls if it's truly down,
            # but this lets the server start without LM Studio being up yet.
            self._model_id = "DeepSeek-R1-Distill-Qwen-7B"
            self._ready = True

    @classmethod
    def force_cancel(cls):
        """Force-cancel any in-flight generation. Returns True if signalled.

        Sets the global cancel event and waits up to 2s for the streaming loop
        to observe it, rather than blindly clearing after 100ms.
        """
        _global_cancel_event.set()
        # Wait for the streaming loop to see the cancel signal.
        # The event stays set until the next stream_chat call clears it,
        # ensuring no race between set/clear timing.
        time.sleep(0.5)
        # Clear after a generous window — if no stream is running, we still
        # need to clean up so the next call can proceed.
        _global_cancel_event.clear()
        return True

    def count_tokens(self, messages):
        """Estimate token count from messages (heuristic — no local tokenizer).

        Uses ~3.2 chars/token (conservative) instead of ~4 chars/token.
        Code, JSON, and whitespace-heavy content tokenize at ~2.5-3 chars/token,
        so 3.2 avoids underestimating which can push input+output past context limits.
        """
        total_chars = sum(len(m.get('content', '')) for m in messages)
        return int(total_chars / 3.2)

    @staticmethod
    def _fold_system_into_user(messages):
        """Fold system messages into the first user message for models that don't support system role."""
        system_parts = []
        other_msgs = []
        for m in messages:
            if m["role"] == "system":
                system_parts.append(m["content"])
            else:
                other_msgs.append(m)

        if not system_parts:
            return other_msgs

        prefix = "\n\n".join(system_parts)
        # Prepend to first user message
        if other_msgs and other_msgs[0]["role"] == "user":
            other_msgs[0] = {
                "role": "user",
                "content": prefix + "\n\n" + other_msgs[0]["content"]
            }
        else:
            # No user message yet, create one
            other_msgs.insert(0, {"role": "user", "content": prefix})

        return other_msgs

    def stream_chat(self, messages, max_new_tokens=4096, temperature=0.7, cancel_event=None, read_timeout=300):
        """Stream response tokens from LM Studio."""
        self._cancel_event = cancel_event

        if not self._ready:
            raise RuntimeError("LLM engine not ready")

        # If we know this model doesn't support system role, fold it in advance
        if getattr(self, '_no_system_role', False):
            messages = self._fold_system_into_user(messages)

        # Check for system-role errors on first call and auto-retry with folded messages
        has_system = any(m["role"] == "system" for m in messages)
        need_check = has_system and not getattr(self, '_no_system_role', False)

        raw_api = self._api_stream(messages, max_new_tokens, temperature, cancel_event, read_timeout=read_timeout)
        stream = self._strip_think_tags(raw_api)

        if need_check:
            # Buffer only the first chunk to check for errors
            # (LM Studio sends error events before any content, so first chunk = error)
            first_chunk = None
            try:
                first_chunk = next(stream)
            except StopIteration:
                return

            if '[Error from LLM:' in first_chunk and ('role' in first_chunk.lower() or 'template' in first_chunk.lower()):
                self._no_system_role = True
                print("[LLM] Model doesn't support system role, retrying with folded messages", flush=True)
                # IMPORTANT: close the old generators to release _gen_lock before retrying
                stream.close()
                raw_api.close()
                folded = self._fold_system_into_user(messages)
                yield from self._strip_think_tags(
                    self._api_stream(folded, max_new_tokens, temperature, cancel_event)
                )
                return

            # No error — yield the first chunk then stream the rest
            yield first_chunk
            yield from stream
        else:
            yield from stream

    # Sentinel prefix used to tag thinking tokens in the stream.
    # The agent service checks for this prefix to route thinking tokens
    # to a separate SSE event instead of appending to the response.
    THINK_PREFIX = "\x00THINK:"

    @staticmethod
    def _strip_think_tags(token_stream):
        """Extract <think>...</think> reasoning blocks from a token stream.
        Instead of discarding them, yields thinking tokens prefixed with
        THINK_PREFIX so the agent loop can emit them as separate SSE events.
        DeepSeek R1 models emit these before their actual response."""
        inside_think = False
        buffer = ""
        error_passthrough = False
        TPFX = LLMEngine.THINK_PREFIX
        for token in token_stream:
            # Pass through tokens already tagged as thinking (e.g. from delta.reasoning)
            if token.startswith(TPFX):
                # Flush any buffered content first
                if buffer:
                    yield buffer
                    buffer = ""
                yield token
                continue
            buffer += token
            # Safety: if the buffer contains an error marker, stop stripping
            # and pass everything through verbatim. Error messages must not
            # be mangled by think-tag removal.
            if not error_passthrough and ('[Error from LLM:' in buffer or '[Error:' in buffer):
                error_passthrough = True
                yield buffer
                buffer = ""
                continue
            if error_passthrough:
                yield token
                continue
            while buffer:
                if inside_think:
                    end_idx = buffer.find("</think>")
                    if end_idx != -1:
                        # Yield thinking content before </think>, then exit think mode
                        think_content = buffer[:end_idx]
                        if think_content:
                            yield TPFX + think_content
                        buffer = buffer[end_idx + len("</think>"):]
                        inside_think = False
                    else:
                        # Still inside <think> — yield buffered thinking and wait
                        if buffer:
                            yield TPFX + buffer
                        buffer = ""
                        break
                else:
                    start_idx = buffer.find("<think>")
                    if start_idx != -1:
                        # Yield text before <think>, then enter think mode
                        before = buffer[:start_idx]
                        if before:
                            yield before
                        buffer = buffer[start_idx + len("<think>"):]
                        inside_think = True
                    else:
                        # No <think> tag — but buffer might end with partial "<thi..."
                        # Keep last 7 chars as potential partial tag
                        if len(buffer) > 7:
                            yield buffer[:-7]
                            buffer = buffer[-7:]
                        else:
                            break
        # Flush remaining buffer
        if buffer and not inside_think:
            yield buffer

    def _api_stream(self, messages, max_new_tokens, temperature, cancel_event, read_timeout=300):
        """Call the LLM API. Tries streaming first, falls back to non-streaming."""
        with self._gen_lock:
            payload = {
                "model": self._model_id,
                "messages": messages,
                "max_tokens": max_new_tokens,
                "temperature": max(temperature, 0.01),
                "top_p": 0.8,
            }

            # Try streaming first (LM Studio supports it, GPT4All does not)
            if not getattr(self, '_no_stream', False):
                try:
                    stream_payload = {**payload, "stream": True}
                    resp = requests.post(
                        _CHAT_URL,
                        json=stream_payload,
                        stream=True,
                        timeout=(5, read_timeout),
                    )
                    resp.raise_for_status()

                    current_event = None
                    # Force UTF-8 decoding — LM Studio may not set charset
                    # in Content-Type, causing requests to default to ISO-8859-1
                    # which corrupts multi-byte chars (em-dashes → â|| mojibake)
                    resp.encoding = 'utf-8'
                    for line in resp.iter_lines(decode_unicode=True):
                        if cancel_event and cancel_event.is_set():
                            resp.close()
                            return
                        if _global_cancel_event.is_set():
                            resp.close()
                            return

                        if not line:
                            current_event = None
                            continue

                        # Track SSE event type
                        if line.startswith("event: "):
                            current_event = line[7:].strip()
                            continue

                        if not line.startswith("data: "):
                            continue

                        data_str = line[6:]

                        # Handle SSE error events (e.g. from LM Studio template errors)
                        if current_event == "error":
                            try:
                                err_data = json.loads(data_str)
                                err_msg = err_data.get("message", err_data.get("error", {}).get("message", str(err_data)))
                            except (json.JSONDecodeError, ValueError):
                                err_msg = data_str
                            log.error("LLM SSE error: %s", err_msg)
                            print(f"[LLM] SSE error: {err_msg}", flush=True)
                            yield f"\n\n[Error from LLM: {err_msg}]"
                            return

                        if data_str.strip() == "[DONE]":
                            break

                        try:
                            chunk = json.loads(data_str)
                            delta = chunk.get("choices", [{}])[0].get("delta", {})
                            # GPT-OSS reasoning models send chain-of-thought in delta.reasoning
                            reasoning = delta.get("reasoning", "")
                            if reasoning:
                                yield LLMEngine.THINK_PREFIX + reasoning
                            content = delta.get("content", "")
                            if content:
                                yield content
                        except (json.JSONDecodeError, IndexError, KeyError):
                            continue
                    return

                except requests.HTTPError as e:
                    if e.response is not None and e.response.status_code == 400:
                        # Check if this is a "streaming not supported" error vs a
                        # request-specific error (bad payload). Only disable streaming
                        # permanently if the error message suggests it's unsupported.
                        err_body = ''
                        try:
                            err_body = e.response.text.lower()
                        except Exception:
                            pass
                        if 'stream' in err_body or 'not supported' in err_body:
                            log.info("Streaming not supported, falling back to non-streaming")
                            self._no_stream = True
                        else:
                            # Transient 400 (bad payload) — fall back for this request only
                            log.warning(f"Streaming request got 400 (transient): {err_body[:200]}")
                    else:
                        raise
                except requests.ConnectionError:
                    yield "\n\n[Error: Cannot connect to LLM server at localhost:1234. Is it running?]"
                    return
                except requests.Timeout:
                    yield "\n\n[Error: LLM request timed out]"
                    return

            # Non-streaming fallback — get full response then yield in chunks
            try:
                resp = requests.post(
                    _CHAT_URL,
                    json=payload,
                    timeout=(5, read_timeout),
                )
                resp.raise_for_status()
                data = resp.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")

                if cancel_event and cancel_event.is_set():
                    return
                if _global_cancel_event.is_set():
                    return

                # Yield in small chunks to simulate streaming for the SSE frontend
                chunk_size = 4
                for i in range(0, len(content), chunk_size):
                    if cancel_event and cancel_event.is_set():
                        return
                    if _global_cancel_event.is_set():
                        return
                    yield content[i:i + chunk_size]
                    time.sleep(0.01)

            except requests.ConnectionError:
                yield "\n\n[Error: Cannot connect to LLM server at localhost:1234. Is it running?]"
            except requests.Timeout:
                yield "\n\n[Error: LLM request timed out]"
            except Exception as e:
                log.error("LLM API error: %s", e)
                yield f"\n\n[Error during generation: {e}]"
