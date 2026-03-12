import os
import re
import sys
import threading
from flask import Blueprint, request, jsonify, Response
from services.task_service import TaskService
from services.storage import StorageService
from services.agent_service import AgentService
from services.plan_engine import parse_plan, select_next
from prompts import build_task_reformat_prompt

tasks_bp = Blueprint('tasks', __name__)

@tasks_bp.route('/api/tasks', methods=['GET'])
def list_tasks():
    project_id = request.args.get('projectId')
    tasks = TaskService.list_tasks(project_id)
    return jsonify(tasks)

@tasks_bp.route('/api/tasks', methods=['POST'])
def create_task():
    data = request.json
    project_id = data.get('projectId')
    workflow_type = data.get('workflowType', 'Full SDD workflow')
    details = data.get('details')
    settings = data.get('settings', {})

    if not project_id or not details:
        return jsonify({"error": "ProjectId and details are required"}), 400

    try:
        task = TaskService.create_task(project_id, workflow_type, details, settings)
        return jsonify(task), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@tasks_bp.route('/api/tasks/<task_id>', methods=['GET'])
def get_task(task_id):
    task = TaskService.get_task(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404
    return jsonify(task)

@tasks_bp.route('/api/tasks/<task_id>', methods=['DELETE'])
def delete_task(task_id):
    try:
        TaskService.delete_task(task_id)
        return jsonify({"status": "deleted"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@tasks_bp.route('/api/tasks/batch-delete', methods=['POST'])
def batch_delete_tasks():
    data = request.json or {}
    task_ids = data.get('taskIds', [])
    if not task_ids:
        return jsonify({"error": "No task IDs provided"}), 400
    # Validate input type and cap batch size to prevent DoS
    if not isinstance(task_ids, list) or len(task_ids) > 100:
        return jsonify({"error": "taskIds must be a list of at most 100 IDs"}), 400
    deleted = 0
    errors = []
    for task_id in task_ids:
        # Validate task_id format
        if not isinstance(task_id, str) or not re.match(r'^[a-zA-Z0-9_-]{1,64}$', task_id):
            errors.append({"id": str(task_id)[:64], "error": "Invalid task ID format"})
            continue
        try:
            TaskService.delete_task(task_id)
            deleted += 1
        except Exception as e:
            errors.append({"id": task_id, "error": str(e)})
    return jsonify({"deleted": deleted, "errors": errors})


@tasks_bp.route('/api/tasks/cleanup', methods=['POST'])
def cleanup_tasks():
    """Remove workspaces for tasks older than N days (default 30)."""
    from config import Config

    data = request.get_json(silent=True) or {}
    max_age_days = data.get('maxAgeDays', 30)
    # Validate max_age_days is a reasonable number
    if not isinstance(max_age_days, (int, float)) or max_age_days < 1:
        return jsonify({"error": "maxAgeDays must be >= 1"}), 400

    import time as _time
    cutoff = _time.time() - (max_age_days * 86400)
    tasks = TaskService.list_tasks()
    # Safety: resolve the expected workspace parent directory
    workspace_parent = os.path.abspath(os.path.join(Config.STORAGE_DIR, 'workspaces'))
    cleaned = 0
    for t in tasks:
        created = t.get('createdAt', '')
        if not created:
            continue
        try:
            from datetime import datetime
            ts = datetime.fromisoformat(created.replace('Z', '+00:00')).timestamp()
            if ts < cutoff:
                workspace = t.get('workspacePath', '')
                if not workspace:
                    continue
                # CRITICAL: Verify workspace is within our storage/workspaces dir
                # This prevents a manipulated task JSON from causing deletion of
                # arbitrary directories via path traversal
                abs_ws = os.path.abspath(workspace)
                if not abs_ws.startswith(workspace_parent + os.sep):
                    continue
                if os.path.exists(abs_ws):
                    import shutil
                    shutil.rmtree(abs_ws, ignore_errors=True)
                    cleaned += 1
        except Exception:
            continue

    return jsonify({"cleaned": cleaned, "maxAgeDays": max_age_days})


@tasks_bp.route('/api/tasks/<task_id>/pause', methods=['POST'])
def pause_task(task_id):
    """Pause a task — designed for navigator.sendBeacon (POST-only)."""
    task = StorageService.load_json('tasks', f"{task_id}.json")
    if task and task.get('status') == 'In Progress':
        task['status'] = 'Paused'
        StorageService.save_json('tasks', f"{task_id}.json", task)
        try:
            print(f"[Task] Paused task {task_id}", file=sys.stderr, flush=True)
        except OSError:
            pass
    return jsonify({"status": "ok"})

@tasks_bp.route('/api/tasks/<task_id>', methods=['PATCH'])
def update_task(task_id):
    data = request.json or {}
    task = StorageService.load_json('tasks', f"{task_id}.json")
    if not task:
        return jsonify({"error": "Task not found"}), 404

    # Validate status is a known value
    VALID_STATUSES = {'Pending', 'To Do', 'In Progress', 'Paused', 'Completed', 'Failed'}
    if 'status' in data:
        if data['status'] not in VALID_STATUSES:
            return jsonify({"error": f"Invalid status. Must be one of: {', '.join(sorted(VALID_STATUSES))}"}), 400
        task['status'] = data['status']

    if 'settings' in data:
        if not isinstance(data['settings'], dict):
            return jsonify({"error": "settings must be a JSON object"}), 400
        task['settings'] = {**task.get('settings', {}), **data['settings']}

    if 'hasStalled' in data:
        if data['hasStalled']:
            task['hasStalled'] = True
        else:
            task.pop('hasStalled', None)

    StorageService.save_json('tasks', f"{task_id}.json", task)
    return jsonify(TaskService.get_task(task_id))

@tasks_bp.route('/api/tasks/<task_id>/next-step', methods=['GET'])
def get_next_step(task_id):
    """Return the next step to execute based on the deterministic selection algorithm."""
    task = TaskService.get_task(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404

    workspace_path = task.get('workspacePath')
    if not workspace_path:
        return jsonify({"error": "Task has no workspace"}), 400

    plan_path = os.path.join(workspace_path, '.sentinel', 'tasks', task_id, 'plan.md')
    plan = parse_plan(plan_path)
    result = select_next(plan)

    if result.halted:
        return jsonify({"halted": True, "reason": result.halt_reason, "warnings": result.warnings})
    if result.target is None:
        return jsonify({"complete": True, "warnings": result.warnings})

    return jsonify({
        "stepId": result.target.id,
        "stepName": result.target.name,
        "isSubtask": not result.target.is_root,
        "parentId": result.target.parent_id,
        "warnings": result.warnings,
    })


@tasks_bp.route('/api/tasks/<task_id>/steps/<step_id>/start', methods=['POST'])
def start_step(task_id, step_id):
    # Health gate: check if LM Studio is reachable before allowing step start
    import requests as _req
    try:
        _llm_resp = _req.get('http://localhost:1234/v1/models', timeout=2)
        _llm_resp.raise_for_status()
    except Exception:
        return jsonify({"error": "LM Studio is not reachable. Please start LM Studio and try again."}), 503

    task = TaskService.get_task(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404

    # Find the step — search root steps and their children (subtasks)
    def _find_step_in_list(steps, target_id):
        for s in steps:
            if s['id'] == target_id:
                return s
            for child in s.get('children', []):
                if child['id'] == target_id:
                    return child
        return None

    step = _find_step_in_list(task.get('steps', []), step_id)
    if not step:
        return jsonify({"error": "Step not found"}), 404

    # If step already has a chatId, just return it (but still auto-transition task status)
    if step.get('chatId'):
        raw_task = StorageService.load_json('tasks', f"{task_id}.json")
        if raw_task and raw_task.get('status') not in ('In Progress', 'Completed', 'Failed'):
            raw_task['status'] = 'In Progress'
            StorageService.save_json('tasks', f"{task_id}.json", raw_task)
        return jsonify({"stepId": step_id, "chatId": step['chatId']})

    # Check if a chat with this step's name already exists (race condition guard:
    # the frontend ChatPanel may have created one via auto-start before startStep returns)
    existing_chats = AgentService.list_chats(task_id)
    existing = next((c for c in existing_chats if c.get('name') == step['name']), None)
    if existing:
        chat = existing
    else:
        # Create a new chat for this step
        chat = AgentService.create_chat(task_id, name=step['name'])

    # Link the chat to the step in plan.md and set in_progress
    workspace_path = task.get('workspacePath')
    TaskService.update_step_in_plan(workspace_path, task_id, step_id, {
        'status': 'in_progress',
        'chatId': chat['id']
    })

    # Auto-transition task status to "In Progress" when a step starts
    raw_task = StorageService.load_json('tasks', f"{task_id}.json")
    if raw_task and raw_task.get('status') != 'In Progress':
        raw_task['status'] = 'In Progress'
        StorageService.save_json('tasks', f"{task_id}.json", raw_task)
        try:
            print(f"[Task] Auto-transitioned task {task_id} to 'In Progress'", file=sys.stderr, flush=True)
        except OSError:
            pass

    return jsonify({"stepId": step_id, "chatId": chat['id']}), 201

@tasks_bp.route('/api/tasks/<task_id>/steps/<step_id>', methods=['PATCH'])
def update_step_route(task_id, step_id):
    data = request.json
    task = TaskService.get_task(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404

    workspace_path = task.get('workspacePath')
    updates = {}
    if 'status' in data:
        updates['status'] = data['status']

    success = TaskService.update_step_in_plan(workspace_path, task_id, step_id, updates)
    if not success:
        return jsonify({"error": "Failed to update step"}), 500

    # Auto-transition task to "Completed" when all steps are done
    if updates.get('status') == 'completed':
        updated_task = TaskService.get_task(task_id)
        all_steps = updated_task.get('steps', [])
        flat = []
        for s in all_steps:
            flat.append(s)
            flat.extend(s.get('children', []))
        if flat and all(s.get('status') == 'completed' for s in flat):
            raw_task = StorageService.load_json('tasks', f"{task_id}.json")
            if raw_task and raw_task.get('status') != 'Completed':
                raw_task['status'] = 'Completed'
                StorageService.save_json('tasks', f"{task_id}.json", raw_task)
        return jsonify(updated_task)

    return jsonify(TaskService.get_task(task_id))


@tasks_bp.route('/api/tasks/<task_id>/retry-install', methods=['POST'])
def retry_install(task_id):
    """Re-trigger auto-install of dependencies for a task."""
    task = TaskService.get_task(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404

    workspace_path = task.get('workspacePath', '')
    if not workspace_path:
        return jsonify({"error": "No workspace path"}), 400

    try:
        result = AgentService._auto_install_dependencies(workspace_path)
        if result.get('installed'):
            return jsonify({"status": "success", "packages": result['installed']})
        elif result.get('errors'):
            return jsonify({"status": "error", "errors": result['errors']}), 500
        else:
            return jsonify({"status": "no_deps", "message": "No dependencies to install"})
    except Exception as e:
        return jsonify({"status": "error", "errors": [str(e)]}), 500


def _find_open_port(start=5000, end=9000):
    """Find an available localhost port in the given range."""
    import socket
    # Preferred ports: 5000, 8080, 8000, 3000, then scan
    for port in [5000, 8080, 8000, 3000]:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('127.0.0.1', port))
                return port
        except OSError:
            continue
    # Fallback: scan range
    for port in range(start, end):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('127.0.0.1', port))
                return port
        except OSError:
            continue
    return 8080  # last resort


_WEB_KEYWORDS = re.compile(
    r'\b(?:web|website|webapp|web\s*app|dashboard|flask|django|html|frontend|'
    r'server|api|rest|http|browser|responsive|ui|interface|page|site|'
    r'portfolio|landing|blog|forum|chat|e-?commerce|shop|store|'
    r'graphical|visual|display|render|chart|graph|plot|'
    r'three\.?js|d3|canvas|svg|animation|3d|webgl|css|tailwind|bootstrap)\b',
    re.IGNORECASE
)


@tasks_bp.route('/api/reformat-task', methods=['POST'])
def reformat_task():
    """Use the LLM to reformat a rough task description into a well-defined prompt."""
    data = request.json or {}
    details = (data.get('details') or '').strip()
    complexity = data.get('complexity', 5)  # 1-10 scale

    if not details:
        return jsonify({"error": "Task details are required"}), 400

    # Cap details length to prevent absurdly long LLM prompts
    if len(details) > 10_000:
        return jsonify({"error": "Task details too long (max 10000 chars)"}), 400

    # Validate complexity is in expected range
    if not isinstance(complexity, (int, float)) or complexity < 1 or complexity > 10:
        complexity = 5

    from prompts.task_reformat import is_vague_input, get_prebuilt_spec

    # For vague inputs, skip LLM entirely — return prebuilt spec
    if is_vague_input(details):
        prebuilt = get_prebuilt_spec(complexity=complexity)
        # Inject available port if the prebuilt spec is web-related
        if _WEB_KEYWORDS.search(prebuilt):
            port = _find_open_port()
            prebuilt += f" The server should run on localhost port {port}."
        return jsonify({"reformatted": prebuilt})

    system_content, user_preamble, shot_a_input, shot_a_output = build_task_reformat_prompt(complexity=complexity)

    # Detect web projects and find an available port
    is_web = bool(_WEB_KEYWORDS.search(details))
    port_hint = ''
    if is_web:
        port = _find_open_port()
        port_hint = (
            f" The server should run on localhost port {port} "
            f"(http://localhost:{port})."
        )

    # Follow-up instruction: PRESERVE the user's idea, just reformat it
    if complexity <= 3:
        follow_up = (
            f"Good. Now rewrite the user's task below using the same format. "
            f"Keep their project idea -- just make it clearer and more specific. "
            f"2-4 sentences, plain text, no code, no markdown.{port_hint}\n\n\"{details}\""
        )
    else:
        follow_up = (
            f"Good. Now rewrite the user's task below using the same format. "
            f"Keep their project idea -- do NOT change what they want to build. "
            f"Just make it clearer, more specific, and well-structured. Describe "
            f"what to build and key features. Plain prose only, no code, no "
            f"markdown, no bullet lists.{port_hint}\n\n\"{details}\""
        )

    # Multi-turn few-shot: put the example in an assistant turn so the model
    # sees it as something it already "said", then pattern-matches on the real input.
    prompt_messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": f"{user_preamble}\"{shot_a_input}\""},
        {"role": "assistant", "content": shot_a_output},
        {"role": "user", "content": follow_up},
    ]

    try:
        from services.llm_engine import get_llm_engine, LLMEngine
        engine = get_llm_engine()

        # Scale token budget with complexity so higher levels get more room.
        # Reasoning models (GPT-OSS) spend ~200+ tokens on chain-of-thought before
        # emitting content, so budgets must be generous enough for both.
        # Bumped from original values to give the model room for quality output.
        token_budget = 384 if complexity <= 2 else 512 if complexity <= 3 else 896 if complexity <= 5 else 1280 if complexity <= 7 else 1536

        def _call_llm(messages, budget):
            chunks = []
            cancel_event = threading.Event()
            TPFX = LLMEngine.THINK_PREFIX
            for chunk in engine.stream_chat(
                messages,
                max_new_tokens=budget,
                temperature=0.8,
                cancel_event=cancel_event,
            ):
                # Skip reasoning/thinking tokens — we only want content
                if chunk.startswith(TPFX):
                    continue
                chunks.append(chunk)
            return ''.join(chunks).strip()

        reformatted = _call_llm(prompt_messages, token_budget)
        # If reasoning ate the whole budget, retry once with more room
        if not reformatted:
            reformatted = _call_llm(prompt_messages, token_budget * 2)

        try:
            safe_preview = reformatted[:200].encode('ascii', 'replace').decode('ascii')
            print(f"[Reformat] Raw response ({len(reformatted)} chars): {safe_preview}...", flush=True)
        except Exception:
            pass

        # Strip DeepSeek R1 <think>...</think> reasoning blocks
        reformatted = re.sub(r'<think>.*?</think>', '', reformatted, flags=re.DOTALL).strip()
        # Also strip GPT-OSS channel tags
        reformatted = re.sub(r'<\|channel\|>.*?(?=<\|channel\|>|\Z)', '', reformatted, flags=re.DOTALL).strip()
        # Strip any remaining [Error from LLM: ...] markers
        reformatted = re.sub(r'\[Error from LLM:.*?\]', '', reformatted, flags=re.DOTALL).strip()

        # Fix mojibake: model outputs UTF-8 bytes misinterpreted as latin-1.
        # Match sequences like \u00e2\u0080\u00XX (3-byte UTF-8 encoded as 3 latin-1 chars)
        # and repair them individually.
        def _fix_mojibake(m):
            try:
                raw = m.group(0).encode('latin-1').decode('utf-8')
                # Convert the decoded unicode char to ASCII
                _to_ascii = {
                    '\u2011': '-', '\u2010': '-',                  # hyphens
                    '\u2013': '-', '\u2014': '--',                 # dashes
                    '\u2018': "'", '\u2019': "'",                  # single quotes
                    '\u201c': '"', '\u201d': '"',                  # double quotes
                    '\u2026': '...',                                # ellipsis
                    '\u00a0': ' ',                                  # nbsp
                    '\u2022': '-',                                  # bullet
                }
                return _to_ascii.get(raw, raw)
            except (UnicodeDecodeError, UnicodeEncodeError):
                return ''  # strip unrecoverable sequences

        reformatted = re.sub(r'[\u00c0-\u00ef][\u0080-\u00bf]{1,2}', _fix_mojibake, reformatted)

        # Replace any remaining Unicode punctuation with ASCII equivalents
        _unicode_map = {
            '\u2018': "'", '\u2019': "'",     # smart single quotes
            '\u201c': '"', '\u201d': '"',     # smart double quotes
            '\u2013': '-', '\u2014': '--',    # en-dash, em-dash
            '\u2011': '-', '\u2010': '-',     # hyphens
            '\u2026': '...',                   # ellipsis
            '\u00a0': ' ',                     # non-breaking space
            '\u200b': '',                      # zero-width space
        }
        for uc, asc in _unicode_map.items():
            reformatted = reformatted.replace(uc, asc)

        if not reformatted:
            return jsonify({"error": "LLM returned empty response"}), 500

        return jsonify({"reformatted": reformatted})

    except Exception as e:
        import traceback
        # Print to both stdout and stderr for visibility on Windows
        err_msg = f"[Reformat] Error: {e}"
        try:
            print(err_msg, flush=True)
            traceback.print_exc()
        except OSError:
            pass
        try:
            print(err_msg, file=sys.stderr, flush=True)
        except OSError:
            pass
        return jsonify({"error": f"Reformat failed: {str(e)}"}), 500


@tasks_bp.route('/api/reformat-task-stream', methods=['POST'])
def reformat_task_stream():
    """SSE streaming version of reformat — yields tokens for typewriter effect."""
    data = request.json or {}
    details = (data.get('details') or '').strip()
    complexity = data.get('complexity', 5)

    if not details:
        return jsonify({"error": "Task details are required"}), 400

    # Cap details length
    if len(details) > 10_000:
        return jsonify({"error": "Task details too long (max 10000 chars)"}), 400

    # Validate complexity
    if not isinstance(complexity, (int, float)) or complexity < 1 or complexity > 10:
        complexity = 5

    from prompts.task_reformat import is_vague_input, get_prebuilt_spec

    # For vague inputs, skip LLM entirely — stream prebuilt spec for typewriter effect
    if is_vague_input(details):
        prebuilt = get_prebuilt_spec(complexity=complexity)
        if _WEB_KEYWORDS.search(prebuilt):
            port = _find_open_port()
            prebuilt += f" The server should run on localhost port {port}."
        def generate_prebuilt():
            import json as _json
            words = prebuilt.split(' ')
            for i, word in enumerate(words):
                token = word if i == 0 else ' ' + word
                yield f"data: {_json.dumps({'token': token})}\n\n"
            yield f"data: {_json.dumps({'done': True})}\n\n"
        return Response(generate_prebuilt(), mimetype='text/event-stream',
                        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

    system_content, user_preamble, shot_a_input, shot_a_output = build_task_reformat_prompt(complexity=complexity)

    # Detect web projects and find an available port
    is_web = bool(_WEB_KEYWORDS.search(details))
    port_hint = ''
    if is_web:
        port = _find_open_port()
        port_hint = (
            f" The server should run on localhost port {port} "
            f"(http://localhost:{port})."
        )

    # Follow-up instruction: PRESERVE the user's idea, just reformat it
    if complexity <= 3:
        follow_up = (
            f"Good. Now rewrite the user's task below using the same format. "
            f"Keep their project idea -- just make it clearer and more specific. "
            f"2-4 sentences, plain text, no code, no markdown.{port_hint}\n\n\"{details}\""
        )
    else:
        follow_up = (
            f"Good. Now rewrite the user's task below using the same format. "
            f"Keep their project idea -- do NOT change what they want to build. "
            f"Just make it clearer, more specific, and well-structured. Describe "
            f"what to build and key features. Plain prose only, no code, no "
            f"markdown, no bullet lists.{port_hint}\n\n\"{details}\""
        )

    prompt_messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": f"{user_preamble}\"{shot_a_input}\""},
        {"role": "assistant", "content": shot_a_output},
        {"role": "user", "content": follow_up},
    ]

    def generate():
        import json as _json
        try:
            from services.llm_engine import get_llm_engine, LLMEngine
            engine = get_llm_engine()
            TPFX = LLMEngine.THINK_PREFIX
            token_budget = 384 if complexity <= 2 else 512 if complexity <= 3 else 896 if complexity <= 5 else 1280 if complexity <= 7 else 1536
            cancel_event = threading.Event()

            # Unicode punctuation → ASCII map
            _uc_map = {
                '\u2018': "'", '\u2019': "'",
                '\u201c': '"', '\u201d': '"',
                '\u2013': '-', '\u2014': '--',
                '\u2011': '-', '\u2010': '-',
                '\u2026': '...', '\u00a0': ' ', '\u200b': '',
            }

            inside_think = False
            inside_channel = False
            sent_thinking_signal = False

            for token in engine.stream_chat(
                prompt_messages,
                max_new_tokens=token_budget,
                temperature=0.8,
                cancel_event=cancel_event,
            ):
                # Signal that the model is reasoning (send once)
                if token.startswith(TPFX):
                    if not sent_thinking_signal:
                        sent_thinking_signal = True
                        yield f"data: {_json.dumps({'thinking': True})}\n\n"
                    continue

                # Skip <think>...</think> blocks
                if '<think>' in token:
                    inside_think = True
                    continue
                if inside_think:
                    if '</think>' in token:
                        inside_think = False
                    continue

                # Skip GPT-OSS <|channel|> blocks
                if '<|channel|>' in token:
                    inside_channel = True
                    continue
                if inside_channel:
                    if '<|message|>' in token:
                        inside_channel = False
                    continue

                # Clean mojibake triplets
                cleaned = re.sub(r'[\u00e2][\u0080-\u009f][\u0080-\u00bf]', '', token)
                # Replace unicode punctuation
                for uc, asc in _uc_map.items():
                    cleaned = cleaned.replace(uc, asc)

                if cleaned:
                    yield f"data: {_json.dumps({'token': cleaned})}\n\n"

            yield f"data: {_json.dumps({'done': True})}\n\n"
        except Exception as e:
            yield f"data: {_json.dumps({'error': str(e)})}\n\n"

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
