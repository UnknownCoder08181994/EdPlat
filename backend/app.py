import sys
import io
import os

# Fix broken stdout AND stderr on Windows (OSError: [Errno 22] Invalid argument)
# This happens when Flask runs without a proper console attached.
# print() defaults to stdout, so both streams need patching.
for _stream_name in ('stdout', 'stderr'):
    _stream = getattr(sys, _stream_name)
    try:
        _stream.write('')
    except OSError:
        setattr(sys, _stream_name, io.TextIOWrapper(
            open(_stream.fileno(), 'wb', closefd=False),
            encoding='utf-8', errors='replace', line_buffering=True
        ))

print("[BOOT] LLM backend: LM Studio at localhost:1234", flush=True)

from flask import Flask, jsonify, render_template
from flask_cors import CORS
from config import Config
from routes.projects import projects_bp
from routes.tasks import tasks_bp
from routes.chats import chats_bp
from routes.files import files_bp
from routes.terminal import terminal_bp

app = Flask(__name__, template_folder='templates', static_folder='static', static_url_path='/static')
app.config.from_object(Config)
app.config['JSON_AS_ASCII'] = False  # Preserve UTF-8 in JSON responses
CORS(app)

app.register_blueprint(projects_bp)
app.register_blueprint(tasks_bp)
app.register_blueprint(chats_bp)
app.register_blueprint(files_bp)
app.register_blueprint(terminal_bp)

# Seed demo data on first run (idempotent)
from services.seed_data import ensure_seed_data
ensure_seed_data()

# Seed experience memory (RL learning system) on first run
from services.experience_memory import ExperienceMemory
ExperienceMemory.ensure_seeded()

# ── Crash recovery: detect stalled tasks on startup ──
def _detect_stalled_tasks():
    """Scan all tasks for 'In Progress' status with in_progress steps.
    These indicate the server crashed mid-generation. Mark them with hasStalled flag."""
    try:
        from services.task_service import TaskService
        from services.storage import StorageService
        tasks = TaskService.list_tasks()
        stalled_count = 0
        for t in tasks:
            if t.get('status') != 'In Progress':
                continue
            full_task = TaskService.get_task(t['id'])
            if not full_task:
                continue
            has_active_step = False
            for step in full_task.get('steps', []):
                if step.get('status') == 'in_progress':
                    has_active_step = True
                    break
                for child in step.get('children', []):
                    if child.get('status') == 'in_progress':
                        has_active_step = True
                        break
                if has_active_step:
                    break
            if has_active_step:
                raw = StorageService.load_json('tasks', f"{t['id']}.json")
                if raw and not raw.get('hasStalled'):
                    raw['hasStalled'] = True
                    StorageService.save_json('tasks', f"{t['id']}.json", raw)
                    stalled_count += 1
        if stalled_count:
            print(f"[BOOT] Detected {stalled_count} stalled task(s) from previous crash", flush=True)
    except Exception as e:
        print(f"[BOOT] Stall detection error: {e}", flush=True)

_detect_stalled_tasks()

@app.route('/')
@app.route('/task/<task_id>')
def serve_app(task_id=None):
    return render_template('base.html')

# Catch sub-path requests under /task/ (e.g. /task/css/style.css from relative
# links in generated projects) — return the SPA shell so the JS router handles it.
@app.route('/task/<task_id>/<path:subpath>')
def serve_app_subpath(task_id, subpath):
    return render_template('base.html')

@app.errorhandler(Exception)
def handle_exception(e):
    """Global error handler — always return JSON, never HTML."""
    from werkzeug.exceptions import HTTPException
    import traceback
    try:
        traceback.print_exc()
    except OSError:
        pass  # Windows: stderr broken when Flask runs without a console
    # Preserve the correct HTTP status code for client/HTTP errors (404, 400, etc.)
    status_code = e.code if isinstance(e, HTTPException) else 500
    return jsonify({"error": str(e), "type": type(e).__name__}), status_code

@app.route('/favicon.ico')
def favicon():
    return '', 204

@app.route('/.well-known/<path:subpath>')
def well_known_sink(subpath):
    return '', 204

@app.route('/api/health')
def health():
    return jsonify({"status": "ok", "message": "Sentinel Clone Backend Running"})

@app.route('/api/tasks/<task_id>/llm-log')
def get_llm_log(task_id):
    """Return the raw LLM activity log for a task.

    Never returns 404 — returns an empty log with a 'not started' message
    if the task hasn't produced any LLM output yet.
    """
    from flask import Response
    import re as _re
    # Sanitize task_id to prevent directory traversal (must look like a UUID)
    if not _re.match(r'^[a-zA-Z0-9_-]{1,64}$', task_id):
        return jsonify({"error": "Invalid task ID"}), 400
    log_dir = os.path.join(Config.STORAGE_DIR, 'llm_logs')
    log_path = os.path.join(log_dir, f'{task_id}.log')
    # Verify resolved path is within log directory
    if not os.path.abspath(log_path).startswith(os.path.abspath(log_dir)):
        return jsonify({"error": "Invalid task ID"}), 400
    if not os.path.isfile(log_path):
        content = f'[--:--:--.---] [META] No LLM activity recorded yet for task {task_id}\n'
        return Response(content, mimetype='text/plain; charset=utf-8')
    try:
        with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read(2_000_000)  # Cap at 2MB to prevent OOM
    except Exception:
        content = '[--:--:--.---] [META] Error reading log file\n'
    return Response(content, mimetype='text/plain; charset=utf-8')

if __name__ == '__main__':
    import os
    # Disable reloader to prevent restarts when torch/transformers files are accessed
    # This is necessary because the model loading touches many library files
    use_reloader = os.environ.get('FLASK_USE_RELOADER', '0') == '1'
    app.run(debug=True, port=5002, use_reloader=use_reloader, threaded=True)
