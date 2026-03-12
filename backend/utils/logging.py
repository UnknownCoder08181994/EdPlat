"""Safe stderr logging for Windows.

On Windows, sys.stderr can go stale mid-session (e.g., console buffer fills,
terminal tab switches, or the process is backgrounded). Any bare
print(..., file=sys.stderr, flush=True) will crash with:

    OSError: [Errno 22] Invalid argument

This module provides _safe_log() which catches the error, attempts to
reopen stderr, and silently discards if truly broken — rather than
crashing the Flask generator thread and returning HTTP 500.
"""
import sys
import io


def _safe_log(msg):
    """Print to stderr without crashing if the handle is broken (Windows OSError 22)."""
    try:
        print(msg, file=sys.stderr, flush=True)
    except OSError:
        # stderr handle went stale mid-session — try to reopen it
        try:
            sys.stderr = io.TextIOWrapper(
                open(sys.stderr.fileno(), 'wb', closefd=False),
                encoding='utf-8', errors='replace', line_buffering=True
            )
            print(msg, file=sys.stderr, flush=True)
        except Exception:
            pass  # Truly broken — silently discard rather than crash the agent loop
