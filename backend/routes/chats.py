import os
import sys
import json
import threading
import requests as _requests
from flask import Blueprint, request, jsonify, Response, stream_with_context
from services.agent_service import AgentService
from services.task_service import TaskService
from services.llm_engine import LLMEngine, get_llm_engine
from utils.logging import _safe_log

chats_bp = Blueprint('chats', __name__)

# ── Cancel Event Registry ────────────────────────────────────────────
# Tracks active cancel events by chat_id so the cancel endpoint can
# signal in-flight generations to stop and release the GPU lock.
# Also tracks task_id → set(chat_id) for task-level cancellation.
_cancel_registry_lock = threading.Lock()
_active_cancel_events: dict = {}  # chat_id → threading.Event
_task_chat_map: dict = {}  # task_id → set(chat_id)

def _register_cancel_event(chat_id: str, event: threading.Event, task_id: str = None):
    with _cancel_registry_lock:
        _active_cancel_events[chat_id] = event
        if task_id:
            if task_id not in _task_chat_map:
                _task_chat_map[task_id] = set()
            _task_chat_map[task_id].add(chat_id)

def _unregister_cancel_event(chat_id: str, task_id: str = None):
    with _cancel_registry_lock:
        _active_cancel_events.pop(chat_id, None)
        if task_id and task_id in _task_chat_map:
            _task_chat_map[task_id].discard(chat_id)
            if not _task_chat_map[task_id]:
                del _task_chat_map[task_id]

def _get_cancel_event(chat_id: str):
    with _cancel_registry_lock:
        return _active_cancel_events.get(chat_id)

def _cancel_all_for_task(task_id: str) -> int:
    """Cancel all active chat streams for a task. Returns count of cancelled chats."""
    with _cancel_registry_lock:
        chat_ids = list(_task_chat_map.get(task_id, set()))
    cancelled = 0
    for cid in chat_ids:
        event = _get_cancel_event(cid)
        if event:
            event.set()
            cancelled += 1
            _safe_log(f"[SSE] Task-level cancel: cancelled chat {cid} for task {task_id}")
    return cancelled

# ── Routes ────────────────────────────────────────────────────────────

@chats_bp.route('/api/tasks/<task_id>/chats', methods=['GET'])
def list_chats(task_id):
    chats = AgentService.list_chats(task_id)
    return jsonify(chats)

@chats_bp.route('/api/tasks/<task_id>/chats', methods=['POST'])
def create_chat(task_id):
    chat = AgentService.create_chat(task_id)
    return jsonify(chat), 201

@chats_bp.route('/api/chats/<chat_id>/messages', methods=['POST'])
def add_message(chat_id):
    data = request.json or {}
    task_id = data.get('taskId')
    if not task_id:
        return jsonify({"error": "taskId is required"}), 400

    content = data.get('content')
    role = data.get('role', 'user')

    # Validate role is one of the expected values
    if role not in ('user', 'assistant', 'system'):
        return jsonify({"error": "Invalid role"}), 400

    # Cap content length
    if content and len(content) > 100_000:
        return jsonify({"error": "Message content too long (max 100000 chars)"}), 400

    msg = AgentService.add_message(task_id, chat_id, role, content)
    if not msg:
        return jsonify({"error": "Chat not found"}), 404

    return jsonify(msg), 201

@chats_bp.route('/api/chats/<chat_id>/stream', methods=['GET'])
def stream_chat(chat_id):
    task_id = request.args.get('taskId')
    if not task_id:
        return jsonify({"error": "taskId query param is required"}), 400

    message = request.args.get('message')

    # Cap message length to prevent absurdly large prompts from being injected
    if message and len(message) > 50_000:
        return jsonify({"error": "Message too long (max 50000 chars)"}), 400

    # Cancel event: set when client disconnects so the agent loop + LLM
    # can abort early instead of holding the GPU lock for a dead connection.
    cancel_event = threading.Event()
    _register_cancel_event(chat_id, cancel_event, task_id=task_id)

    # Shared state for saving partial responses on disconnect.
    # The agent loop updates stream_state['unsaved'] with the current partial response.
    # On GeneratorExit (client disconnect), we save whatever was accumulated.
    stream_state = {"unsaved": ""}

    def generate():
        try:
            if message:
                for chunk in AgentService.run_agent_stream(task_id, chat_id, message, cancel_event=cancel_event, stream_state=stream_state):
                    yield chunk
            else:
                for chunk in AgentService.continue_chat_stream(task_id, chat_id, cancel_event=cancel_event, stream_state=stream_state):
                    yield chunk
        except GeneratorExit:
            # Client disconnected — signal cancellation
            cancel_event.set()
            _safe_log(f"[SSE] Client disconnected, cancelling stream for chat {chat_id}")
            # Save any partial response that wasn't persisted yet
            unsaved = stream_state.get("unsaved", "").strip()
            if unsaved:
                try:
                    AgentService.add_message(task_id, chat_id, "assistant", unsaved)
                    _safe_log(f"[SSE] Saved partial response ({len(unsaved)} chars) for chat {chat_id}")
                except Exception:
                    pass
        except Exception as e:
            # Catch-all: LLM crash, OOM, timeout, etc.
            _safe_log(f"[SSE] Stream error for chat {chat_id}: {e}")
            import traceback
            traceback.print_exc()
            try:
                yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
                yield f"event: done\ndata: {json.dumps({'full_content': '', 'error': True})}\n\n"
            except Exception:
                pass
        finally:
            _unregister_cancel_event(chat_id, task_id=task_id)

    return Response(
        stream_with_context(generate()),
        content_type='text/event-stream; charset=utf-8',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        }
    )

# ── Cancel Endpoints ──────────────────────────────────────────────────

@chats_bp.route('/api/chats/<chat_id>/cancel', methods=['POST'])
def cancel_chat(chat_id):
    """Cancel an in-flight generation for a specific chat."""
    event = _get_cancel_event(chat_id)
    if event:
        event.set()
        _safe_log(f"[SSE] Cancel requested for chat {chat_id}")
        return jsonify({"status": "cancelled"})
    return jsonify({"status": "no_active_generation"})

@chats_bp.route('/api/tasks/<task_id>/cancel-all', methods=['POST'])
def cancel_all_task_chats(task_id):
    """Cancel ALL active generations for a task. Used when navigating away or creating a new task."""
    cancelled = _cancel_all_for_task(task_id)
    _safe_log(f"[SSE] Cancel-all for task {task_id}: {cancelled} streams cancelled")
    return jsonify({"status": "cancelled", "count": cancelled})

@chats_bp.route('/api/gpu/cancel', methods=['POST'])
def cancel_gpu():
    """Emergency: force-cancel whatever is running on the GPU."""
    released = LLMEngine.force_cancel()
    return jsonify({"status": "released" if released else "timeout"})

# ── LLM Status Endpoint ──────────────────────────────────────────────

@chats_bp.route('/api/llm/status', methods=['GET'])
def llm_status():
    """Check LM Studio connectivity and return model info."""
    engine = get_llm_engine()
    try:
        resp = _requests.get('http://localhost:1234/v1/models', timeout=2)
        resp.raise_for_status()
        data = resp.json()
        models = data.get('data', [])
        return jsonify({
            'connected': True,
            'model': engine._model_id,
            'context_size': engine.context_size,
            'models_available': len(models),
        })
    except Exception as e:
        return jsonify({
            'connected': False,
            'model': getattr(engine, '_model_id', None),
            'context_size': getattr(engine, 'context_size', None),
            'error': str(e),
        })

# ── Review Stream Endpoint ───────────────────────────────────────────

@chats_bp.route('/api/chats/<chat_id>/review', methods=['GET'])
def review_stream(chat_id):
    """Stream a code review for a specific chat/step.

    The review agent reads the files written during the step, reviews them,
    and can use EditFile to make improvements. Streams SSE events:
      - review_status: {status: "..."} — progress updates
      - review_token: {token: "..."} — review content tokens
      - review_edit: {path, old_string, new_string} — file edit made
      - review_done: {content: "...", edits: [...]} — final review
      - review_error: {error: "..."} — on failure
    """
    task_id = request.args.get('taskId')
    prompt = request.args.get('prompt', 'Please review my changes')
    if not task_id:
        return jsonify({"error": "taskId query param is required"}), 400

    review_id = f"review-{chat_id}"
    cancel_event = threading.Event()
    _register_cancel_event(review_id, cancel_event, task_id=task_id)

    def generate():
        try:
            for chunk in AgentService.run_review_stream(
                task_id, chat_id, prompt, cancel_event=cancel_event
            ):
                yield chunk
        except GeneratorExit:
            cancel_event.set()
            _safe_log(f"[Review] Client disconnected for chat {chat_id}")
        except Exception as e:
            _safe_log(f"[Review] Stream error for chat {chat_id}: {e}")
            import traceback
            traceback.print_exc()
            try:
                yield f"event: review_error\ndata: {json.dumps({'error': str(e)})}\n\n"
            except Exception:
                pass
        finally:
            _unregister_cancel_event(review_id, task_id=task_id)

    return Response(
        stream_with_context(generate()),
        content_type='text/event-stream; charset=utf-8',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        }
    )

@chats_bp.route('/api/chats/<chat_id>/cancel-review', methods=['POST'])
def cancel_review(chat_id):
    """Cancel an in-flight review for a specific chat."""
    review_id = f"review-{chat_id}"
    event = _get_cancel_event(review_id)
    if event:
        event.set()
        _safe_log(f"[Review] Cancel requested for chat {chat_id}")
        return jsonify({"status": "cancelled"})
    return jsonify({"status": "no_active_review"})

# ── Apply Review Edits Endpoint ──────────────────────────────────────

@chats_bp.route('/api/chats/<chat_id>/apply-review-edits', methods=['POST'])
def apply_review_edits(chat_id):
    """Apply review edits to committed changes.

    Takes the list of file paths edited by the review agent and updates
    the committed changes summary message in the chat to reflect those edits.
    """
    data = request.get_json() or {}
    task_id = data.get('taskId')
    edited_paths = data.get('editedPaths', [])
    edit_details = data.get('editDetails', [])  # [{path, added, removed}]

    if not task_id:
        return jsonify({"error": "taskId is required"}), 400
    if not edited_paths:
        return jsonify({"error": "editedPaths is required"}), 400

    # Build lookup for per-file deltas from edit details
    delta_map = {}
    for ed in edit_details:
        p = ed.get('path', '')
        if p not in delta_map:
            delta_map[p] = {'added': 0, 'removed': 0}
        delta_map[p]['added'] += ed.get('added', 0)
        delta_map[p]['removed'] += ed.get('removed', 0)

    task = TaskService.get_task(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404

    chat = AgentService.get_chat(task_id, chat_id)
    if not chat:
        return jsonify({"error": "Chat not found"}), 404

    workspace_path = task.get('workspacePath', '')
    all_steps = task.get('steps', [])
    step_for_chat = AgentService._find_step_by_chat_id(all_steps, chat_id)
    step_id = step_for_chat['id'] if step_for_chat else None

    SDD_STEPS = {'requirements', 'technical-specification', 'planning'}
    artifacts_dir = os.path.join(workspace_path, '.sentinel', 'tasks', task_id)
    if step_id and step_id in SDD_STEPS:
        agent_root = artifacts_dir
    else:
        agent_root = workspace_path

    # Find the summary message in the chat and update it
    summary_msg = None
    for msg in chat.get('messages', []):
        if msg.get('is_summary') and msg.get('structured'):
            summary_msg = msg

    if not summary_msg:
        return jsonify({"error": "No committed changes summary found"}), 404

    structured = summary_msg['structured']
    files_data = structured.get('files', [])

    # Mark edited files and apply line deltas
    total_delta_added = 0
    total_delta_removed = 0
    for edited_path in edited_paths:
        edited_name = os.path.basename(edited_path)
        delta = delta_map.get(edited_path, {'added': 0, 'removed': 0})
        # Find matching file in committed changes
        matched = False
        for f in files_data:
            if f['name'] == edited_name or edited_path.endswith(f['name']):
                f['isEdited'] = True
                f['isNew'] = False
                f['added'] = f.get('added', 0) + delta['added']
                f['removed'] = f.get('removed', 0) + delta['removed']
                total_delta_added += delta['added']
                total_delta_removed += delta['removed']
                matched = True
                break
        # If the file wasn't in committed changes, add it
        if not matched:
            abs_path = os.path.join(agent_root, edited_path)
            added = delta['added']
            if not added and os.path.isfile(abs_path):
                try:
                    with open(abs_path, 'r', encoding='utf-8') as fh:
                        added = len(fh.readlines())
                except Exception:
                    pass
            dir_path = os.path.dirname(edited_path).replace('\\', '/')
            files_data.append({
                'name': edited_name,
                'path': dir_path + '/' if dir_path else '',
                'isNew': False,
                'isEdited': True,
                'added': added,
                'removed': delta['removed'],
            })
            total_delta_added += added
            total_delta_removed += delta['removed']
            structured['totalFiles'] = len(files_data)

    # Update totals
    structured['totalAdded'] = structured.get('totalAdded', 0) + total_delta_added
    structured['totalRemoved'] = structured.get('totalRemoved', 0) + total_delta_removed

    # Save updated chat
    summary_msg['structured'] = structured
    AgentService.save_chat(task_id, chat_id, chat)

    return jsonify({"status": "ok", "structured": structured})
