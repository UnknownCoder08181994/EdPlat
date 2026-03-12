"""SSE streaming terminal endpoint + kill endpoint + execution agent."""

import os
import uuid
import subprocess
import threading
import json
from flask import Blueprint, request, Response, jsonify, stream_with_context
from services.task_service import TaskService
from services.agent_service import AgentService

terminal_bp = Blueprint('terminal', __name__)

# ── Process registry ──────────────────────────────────────
_process_lock = threading.Lock()
_active_processes = {}  # session_id → { process: Popen, cancel_event: Event }

# ── Execution agent cancel registry ───────────────────────
_exec_cancel_events = {}  # session_id → threading.Event


def _register_process(session_id, proc, cancel_event):
    with _process_lock:
        _active_processes[session_id] = {
            'process': proc,
            'cancel_event': cancel_event,
        }


def _unregister_process(session_id):
    with _process_lock:
        _active_processes.pop(session_id, None)


def _get_process(session_id):
    with _process_lock:
        return _active_processes.get(session_id)


def _get_workspace(task_id):
    """Resolve workspace path from task_id."""
    task = TaskService.get_task(task_id)
    if not task:
        return None
    return task.get('workspacePath')


def _build_venv_env(workspace_path):
    """Build env dict with venv on PATH (same logic as tool_service)."""
    env = os.environ.copy()
    venv_scripts = os.path.join(workspace_path, '.venv', 'Scripts')
    if not os.path.isdir(venv_scripts):
        venv_scripts = os.path.join(workspace_path, '.venv', 'bin')
    if os.path.isdir(venv_scripts):
        env['PATH'] = venv_scripts + os.pathsep + env.get('PATH', '')
        env['VIRTUAL_ENV'] = os.path.join(workspace_path, '.venv')
    return env


# ── SSE streaming command ─────────────────────────────────
@terminal_bp.route('/api/tasks/<task_id>/terminal/stream', methods=['POST'])
def stream_command(task_id):
    workspace_path = _get_workspace(task_id)
    if not workspace_path or not os.path.isdir(workspace_path):
        return jsonify({"error": "Task or workspace not found"}), 404

    data = request.json or {}
    command = data.get('command', '').strip()
    if not command:
        return jsonify({"error": "Command is required"}), 400

    # Cap command length to prevent abuse
    if len(command) > 2000:
        return jsonify({"error": "Command too long (max 2000 chars)"}), 400

    # Validate cwd is within workspace (prevent directory traversal)
    cwd = data.get('cwd') or workspace_path
    if cwd != workspace_path:
        abs_cwd = os.path.abspath(cwd)
        abs_ws = os.path.abspath(workspace_path)
        if not (abs_cwd == abs_ws or abs_cwd.startswith(abs_ws + os.sep)):
            return jsonify({"error": "cwd must be within workspace"}), 400
        cwd = abs_cwd

    session_id = str(uuid.uuid4())
    env = _build_venv_env(workspace_path)
    cancel_event = threading.Event()

    def generate():
        proc = None
        try:
            proc = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                cwd=cwd,
                env=env,
            )
            _register_process(session_id, proc, cancel_event)

            # Send session ID so client can reference it for kill
            yield f"event: terminal_session\ndata: {json.dumps({'sessionId': session_id})}\n\n"

            # Stream stdout line by line
            for line in proc.stdout:
                if cancel_event.is_set():
                    yield f"event: terminal_output\ndata: {json.dumps({'line': 'Process killed.'})}\n\n"
                    break
                yield f"event: terminal_output\ndata: {json.dumps({'line': line.rstrip(chr(10))})}\n\n"

            proc.stdout.close()
            exit_code = proc.wait(timeout=5)
            yield f"event: terminal_done\ndata: {json.dumps({'exitCode': exit_code})}\n\n"

        except Exception as e:
            yield f"event: terminal_error\ndata: {json.dumps({'error': str(e)})}\n\n"
        finally:
            _unregister_process(session_id)
            if proc and proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=3)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass

    return Response(
        stream_with_context(generate()),
        content_type='text/event-stream; charset=utf-8',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        }
    )


# ── Kill running process ──────────────────────────────────
@terminal_bp.route('/api/terminal/<session_id>/kill', methods=['POST'])
def kill_process(session_id):
    entry = _get_process(session_id)
    if not entry:
        return jsonify({"error": "Session not found"}), 404

    entry['cancel_event'].set()
    proc = entry['process']
    try:
        proc.terminate()
        proc.wait(timeout=3)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass

    return jsonify({"status": "killed"})


# ── Execution Agent (auto-fix) ───────────────────────────
@terminal_bp.route('/api/tasks/<task_id>/execute', methods=['POST'])
def execute_project(task_id):
    """Start the execution agent for a task.

    SSE stream that runs the project, diagnoses errors, fixes them, and retries.
    """
    workspace_path = _get_workspace(task_id)
    if not workspace_path or not os.path.isdir(workspace_path):
        return jsonify({"error": "Task or workspace not found"}), 404

    session_id = f"exec-{task_id}"
    cancel_event = threading.Event()
    _exec_cancel_events[session_id] = cancel_event

    def generate():
        try:
            for chunk in AgentService.run_execution_stream(
                task_id, cancel_event=cancel_event
            ):
                yield chunk
        except GeneratorExit:
            cancel_event.set()
        except Exception as e:
            yield f"event: exec_error\ndata: {json.dumps({'error': str(e)})}\n\n"
        finally:
            _exec_cancel_events.pop(session_id, None)

    return Response(
        stream_with_context(generate()),
        content_type='text/event-stream; charset=utf-8',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        }
    )


@terminal_bp.route('/api/tasks/<task_id>/execute/cancel', methods=['POST'])
def cancel_execution(task_id):
    """Cancel a running execution agent."""
    session_id = f"exec-{task_id}"
    event = _exec_cancel_events.get(session_id)
    if event:
        event.set()
        return jsonify({"status": "cancelled"})
    return jsonify({"status": "no_active_execution"})


@terminal_bp.route('/api/tasks/<task_id>/rl-report', methods=['POST'])
def generate_rl_report(task_id):
    """Generate the RL learning report for a task on demand.

    Called after Run Project succeeds (or any time the user wants
    a snapshot of what the RL system has learned for this task).
    """
    workspace_path = _get_workspace(task_id)
    if not workspace_path or not os.path.isdir(workspace_path):
        return jsonify({"error": "Task or workspace not found"}), 404

    try:
        AgentService.generate_rl_report_for_task(task_id, workspace_path)
        return jsonify({"status": "ok", "path": "rl-learning-report.txt"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
