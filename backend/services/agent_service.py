import os
import sys
import io
import json
import uuid
import time
import re
import fnmatch
import platform
import subprocess
from datetime import datetime

from utils.logging import _safe_log
from config import Config
from services.error_memory import ErrorMemory
from services.llm_logger import LLMLogger

# Python standard library modules — single source of truth for the whole file.
# Used by _validate_project_integrity, ensure_dependencies, _scan_and_generate_requirements.
# Use Python's own stdlib list (3.10+), fall back to a manual set for older versions
import sys as _sys
if hasattr(_sys, 'stdlib_module_names'):
    _PYTHON_STDLIB = {n.split('.')[0] for n in _sys.stdlib_module_names}
else:
    _PYTHON_STDLIB = {
        '__future__', 'abc', 'argparse', 'ast', 'asyncio', 'base64',
        'collections', 'contextlib', 'copy', 'csv', 'dataclasses',
        'datetime', 'decimal', 'email', 'enum', 'functools', 'glob',
        'hashlib', 'hmac', 'html', 'http', 'importlib', 'inspect',
        'io', 'itertools', 'json', 'logging', 'math', 'multiprocessing',
        'operator', 'os', 'pathlib', 'pickle', 'platform', 'pprint',
        're', 'secrets', 'shutil', 'signal', 'smtplib', 'socket',
        'sqlite3', 'ssl', 'string', 'struct', 'subprocess', 'sys',
        'tempfile', 'textwrap', 'threading', 'time', 'traceback',
        'typing', 'unittest', 'urllib', 'uuid', 'warnings', 'xml',
        'zipfile', 'configparser', 'queue', 'weakref', 'types',
        'numbers', 'fractions', 'statistics', 'random', 'bisect',
        'heapq', 'array', 'ctypes', 'concurrent', 'tkinter',
        'socketserver', 'mimetypes', 'codecs', 'select', 'selectors',
        'fnmatch', 'getpass', 'locale', 'shelve', 'dbm',
    }
from services.llm_engine import get_llm_engine, LLMEngine
from services.task_service import TaskService
from services.tool_service import ToolService
from services.micro_agents import (
    post_write_checks, build_signature_index,
    scan_downstream_dependencies, track_progress,
    optimize_history, run_tests, ImportGraph,
)
from services.reward_scorer import score_step, score_execution, score_task
from services.experience_memory import ExperienceMemory
from services.reward_agent import generate_lessons as _generate_reward_lessons
from prompts import (
    build_requirements_prompt,
    build_technical_specification_prompt,
    build_planning_prompt,
    build_implementation_prompt,
    build_code_context,
    build_read_before_write_rules,
    build_system_prompt,
    build_review_prompt,
    build_api_check_prompt,
    build_quality_check_prompt,
    build_fix_summary_prompt,
    nudges,
)

class AgentService:
    @staticmethod
    def _get_chat_dir(task_id):
        path = os.path.join(Config.STORAGE_DIR, 'chats', task_id)
        os.makedirs(path, exist_ok=True)
        return path

    @staticmethod
    def _get_chat_path(task_id, chat_id):
        return os.path.join(AgentService._get_chat_dir(task_id), f"{chat_id}.json")

    @staticmethod
    def list_chats(task_id):
        dir_path = AgentService._get_chat_dir(task_id)
        chats = []
        if os.path.exists(dir_path):
            for f in os.listdir(dir_path):
                if f.endswith('.json'):
                    path = os.path.join(dir_path, f)
                    try:
                        with open(path, 'r', encoding='utf-8') as file:
                            chat = json.load(file)
                            chats.append(chat)
                    except:
                        pass
        # Sort by createdAt
        chats.sort(key=lambda x: x.get('createdAt', ''), reverse=True)
        return chats

    @staticmethod
    def create_chat(task_id, name="New Chat"):
        chat_id = str(uuid.uuid4())
        chat = {
            "id": chat_id,
            "taskId": task_id,
            "name": name,
            "createdAt": datetime.now().isoformat(),
            "messages": [],
            "status": "active"
        }

        path = AgentService._get_chat_path(task_id, chat_id)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(chat, f, indent=2)

        return chat

    @staticmethod
    def get_chat(task_id, chat_id):
        path = AgentService._get_chat_path(task_id, chat_id)
        if not os.path.exists(path):
            return None
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    @staticmethod
    def save_chat(task_id, chat_id, chat_data):
        path = AgentService._get_chat_path(task_id, chat_id)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(chat_data, f, indent=2)

    @staticmethod
    def add_message(task_id, chat_id, role, content, meta=None):
        chat = AgentService.get_chat(task_id, chat_id)
        if not chat:
            return None

        message = {
            "id": str(uuid.uuid4()),
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        }
        if meta:
            message.update(meta)

        chat['messages'].append(message)
        AgentService.save_chat(task_id, chat_id, chat)
        return message

    @staticmethod
    def run_agent_stream(task_id, chat_id, user_message_content, cancel_event=None, stream_state=None):
        """
        Main agent loop.
        1. Add user message (idempotent — skips if already the last message).
        2. Stream response from LLM.
        3. Persist assistant message.
        """
        # 1. Add user message — check for duplicates first (retry safety)
        chat = AgentService.get_chat(task_id, chat_id)
        if chat:
            messages = chat.get('messages', [])
            last_msg = messages[-1] if messages else None
            if not (last_msg
                    and last_msg.get('role') == 'user'
                    and last_msg.get('content') == user_message_content):
                AgentService.add_message(task_id, chat_id, "user", user_message_content)
            else:
                _safe_log(f"[Agent] Skipping duplicate user message (retry detected)")
        else:
            AgentService.add_message(task_id, chat_id, "user", user_message_content)

        # 2. Continue stream
        for chunk in AgentService.continue_chat_stream(task_id, chat_id, cancel_event=cancel_event, stream_state=stream_state):
            yield chunk

    @staticmethod
    def run_review_stream(task_id, chat_id, user_prompt, cancel_event=None):
        """
        Review agent: reads files written in the step's chat, reviews them,
        and optionally uses EditFile to improve them. Streams SSE events.

        Events:
          - review_status: progress updates
          - review_token: streamed review content
          - review_edit: file edit made {path, old_string, new_string}
          - review_done: final review {content, edits}
          - review_error: on failure
        """
        task = TaskService.get_task(task_id)
        chat = AgentService.get_chat(task_id, chat_id)

        if not chat or not task:
            yield f"event: review_error\ndata: {json.dumps({'error': 'Chat or Task not found'})}\n\n"
            return

        workspace_path = task.get('workspacePath')
        if not workspace_path or not os.path.exists(workspace_path):
            yield f"event: review_error\ndata: {json.dumps({'error': 'Workspace not found'})}\n\n"
            return

        # Find the step this chat belongs to
        all_steps = task.get('steps', [])
        step_for_chat = AgentService._find_step_by_chat_id(all_steps, chat_id)
        step_id = step_for_chat['id'] if step_for_chat else None

        yield f"event: review_status\ndata: {json.dumps({'status': 'Analyzing files from this step...'})}\n\n"

        # Collect files written in this step from the chat history
        # Look at assistant messages for WriteFile/EditFile tool calls
        # Supports both <tool_code> and GPT-OSS <|channel|> formats
        written_file_paths = set()
        for msg in chat.get('messages', []):
            if msg.get('role') == 'assistant':
                content = msg.get('content', '')
                # Method 1: <tool_code>...</tool_code> blocks
                tool_blocks = re.findall(r'<tool_code>(.*?)</tool_code>', content, re.DOTALL)
                # Method 2: GPT-OSS <|channel|>...<|message|>... blocks
                gptoss_blocks = re.findall(
                    r'<\|channel\|>[^<]*(?:to=\w+\s*)?<\|(?:constrain\|>[^<]*<\|)?message\|>(.*?)(?=<\|channel\|>|\Z)',
                    content, re.DOTALL
                )
                for block in tool_blocks + gptoss_blocks:
                    path_match = re.search(r'"path"\s*:\s*"([^"]+)"', block)
                    name_match = re.search(r'"name"\s*:\s*"(WriteFile|EditFile)"', block)
                    if path_match and name_match:
                        written_file_paths.add(path_match.group(1))

        # Fallback: check step summary metadata for written files
        if not written_file_paths:
            for msg in chat.get('messages', []):
                structured = msg.get('structured')
                if structured and 'files' in structured:
                    for f in structured['files']:
                        fpath = f.get('name') or f.get('path', '')
                        if fpath:
                            written_file_paths.add(fpath)

        # Fallback 2: check file_written SSE events stored as user messages
        if not written_file_paths:
            for msg in chat.get('messages', []):
                if msg.get('role') == 'user' and msg.get('is_tool_result'):
                    content = msg.get('content', '')
                    # Tool results look like "Tool Result: Successfully wrote to requirements.md [meta:...]"
                    write_match = re.search(r'Successfully (?:wrote to|edited) (.+?)(?:\s*\[meta:|$)', content)
                    if write_match:
                        written_file_paths.add(write_match.group(1).strip())

        # ── Fallback: check if artifact exists on disk ──
        if not written_file_paths:
            SDD_ARTIFACT_MAP = {
                'requirements': 'requirements.md',
                'technical-specification': 'spec.md',
                'planning': 'implementation-plan.md',
            }
            if step_id in SDD_ARTIFACT_MAP:
                disk_artifact = SDD_ARTIFACT_MAP[step_id]
                disk_path = os.path.join(workspace_path, '.sentinel', 'tasks', task_id, disk_artifact)
                if os.path.isfile(disk_path) and os.path.getsize(disk_path) > 200:
                    written_file_paths.add(disk_artifact)
                    _safe_log(f"[Review] Fallback: found artifact '{disk_artifact}' on disk ({os.path.getsize(disk_path)} bytes)")

        if not written_file_paths:
            # No files to review — this is normal for impl steps that don't
            # need changes (e.g., wiring already done by prior steps).
            # Emit review_done so frontend auto-advances via flushPendingStepCompleted().
            _safe_log(f"[Review] No files found for step {step_id} — auto-passing review")
            yield f"event: review_status\ndata: {json.dumps({'status': 'No files changed — nothing to review'})}\n\n"
            yield f"event: review_done\ndata: {json.dumps({'content': 'No files were changed in this step. Review auto-passed.', 'edits': [], 'editDetails': []})}\n\n"
            return

        yield f"event: review_status\ndata: {json.dumps({'status': f'Reading {len(written_file_paths)} file(s)...'})}\n\n"

        # Determine the root path for reading files
        SDD_STEPS = {'requirements', 'technical-specification', 'planning'}
        artifacts_dir = os.path.join(workspace_path, '.sentinel', 'tasks', task_id)
        if step_id and step_id in SDD_STEPS:
            agent_root = artifacts_dir
        else:
            agent_root = workspace_path

        # Read file contents for the review
        file_contents = {}
        SKIP_DIRS = {'.venv', 'venv', '__pycache__', '.git', '.sentinel', 'node_modules'}
        for fpath in sorted(written_file_paths):
            abs_path = os.path.join(agent_root, fpath)
            if os.path.isfile(abs_path):
                try:
                    with open(abs_path, 'r', encoding='utf-8', errors='replace') as f:
                        file_contents[fpath] = f.read()
                except Exception:
                    _safe_log(f"[Review] Unable to read file: {abs_path}")
                    file_contents[fpath] = '(unable to read file)'
            else:
                _safe_log(f"[Review] File not found at: {abs_path}")
                # Fallback: search workspace by basename (handles path-prefix mismatches)
                target_name = os.path.basename(fpath)
                found = False
                for root_d, dirs_w, fnames_w in os.walk(workspace_path):
                    dirs_w[:] = [d for d in dirs_w if d not in SKIP_DIRS]
                    if target_name in fnames_w:
                        alt_path = os.path.join(root_d, target_name)
                        try:
                            with open(alt_path, 'r', encoding='utf-8', errors='replace') as f:
                                file_contents[fpath] = f.read()
                            _safe_log(f"[Review] Found {target_name} at {alt_path} (basename fallback)")
                            found = True
                            break
                        except Exception:
                            pass
                if not found:
                    file_contents[fpath] = '(file not found)'

        # Load ALL project source files so the review agent can read/edit any file
        written_paths = set(file_contents.keys())
        all_project_files = {}
        if step_id and step_id not in SDD_STEPS:
            SOURCE_EXTS = {'.py', '.js', '.ts', '.html', '.css', '.json', '.yaml', '.yml', '.toml', '.cfg', '.ini'}
            total_extra = 0
            MAX_EXTRA = 40000
            for root_d, dirs_p, fnames_p in os.walk(workspace_path):
                dirs_p[:] = [d for d in dirs_p if d not in SKIP_DIRS]
                for fname_p in sorted(fnames_p):
                    ext_p = os.path.splitext(fname_p)[1]
                    if ext_p not in SOURCE_EXTS:
                        continue
                    full_p = os.path.join(root_d, fname_p)
                    rel_p = os.path.relpath(full_p, workspace_path).replace('\\', '/')
                    if rel_p in written_paths:
                        continue
                    if total_extra > MAX_EXTRA:
                        break
                    try:
                        with open(full_p, 'r', encoding='utf-8', errors='replace') as f:
                            content_p = f.read()
                        all_project_files[rel_p] = content_p
                        total_extra += len(content_p)
                    except Exception:
                        pass

        # ═══════════════════════════════════════════════════════════
        # MULTI-PASS REVIEW PIPELINE
        # Pass 1: Deterministic checks (no LLM)
        # Pass 2: API Compatibility (LLM, focused)
        # Pass 3: Code Quality & Logic (LLM, focused)
        # Pass 4: Fix Remaining & Write Summary (LLM)
        # ═══════════════════════════════════════════════════════════

        os_name = platform.system()
        tool_service = ToolService(agent_root, current_step_id=step_id, workspace_path=workspace_path)
        llm = get_llm_engine()
        all_edits = []  # Combined edits from all passes

        # Build step context (shared across passes)
        step_context = ""
        if step_for_chat:
            step_name = step_for_chat.get('name', '')
            step_desc = step_for_chat.get('description', '')
            step_context = f"## Step Context\n**Step:** {step_name}\n"
            if step_desc:
                step_context += f"**Description:** {step_desc}\n"
                # Extract structured metadata from step description for review checklist
                _files_match = re.search(r'Files?:\s*(.+)', step_desc)
                _modifies_match = re.search(r'Modifies?:\s*(.+)', step_desc)
                _depends_match = re.search(r'Depends?\s*on:\s*(.+)', step_desc)
                if _files_match:
                    step_context += f"**Expected Files:** {_files_match.group(1).strip()}\n"
                if _modifies_match:
                    step_context += f"**Must Modify:** {_modifies_match.group(1).strip()}\n"
                if _depends_match:
                    step_context += f"**Depends On:** {_depends_match.group(1).strip()}\n"
                step_context += (
                    "\n**Review Checklist:**\n"
                    "- Verify ALL files listed in Expected Files were created\n"
                    "- Verify ALL files in Must Modify were actually edited\n"
                    "- Verify imports from Depends On steps resolve correctly\n"
                )
            step_context += "\n"

        # Load requirements + spec artifacts so the review can validate
        # code against acceptance criteria and architecture decisions.
        artifacts_dir_review = os.path.join(workspace_path, '.sentinel', 'tasks', task.get('id', task_id))
        spec_context = ""
        for artifact_name_r in ('requirements.md', 'spec.md', 'implementation-plan.md'):
            artifact_path_r = os.path.join(artifacts_dir_review, artifact_name_r)
            if os.path.isfile(artifact_path_r):
                try:
                    with open(artifact_path_r, 'r', encoding='utf-8') as f:
                        artifact_content_r = f.read()
                    if artifact_content_r.strip():
                        # Tighter limit for implementation-plan.md (can be large)
                        max_chars_r = 2000 if artifact_name_r == 'implementation-plan.md' else 3000
                        if len(artifact_content_r) > max_chars_r:
                            artifact_content_r = artifact_content_r[:max_chars_r] + "\n...(truncated)"
                        spec_context += f"## {artifact_name_r} (project specification)\n{artifact_content_r}\n\n"
                except Exception:
                    pass

        # Helper: build files_context from current file_contents + project files
        def _build_files_context():
            ctx = "## Files to Review (written in this step)\n\n"
            for fp, cnt in file_contents.items():
                ext = os.path.splitext(fp)[1].lstrip('.')
                ctx += f"### `{fp}`\n```{ext}\n{cnt}\n```\n\n"
            if all_project_files:
                ctx += "## Other Project Files (for reference — you can EditFile these too)\n\n"
                for fp, cnt in all_project_files.items():
                    ext = os.path.splitext(fp)[1].lstrip('.')
                    ctx += f"### `{fp}`\n```{ext}\n{cnt}\n```\n\n"
            return ctx

        # Helper: re-read files from disk (after edits by a previous pass)
        def _refresh_file_contents():
            for fp in list(file_contents.keys()):
                abs_p = os.path.join(agent_root, fp)
                if os.path.isfile(abs_p):
                    try:
                        with open(abs_p, 'r', encoding='utf-8', errors='replace') as f:
                            file_contents[fp] = f.read()
                    except Exception:
                        pass
            for fp in list(all_project_files.keys()):
                abs_p = os.path.join(workspace_path, fp)
                if os.path.isfile(abs_p):
                    try:
                        with open(abs_p, 'r', encoding='utf-8', errors='replace') as f:
                            all_project_files[fp] = f.read()
                    except Exception:
                        pass

        # Helper: strip tool blocks from LLM output
        def _clean_response(text):
            text = re.sub(r'<tool_code>.*?</tool_code>', '', text, flags=re.DOTALL)
            text = re.sub(r'<\|channel\|>[\s\S]*?(?=<\|channel\|>|\Z)', '', text, flags=re.DOTALL).strip()
            text = re.sub(
                r'\{["\s]*"name":\s*"(?:EditFile|WriteFile)"[^}]*"arguments"\s*:\s*\{[^}]*\}\s*\}',
                '', text, flags=re.DOTALL
            ).strip()
            text = re.sub(r'(?m)^#+\s*(?:Here are the edits|Edits?):?\s*$', '', text).strip()
            text = re.sub(r'\n{3,}', '\n\n', text)
            return text

        SDD_STEPS_CHECK = {'requirements', 'technical-specification', 'planning'}
        is_impl_step = step_id and step_id not in SDD_STEPS_CHECK

        # ── PASS 1: Deterministic checks (no LLM) ──────────────────
        yield f"event: review_pass\ndata: {json.dumps({'pass': 'deterministic', 'status': 'starting'})}\n\n"
        yield f"event: review_status\ndata: {json.dumps({'status': 'Pass 1: Analyzing code...'})}\n\n"

        code_issues = []
        code_warnings = []
        import_graph = {}
        integrity_py_files = {}
        code_check_context = ""

        if is_impl_step:
            try:
                integrity_result = AgentService._validate_project_integrity(workspace_path)
                code_issues = integrity_result.get('issues', [])
                code_warnings = integrity_result.get('warnings', [])
                import_graph = integrity_result.get('import_graph', {})
                integrity_py_files = integrity_result.get('py_files', {})

                yield f"event: review_code_check\ndata: {json.dumps({'issues': code_issues, 'fileCount': len(file_contents)})}\n\n"

                if code_issues:
                    _safe_log(f"[Review] Pass 1: {len(code_issues)} issue(s) found")
                    issue_lines = '\n'.join(f"- {issue}" for issue in code_issues)
                    code_check_context = (
                        "## Code Quality Analysis (automated — fix these issues)\n"
                        f"{issue_lines}\n\n"
                        "**You MUST address every issue above.** Use EditFile to fix code issues. "
                        "Use WriteFile to create/update requirements.txt if dependencies are missing.\n\n"
                    )
                else:
                    _safe_log("[Review] Pass 1: no issues found")

                if code_warnings:
                    _safe_log(f"[Review] Pass 1: {len(code_warnings)} warning(s)")
            except Exception as e:
                _safe_log(f"[Review] Pass 1 error: {e}")

            # Persist review issues for execution agent handoff
            if code_issues:
                try:
                    issues_dir = os.path.join(workspace_path, '.sentinel', 'tasks', task_id)
                    os.makedirs(issues_dir, exist_ok=True)
                    issues_path = os.path.join(issues_dir, 'review-issues.json')
                    with open(issues_path, 'w', encoding='utf-8') as f:
                        json.dump({'issues': code_issues, 'warnings': code_warnings}, f)
                except Exception:
                    pass

            # ── Read execution log for runtime context ──
            # The execution agent writes execution.log with warnings, fixes,
            # and final output. Feed this into the review so the LLM can
            # reason about runtime issues (dep failures, crashes, etc.)
            exec_context = ""
            try:
                exec_log_path = os.path.join(
                    workspace_path, '.sentinel', 'tasks', task_id, 'execution.log'
                )
                if os.path.isfile(exec_log_path):
                    with open(exec_log_path, 'r', encoding='utf-8') as f:
                        exec_log_data = json.load(f)
                    _exec_parts = []
                    if not exec_log_data.get('success'):
                        _exec_parts.append(f"- Execution FAILED after {exec_log_data.get('attempts', '?')} attempt(s)")
                    else:
                        _exec_parts.append(f"- Execution succeeded after {exec_log_data.get('attempts', '?')} attempt(s)")
                    for w in exec_log_data.get('warnings', []):
                        _exec_parts.append(f"- RUNTIME WARNING: {w}")
                    for fix in exec_log_data.get('fixes', [])[:10]:
                        _p = fix.get('path', '')
                        _t = fix.get('tool', '')
                        if _p:
                            _exec_parts.append(f"- Auto-fix applied: {_t} → {_p}")
                    _final = exec_log_data.get('final_output', '')
                    if _final and not exec_log_data.get('success'):
                        # Include last error output (truncated) for failed runs
                        _exec_parts.append(f"- Last output: {_final[:500]}")
                    if _exec_parts:
                        exec_context = (
                            "## Execution Agent Results (runtime testing)\n"
                            + '\n'.join(_exec_parts) + '\n\n'
                            "If there are runtime warnings or failures above, check that the code "
                            "handles these cases. Fix dependency issues in requirements.txt. "
                            "Fix runtime errors in the source code.\n\n"
                        )
                        code_warnings.extend(
                            w for w in exec_log_data.get('warnings', [])
                            if w not in code_warnings
                        )
                        _safe_log(f"[Review] Loaded execution log: {len(_exec_parts)} items, success={exec_log_data.get('success')}")
            except Exception as e:
                _safe_log(f"[Review] Error reading execution log: {e}")

            # Append execution context to code_check_context so all passes see it
            if exec_context:
                code_check_context += exec_context

        yield f"event: review_pass\ndata: {json.dumps({'pass': 'deterministic', 'status': 'done', 'issues': code_issues})}\n\n"

        if cancel_event and cancel_event.is_set():
            yield f"event: review_done\ndata: {json.dumps({'content': 'Review cancelled.', 'edits': [], 'editDetails': []})}\n\n"
            return

        # Build import context using the graph (replaces 4000-char signatures)
        import_context = ""
        if is_impl_step and import_graph and integrity_py_files:
            import_context = AgentService._build_full_import_context(
                workspace_path, set(file_contents.keys()), import_graph, integrity_py_files
            )

        # ── PASS 2: API Compatibility (LLM, focused) ───────────────
        time.sleep(0.5)  # Cooldown between passes to avoid GPU overload
        yield f"event: review_pass\ndata: {json.dumps({'pass': 'api_check', 'status': 'starting'})}\n\n"
        yield f"event: review_status\ndata: {json.dumps({'status': 'Pass 2: Checking API compatibility...'})}\n\n"

        pass2_results = {'text': '', 'edits': []}
        if is_impl_step:
            files_context = _build_files_context()
            api_system = build_api_check_prompt(os_name=os_name)
            api_user = (
                f"{step_context}"
                f"{spec_context}"
                f"{code_check_context}"
                f"{files_context}"
                f"{import_context}"
                "\n## Task\nCheck API compatibility across all files. Fix any mismatches with EditFile.\n"
            )
            api_history = [
                {"role": "system", "content": api_system},
                {"role": "user", "content": api_user},
            ]
            for event in AgentService._run_review_pass(
                llm, api_history, tool_service, cancel_event, pass2_results, max_turns=3
            ):
                yield event
            all_edits.extend(pass2_results.get('edits', []))

        pass2_edit_paths = [e['path'] for e in pass2_results.get('edits', [])]
        yield f"event: review_pass\ndata: {json.dumps({'pass': 'api_check', 'status': 'done', 'edits': pass2_edit_paths})}\n\n"

        if cancel_event and cancel_event.is_set():
            # Emit partial results
            review_content = _clean_response(pass2_results.get('text', ''))
            yield f"event: review_done\ndata: {json.dumps({'content': review_content, 'edits': pass2_edit_paths, 'editDetails': []})}\n\n"
            return

        # ── PASS 3: Code Quality & Logic (LLM, focused) ────────────
        time.sleep(0.5)  # Cooldown between passes
        yield f"event: review_pass\ndata: {json.dumps({'pass': 'quality', 'status': 'starting'})}\n\n"
        yield f"event: review_status\ndata: {json.dumps({'status': 'Pass 3: Reviewing code quality...'})}\n\n"

        pass3_results = {'text': '', 'edits': []}
        if is_impl_step:
            # Re-read files if Pass 2 made edits
            if pass2_results.get('edits'):
                _refresh_file_contents()

            files_context = _build_files_context()

            # Build prior issues summary so Pass 3 doesn't repeat
            prior_context = ""
            if code_issues or pass2_results.get('text'):
                prior_context = "## Issues already found by previous passes (DO NOT repeat these):\n"
                if code_issues:
                    prior_context += '\n'.join(f"- {i}" for i in code_issues) + '\n'
                if pass2_results.get('text'):
                    cleaned_p2 = _clean_response(pass2_results['text'])
                    if cleaned_p2:
                        prior_context += f"\n### Pass 2 findings:\n{cleaned_p2[:1500]}\n"
                prior_context += "\n"
            if code_warnings:
                prior_context += "## Warnings (non-critical):\n"
                prior_context += '\n'.join(f"- {w}" for w in code_warnings) + '\n\n'

            quality_system = build_quality_check_prompt(os_name=os_name)
            quality_user = (
                f"{step_context}"
                f"{spec_context}"
                f"{prior_context}"
                f"{files_context}"
                "\n## Task\nCheck code quality and logic ONLY. Do not repeat import/API checks. "
                "Verify the code implements the requirements from requirements.md above.\n"
            )
            quality_history = [
                {"role": "system", "content": quality_system},
                {"role": "user", "content": quality_user},
            ]
            for event in AgentService._run_review_pass(
                llm, quality_history, tool_service, cancel_event, pass3_results, max_turns=3
            ):
                yield event
            all_edits.extend(pass3_results.get('edits', []))

        pass3_edit_paths = [e['path'] for e in pass3_results.get('edits', [])]
        yield f"event: review_pass\ndata: {json.dumps({'pass': 'quality', 'status': 'done', 'edits': pass3_edit_paths})}\n\n"

        if cancel_event and cancel_event.is_set():
            combined_paths = pass2_edit_paths + pass3_edit_paths
            review_content = _clean_response(pass3_results.get('text', '') or pass2_results.get('text', ''))
            yield f"event: review_done\ndata: {json.dumps({'content': review_content, 'edits': combined_paths, 'editDetails': []})}\n\n"
            return

        # ── PASS 4: Fix Remaining & Write Summary (LLM) ────────────
        time.sleep(0.5)  # Cooldown between passes
        yield f"event: review_pass\ndata: {json.dumps({'pass': 'fix_summary', 'status': 'starting'})}\n\n"
        yield f"event: review_status\ndata: {json.dumps({'status': 'Pass 4: Writing review summary...'})}\n\n"

        # Re-read files after Pass 2+3 edits
        if pass2_results.get('edits') or pass3_results.get('edits'):
            _refresh_file_contents()

        files_context = _build_files_context()

        # Compile all issues for the summary pass
        all_issues_text = "## All Issues Found By Previous Passes\n\n"
        if code_issues:
            all_issues_text += "### Pass 1 — Deterministic Analysis\n"
            all_issues_text += '\n'.join(f"- {i}" for i in code_issues) + '\n\n'
        if code_warnings:
            all_issues_text += "### Warnings\n"
            all_issues_text += '\n'.join(f"- {w}" for w in code_warnings) + '\n\n'

        # Summarize edits made by previous passes
        prev_edits_summary = ""
        if all_edits:
            prev_edits_summary = "### Edits already made by previous passes\n"
            seen_paths = set()
            for e in all_edits:
                p = e.get('path', '')
                if p and p not in seen_paths:
                    seen_paths.add(p)
                    prev_edits_summary += f"- Edited `{p}`\n"
            prev_edits_summary += "\n"

        pass2_clean = _clean_response(pass2_results.get('text', ''))
        pass3_clean = _clean_response(pass3_results.get('text', ''))
        if pass2_clean:
            all_issues_text += f"### Pass 2 — API Compatibility\n{pass2_clean[:1500]}\n\n"
        if pass3_clean:
            all_issues_text += f"### Pass 3 — Code Quality\n{pass3_clean[:1500]}\n\n"

        fix_system = build_fix_summary_prompt(os_name=os_name)
        fix_user = (
            f"{step_context}"
            f"{spec_context}"
            f"{all_issues_text}"
            f"{prev_edits_summary}"
            f"{files_context}"
            "\n## Task\nFix any remaining unfixed issues. Verify code satisfies requirements.md. Then write the final review summary.\n"
        )
        fix_history = [
            {"role": "system", "content": fix_system},
            {"role": "user", "content": fix_user},
        ]

        pass4_results = {'text': '', 'edits': []}
        for event in AgentService._run_review_pass(
            llm, fix_history, tool_service, cancel_event, pass4_results, max_turns=3
        ):
            yield event
        all_edits.extend(pass4_results.get('edits', []))

        pass4_edit_paths = [e['path'] for e in pass4_results.get('edits', [])]
        yield f"event: review_pass\ndata: {json.dumps({'pass': 'fix_summary', 'status': 'done', 'edits': pass4_edit_paths})}\n\n"

        # ── CLEANUP: combine results, persist, emit review_done ─────
        review_content = _clean_response(pass4_results.get('text', ''))

        # If Pass 4 produced no text (error, etc.), fall back to combined P2+P3
        if not review_content.strip():
            parts = []
            if pass2_clean:
                parts.append(f"## API Compatibility\n{pass2_clean}")
            if pass3_clean:
                parts.append(f"## Code Quality\n{pass3_clean}")
            review_content = '\n\n'.join(parts) if parts else 'Review completed with no output.'

        # Build edit summary with per-file line deltas
        edit_details = {}
        for e in all_edits:
            p = e.get('path', '')
            if not p:
                continue
            old_lines = e.get('old_string', '').count('\n') + (1 if e.get('old_string') else 0)
            new_lines = e.get('new_string', '').count('\n') + (1 if e.get('new_string') else 0)
            if p not in edit_details:
                edit_details[p] = {'added': 0, 'removed': 0}
            edit_details[p]['added'] += max(0, new_lines - old_lines)
            edit_details[p]['removed'] += max(0, old_lines - new_lines)
        edit_paths = list(edit_details.keys())
        edits_with_deltas = [{'path': p, 'added': d['added'], 'removed': d['removed']} for p, d in edit_details.items()]

        # Append "Final Code" section if any edits were made
        if all_edits:
            final_code_section = "\n\n---\n\n## Final Code\n\n"
            changed_lines_per_file = {}
            for e in all_edits:
                p = e.get('path', '')
                new_str = e.get('new_string', '')
                if p not in changed_lines_per_file:
                    changed_lines_per_file[p] = set()
                for line in new_str.splitlines():
                    stripped = line.strip()
                    if stripped:
                        changed_lines_per_file[p].add(stripped)

            edited_files_shown = set()
            for e in all_edits:
                p = e.get('path', '')
                if not p or p in edited_files_shown:
                    continue
                edited_files_shown.add(p)
                abs_path = os.path.join(agent_root, p)
                if os.path.isfile(abs_path):
                    try:
                        with open(abs_path, 'r', encoding='utf-8') as f:
                            final_content = f.read()
                        ext = os.path.splitext(p)[1].lstrip('.')
                        changed_set = changed_lines_per_file.get(p, set())
                        if changed_set:
                            annotated_lines = []
                            for line in final_content.splitlines():
                                if line.strip() and line.strip() in changed_set:
                                    annotated_lines.append(f"{line}  # Changed")
                                else:
                                    annotated_lines.append(line)
                            final_content = '\n'.join(annotated_lines)
                        final_code_section += f"### `{p}`\n```{ext}\n{final_content}\n```\n\n"
                    except Exception:
                        pass
            review_content += final_code_section

        # Persist review result
        try:
            chat_data = AgentService.get_chat(task_id, chat_id)
            if chat_data:
                chat_data['review'] = {
                    'content': review_content,
                    'edits': edit_paths,
                    'editDetails': edits_with_deltas,
                }
                AgentService.save_chat(task_id, chat_id, chat_data)
        except Exception as e:
            _safe_log(f"[Review] Failed to persist review: {e}")

        # Persist review summary for downstream agent consumption (main agent, execution agent)
        try:
            _review_summary = {
                'step_id': step_id,
                'issues_found': len(code_issues),
                'warnings_found': len(code_warnings),
                'edits_made': len(all_edits),
                'edited_files': edit_paths,
                'issues': code_issues[:15],
                'warnings': code_warnings[:10],
                'summary': review_content[:2000],
            }
            _summary_dir = os.path.join(workspace_path, '.sentinel', 'tasks', task_id)
            os.makedirs(_summary_dir, exist_ok=True)
            with open(os.path.join(_summary_dir, 'review-summary.json'), 'w', encoding='utf-8') as _rsf:
                json.dump(_review_summary, _rsf, indent=2)
            _safe_log(f"[Review] Persisted review summary: {len(code_issues)} issues, {len(all_edits)} edits")
        except Exception as e:
            _safe_log(f"[Review] Failed to persist review summary: {e}")

        yield f"event: review_done\ndata: {json.dumps({'content': review_content, 'edits': edit_paths, 'editDetails': edits_with_deltas})}\n\n"

    @staticmethod
    def _load_prior_step_context(workspace_path, task_id, current_step_id, all_steps):
        """Load artifact files from completed prior steps."""
        context_parts = []
        artifacts_dir = os.path.join(workspace_path, '.sentinel', 'tasks', task_id)

        artifact_files = {
            'requirements': 'requirements.md',
            'technical-specification': 'spec.md',
            'planning': 'implementation-plan.md',
            'implementation': 'implementation-plan.md',
        }

        # For child step IDs (e.g., "parent::child"), break at the parent position.
        # Child IDs never match root step IDs, so without this the break never fires
        # and ALL root steps' artifacts get included (even steps after the current parent).
        target_id = current_step_id.split('::')[0] if '::' in current_step_id else current_step_id

        for step in all_steps:
            if step['id'] == target_id:
                break  # Only include steps BEFORE the current one (or its parent)
            if step['status'] != 'completed':
                continue

            filename = artifact_files.get(step['id'], f"{step['id']}.md")
            if filename:
                path = os.path.join(artifacts_dir, filename)
                if os.path.exists(path):
                    try:
                        with open(path, 'r', encoding='utf-8') as f:
                            content = f.read()
                        if content.strip():
                            if len(content) > 4000:
                                content = content[:4000] + "\n...(truncated)"
                            context_parts.append(f"### {step['name']} output:\n{content}")
                    except Exception:
                        pass

        return "\n\n---\n\n".join(context_parts)

    @staticmethod
    def _load_prior_step_context_from_chats(task_id, current_step_id, all_steps):
        """Fallback: extract context from prior step chat history when artifact files don't exist."""
        context_parts = []
        for step in all_steps:
            if step['id'] == current_step_id:
                break
            if step['status'] != 'completed' or not step.get('chatId'):
                continue
            chat = AgentService.get_chat(task_id, step['chatId'])
            if not chat or not chat.get('messages'):
                continue
            # Find last substantial assistant message
            for msg in reversed(chat['messages']):
                if msg['role'] == 'assistant' and len(msg.get('content', '')) > 100:
                    content = re.sub(r'<tool_code>.*?</tool_code>', '', msg['content'], flags=re.DOTALL).strip()
                    content = content.replace('[STEP_COMPLETE]', '').strip()
                    if len(content) > 50:
                        if len(content) > 3000:
                            content = content[:3000] + "\n...(truncated)"
                        context_parts.append(f"### {step['name']} output:\n{content}")
                        break
        return "\n\n---\n\n".join(context_parts)

    @staticmethod
    def _get_expected_artifact(step_id, artifacts_path):
        """Return the expected artifact filename for a step, or None if no artifact is needed.

        SDD steps (requirements, technical-specification, planning) produce markdown
        artifacts that must exist before the step can be marked complete.
        The parent 'implementation' step reuses the plan artifact.
        Implementation *child* steps (e.g. 'script-core', 'enhanced-features') produce
        code files, NOT markdown artifacts — so we return None for them.  The step
        completion logic already checks written_files for those steps via the
        zero-files nudge.
        """
        artifact_map = {
            'requirements': 'requirements.md',
            'technical-specification': 'spec.md',
            'planning': 'implementation-plan.md',
            'implementation': 'implementation-plan.md',  # Implementation reuses the plan (updates checkboxes)
        }
        filename = artifact_map.get(step_id)
        if filename:
            return os.path.join(artifacts_path, filename)
        # Implementation child steps write code files, not .md artifacts.
        # Return None so the completion logic skips artifact validation
        # and relies on the written_files check instead.
        return None

    @staticmethod
    def _extract_owned_files(step_description: str) -> list:
        """Extract expected file paths from a step description's Files: line.

        Returns a list of filenames (e.g. ['main.py', 'utils.py']).
        Used by the hardcoded completion logic to detect when all expected
        files have been written.
        """
        FILE_EXTS = (
            "py", "md", "txt", "json", "yaml", "yml", "toml", "ini", "cfg",
            "html", "css", "js", "ts", "tsx", "csv", "xlsx"
        )
        files_lines = re.findall(
            r"(?im)^\s*Files?\s*:\s*(.+?)\s*$",
            step_description
        )
        owned = []
        for line in files_lines:
            parts = re.split(r"\s*,\s*|\s+\band\b\s+", line.strip())
            for p in parts:
                p = p.strip().strip("`").strip()
                if p and re.search(rf"(?i)\.({'|'.join(FILE_EXTS)})\b", p):
                    owned.append(p)
        return owned

    @staticmethod
    def _extract_modifies_files(step_description: str) -> list:
        """Extract file paths from a step description's Modifies: line.

        Returns list of bare filenames (e.g. ['app.py', 'config.py']).
        Strips parenthetical notes like "(register_blueprint)".
        Used by the step completion wiring checks to verify the agent
        actually edited the files it was supposed to modify.
        """
        FILE_EXTS = (
            "py", "md", "txt", "json", "yaml", "yml", "toml", "ini", "cfg",
            "html", "css", "js", "ts", "tsx", "csv", "xlsx"
        )
        mod_lines = re.findall(
            r"(?im)^\s*Modifies?\s*:\s*(.+?)\s*$",
            step_description
        )
        modifies = []
        for line in mod_lines:
            parts = re.split(r"\s*,\s*|\s+\band\b\s+", line.strip())
            for p in parts:
                p = p.strip().strip("`").strip()
                # Strip parenthetical notes like "(register_blueprint)"
                p = re.sub(r"\s*\(.*?\)\s*$", "", p).strip()
                if p and re.search(rf"(?i)\.({'|'.join(FILE_EXTS)})\b", p):
                    modifies.append(p)
        return modifies

    @staticmethod
    def _get_step_read_instructions(step_id, artifacts_path, step_name='', step_description='', parent_name='', parent_description='', task_details='', existing_files=None, complexity=5, **kwargs):
        """Return step-specific read instructions to guide the agent on what to read first.

        Prompt content lives in prompts/*.py — this method delegates to them.
        """
        _fp = kwargs.get('_fingerprint')
        _cm = kwargs.get('_compact_mode', False)
        prompt_kwargs = dict(
            artifacts_path=artifacts_path,
            step_id=step_id,
            step_name=step_name,
            step_description=step_description,
            parent_name=parent_name,
            parent_description=parent_description,
            task_details=task_details,
            complexity=complexity,
        )

        # Look up relevant pitfalls from error memory
        pitfalls = ErrorMemory.lookup(
            step_type=step_id or 'implementation',
            task_details=task_details,
            max_entries=3,
            fingerprint=_fp,
        )
        prompt_kwargs['known_pitfalls'] = ErrorMemory.format_for_prompt(
            pitfalls, compact_mode=_cm,
        ) if pitfalls else ''

        if step_id == 'requirements':
            # Micro-task orchestration handles phase-specific prompts via user messages.
            # Return minimal instructions for the system prompt.
            return (
                "You are in the REQUIREMENTS step. Follow the instructions in each message carefully. "
                "When asked for JSON, output ONLY valid JSON with no commentary. "
                "When asked to write a file, use WriteFile immediately."
            )
        elif step_id == 'technical-specification':
            return build_technical_specification_prompt(**prompt_kwargs)
        elif step_id == 'planning':
            return build_planning_prompt(**prompt_kwargs)
        else:
            prompt_kwargs['existing_files'] = existing_files or []
            # Cross-step integrity injection: if the previous step left issues,
            # prepend a warning into the implementation prompt so the model
            # knows to avoid/fix those problems.
            _prior_integrity_warning = ''
            try:
                _integrity_path = os.path.join(artifacts_path, 'last_integrity.json')
                if os.path.isfile(_integrity_path):
                    with open(_integrity_path, 'r', encoding='utf-8') as _if:
                        _integrity_data = json.load(_if)
                    _prior_issues = _integrity_data.get('issues', [])
                    if _prior_issues:
                        _prior_integrity_warning = (
                            "WARNING: The previous step left these issues unresolved:\n" +
                            '\n'.join(f"  - {i}" for i in _prior_issues[:5]) +
                            "\nYou MUST avoid repeating these mistakes. "
                            "If any of these issues affect files you are working on, FIX them.\n\n"
                        )
            except Exception:
                pass
            prompt_kwargs['prior_integrity_warning'] = _prior_integrity_warning
            return build_implementation_prompt(**prompt_kwargs)

    @staticmethod
    def _find_step_by_chat_id(steps, chat_id):
        """Search root steps and their children for a step matching the given chatId."""
        for s in steps:
            if s.get('chatId') == chat_id:
                return s
            for child in s.get('children', []):
                if child.get('chatId') == chat_id:
                    return child
        return None

    @staticmethod
    def _find_step_by_name(steps, name):
        """Search root steps and their children for a step matching the given name (case-insensitive)."""
        target = name.strip().lower()
        for s in steps:
            if s.get('name', '').strip().lower() == target:
                return s
            for child in s.get('children', []):
                if child.get('name', '').strip().lower() == target:
                    return child
        return None

    @staticmethod
    def _parse_write_meta(result_str):
        """Extract diff metadata from WriteFile result string.

        Result format: "Successfully wrote to path [meta:is_new=True,added=10,removed=0]"
        Returns dict with is_new, added, removed keys.
        """
        meta = {'is_new': False, 'added': 0, 'removed': 0}
        meta_match = re.search(r'\[meta:is_new=(True|False),added=(\d+),removed=(\d+)\]', result_str)
        if meta_match:
            meta['is_new'] = meta_match.group(1) == 'True'
            meta['added'] = int(meta_match.group(2))
            meta['removed'] = int(meta_match.group(3))
        return meta

    @staticmethod
    def _extract_markdown_from_narration(response: str) -> str:
        """Extract markdown content from a model response that narrated instead of using WriteFile.

        The small model sometimes writes the full markdown document in the chat
        (either in a fenced code block or inline) instead of calling WriteFile.
        This method recovers that content so it can be auto-saved.

        Returns the extracted markdown content, or '' if nothing useful found.
        """
        # Strategy 1: fenced markdown code block (```markdown ... ```)
        fenced = re.findall(r'```(?:markdown|md)\s*\n(.*?)```', response, re.DOTALL)
        if fenced:
            # Take the longest fenced block
            best = max(fenced, key=len)
            if len(best.strip()) > 200:
                return best.strip()

        # Strategy 2: any fenced code block that looks like markdown (has # headings)
        any_fenced = re.findall(r'```\s*\n(.*?)```', response, re.DOTALL)
        for block in sorted(any_fenced, key=len, reverse=True):
            if re.search(r'^#{1,3}\s+', block, re.MULTILINE) and len(block.strip()) > 200:
                return block.strip()

        # Strategy 3: inline markdown — find the first heading and take everything from there
        # Stop at [STEP_COMPLETE] or end of response
        heading_match = re.search(r'^(#{1,2}\s+\S.+)$', response, re.MULTILINE)
        if heading_match:
            start = heading_match.start()
            # Find end boundary
            end_match = re.search(r'\[STEP.?COMPLETE\]', response[start:], re.IGNORECASE)
            if end_match:
                content = response[start:start + end_match.start()].strip()
            else:
                content = response[start:].strip()
            # Validate it looks like a real document (multiple headings, substantial content)
            heading_count = len(re.findall(r'^#{1,3}\s+', content, re.MULTILINE))
            if heading_count >= 2 and len(content) > 200:
                return content

        return ''

    @staticmethod
    def _validate_artifact_content(content: str, artifact_name: str) -> tuple:
        """Validate artifact content is real, not placeholder garbage.

        Returns (is_valid: bool, reason: str).
        """
        if len(content) < 200:
            return False, f"Too short ({len(content)} chars, need 200+)"

        # Count "..." placeholder sections
        ellipsis_count = content.count('...')
        # Count actual content lines (non-empty, non-heading, non-ellipsis)
        content_lines = [l for l in content.split('\n')
                         if l.strip() and not l.strip().startswith('#')
                         and l.strip() != '...']

        if ellipsis_count > 2 and len(content_lines) < ellipsis_count * 3:
            return False, f"Too many placeholders ({ellipsis_count} '...' vs {len(content_lines)} content lines)"

        # Check for narration-only content (no real deliverable)
        narration_markers = [
            'i will now', "i'll now", 'let me create', 'let me now',
            'i need to', 'i should', "now i'm creating", "i'm going to",
            "first, i'll", "next, i'll", 'to create', 'i will create',
        ]
        narration_hits = sum(1 for m in narration_markers if m in content.lower())
        if narration_hits >= 3:
            return False, f"Content is narration about work, not actual deliverable ({narration_hits} narration phrases)"

        # For markdown artifacts: check sections have real content (not just headings + ...)
        if artifact_name.endswith('.md'):
            sections = re.split(r'^#{1,3}\s+', content, flags=re.MULTILINE)
            empty_sections = sum(1 for s in sections[1:] if s.strip() in ('', '...', '...\n'))
            total_sections = len(sections) - 1  # exclude pre-heading content
            if total_sections > 0 and empty_sections / total_sections > 0.5:
                return False, f"{empty_sections}/{total_sections} sections are empty/placeholder"

        # Coherence check: ensure content has meaningful structure, not rambling
        # Split into words and check for excessive repetition
        words = re.findall(r'[a-zA-Z]{3,}', content.lower())
        if len(words) > 30:
            from collections import Counter
            word_counts = Counter(words)
            # If top 3 non-common words make up >30% of all words, it's repetitive
            common = {'the', 'and', 'for', 'that', 'this', 'with', 'from', 'are', 'not',
                       'but', 'was', 'have', 'has', 'had', 'will', 'can', 'would', 'could',
                       'should', 'may', 'might', 'shall', 'its', 'our', 'their', 'your',
                       'all', 'each', 'which', 'when', 'where', 'what', 'how', 'who', 'they'}
            meaningful = [(w, c) for w, c in word_counts.most_common(20) if w not in common]
            if meaningful:
                top3_count = sum(c for _, c in meaningful[:3])
                if top3_count > len(words) * 0.3:
                    return False, f"Content appears repetitive (top words account for {top3_count}/{len(words)} tokens)"

        # For implementation-plan.md specifically: ensure there are actionable task headings
        if artifact_name == 'implementation-plan.md':
            heading_count = len(re.findall(r'^#{2,3}\s+', content, re.MULTILINE))
            if heading_count < 2:
                return False, f"Implementation plan needs at least 2 task headings (found {heading_count})"
            # Check that headings have reasonable names (not garbage)
            headings = re.findall(r'^#{2,3}\s+(.+)$', content, re.MULTILINE)
            garbage_headings = 0
            for h in headings:
                h_clean = h.strip()
                # Garbage: very short, all caps with no spaces, or has no alphabetic chars
                alpha = len(re.findall(r'[a-zA-Z]', h_clean))
                if len(h_clean) < 3 or alpha < len(h_clean) * 0.5:
                    garbage_headings += 1
            if garbage_headings > len(headings) * 0.5:
                return False, f"Too many nonsensical headings ({garbage_headings}/{len(headings)})"

        return True, "OK"

    @staticmethod
    def _validate_project_integrity(workspace_path):
        """Project integrity check for Python workspaces (multi-pass review Pass 1).

        Checks:
        1. All .py files parse without syntax errors
        2. Local imports resolve to existing files
        3. Imported names match actual definitions
        4. Third-party dependencies in requirements.txt + installed in .venv
        5. Truncation detection (placeholder functions, missing entry points)
        6. Hardcoded credentials / absolute paths

        Returns a dict:
          {
            'issues': [...],           # list of issue strings
            'import_graph': {...},     # rel_path -> [list of local files it imports]
            'warnings': [...],         # non-critical observations
            'defined_names': {...},    # module_name -> set of defined names
            'py_files': {...},         # rel_path -> source code
          }
        """
        import ast

        issues = []
        warnings = []
        py_files = {}  # rel_path -> source code
        defined_names = {}  # module_name -> set of defined names (functions, classes)
        import_graph = {}  # rel_path -> [list of local rel_paths it imports]

        SKIP_DIRS = {'.git', '__pycache__', 'node_modules', '.venv', 'venv', '.sentinel'}
        empty_result = {'issues': issues, 'import_graph': import_graph,
                        'warnings': warnings, 'defined_names': defined_names, 'py_files': py_files}

        # 1) Read all .py files
        try:
            for root, dirs, files in os.walk(workspace_path):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith('.')]
                for fname in files:
                    if not fname.endswith('.py'):
                        continue
                    abs_p = os.path.join(root, fname)
                    rel_p = os.path.relpath(abs_p, workspace_path).replace('\\', '/')
                    try:
                        with open(abs_p, 'r', encoding='utf-8', errors='replace') as f:
                            py_files[rel_p] = f.read()
                    except Exception:
                        pass
        except Exception:
            return empty_result

        if not py_files:
            return empty_result

        # 2) Parse each file — check syntax, collect definitions, detect truncation
        ENTRY_POINTS = {'main.py', 'app.py', 'cli.py', '__main__.py'}
        for rel_p, source in py_files.items():
            module_name = rel_p.replace('/', '.').replace('.py', '')
            if module_name.endswith('.__init__'):
                module_name = module_name[:-9]
            try:
                tree = ast.parse(source, filename=rel_p)
            except SyntaxError as e:
                issues.append(f"Syntax error in {rel_p} line {e.lineno}: {e.msg}")
                continue

            # Secondary check: py_compile via subprocess catches issues ast.parse misses
            # (e.g. encoding issues, certain escape problems, version-specific compilation errors)
            abs_file = os.path.join(workspace_path, rel_p.replace('/', os.sep))
            if os.path.isfile(abs_file):
                try:
                    venv_python = None
                    venv_dir = os.path.join(workspace_path, '.venv')
                    if os.path.isdir(venv_dir):
                        scripts = 'Scripts' if platform.system() == 'Windows' else 'bin'
                        candidate = os.path.join(venv_dir, scripts, 'python.exe' if platform.system() == 'Windows' else 'python')
                        if os.path.isfile(candidate):
                            venv_python = candidate
                    python_exe = venv_python or sys.executable
                    compile_result = subprocess.run(
                        [python_exe, '-c',
                         f'import py_compile; py_compile.compile(r"{abs_file}", doraise=True)'],
                        capture_output=True, text=True, timeout=10,
                        cwd=workspace_path
                    )
                    if compile_result.returncode != 0:
                        err_msg = compile_result.stderr.strip()
                        for line in err_msg.split('\n'):
                            if 'Error' in line or 'error' in line:
                                err_msg = line.strip()
                                break
                        if err_msg and f"Syntax error in {rel_p}" not in ' '.join(issues):
                            issues.append(f"Compilation error in {rel_p}: {err_msg}")
                except (subprocess.TimeoutExpired, Exception):
                    pass

            # Targeted check: backslash-newline inside f-strings (WriteFile escape artifact)
            fstring_backslash_re = re.compile(r'f["\'].*\\\s*\n', re.MULTILINE)
            if fstring_backslash_re.search(source):
                matches = fstring_backslash_re.findall(source)
                warnings.append(
                    f"Suspicious f-string in {rel_p}: {len(matches)} backslash continuation(s) "
                    f"inside f-string — may cause runtime issues"
                )

            # Collect top-level definitions
            names = set()
            has_name_main = False
            placeholder_funcs = []
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    names.add(node.name)
                    # Detect placeholder/truncated functions (body is just pass or Ellipsis)
                    if len(node.body) == 1:
                        body_node = node.body[0]
                        if isinstance(body_node, ast.Pass):
                            placeholder_funcs.append(node.name)
                        elif (isinstance(body_node, ast.Expr) and
                              isinstance(body_node.value, ast.Constant) and
                              body_node.value.value is ...):
                            placeholder_funcs.append(node.name)
                elif isinstance(node, ast.ClassDef):
                    names.add(node.name)
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            names.add(target.id)
                elif isinstance(node, ast.If):
                    # Check for if __name__ == '__main__'
                    try:
                        test = node.test
                        if (isinstance(test, ast.Compare) and
                            isinstance(test.left, ast.Name) and test.left.id == '__name__' and
                            len(test.comparators) == 1 and
                            isinstance(test.comparators[0], ast.Constant) and
                            test.comparators[0].value == '__main__'):
                            has_name_main = True
                    except Exception:
                        pass
            defined_names[module_name] = names

            # Truncation warnings
            fname_only = os.path.basename(rel_p)
            if fname_only in ENTRY_POINTS and not has_name_main and len(source.strip()) > 50:
                warnings.append(f"Entry point {rel_p} has no `if __name__ == '__main__'` block")
            if placeholder_funcs:
                func_list = ', '.join(placeholder_funcs[:3])
                if len(placeholder_funcs) > 3:
                    func_list += f' (+{len(placeholder_funcs) - 3} more)'
                warnings.append(f"Placeholder functions in {rel_p}: {func_list}")

        STDLIB = _PYTHON_STDLIB

        # Common pip-package-name → import-name mappings
        PIP_TO_IMPORT = {
            'pyyaml': 'yaml', 'pillow': 'pil', 'python-dotenv': 'dotenv',
            'beautifulsoup4': 'bs4', 'scikit-learn': 'sklearn',
            'opencv-python': 'cv2', 'opencv-python-headless': 'cv2',
            'python-dateutil': 'dateutil', 'pymysql': 'pymysql',
            'psycopg2-binary': 'psycopg2', 'python-magic': 'magic',
        }
        # Build reverse map: import_name → pip_name(s)
        IMPORT_TO_PIP = {}
        for pip_name, import_name in PIP_TO_IMPORT.items():
            IMPORT_TO_PIP.setdefault(import_name.lower(), []).append(pip_name)

        # Helper: resolve a module name to a local rel_path (or None)
        def _resolve_local(mod_name):
            """Return the rel_path of a local module, or None."""
            parts = mod_name.split('.')
            top = parts[0]
            # Check as top-level .py file
            if f"{top}.py" in py_files:
                return f"{top}.py"
            # Check as package __init__.py
            if f"{top}/__init__.py" in py_files:
                return f"{top}/__init__.py"
            return None

        # Read requirements.txt once
        req_path = os.path.join(workspace_path, 'requirements.txt')
        reqs_packages = set()  # normalized pip package names
        if os.path.isfile(req_path):
            try:
                with open(req_path, 'r') as rf:
                    reqs_text = rf.read()
                for line in reqs_text.splitlines():
                    line = line.strip()
                    if line and not line.startswith('#'):
                        pkg = re.split(r'[>=<!\[\];]', line)[0].strip().lower()
                        if pkg:
                            reqs_packages.add(pkg)
            except Exception:
                pass

        # Detect .venv site-packages path
        site_packages = None
        venv_path = os.path.join(workspace_path, '.venv')
        if os.path.isdir(venv_path):
            sp = os.path.join(venv_path, 'Lib', 'site-packages')
            if os.path.isdir(sp):
                site_packages = sp
            else:
                lib_dir = os.path.join(venv_path, 'lib')
                if os.path.isdir(lib_dir):
                    for d in os.listdir(lib_dir):
                        if d.startswith('python'):
                            sp = os.path.join(lib_dir, d, 'site-packages')
                            if os.path.isdir(sp):
                                site_packages = sp
                                break

        # Cache installed packages from site-packages
        installed_packages = set()
        if site_packages:
            try:
                for entry in os.listdir(site_packages):
                    installed_packages.add(entry.lower().split('.')[0].replace('-', '_'))
            except Exception:
                pass

        # Track which third-party packages we've already checked (avoid dupes)
        checked_third_party = set()

        # 3) Check imports resolve + build import graph
        for rel_p, source in py_files.items():
            try:
                tree = ast.parse(source, filename=rel_p)
            except SyntaxError:
                continue  # Already reported above

            local_imports = []  # collect local file edges for import_graph

            for node in ast.walk(tree):
                # Handle `import X`
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        top_pkg = alias.name.split('.')[0]
                        if top_pkg in defined_names or top_pkg in STDLIB:
                            # Record local import edge
                            local_path = _resolve_local(top_pkg)
                            if local_path and local_path != rel_p:
                                local_imports.append(local_path)
                            continue
                        if top_pkg not in checked_third_party:
                            checked_third_party.add(top_pkg)
                            AgentService._check_third_party_dep(
                                top_pkg, rel_p, reqs_packages, installed_packages,
                                IMPORT_TO_PIP, py_files, issues
                            )

                # Handle `from X import Y`
                elif isinstance(node, ast.ImportFrom) and node.module:
                    mod = node.module
                    top_pkg = mod.split('.')[0]

                    # Local module — check imported names exist
                    if mod in defined_names:
                        local_path = _resolve_local(mod)
                        if local_path and local_path != rel_p:
                            local_imports.append(local_path)
                        for alias in (node.names or []):
                            name = alias.name
                            if name != '*' and name not in defined_names[mod]:
                                issues.append(
                                    f"{rel_p}: imports '{name}' from '{mod}' "
                                    f"but '{mod}.py' does not define '{name}'"
                                )
                    elif top_pkg in defined_names:
                        # Sub-module of a local package — record edge
                        local_path = _resolve_local(top_pkg)
                        if local_path and local_path != rel_p:
                            local_imports.append(local_path)
                    elif top_pkg in STDLIB:
                        pass  # Standard library
                    else:
                        # Check if it's a local file we haven't mapped
                        possible = f"{top_pkg}.py"
                        if possible in py_files or f"{top_pkg}/__init__.py" in py_files:
                            local_path = _resolve_local(top_pkg)
                            if local_path and local_path != rel_p:
                                local_imports.append(local_path)
                            continue  # Local module

                        # Third-party package — check requirements.txt + installation
                        if top_pkg not in checked_third_party:
                            checked_third_party.add(top_pkg)
                            AgentService._check_third_party_dep(
                                top_pkg, rel_p, reqs_packages, installed_packages,
                                IMPORT_TO_PIP, py_files, issues
                            )

            # De-dup and store import graph edges
            if local_imports:
                import_graph[rel_p] = list(set(local_imports))

        # 4) Hardcoded credential / path scan
        CRED_PATTERNS = [
            (r'(?:password|secret|api_key|api_secret|token|auth_token)\s*=\s*["\'][^"\']{4,}["\']',
             'Possible hardcoded credential'),
            (r'[A-Za-z]:\\[^\s"\'\\]+(?:\\[^\s"\'\\]+)+',
             'Hardcoded Windows path'),
            (r'(?:/home/\w+/|/Users/\w+/|/root/)\S+',
             'Hardcoded Unix path'),
        ]
        for rel_p, source in py_files.items():
            for pattern, label in CRED_PATTERNS:
                matches = re.findall(pattern, source, re.IGNORECASE)
                for match in matches[:2]:  # Limit to 2 per pattern per file
                    snippet = match[:60] + ('...' if len(match) > 60 else '')
                    warnings.append(f"{label} in {rel_p}: `{snippet}`")

        # 5) Entry-point reachability — detect orphan modules
        ENTRY_NAMES = {'main.py', 'app.py', 'cli.py', 'server.py', 'run.py', 'manage.py', 'wsgi.py'}
        entry_files = [p for p in py_files if os.path.basename(p) in ENTRY_NAMES]
        if entry_files:
            reachable = set(entry_files)
            queue = list(entry_files)
            while queue:
                current = queue.pop(0)
                for target in import_graph.get(current, []):
                    if target not in reachable:
                        reachable.add(target)
                        queue.append(target)
            SKIP_ORPHAN = {'setup.py', 'conftest.py'}
            for rel_p in py_files:
                basename = os.path.basename(rel_p)
                if rel_p in reachable:
                    continue
                if basename.startswith('test_') or basename in SKIP_ORPHAN:
                    continue
                if basename == '__init__.py':
                    continue
                issues.append(
                    f"Orphan module: {rel_p} is never imported from any entry point "
                    f"({', '.join(entry_files)}). It will not run."
                )

        # 6) Flask blueprint registration check
        blueprints = {}  # file -> list of blueprint variable names
        for rel_p, source in py_files.items():
            bp_vars = re.findall(r'(\w+)\s*=\s*Blueprint\s*\(', source)
            if bp_vars:
                blueprints[rel_p] = bp_vars
        if blueprints:
            all_sources = '\n'.join(py_files.values())
            for rel_p, bp_vars in blueprints.items():
                for bp_var in bp_vars:
                    if not re.search(rf'register_blueprint\s*\(\s*{re.escape(bp_var)}\b', all_sources):
                        issues.append(
                            f"Unregistered Flask blueprint: '{bp_var}' defined in {rel_p} "
                            f"but no file calls register_blueprint({bp_var})"
                        )

        return {
            'issues': issues,
            'import_graph': import_graph,
            'warnings': warnings,
            'defined_names': defined_names,
            'py_files': py_files,
        }

    # Dev/test tool packages — used via CLI, not as runtime imports.
    # Skip "Uninstalled dependency" warnings for these since they'll be installed during execution.
    _DEV_TOOL_PACKAGES = {
        'pytest', 'black', 'flake8', 'mypy', 'pylint', 'isort', 'autopep8',
        'coverage', 'tox', 'nox', 'pre_commit', 'bandit', 'pyright',
        'ruff', 'yapf', 'pyflakes', 'pycodestyle', 'pydocstyle',
        'setuptools', 'wheel', 'pip', 'twine', 'build',
    }

    @staticmethod
    def _check_third_party_dep(top_pkg, rel_p, reqs_packages, installed_packages,
                                import_to_pip, py_files, issues):
        """Check if a third-party package is in requirements.txt and installed."""
        pkg_lower = top_pkg.lower()

        # False-positive guard: if top_pkg exists as a local file or package directory,
        # it's a local module — not a third-party dependency. This catches cases where
        # defined_names didn't map it (e.g. missing __init__.py, namespace packages).
        if (f"{top_pkg}.py" in py_files
                or f"{top_pkg}/__init__.py" in py_files
                or any(p.startswith(f"{top_pkg}/") for p in py_files)):
            return  # It's local, not third-party

        # Skip dev/test tool packages — they're CLI tools, installed during execution
        if pkg_lower in AgentService._DEV_TOOL_PACKAGES:
            return

        # Check if it's in requirements.txt (try direct name and known mappings)
        in_reqs = False
        if pkg_lower in reqs_packages or pkg_lower.replace('_', '-') in reqs_packages:
            in_reqs = True
        else:
            # Check reverse mapping: maybe the pip name differs from import name
            pip_names = import_to_pip.get(pkg_lower, [])
            for pn in pip_names:
                if pn in reqs_packages:
                    in_reqs = True
                    break

        # Check if it's installed in .venv
        is_installed = False
        if installed_packages:
            normalized = pkg_lower.replace('-', '_')
            if normalized in installed_packages:
                is_installed = True
            else:
                # Check known mappings
                pip_names = import_to_pip.get(pkg_lower, [])
                for pn in pip_names:
                    if pn.lower().replace('-', '_') in installed_packages:
                        is_installed = True
                        break

        if not in_reqs and not is_installed:
            issues.append(
                f"Missing dependency: '{top_pkg}' is imported in {rel_p} but not listed in "
                f"requirements.txt and not installed in .venv"
            )
        elif in_reqs and not is_installed and installed_packages:
            issues.append(
                f"Uninstalled dependency: '{top_pkg}' is in requirements.txt but not installed "
                f"in .venv — run: pip install -r requirements.txt"
            )

    @staticmethod
    def _auto_install_dependencies(workspace_path):
        """Deterministic post-implementation hook: scan .py files for third-party
        imports, ensure requirements.txt exists, and run pip install.

        This is 100% hardcoded — no LLM involved. It:
        1. Walks all .py files, extracts top-level import names via AST
        2. Filters out stdlib and local modules
        3. Maps import names to pip package names (handles pyyaml→yaml etc.)
        4. Reads existing requirements.txt (if any)
        5. Adds any missing packages to requirements.txt
        6. Runs `pip install -r requirements.txt` in the workspace .venv

        Returns dict: {installed: [...], errors: [...], requirements_updated: bool}
        """
        import ast as _ast

        result = {'installed': [], 'errors': [], 'requirements_updated': False}

        SKIP_DIRS = {'.git', '__pycache__', 'node_modules', '.venv', 'venv', '.sentinel'}

        STDLIB = _PYTHON_STDLIB

        # Import name → pip package name (when they differ)
        IMPORT_TO_PIP = {
            'yaml': 'pyyaml', 'pil': 'pillow', 'dotenv': 'python-dotenv',
            'bs4': 'beautifulsoup4', 'sklearn': 'scikit-learn',
            'cv2': 'opencv-python', 'dateutil': 'python-dateutil',
            'psycopg2': 'psycopg2-binary', 'magic': 'python-magic',
            'gi': 'pygobject', 'wx': 'wxpython', 'attr': 'attrs',
            'serial': 'pyserial', 'usb': 'pyusb', 'jose': 'python-jose',
            'jwt': 'pyjwt', 'lxml': 'lxml', 'PIL': 'pillow',
        }

        # 1) Collect all .py files
        py_files = {}
        try:
            for root, dirs, files in os.walk(workspace_path):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith('.')]
                for fname in files:
                    if not fname.endswith('.py'):
                        continue
                    abs_p = os.path.join(root, fname)
                    rel_p = os.path.relpath(abs_p, workspace_path).replace('\\', '/')
                    try:
                        with open(abs_p, 'r', encoding='utf-8', errors='replace') as f:
                            py_files[rel_p] = f.read()
                    except Exception:
                        pass
        except Exception as e:
            result['errors'].append(f"Failed to scan workspace: {e}")
            return result

        if not py_files:
            return result

        # 2) Collect local module names (so we don't treat them as third-party)
        local_modules = set()
        for rel_p in py_files:
            # "app.py" → "app", "utils/helpers.py" → "utils"
            top = rel_p.split('/')[0].replace('.py', '')
            local_modules.add(top)

        # 3) Extract all third-party import names
        third_party_imports = set()
        for rel_p, source in py_files.items():
            try:
                tree = _ast.parse(source, filename=rel_p)
            except SyntaxError:
                continue

            for node in _ast.walk(tree):
                if isinstance(node, _ast.Import):
                    for alias in node.names:
                        top_pkg = alias.name.split('.')[0]
                        if top_pkg not in STDLIB and top_pkg not in local_modules:
                            third_party_imports.add(top_pkg)
                elif isinstance(node, _ast.ImportFrom) and node.module:
                    top_pkg = node.module.split('.')[0]
                    if top_pkg not in STDLIB and top_pkg not in local_modules:
                        third_party_imports.add(top_pkg)

        if not third_party_imports:
            _safe_log("[AutoInstall] No third-party imports detected")
            return result

        _safe_log(f"[AutoInstall] Detected third-party imports: {sorted(third_party_imports)}")

        # 4) Map import names to pip package names
        pip_packages = set()
        for imp in third_party_imports:
            pip_name = IMPORT_TO_PIP.get(imp.lower(), imp)
            pip_packages.add(pip_name)

        # 5) Read existing requirements.txt
        req_path = os.path.join(workspace_path, 'requirements.txt')
        existing_packages = set()
        if os.path.isfile(req_path):
            try:
                with open(req_path, 'r', encoding='utf-8') as rf:
                    for line in rf:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            pkg = re.split(r'[>=<!\[\];]', line)[0].strip().lower()
                            if pkg:
                                existing_packages.add(pkg)
            except Exception:
                pass

        # 6) Add missing packages to requirements.txt
        missing = pip_packages - existing_packages
        # Also check normalized names (underscore vs hyphen)
        truly_missing = set()
        for pkg in missing:
            normalized = pkg.lower().replace('-', '_')
            # Check if any existing package matches after normalization
            found = False
            for existing in existing_packages:
                if existing.replace('-', '_') == normalized:
                    found = True
                    break
            if not found:
                truly_missing.add(pkg)

        if truly_missing:
            _safe_log(f"[AutoInstall] Adding to requirements.txt: {sorted(truly_missing)}")
            try:
                with open(req_path, 'a', encoding='utf-8') as wf:
                    if existing_packages:
                        # File exists with content, just append
                        wf.write('\n')
                    for pkg in sorted(truly_missing):
                        wf.write(f"{pkg}\n")
                result['requirements_updated'] = True
            except Exception as e:
                result['errors'].append(f"Failed to update requirements.txt: {e}")

        # 7) Ensure .venv exists
        venv_path = os.path.join(workspace_path, '.venv')
        if not os.path.isdir(venv_path):
            _safe_log("[AutoInstall] Creating .venv")
            try:
                subprocess.run(
                    [sys.executable, '-m', 'venv', venv_path],
                    capture_output=True, text=True, timeout=60
                )
            except Exception as e:
                result['errors'].append(f"Failed to create .venv: {e}")
                return result

        # 8) Run pip install -r requirements.txt
        if not os.path.isfile(req_path):
            _safe_log("[AutoInstall] No requirements.txt to install from")
            return result

        # Find pip in venv
        if platform.system() == 'Windows':
            pip_path = os.path.join(venv_path, 'Scripts', 'pip.exe')
        else:
            pip_path = os.path.join(venv_path, 'bin', 'pip')

        if not os.path.isfile(pip_path):
            # Fallback: use python -m pip
            pip_cmd = [os.path.join(venv_path, 'Scripts' if platform.system() == 'Windows' else 'bin', 'python'), '-m', 'pip']
        else:
            pip_cmd = [pip_path]

        install_cmd = pip_cmd + ['install', '-r', req_path, '--quiet']
        _safe_log(f"[AutoInstall] Running: {' '.join(install_cmd)}")

        try:
            proc = subprocess.run(
                install_cmd,
                capture_output=True, text=True, timeout=300,
                cwd=workspace_path
            )
            if proc.returncode == 0:
                # Parse installed packages from output
                for line in (proc.stdout or '').splitlines():
                    line = line.strip()
                    if 'Successfully installed' in line:
                        # "Successfully installed flask-3.0.0 jinja2-3.1.2 ..."
                        parts = line.split('Successfully installed')[-1].strip().split()
                        for part in parts:
                            pkg_name = part.rsplit('-', 1)[0] if '-' in part else part
                            result['installed'].append(pkg_name)
                if result['installed']:
                    _safe_log(f"[AutoInstall] Installed: {result['installed']}")
                else:
                    _safe_log("[AutoInstall] pip install completed (all deps already satisfied)")
            else:
                err_msg = (proc.stderr or proc.stdout or 'Unknown error').strip()
                # Truncate long error messages
                if len(err_msg) > 500:
                    err_msg = err_msg[:500] + '...'
                result['errors'].append(f"pip install failed: {err_msg}")
                _safe_log(f"[AutoInstall] pip install failed: {err_msg}")
        except subprocess.TimeoutExpired:
            result['errors'].append("pip install timed out after 300 seconds")
            _safe_log("[AutoInstall] pip install timed out")
        except Exception as e:
            result['errors'].append(f"pip install error: {e}")
            _safe_log(f"[AutoInstall] pip install error: {e}")

        return result

    @staticmethod
    def _build_full_import_context(workspace_path, written_files, import_graph, py_files):
        """Build full-content context for files imported by the written files.

        Instead of 4000-char signatures, this follows the import graph to depth 2
        and returns the FULL source of imported files so the LLM can check API
        compatibility properly.

        Args:
            workspace_path: absolute path to workspace
            written_files: set of rel_paths that were written this step
            import_graph: dict from _validate_project_integrity {file -> [imported files]}
            py_files: dict {rel_path -> source code}

        Returns:
            str: formatted context string with full file contents, or empty string
        """
        MAX_IMPORT_CONTEXT_CHARS = 12000

        # Collect all files imported by written files (depth 2)
        imported_files = set()
        # Depth 1: direct imports of written files
        for wf in written_files:
            for dep in import_graph.get(wf, []):
                if dep not in written_files:
                    imported_files.add(dep)
        # Depth 2: imports of those imports
        depth1_copy = set(imported_files)
        for dep in depth1_copy:
            for dep2 in import_graph.get(dep, []):
                if dep2 not in written_files and dep2 not in imported_files:
                    imported_files.add(dep2)

        if not imported_files:
            return ""

        context = "## Imported Files (full content for API checking)\n\n"
        total_chars = 0
        for fpath in sorted(imported_files):
            source = py_files.get(fpath, '')
            if not source:
                continue
            ext = os.path.splitext(fpath)[1].lstrip('.')
            entry = f"### `{fpath}`\n```{ext}\n{source}\n```\n\n"
            if total_chars + len(entry) > MAX_IMPORT_CONTEXT_CHARS:
                # Fall back to signatures for remaining files
                sig_lines = []
                for line in source.splitlines():
                    stripped = line.strip()
                    if (stripped.startswith('import ') or stripped.startswith('from ') or
                        stripped.startswith('class ') or stripped.startswith('def ') or
                        stripped.startswith('@')):
                        sig_lines.append(stripped)
                if sig_lines:
                    sig_text = '\n'.join(sig_lines)
                    entry = f"### `{fpath}` (signatures only — file too large)\n```{ext}\n{sig_text}\n```\n\n"
                    if total_chars + len(entry) > MAX_IMPORT_CONTEXT_CHARS + 2000:
                        break  # Hard cap
            context += entry
            total_chars += len(entry)

        return context

    @staticmethod
    def _run_review_pass(llm, history, tool_service, cancel_event, results,
                         max_turns=3, max_tokens=3072, timeout_seconds=120,
                         event_prefix='review', allowed_tools=None):
        """Run a single LLM review pass with tool execution loop.

        This is a generator that yields SSE event strings. The caller iterates
        over it and forwards events to the client.

        Args:
            llm: LLMEngine instance
            history: list of message dicts (will be mutated)
            tool_service: ToolService for EditFile/WriteFile
            cancel_event: threading.Event for cancellation
            results: mutable dict — populated with {'text': str, 'edits': list}
            max_turns: max LLM turns per pass (default 3)
            max_tokens: max_new_tokens for LLM (default 3072)
            timeout_seconds: max seconds for this pass (default 120)
            event_prefix: SSE event name prefix (default 'review', can be 'exec')
            allowed_tools: set of tool names to allow (default: {'EditFile', 'WriteFile'})

        Yields:
            SSE event strings ({prefix}_token, {prefix}_status, {prefix}_edit)
        """
        if allowed_tools is None:
            allowed_tools = {'EditFile', 'WriteFile'}
        TPFX = LLMEngine.THINK_PREFIX
        full_response = ""
        edits_made = []
        turn = 0
        _pass_start = time.time()

        while turn < max_turns:
            turn += 1

            # Check per-pass timeout
            if time.time() - _pass_start > timeout_seconds:
                _safe_log(f"[Review Pass] Timed out after {timeout_seconds}s")
                yield f"event: {event_prefix}_status\ndata: {json.dumps({'status': f'Pass timed out after {timeout_seconds}s'})}\n\n"
                break

            if cancel_event and cancel_event.is_set():
                break

            review_started = False
            try:
                for token in llm.stream_chat(history, max_new_tokens=max_tokens,
                                             temperature=0.3, cancel_event=cancel_event, read_timeout=120):
                    # Check timeout during streaming
                    if time.time() - _pass_start > timeout_seconds:
                        _safe_log(f"[Review Pass] Timed out during streaming after {timeout_seconds}s")
                        yield f"event: {event_prefix}_status\ndata: {json.dumps({'status': f'Pass timed out after {timeout_seconds}s'})}\n\n"
                        break

                    if token.startswith(TPFX):
                        continue
                    if not review_started:
                        review_started = True
                    full_response += token

                    # Early abort: LLM error
                    if len(full_response) < 400 and '[Error from LLM:' in full_response:
                        error_msg = full_response.strip().replace('[Error from LLM:', '').rstrip(']').strip()
                        _safe_log(f"[Review Pass] LLM error: {error_msg[:200]}")
                        yield f"event: {event_prefix}_error\ndata: {json.dumps({'error': f'LLM error: {error_msg}'})}\n\n"
                        results['text'] = full_response
                        results['edits'] = edits_made
                        return
                    if len(full_response) < 400 and '[Error:' in full_response and full_response.strip().startswith('[Error:'):
                        error_msg = full_response.strip()
                        _safe_log(f"[Review Pass] Error: {error_msg[:200]}")
                        yield f"event: {event_prefix}_error\ndata: {json.dumps({'error': error_msg})}\n\n"
                        results['text'] = full_response
                        results['edits'] = edits_made
                        return

                    yield f"event: {event_prefix}_token\ndata: {json.dumps({'token': token})}\n\n"
            except Exception as e:
                _safe_log(f"[Review Pass] LLM error: {e}")
                yield f"event: {event_prefix}_error\ndata: {json.dumps({'error': str(e)})}\n\n"
                results['text'] = full_response
                results['edits'] = edits_made
                return

            if cancel_event and cancel_event.is_set():
                break

            # Check for tool calls — both <tool_code> and GPT-OSS formats
            tool_blocks = list(re.finditer(r'<tool_code>(.*?)</tool_code>', full_response, re.DOTALL))
            # GPT-OSS format — accept any channel type (commentary, analysis, code, etc.)
            gptoss_tool_blocks = re.findall(
                r'<\|channel\|>\w+\s+to=(\w+)\s*(?:<\|constrain\|>json)?[^<]*<\|message\|>(.*?)(?=<\|channel\|>|\Z)',
                full_response, re.DOTALL
            )
            normalized_gptoss = []
            for tool_name_hint, tool_body in gptoss_tool_blocks:
                body = tool_body.strip()
                try:
                    parsed = json.loads(body)
                    if 'name' not in parsed:
                        parsed = {'name': tool_name_hint, 'arguments': parsed}
                    normalized_gptoss.append(json.dumps(parsed))
                except Exception:
                    normalized_gptoss.append(json.dumps({'name': tool_name_hint, 'arguments': {}}))

            if not tool_blocks and not normalized_gptoss:
                break  # No tool calls — pass complete

            # Execute tool calls
            history.append({"role": "assistant", "content": full_response})
            tool_executed = False

            # Process standard <tool_code> blocks
            for tb_match in tool_blocks:
                block_text = tb_match.group(1).strip()
                try:
                    tc = json.loads(block_text)
                except Exception:
                    name_m = re.search(r'"name"\s*:\s*"(\w+)"', block_text)
                    if not name_m:
                        continue
                    tc = {'name': name_m.group(1), 'arguments': {}}
                    path_m = re.search(r'"path"\s*:\s*"([^"]+)"', block_text)
                    old_m = re.search(r'"old_string"\s*:\s*"((?:[^"\\]|\\.)*)"', block_text, re.DOTALL)
                    new_m = re.search(r'"new_string"\s*:\s*"((?:[^"\\]|\\.)*)"', block_text, re.DOTALL)
                    if path_m:
                        tc['arguments']['path'] = path_m.group(1)
                    if old_m:
                        tc['arguments']['old_string'] = old_m.group(1).replace('\\n', '\n').replace('\\t', '\t').replace('\\"', '"').replace('\\\\', '\\')
                    if new_m:
                        tc['arguments']['new_string'] = new_m.group(1).replace('\\n', '\n').replace('\\t', '\t').replace('\\"', '"').replace('\\\\', '\\')

                tool_name = tc.get('name', '')
                tool_args = tc.get('arguments', {})
                if tool_name not in allowed_tools:
                    continue

                edit_path = tool_args.get('path', tool_args.get('command', 'file'))
                action_labels = {'WriteFile': 'Writing', 'EditFile': 'Editing',
                                 'ReadFile': 'Reading', 'RunCommand': 'Running'}
                action_label = action_labels.get(tool_name, 'Executing')
                yield f"event: {event_prefix}_status\ndata: {json.dumps({'status': action_label + ' ' + edit_path + '...'})}\n\n"

                try:
                    result = tool_service.execute_tool(tool_name, tool_args)
                    edit_info = {
                        'path': tool_args.get('path', tool_args.get('command', '')),
                        'old_string': tool_args.get('old_string', ''),
                        'new_string': tool_args.get('new_string', ''),
                        'result': result,
                    }
                    edits_made.append(edit_info)
                    yield f"event: {event_prefix}_edit\ndata: {json.dumps(edit_info)}\n\n"
                    history.append({"role": "user", "content": f"Tool Result: {result}"})
                    tool_executed = True
                except Exception as e:
                    _safe_log(f"[Review Pass] {tool_name} error: {e}")
                    history.append({"role": "user", "content": f"Tool Error: {str(e)}"})
                    tool_executed = True

            # Process GPT-OSS format tool blocks
            for block_json in normalized_gptoss:
                try:
                    tc = json.loads(block_json)
                except Exception:
                    continue
                tool_name = tc.get('name', '')
                tool_args = tc.get('arguments', {})
                if tool_name not in allowed_tools:
                    continue
                edit_path = tool_args.get('path', tool_args.get('command', 'file'))
                action_labels = {'WriteFile': 'Writing', 'EditFile': 'Editing',
                                 'ReadFile': 'Reading', 'RunCommand': 'Running'}
                action_label = action_labels.get(tool_name, 'Executing')
                yield f"event: {event_prefix}_status\ndata: {json.dumps({'status': action_label + ' ' + edit_path + '...'})}\n\n"
                try:
                    result = tool_service.execute_tool(tool_name, tool_args)
                    edit_info = {
                        'path': tool_args.get('path', tool_args.get('command', '')),
                        'old_string': tool_args.get('old_string', ''),
                        'new_string': tool_args.get('new_string', ''),
                        'result': result,
                    }
                    edits_made.append(edit_info)
                    yield f"event: {event_prefix}_edit\ndata: {json.dumps(edit_info)}\n\n"
                    history.append({"role": "user", "content": f"Tool Result: {result}"})
                    tool_executed = True
                except Exception as e:
                    _safe_log(f"[Review Pass] {tool_name} error (GPT-OSS): {e}")
                    history.append({"role": "user", "content": f"Tool Error: {str(e)}"})
                    tool_executed = True

            if not tool_executed:
                break

            # Reset for next turn
            full_response = ""
            yield f"event: {event_prefix}_status\ndata: {json.dumps({'status': 'Continuing...'})}\n\n"

        # Populate results
        results['text'] = full_response
        results['edits'] = edits_made

    # ── Step-Fix Agent (reopens an implementation step to fix runtime errors) ──

    @staticmethod
    def _build_step_fix_message(error_class, error_output, workspace_path):
        """Build the fix message for an implementation step's chat.

        Delegates to prompts.execution.build_step_fix_message().
        Converts error file path to relative before passing to prompt.
        """
        from prompts.execution import build_step_fix_message
        error_file = error_class.get('file', 'unknown')
        try:
            error_file_rel = os.path.relpath(error_file, workspace_path).replace('\\', '/')
        except (ValueError, TypeError):
            error_file_rel = error_file
        return build_step_fix_message(
            error_class=error_class,
            error_output=error_output or '',
            error_file_rel=error_file_rel,
        )

    @staticmethod
    def _run_step_fix(workspace_path, task_id, step_dict, error_class,
                      error_output, cancel_event=None):
        """Run a targeted fix on an implementation step's code.

        Reopens the step's chat context, injects a fix message describing the
        runtime error, and runs a limited agent loop (via _run_review_pass) to
        have the implementation LLM fix its own code.

        Generator yielding SSE event strings (exec_step_fix_* events).

        Args:
            workspace_path: Absolute path to the project workspace
            task_id: Task ID
            step_dict: Step dict from _trace_error_to_step
            error_class: Error classification from _classify_error
            error_output: Raw error output string
            cancel_event: Optional threading.Event for cancellation
        """
        import platform

        step_id = step_dict.get('id', '')
        step_name = step_dict.get('name', step_id)
        error_file = error_class.get('file', 'unknown')
        error_type = error_class.get('errorType', 'Unknown')

        try:
            error_file_short = os.path.relpath(error_file, workspace_path).replace('\\', '/')
        except (ValueError, TypeError):
            error_file_short = error_file

        _safe_log(f"[Step Fix] Starting fix for step '{step_name}' ({step_id}), error in {error_file_short}")

        yield f"event: exec_step_fix_start\ndata: {json.dumps({'stepId': step_id, 'stepName': step_name, 'errorFile': error_file_short, 'errorType': error_type})}\n\n"

        try:
            # ── Get or create the step's chat ──
            chat_id = step_dict.get('chatId')
            chat = None
            if chat_id:
                chat = AgentService.get_chat(task_id, chat_id)

            if not chat:
                # Create a fresh chat for the step fix
                chat = AgentService.create_chat(task_id, name=f"{step_name} (Fix)")
                chat_id = chat['id']
                # Link chat to step in plan.md
                try:
                    TaskService.update_step_in_plan(
                        workspace_path, task_id, step_id,
                        {'chatId': chat_id}
                    )
                except Exception as e:
                    _safe_log(f"[Step Fix] Could not link chat to step: {e}")

            _msg_count = len(chat.get('messages', []))
            yield f"event: exec_step_fix_status\ndata: {json.dumps({'status': f'Loaded step context ({_msg_count} prior messages)'})}\n\n"

            # ── Build LLM context (simplified from continue_chat_stream) ──
            task = TaskService.get_task(task_id)
            if not task:
                yield f"event: exec_step_fix_failed\ndata: {json.dumps({'stepId': step_id, 'reason': 'Task not found'})}\n\n"
                return

            artifacts_path = os.path.join('.sentinel', 'tasks', task_id)
            os_name = platform.system()

            # Build tool service
            tool_service = ToolService(workspace_path, current_step_id=step_id, workspace_path=workspace_path)
            tools_def = tool_service.get_tool_definitions()

            # Look up parent context for child steps
            parent_context = None
            all_steps = task.get('steps', [])
            if '::' in step_id:
                parent_id = step_id.split('::')[0]
                for s in all_steps:
                    if s['id'] == parent_id:
                        parent_context = {
                            'name': s.get('name', ''),
                            'description': s.get('description', '')
                        }
                        break

            # List existing workspace files
            existing_files = []
            try:
                SKIP_DIRS = {'.git', '__pycache__', 'node_modules', '.venv', 'venv', '.sentinel'}
                for root, dirs, files in os.walk(workspace_path):
                    dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith('.')]
                    for fname in files:
                        if not fname.startswith('.'):
                            rel = os.path.relpath(os.path.join(root, fname), workspace_path).replace('\\', '/')
                            existing_files.append(rel)
            except Exception:
                pass

            # Build step instructions
            step_instructions = AgentService._get_step_read_instructions(
                step_id, artifacts_path,
                step_name=step_name,
                step_description=step_dict.get('description', ''),
                parent_name=parent_context['name'] if parent_context else '',
                parent_description=parent_context['description'] if parent_context else '',
                task_details=task.get('details', ''),
                existing_files=existing_files,
                complexity=task.get('settings', {}).get('complexity', 5),
            )

            # Build system prompt
            system_prompt = build_system_prompt(
                os_name=os_name,
                step_id=step_id,
                workspace_path=workspace_path,
                artifacts_path=artifacts_path,
                task_details=task.get('details', 'No description.'),
                tools_def=tools_def,
                step_for_chat=step_dict,
                all_steps=all_steps,
                parent_context=parent_context,
                step_instructions=step_instructions,
                artifact_name='',
                existing_files=existing_files,
            )

            # Pre-seed artifacts (implementation-plan.md, spec.md, etc.)
            seeded = AgentService._seed_prior_artifacts(
                workspace_path, task_id, step_id, artifacts_path,
                max_seed_chars=4000,
                step_description=step_dict.get('description', '')
            )

            # Build history: system + seeded + existing messages (truncated) + fix message
            history = [{"role": "system", "content": system_prompt}]
            for msg in seeded:
                history.append(msg)

            # Append existing chat messages (truncate to last 4 if too many)
            existing_msgs = chat.get('messages', [])
            if len(existing_msgs) > 10:
                existing_msgs = existing_msgs[-4:]
            for msg in existing_msgs:
                history.append({"role": msg['role'], "content": msg['content']})

            # Build and append the fix message
            fix_message = AgentService._build_step_fix_message(error_class, error_output, workspace_path)
            history.append({"role": "user", "content": fix_message})

            # Persist fix message to chat
            AgentService.add_message(task_id, chat_id, "user", fix_message)

            yield f"event: exec_step_fix_status\ndata: {json.dumps({'status': 'Running implementation LLM to fix error...'})}\n\n"

            # ── Run mini agent loop ──
            llm = get_llm_engine()
            pass_results = {'text': '', 'edits': []}

            for event_str in AgentService._run_review_pass(
                llm, history, tool_service, cancel_event, pass_results,
                max_turns=5,
                max_tokens=3072,
                timeout_seconds=120,
                event_prefix='exec_step_fix',
                allowed_tools={'EditFile', 'WriteFile', 'ReadFile'}
            ):
                yield event_str

            # Persist assistant response to chat
            if pass_results.get('text'):
                AgentService.add_message(task_id, chat_id, "assistant", pass_results['text'])

            # ── Emit result ──
            files_fixed = [e.get('path', '') for e in pass_results.get('edits', []) if e.get('path')]
            if files_fixed:
                _safe_log(f"[Step Fix] Fixed {len(files_fixed)} file(s): {files_fixed}")
                yield f"event: exec_step_fix_complete\ndata: {json.dumps({'stepId': step_id, 'filesFixed': files_fixed})}\n\n"
            else:
                _safe_log(f"[Step Fix] No fixes applied by LLM")
                yield f"event: exec_step_fix_failed\ndata: {json.dumps({'stepId': step_id, 'reason': 'LLM made no fixes'})}\n\n"

        except Exception as e:
            _safe_log(f"[Step Fix] Error: {e}")
            yield f"event: exec_step_fix_failed\ndata: {json.dumps({'stepId': step_id, 'reason': str(e)})}\n\n"

    # ── Execution Agent ─────────────────────────────────────────────────

    @staticmethod
    def _classify_error(error_output):
        """Parse Python traceback and classify the error type.

        Returns: {type, errorType, file, line, module, message}
        """
        # Defensive: ensure string, cap length for regex safety
        if not error_output:
            return {'type': 'unknown', 'errorType': 'Unknown', 'file': None,
                    'line': None, 'module': None, 'message': ''}
        if not isinstance(error_output, str):
            error_output = str(error_output)
        # Cap at 50KB to prevent catastrophic regex backtracking
        error_output = error_output[:50_000]
        result = {'type': 'unknown', 'errorType': 'Unknown', 'file': None,
                  'line': None, 'module': None, 'message': error_output[:300]}

        try:
            # ModuleNotFoundError
            m = re.search(r"ModuleNotFoundError:\s*No module named ['\"]([^'\"]+)['\"]", error_output)
            if m:
                result.update({'type': 'module_not_found', 'errorType': 'ModuleNotFoundError', 'module': m.group(1)})
                result['message'] = f"No module named '{m.group(1)}'"

            # ImportError
            if result['type'] == 'unknown':
                m = re.search(r"ImportError:\s*cannot import name ['\"](\w+)['\"] from ['\"]([^'\"]+)['\"]", error_output)
                if m:
                    result.update({'type': 'import', 'errorType': 'ImportError'})
                    result['message'] = f"Cannot import '{m.group(1)}' from '{m.group(2)}'"
                elif 'ImportError:' in error_output:
                    m2 = re.search(r'ImportError:\s*(.+)', error_output)
                    if m2:
                        result.update({'type': 'import', 'errorType': 'ImportError', 'message': m2.group(1).strip()[:200]})

            # SyntaxError
            if result['type'] == 'unknown':
                m = re.search(r'SyntaxError:\s*(.+)', error_output)
                if m:
                    result.update({'type': 'syntax', 'errorType': 'SyntaxError', 'message': m.group(1).strip()[:200]})

            # Any other traceback error
            if result['type'] == 'unknown':
                m = re.search(r'(\w+Error):\s*(.+)', error_output)
                if m:
                    result.update({'type': 'runtime', 'errorType': m.group(1), 'message': m.group(2).strip()[:200]})

            # Extract file and line from traceback
            file_matches = list(re.finditer(r'File "([^"]+)", line (\d+)', error_output))
            if file_matches:
                # Take the last file reference (closest to the actual error)
                last = file_matches[-1]
                result['file'] = last.group(1)
                result['line'] = int(last.group(2))
        except Exception:
            # If regex parsing fails for any reason, return the default result
            pass

        return result

    @staticmethod
    def _trace_error_to_step(workspace_path, task_id, error_class):
        """Trace a runtime error back to the implementation step that owns the failing file.

        Uses the error file path from _classify_error() and cross-references it
        against each implementation step's Files: and Modifies: metadata.

        Args:
            workspace_path: Absolute path to the project workspace
            task_id: Task ID for loading plan.md
            error_class: Dict from _classify_error() with keys: type, errorType, file, line, module, message

        Returns:
            Step dict if a matching step is found, else None.
        """
        error_file = error_class.get('file')
        if not error_file:
            return None

        # Skip non-workspace files (<string>, stdlib, .venv, etc.)
        if error_file.startswith('<') or not os.path.isabs(error_file):
            # Try treating it as relative to workspace
            abs_candidate = os.path.join(workspace_path, error_file)
            if not os.path.isfile(abs_candidate):
                return None
            error_file = abs_candidate

        try:
            error_rel = os.path.relpath(error_file, workspace_path).replace('\\', '/')
        except ValueError:
            return None

        # Skip files outside workspace (e.g., .venv, stdlib)
        if error_rel.startswith('..') or error_rel.startswith('.venv'):
            return None

        # Load task steps
        try:
            task = TaskService.get_task(task_id)
            if not task:
                return None
            all_steps = task.get('steps', [])
        except Exception:
            return None

        # Flatten all steps and filter to implementation child steps only
        SDD_IDS = {'requirements', 'technical-specification', 'planning', 'implementation'}
        candidates = []
        for s in all_steps:
            for child in s.get('children', []):
                cid = child.get('id', '')
                if cid not in SDD_IDS and child.get('parentId'):
                    candidates.append(child)
            # Also check root-level non-SDD steps (rare but possible)
            sid = s.get('id', '')
            if sid not in SDD_IDS and s.get('children') == []:
                candidates.append(s)

        if not candidates:
            return None

        error_basename = os.path.basename(error_rel)

        # First pass: match against Files: (primary ownership)
        for step in candidates:
            desc = step.get('description', '')
            owned = AgentService._extract_owned_files(desc)
            for f in owned:
                f_norm = f.replace('\\', '/')
                f_base = os.path.basename(f_norm)
                # Exact match
                if f_norm == error_rel:
                    return step
                # Basename match
                if f_base == error_basename:
                    return step
                # Suffix match (error is src/api/routes.py, step has api/routes.py)
                if error_rel.endswith('/' + f_norm) or error_rel.endswith(f_norm):
                    return step

        # Second pass: match against Modifies: (secondary ownership)
        for step in candidates:
            desc = step.get('description', '')
            modifies = AgentService._extract_modifies_files(desc)
            for f in modifies:
                f_norm = f.replace('\\', '/')
                f_base = os.path.basename(f_norm)
                if f_norm == error_rel or f_base == error_basename:
                    return step
                if error_rel.endswith('/' + f_norm) or error_rel.endswith(f_norm):
                    return step

        # Third pass: ImportError fallback — convert module to file path
        module = error_class.get('module')
        if module and error_class.get('type') in ('import', 'module_not_found'):
            # Convert e.g. 'models.user' → 'models/user.py'
            module_path = module.replace('.', '/') + '.py'
            module_basename = os.path.basename(module_path)
            for step in candidates:
                desc = step.get('description', '')
                owned = AgentService._extract_owned_files(desc)
                modifies = AgentService._extract_modifies_files(desc)
                all_files = owned + modifies
                for f in all_files:
                    f_norm = f.replace('\\', '/')
                    f_base = os.path.basename(f_norm)
                    if f_norm == module_path or f_base == module_basename:
                        return step

        return None

    # Junk lines commonly left by review agent / bad diffs
    _JUNK_PATTERNS = re.compile(
        r'^\*\*\* End of File \*\*\*$'
        r'|^<<<<<<< '
        r'|^=======$'
        r'|^>>>>>>> '
        r'|^diff --git '
        r'|^index [0-9a-f]'
        r'|^@@ .* @@'
    )

    @staticmethod
    def _fix_diff_markers(filepath):
        """Deterministically strip stray diff markers (+/-) and junk lines.

        Handles:
        - Lines starting with + or - (diff patch artifacts)
        - Standalone + or - on a line
        - *** End of File ***, merge conflict markers, diff headers

        Returns list of fixed line numbers, or empty list if nothing was fixed.
        """
        try:
            with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
        except Exception:
            return []

        fixed_lines = []
        new_lines = []
        for i, line in enumerate(lines, 1):
            stripped = line.rstrip('\n\r')

            # Remove junk lines entirely
            if stripped and AgentService._JUNK_PATTERNS.match(stripped):
                fixed_lines.append(i)
                continue  # Drop the line entirely

            if not stripped or stripped[0] not in ('+', '-'):
                new_lines.append(line)
                continue

            # Standalone +/- on a line → convert to empty line
            if len(stripped) == 1:
                new_lines.append('\n' if line.endswith('\n') else '')
                fixed_lines.append(i)
                continue

            rest = stripped[1:]
            # Skip diff headers like +++ or ---
            if rest.startswith('++') or rest.startswith('--'):
                new_lines.append(line)
                continue
            # Diff markers at col 0: followed by space/tab/letter/hash/@/(/)
            # (real code like x=-1 has the - mid-line, not at col 0)
            if rest[0] in (' ', '\t', '#', '@', '(', ')', '[', ']', '{', '}', '"', "'") or rest[0].isalpha():
                new_lines.append(rest + '\n' if line.endswith('\n') else rest)
                fixed_lines.append(i)
            else:
                new_lines.append(line)

        if fixed_lines:
            try:
                with open(filepath, 'w', encoding='utf-8', newline='') as f:
                    f.writelines(new_lines)
            except Exception:
                return []

        return fixed_lines

    # Max output from subprocess — prevents OOM on runaway programs
    _MAX_SUBPROCESS_OUTPUT = 100_000  # 100KB per stream

    @staticmethod
    def _run_project_subprocess(command, workspace_path, timeout=30):
        """Run a command and return (exit_code, stdout, stderr).

        Uses the workspace .venv like terminal.py's _build_venv_env.
        Output is capped at _MAX_SUBPROCESS_OUTPUT to prevent OOM.

        On Windows, uses CREATE_NEW_PROCESS_GROUP + taskkill /T to ensure
        child processes (like Flask servers) are killed on timeout.
        """
        # Validate command length
        if isinstance(command, str) and len(command) > 2000:
            return -1, '', 'Command too long (max 2000 characters)'

        env = os.environ.copy()
        venv_scripts = os.path.join(workspace_path, '.venv', 'Scripts')
        if not os.path.isdir(venv_scripts):
            venv_scripts = os.path.join(workspace_path, '.venv', 'bin')
        if os.path.isdir(venv_scripts):
            env['PATH'] = venv_scripts + os.pathsep + env.get('PATH', '')
            env['VIRTUAL_ENV'] = os.path.join(workspace_path, '.venv')

        cap = AgentService._MAX_SUBPROCESS_OUTPUT
        try:
            is_windows = platform.system() == 'Windows'

            # Use Popen for proper cleanup on timeout (especially Windows)
            kwargs = dict(
                shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, cwd=workspace_path, env=env,
            )
            if is_windows:
                kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP

            proc = subprocess.Popen(command, **kwargs)
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                # Kill the entire process tree
                if is_windows:
                    try:
                        subprocess.run(
                            f'taskkill /F /T /PID {proc.pid}',
                            shell=True, capture_output=True, timeout=5
                        )
                    except Exception:
                        proc.kill()
                else:
                    import signal
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    except Exception:
                        proc.kill()
                # Collect any partial output
                try:
                    stdout, stderr = proc.communicate(timeout=3)
                except Exception:
                    stdout, stderr = '', ''
                return -1, (stdout or '')[:cap], f'Process timed out after {timeout}s'

            stdout = (stdout or '')[:cap]
            stderr = (stderr or '')[:cap]
            return proc.returncode, stdout, stderr
        except Exception as e:
            return -1, '', str(e)

    @staticmethod
    def _add_to_requirements_txt(workspace_path, package_name):
        """Add a package to requirements.txt if not already present."""
        req_path = os.path.join(workspace_path, 'requirements.txt')
        existing = set()
        if os.path.isfile(req_path):
            try:
                with open(req_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        stripped = line.strip()
                        if stripped and not stripped.startswith('#'):
                            existing.add(stripped.split('==')[0].split('>=')[0].split('<=')[0].split('[')[0].lower())
            except Exception:
                pass
        if package_name.lower() not in existing:
            try:
                with open(req_path, 'a', encoding='utf-8') as f:
                    f.write(f'{package_name}\n')
            except Exception:
                pass

    @staticmethod
    def _remove_from_requirements_txt(workspace_path, package_name):
        """Remove a package from requirements.txt (e.g. when pip install proves it's not a real package)."""
        req_path = os.path.join(workspace_path, 'requirements.txt')
        if not os.path.isfile(req_path):
            return
        try:
            with open(req_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            pkg_norm = package_name.lower().replace('-', '_')
            new_lines = []
            for line in lines:
                stripped = line.strip()
                if stripped and not stripped.startswith('#'):
                    line_pkg = re.split(r'[>=<!\[\];]', stripped)[0].strip().lower().replace('-', '_')
                    if line_pkg == pkg_norm:
                        continue  # Skip this package
                new_lines.append(line)
            with open(req_path, 'w', encoding='utf-8') as f:
                f.writelines(new_lines)
        except Exception:
            pass

    # Known pip packages whose import name shadows stdlib or common names.
    # Used by _detect_shadowing_files to find local .py files that shadow real packages.
    _KNOWN_PIP_PACKAGES = {
        'flask', 'django', 'fastapi', 'requests', 'sqlalchemy', 'celery',
        'pytest', 'numpy', 'pandas', 'scipy', 'matplotlib', 'pillow',
        'jinja2', 'werkzeug', 'click', 'boto3', 'redis', 'pydantic',
        'uvicorn', 'gunicorn', 'alembic', 'marshmallow', 'wtforms',
        'socketio', 'eventlet', 'gevent', 'stripe', 'twilio', 'sendgrid',
        'psycopg2', 'pymongo', 'motor', 'aiohttp', 'httpx', 'starlette',
        'bottle', 'tornado', 'sanic', 'falcon', 'pyramid', 'cherrypy',
    }

    # Packages with known build failures — map to binary/pure-python alternatives
    _BUILD_SUBS = {
        'psycopg2': 'psycopg2-binary',
        'mysqlclient': 'pymysql',
        'lxml': 'lxml',  # keep but note: needs system libs
        'greenlet': 'greenlet',
        'uvloop': 'uvloop',
    }

    @staticmethod
    def _detect_shadowing_files(workspace_path):
        """Detect local .py files that shadow pip packages or stdlib modules.

        E.g. a file named 'flask.py' at the workspace root will shadow the
        real Flask package, causing 'partially initialized module' errors.

        Returns list of dicts: [{file, renamed_to, updated_imports: [...]}]
        """
        STDLIB = _PYTHON_STDLIB
        KNOWN_PKGS = AgentService._KNOWN_PIP_PACKAGES

        # Also read requirements.txt to know what pip packages are expected
        req_names = set()
        req_path = os.path.join(workspace_path, 'requirements.txt')
        if os.path.isfile(req_path):
            try:
                with open(req_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            pkg = re.split(r'[>=<!\[\];]', line)[0].strip().lower()
                            if pkg:
                                req_names.add(pkg.replace('-', '_'))
            except Exception:
                pass

        # Combine: any name in stdlib, known pip packages, or requirements.txt
        shadow_names = STDLIB | KNOWN_PKGS | req_names

        results = []
        SKIP_DIRS = {'.git', '__pycache__', 'node_modules', '.venv', 'venv', '.sentinel'}

        # Only check root-level .py files (subdirectories are packages, not shadows)
        try:
            for fname in sorted(os.listdir(workspace_path)):
                if not fname.endswith('.py'):
                    continue
                stem = fname[:-3]  # e.g. 'flask' from 'flask.py'
                if stem.lower() not in shadow_names:
                    continue
                # Don't rename __init__.py or setup.py etc.
                if stem.startswith('_') or stem in ('setup', 'conftest', 'manage'):
                    continue

                # This file shadows a real package — rename it
                old_path = os.path.join(workspace_path, fname)
                new_name = f"{stem}_app.py"
                # Avoid collision
                if os.path.exists(os.path.join(workspace_path, new_name)):
                    new_name = f"{stem}_local.py"
                if os.path.exists(os.path.join(workspace_path, new_name)):
                    continue  # Can't find a safe name, skip

                new_path = os.path.join(workspace_path, new_name)
                try:
                    os.rename(old_path, new_path)
                except Exception:
                    continue

                # Update imports in ALL .py files that import the old name
                updated_files = []
                old_module = stem  # e.g. 'flask' — but this is the LOCAL file
                new_module = new_name[:-3]  # e.g. 'flask_app'
                for root, dirs, files in os.walk(workspace_path):
                    dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                    for f in files:
                        if not f.endswith('.py'):
                            continue
                        fpath = os.path.join(root, f)
                        try:
                            with open(fpath, 'r', encoding='utf-8', errors='replace') as fh:
                                content = fh.read()
                        except Exception:
                            continue

                        # Replace imports of the shadowing module
                        # Pattern: 'from flask import X' or 'import flask'
                        # But ONLY when it's importing from the LOCAL file, not the pip package.
                        # Heuristic: if the import references names defined in the old file, it's local.
                        # Simpler approach: replace 'from {stem} import' with 'from {new_module} import'
                        # only if the file also does NOT have the pip package's typical imports.
                        #
                        # Since we renamed the file, any 'from flask import' that was pointing at
                        # the local file will now break. We need to update those.
                        # But 'from flask import Flask' should NOT be touched — that's the real package.
                        #
                        # Strategy: Read the old file's defined names, only rewrite imports that
                        # reference those names.
                        old_file_path = new_path  # file was already renamed
                        try:
                            with open(old_file_path, 'r', encoding='utf-8', errors='replace') as of:
                                old_source = of.read(8000)
                            import ast as _ast
                            old_tree = _ast.parse(old_source)
                            old_names = set()
                            for node in _ast.iter_child_nodes(old_tree):
                                if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                                    old_names.add(node.name)
                                elif isinstance(node, _ast.ClassDef):
                                    old_names.add(node.name)
                                elif isinstance(node, _ast.Assign):
                                    for t in node.targets:
                                        if isinstance(t, _ast.Name):
                                            old_names.add(t.id)
                        except Exception:
                            old_names = set()

                        new_content = content
                        changed = False

                        # Replace 'from {stem} import X, Y' where X/Y are in old_names
                        pattern = rf'^(from\s+){re.escape(stem)}(\s+import\s+)(.+)$'
                        for match in re.finditer(pattern, content, re.MULTILINE):
                            imported_names = [n.strip().split(' as ')[0].strip()
                                              for n in match.group(3).split(',')]
                            # If ANY imported name is from the old local file, rewrite
                            if old_names and any(n in old_names for n in imported_names):
                                old_line = match.group(0)
                                new_line = f"{match.group(1)}{new_module}{match.group(2)}{match.group(3)}"
                                new_content = new_content.replace(old_line, new_line, 1)
                                changed = True

                        # Replace bare 'import {stem}' only if old_names found usage
                        bare_pattern = rf'^import\s+{re.escape(stem)}\s*$'
                        if old_names and re.search(bare_pattern, content, re.MULTILINE):
                            new_content = re.sub(bare_pattern, f'import {new_module}',
                                                 new_content, flags=re.MULTILINE)
                            # Also replace usage: stem.X → new_module.X
                            new_content = new_content.replace(f'{stem}.', f'{new_module}.')
                            changed = True

                        if changed:
                            try:
                                with open(fpath, 'w', encoding='utf-8') as fh:
                                    fh.write(new_content)
                                rel = os.path.relpath(fpath, workspace_path).replace('\\', '/')
                                updated_files.append(rel)
                            except Exception:
                                pass

                results.append({
                    'file': fname,
                    'renamed_to': new_name,
                    'updated_imports': updated_files,
                })
        except Exception:
            pass

        return results

    @staticmethod
    def _fix_pinned_requirements(workspace_path, pip_errors):
        """Fix pinned versions in requirements.txt that pip can't resolve.

        Reads the error messages to find which packages failed, then relaxes
        exact pins (==X.Y.Z) to >= pins so pip can find a compatible version.
        Returns a comma-separated string of fixed package names, or empty string.
        """
        req_path = os.path.join(workspace_path, 'requirements.txt')
        if not os.path.isfile(req_path):
            return ''
        # Extract failed package names from pip errors
        # e.g. "ERROR: Could not find a version that satisfies the requirement Flask==2.3.4"
        failed_pkgs = set()
        for err_line in pip_errors:
            m = re.search(r'requirement\s+(\S+?)(?:==|>=|<=|~=|!=)', err_line, re.IGNORECASE)
            if m:
                failed_pkgs.add(m.group(1).lower())
            else:
                # Try "No matching distribution found for PackageName==X.Y.Z"
                m2 = re.search(r'distribution found for\s+(\S+?)(?:==|>=|<=|~=|!=)', err_line, re.IGNORECASE)
                if m2:
                    failed_pkgs.add(m2.group(1).lower())
        if not failed_pkgs:
            return ''
        try:
            with open(req_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except Exception:
            return ''
        fixed = []
        new_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith('#'):
                pkg_name = re.split(r'[=<>!~\[]', stripped)[0].strip().lower()
                if pkg_name in failed_pkgs and '==' in stripped:
                    # Replace exact pin with unpinned (let pip pick latest)
                    new_lines.append(pkg_name + '\n')
                    fixed.append(pkg_name)
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)
        if fixed:
            try:
                with open(req_path, 'w', encoding='utf-8') as f:
                    f.writelines(new_lines)
            except Exception:
                return ''
        return ', '.join(fixed)

    @staticmethod
    def _read_project_files_for_exec(workspace_path, focus_file=None, max_chars=30000):
        """Read source files for execution agent context.

        Priority order:
          1. Focus file (error file) — up to 8000 chars
          2. Files imported by the focus file — up to 4000 chars each
          3. All other source files — up to 2000 chars each
        Total capped at max_chars (default 30KB).
        """
        import ast as _ast
        SOURCE_EXTS = {'.py', '.js', '.ts', '.jsx', '.tsx', '.json', '.txt', '.md', '.cfg', '.toml', '.yaml', '.yml'}
        SKIP_DIRS = {'.venv', 'venv', '__pycache__', '.git', '.sentinel', 'node_modules'}
        files = {}
        total = 0

        # 1. Read focus file first (full content, 8KB budget)
        focus_source = None
        if focus_file:
            abs_focus = focus_file if os.path.isabs(focus_file) else os.path.join(workspace_path, focus_file)
            if os.path.isfile(abs_focus):
                try:
                    with open(abs_focus, 'r', encoding='utf-8', errors='replace') as f:
                        focus_source = f.read(8000)
                    rel = os.path.relpath(abs_focus, workspace_path).replace('\\', '/')
                    files[rel] = focus_source
                    total += len(focus_source)
                except Exception:
                    pass

        # 2. Follow imports from focus file (Python only)
        if focus_source and focus_file and focus_file.endswith('.py'):
            try:
                tree = _ast.parse(focus_source)
                imported_modules = set()
                for node in _ast.walk(tree):
                    if isinstance(node, _ast.Import):
                        for alias in node.names:
                            imported_modules.add(alias.name.split('.')[0])
                    elif isinstance(node, _ast.ImportFrom) and node.module:
                        imported_modules.add(node.module.split('.')[0])

                # Resolve to local files
                for mod in imported_modules:
                    if total >= max_chars:
                        break
                    if mod in _PYTHON_STDLIB:
                        continue
                    # Check {mod}.py or {mod}/__init__.py
                    for candidate in [f'{mod}.py', os.path.join(mod, '__init__.py')]:
                        cpath = os.path.join(workspace_path, candidate)
                        rel = candidate.replace('\\', '/')
                        if os.path.isfile(cpath) and rel not in files:
                            try:
                                with open(cpath, 'r', encoding='utf-8', errors='replace') as f:
                                    content = f.read(4000)
                                files[rel] = content
                                total += len(content)
                            except Exception:
                                pass
                            break
                    # Also check subdirectory modules (mod/something.py)
                    mod_dir = os.path.join(workspace_path, mod)
                    if os.path.isdir(mod_dir) and total < max_chars:
                        for fname in sorted(os.listdir(mod_dir)):
                            if total >= max_chars:
                                break
                            if fname.endswith('.py') and fname != '__init__.py':
                                fpath = os.path.join(mod_dir, fname)
                                rel = f'{mod}/{fname}'
                                if rel not in files:
                                    try:
                                        with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                                            content = f.read(4000)
                                        files[rel] = content
                                        total += len(content)
                                    except Exception:
                                        pass
            except (SyntaxError, Exception):
                pass  # Focus file may have syntax errors — skip import following

        # 3. Walk workspace for remaining files (2KB each)
        for root, dirs, fnames in os.walk(workspace_path):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for fname in sorted(fnames):
                if total >= max_chars:
                    break
                ext = os.path.splitext(fname)[1].lower()
                if ext not in SOURCE_EXTS:
                    continue
                fpath = os.path.join(root, fname)
                rel = os.path.relpath(fpath, workspace_path).replace('\\', '/')
                if rel in files:
                    continue
                try:
                    with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                        content = f.read(2000)
                    files[rel] = content
                    total += len(content)
                except Exception:
                    continue

        return files

    @staticmethod
    def _build_execution_user_message(error_output, file_contents, entry_point,
                                       project_listing, error_class,
                                       spec_context='', integrity_issues=None,
                                       failed_pip_packages=None):
        """Build the user message for the LLM diagnosis pass."""
        parts = []
        parts.append(f"## Error Output\n```\n{error_output[:3000]}\n```\n")
        parts.append(f"## Error Classification\n"
                     f"Type: {error_class.get('type', 'unknown')}\n"
                     f"Error: {error_class.get('errorType', 'Unknown')}\n"
                     f"File: {error_class.get('file', 'N/A')}\n"
                     f"Line: {error_class.get('line', 'N/A')}\n"
                     f"Message: {error_class.get('message', 'N/A')}\n")
        if failed_pip_packages:
            _pkg_list = ', '.join(sorted(failed_pip_packages))
            parts.append(
                f"## CRITICAL: These are NOT pip packages\n"
                f"pip install FAILED for: **{_pkg_list}**\n"
                f"These are LOCAL MODULES that need to be CREATED as .py files. "
                f"Do NOT try to install them. Create the files with the expected exports.\n"
            )
        if spec_context:
            parts.append(f"## Project Specification\n{spec_context}\n")
        if integrity_issues:
            issues_text = '\n'.join(f"- {i}" for i in integrity_issues[:10])
            parts.append(f"## Known Integrity Issues\n{issues_text}\n")
        parts.append(f"## Entry Point: {entry_point}\n")
        if project_listing:
            parts.append(f"## Project Files\n{project_listing[:2000]}\n")
        parts.append("## Source Code\n")
        for fpath, content in file_contents.items():
            parts.append(f"### `{fpath}`\n```\n{content}\n```\n")
        return '\n'.join(parts)

    @staticmethod
    def _load_sdd_artifacts_for_exec(workspace_path, task_id):
        """Load SDD artifacts for execution agent context.

        Returns a truncated string with requirements + spec summaries.
        Heavily truncated to fit 8192 token context window.
        """
        artifacts_dir = os.path.join(workspace_path, '.sentinel', 'tasks', task_id)
        parts = []
        budget = {'requirements.md': 1500, 'spec.md': 1000, 'implementation-plan.md': 800}
        for artifact_name, max_chars in budget.items():
            artifact_path = os.path.join(artifacts_dir, artifact_name)
            if os.path.isfile(artifact_path):
                try:
                    with open(artifact_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    if content.strip():
                        if len(content) > max_chars:
                            content = content[:max_chars] + '\n...(truncated)'
                        parts.append(f"### {artifact_name}\n{content}\n")
                except Exception:
                    pass
        return '\n'.join(parts) if parts else ''

    # ── Pre-execution helpers ──────────────────────────────────────

    @staticmethod
    def _pre_scan_and_fix(workspace_path):
        """Proactively scan ALL source files and fix common issues before running.

        Runs deterministic fixes on every file:
          - Stray diff markers (+/-)
          - Junk lines (*** End of File ***, merge markers, diff headers)
          - Syntax-check each .py file with compile()

        Returns list of {file, fix, lines} for every file touched.
        """
        SKIP = {'.venv', 'venv', '__pycache__', '.git', 'node_modules', '.sentinel'}
        SOURCE_EXTS = {'.py', '.js', '.ts', '.jsx', '.tsx', '.css', '.html', '.json',
                       '.yaml', '.yml', '.toml', '.cfg', '.sh', '.bat'}
        fixes = []

        for root, dirs, files in os.walk(workspace_path):
            dirs[:] = [d for d in dirs if d not in SKIP]
            for fname in files:
                ext = os.path.splitext(fname)[1].lower()
                if ext not in SOURCE_EXTS:
                    continue
                fpath = os.path.join(root, fname)
                rel = os.path.relpath(fpath, workspace_path).replace('\\', '/')

                # 1. Diff marker / junk line fix
                fixed = AgentService._fix_diff_markers(fpath)
                if fixed:
                    fixes.append({'file': rel, 'fix': 'diff_markers', 'lines': len(fixed)})

                # 2. Python syntax check (compile only)
                if ext == '.py':
                    try:
                        with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                            source = f.read()
                        compile(source, rel, 'exec')
                    except SyntaxError as e:
                        fixes.append({'file': rel, 'fix': 'syntax_error',
                                      'lines': 0, 'detail': f"line {e.lineno}: {e.msg}"})

        return fixes

    @staticmethod
    def _detect_missing_init_files(workspace_path):
        """Detect and create missing __init__.py files for Python packages.

        If a directory contains .py files and is imported as a package from
        other files but has no __init__.py, create an empty one.

        Returns list of created __init__.py paths (relative).
        """
        import ast as _ast
        SKIP = {'.venv', 'venv', '__pycache__', '.git', 'node_modules', '.sentinel'}
        created = []

        # 1. Collect all directories that contain .py files
        py_dirs = set()
        for root, dirs, files in os.walk(workspace_path):
            dirs[:] = [d for d in dirs if d not in SKIP]
            if any(f.endswith('.py') for f in files):
                rel = os.path.relpath(root, workspace_path).replace('\\', '/')
                if rel != '.':
                    py_dirs.add(rel)

        if not py_dirs:
            return created

        # 2. Scan imports to find which local dirs are referenced as packages
        imported_packages = set()
        for root, dirs, files in os.walk(workspace_path):
            dirs[:] = [d for d in dirs if d not in SKIP]
            for fname in files:
                if not fname.endswith('.py'):
                    continue
                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                        source = f.read()
                    tree = _ast.parse(source)
                    for node in _ast.walk(tree):
                        if isinstance(node, _ast.Import):
                            for alias in node.names:
                                imported_packages.add(alias.name.split('.')[0])
                        elif isinstance(node, _ast.ImportFrom) and node.module:
                            imported_packages.add(node.module.split('.')[0])
                except (SyntaxError, Exception):
                    continue

        # 3. For each py_dir that matches an imported package name,
        #    create __init__.py if missing
        for rel_dir in py_dirs:
            dir_name = rel_dir.split('/')[0]  # Top-level package name
            if dir_name not in imported_packages:
                continue
            # Check all levels of this package path
            parts = rel_dir.split('/')
            for i in range(len(parts)):
                sub_dir = '/'.join(parts[:i+1])
                init_path = os.path.join(workspace_path, sub_dir, '__init__.py')
                if not os.path.isfile(init_path):
                    try:
                        with open(init_path, 'w', encoding='utf-8') as f:
                            f.write('')
                        created.append(sub_dir + '/__init__.py')
                    except Exception:
                        pass

        return created

    @staticmethod
    def _scan_and_generate_requirements(workspace_path):
        """Scan all .py imports and generate/update requirements.txt.

        Uses AST parsing to find third-party imports, cross-references with
        stdlib and local modules, maps to pip package names.

        Returns list of newly added package names.
        """
        import ast as _ast
        from prompts.execution import PIP_NAME_MAP
        SKIP = {'.venv', 'venv', '__pycache__', '.git', 'node_modules', '.sentinel'}
        STDLIB = _PYTHON_STDLIB
        # Reverse of PIP_NAME_MAP: import_name → pip_name
        IMPORT_TO_PIP = {v.lower(): k for k, v in {
            'Pillow': 'PIL', 'opencv-python': 'cv2', 'scikit-learn': 'sklearn',
            'PyYAML': 'yaml', 'beautifulsoup4': 'bs4', 'python-dotenv': 'dotenv',
            'PyGObject': 'gi', 'attrs': 'attr', 'python-dateutil': 'dateutil',
            'pyserial': 'serial', 'pyusb': 'usb', 'wxPython': 'wx',
            'pycryptodome': 'Crypto', 'pyjwt': 'jwt', 'python-jose': 'jose',
            'psycopg2-binary': 'psycopg2',
        }.items()}

        # 1. Collect local module names — every directory and .py file at ALL levels
        #    so that `from auth import X` is recognized as local when auth/ is a subpackage.
        local_modules = set()
        for root, dirs, files in os.walk(workspace_path):
            dirs[:] = [d for d in dirs if d not in SKIP and not d.startswith('.')]
            rel_root = os.path.relpath(root, workspace_path).replace('\\', '/')
            # Add every directory name in the path as a potential local module
            if rel_root != '.':
                for part in rel_root.split('/'):
                    local_modules.add(part)
            for fname in files:
                if fname.endswith('.py'):
                    stem = fname[:-3]  # e.g. 'models' from 'models.py'
                    if stem and stem != '__init__':
                        local_modules.add(stem)

        # 2. Extract third-party imports via AST
        third_party = set()
        for root, dirs, files in os.walk(workspace_path):
            dirs[:] = [d for d in dirs if d not in SKIP and not d.startswith('.')]
            for fname in files:
                if not fname.endswith('.py'):
                    continue
                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                        source = f.read()
                    tree = _ast.parse(source)
                    for node in _ast.walk(tree):
                        if isinstance(node, _ast.Import):
                            for alias in node.names:
                                top = alias.name.split('.')[0]
                                if top not in STDLIB and top not in local_modules:
                                    third_party.add(top)
                        elif isinstance(node, _ast.ImportFrom) and node.module:
                            top = node.module.split('.')[0]
                            if top not in STDLIB and top not in local_modules:
                                third_party.add(top)
                except (SyntaxError, Exception):
                    continue

        # Filter out dev/test tools — they shouldn't be auto-added to requirements.txt
        third_party -= AgentService._DEV_TOOL_PACKAGES

        if not third_party:
            return []

        # 3. Map to pip names
        pip_packages = set()
        for imp in third_party:
            pip_name = IMPORT_TO_PIP.get(imp.lower(), imp)
            pip_packages.add(pip_name)

        # 4. Read existing requirements.txt
        req_path = os.path.join(workspace_path, 'requirements.txt')
        existing = set()
        if os.path.isfile(req_path):
            try:
                with open(req_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        s = line.strip()
                        if s and not s.startswith('#'):
                            pkg = re.split(r'[>=<!\[\];]', s)[0].strip().lower()
                            if pkg:
                                existing.add(pkg)
            except Exception:
                pass

        # 5. Add missing packages
        # Normalize for comparison (underscore/hyphen)
        def _norm(n):
            return n.lower().replace('-', '_')
        existing_norm = {_norm(p) for p in existing}
        added = []
        for pkg in sorted(pip_packages):
            if _norm(pkg) not in existing_norm:
                try:
                    with open(req_path, 'a', encoding='utf-8') as f:
                        f.write(f'{pkg}\n')
                    added.append(pkg)
                except Exception:
                    pass

        return added

    @staticmethod
    def _apply_corrective_fixes(workspace_path):
        """Apply all corrective fixes from error memory across workspace files.

        Scans workspace for files matching auto_fix patterns and applies
        regex_replace or line_remove corrections. Feeds results back to
        the error memory bandit.

        Returns: list of {path, description, changes} dicts
        """
        SKIP_DIRS = {'node_modules', 'venv', '.venv', '__pycache__', '.git', '.sentinel', 'dist', 'build'}
        MAX_FILES_PER_PATTERN = 50
        results = []

        try:
            all_fixes = ErrorMemory.get_corrective_fixes(on_write=False)
        except Exception:
            return results

        if not all_fixes:
            return results

        for entry, af in all_fixes:
            pattern = af.get('file_pattern', '')
            find_pat = af.get('find', '')
            fix_type = af.get('type', '')
            if not pattern or not find_pat or not fix_type:
                continue

            # Gather matching files
            matched_files = []
            if '*' in pattern or '?' in pattern:
                # Glob pattern -- walk workspace
                file_count = 0
                for root, dirs, files in os.walk(workspace_path):
                    dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                    for fname in files:
                        if fnmatch.fnmatch(fname, pattern):
                            matched_files.append(os.path.join(root, fname))
                            file_count += 1
                            if file_count >= MAX_FILES_PER_PATTERN:
                                break
                    if file_count >= MAX_FILES_PER_PATTERN:
                        break
            else:
                # Literal filename
                literal = os.path.join(workspace_path, pattern)
                if os.path.isfile(literal):
                    matched_files.append(literal)

            # Apply fix to each matched file
            for fpath in matched_files:
                try:
                    with open(fpath, 'r', encoding='utf-8') as f:
                        content = f.read()
                except (OSError, UnicodeDecodeError):
                    continue

                original = content

                try:
                    if fix_type == 'regex_replace':
                        replace_map = af.get('replace_map')
                        if replace_map:
                            def _char_replacer(m):
                                ch = m.group(0)
                                return replace_map.get(ch, ch)
                            content = re.sub(find_pat, _char_replacer, content)
                        else:
                            replace_str = af.get('replace', '')
                            content = re.sub(find_pat, replace_str, content)

                    elif fix_type == 'line_remove':
                        line_re = re.compile(find_pat)
                        lines = content.splitlines(True)
                        content = ''.join(line for line in lines if not line_re.match(line.strip()))

                except re.error:
                    continue

                if content != original:
                    try:
                        with open(fpath, 'w', encoding='utf-8') as f:
                            f.write(content)
                    except OSError:
                        continue

                    rel_path = os.path.relpath(fpath, workspace_path).replace('\\', '/')
                    desc = af.get('description', 'Corrective fix applied')
                    results.append({
                        'path': rel_path,
                        'description': desc,
                        'changes': 1,
                    })

                    # Record to bandit
                    try:
                        ErrorMemory.record_auto_fix(entry.get('id', ''), success=True)
                    except Exception:
                        pass

        return results

    @staticmethod
    def _fix_corrupted_files(workspace_path, integrity_result, spec_context, cancel_event):
        """Phase 0f: Detect and rewrite truncated/escape-corrupted source files.

        For each file with a syntax error, checks whether the file is corrupted
        (escape artifacts like backslash-quote) or truncated (ends mid-statement).
        If so, calls the LLM with a focused rewrite prompt to regenerate the file
        using the project spec and healthy sibling files as context.

        Yields SSE event strings.  Caller should ``yield from`` this generator.
        """
        import ast as _ast

        issues = integrity_result.get('issues', [])
        py_files = integrity_result.get('py_files', {})
        defined_names = integrity_result.get('defined_names', {})
        import_graph = integrity_result.get('import_graph', {})

        # Collect files that have syntax/compilation errors
        error_files = set()
        for issue in issues:
            for prefix in ('Syntax error in ', 'Compilation error in '):
                if issue.startswith(prefix):
                    rest = issue[len(prefix):]
                    rel = rest.split(' ')[0].split(':')[0]
                    error_files.add(rel)

        if not error_files:
            return

        def _is_corrupted(content):
            """Check for escape-corruption indicators."""
            if not content:
                return True
            if content[0] == '\\':
                return True
            if content[:2] in ('\\"', "\\'"):
                return True
            if content.count('\\"') > 5:
                return True
            return False

        def _is_truncated(content):
            """Check for truncation indicators."""
            if not content or len(content.strip()) < 30:
                return True
            tail = content.rstrip()
            if tail and tail[-1] in '({[,=':
                return True
            # More function defs than bodies suggests truncation
            defs = content.count('def ')
            bodies = (content.count('\n    return ') +
                      content.count('\n    pass') +
                      content.count('\n    raise ') +
                      content.count('\n    yield '))
            if defs > 2 and bodies < defs // 2:
                return True
            return False

        # Find which names other files expect from the corrupted file
        def _expected_names_for(rel_path):
            """Return names that other modules import from this file."""
            module = rel_path.replace('/', '.').replace('.py', '')
            if module.endswith('.__init__'):
                module = module[:-9]
            expected = set()
            for other_rel, source in py_files.items():
                if other_rel == rel_path:
                    continue
                try:
                    tree = _ast.parse(source)
                except Exception:
                    continue
                for node in _ast.walk(tree):
                    if isinstance(node, _ast.ImportFrom) and node.module:
                        imp_mod = node.module.split('.')[0]
                        if imp_mod == module.split('.')[0]:
                            for alias in (node.names or []):
                                expected.add(alias.name)
                    elif isinstance(node, _ast.Import):
                        for alias in node.names:
                            if alias.name.split('.')[0] == module.split('.')[0]:
                                expected.add(alias.name)
            return sorted(expected)

        # Gather healthy related files for context
        def _related_files(rel_path):
            """Return dict of {rel_path: content} for sibling modules."""
            related = {}
            budget = 16000
            for other_rel, source in sorted(py_files.items()):
                if other_rel == rel_path or other_rel in error_files:
                    continue
                if budget <= 0:
                    break
                chunk = source[:4000]
                related[other_rel] = chunk
                budget -= len(chunk)
            return related

        from prompts.execution import build_rewrite_prompt

        for rel in sorted(error_files):
            abs_path = os.path.join(workspace_path, rel.replace('/', os.sep))
            if not os.path.isfile(abs_path):
                continue

            try:
                with open(abs_path, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
            except Exception:
                continue

            # Only trigger LLM rewrite for corruption/truncation, not simple syntax errors
            if not _is_corrupted(content) and not _is_truncated(content):
                continue

            reason = 'corrupted' if _is_corrupted(content) else 'truncated'
            yield f"event: exec_status\ndata: {json.dumps({'status': f'Rewriting {reason} file: {rel}'})}\n\n"

            expected = _expected_names_for(rel)
            related = _related_files(rel)

            system_prompt = build_rewrite_prompt(
                os_name=platform.system(),
                spec_context=spec_context,
                expected_names=expected,
                related_files=related,
            )
            user_msg = (
                f"## File to Rewrite: `{rel}`\n\n"
                f"This file is **{reason}** and cannot be parsed.\n\n"
            )
            if expected:
                user_msg += f"Other modules expect these names: {', '.join(expected)}\n\n"
            if content.strip():
                preview = content[:2000]
                user_msg += f"## Current (broken) content:\n```\n{preview}\n```\n\n"
            user_msg += (
                f"Rewrite `{rel}` completely using WriteFile. "
                "Implement real logic matching the project spec and related files."
            )

            # Snapshot this one file for potential revert
            snapshot_content = content

            llm_history = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ]

            try:
                llm = get_llm_engine()
                ts = ToolService(workspace_path, workspace_path=workspace_path)
                pass_results = {'text': '', 'edits': []}

                for event_str in AgentService._run_review_pass(
                    llm, llm_history, ts, cancel_event, pass_results,
                    max_turns=1, max_tokens=4096, timeout_seconds=120,
                    event_prefix='exec',
                    allowed_tools={'WriteFile', 'ReadFile'},
                ):
                    yield event_str

                # Verify the rewritten file parses
                if os.path.isfile(abs_path):
                    with open(abs_path, 'r', encoding='utf-8', errors='replace') as f:
                        new_content = f.read()
                    try:
                        _ast.parse(new_content, rel)
                        yield f"event: exec_fix\ndata: {json.dumps({'path': rel, 'tool': 'FileRewrite', 'result': f'Rewrote {reason} file ({len(new_content)} bytes)'})}\n\n"
                    except SyntaxError:
                        # LLM rewrite still broken -- revert
                        with open(abs_path, 'w', encoding='utf-8') as f:
                            f.write(snapshot_content)
                        yield f"event: exec_status\ndata: {json.dumps({'status': f'Rewrite of {rel} still has syntax errors, reverted'})}\n\n"

            except Exception as e:
                _safe_log(f"[Execution Agent] Corrupted file rewrite error for {rel}: {e}")

    @staticmethod
    def _fix_missing_stdlib_imports(workspace_path, integrity_result):
        """Phase 0g: Auto-insert missing stdlib imports.

        Scans each .py file's AST for references to stdlib module names
        (like ``datetime.date``) that are used but not imported. Inserts
        ``import <module>`` after the last existing import line.

        Returns list of ``{path, module}`` dicts for files that were fixed.
        """
        import ast as _ast

        SAFE_STDLIB = {
            'datetime', 'os', 'sys', 'json', 're', 'pathlib', 'collections',
            'typing', 'functools', 'itertools', 'math', 'csv', 'io', 'shutil',
            'subprocess', 'tempfile', 'logging', 'hashlib', 'uuid', 'copy',
            'time', 'random', 'textwrap', 'enum', 'abc', 'dataclasses',
            'contextlib', 'string', 'struct', 'decimal', 'fractions',
            'statistics', 'operator', 'glob', 'fnmatch', 'sqlite3',
            'urllib', 'http', 'html', 'xml', 'email', 'base64',
            'codecs', 'pprint', 'traceback', 'warnings', 'threading',
            'multiprocessing', 'socket', 'ssl', 'select', 'signal',
            'argparse', 'configparser', 'platform',
        }

        py_files = integrity_result.get('py_files', {})
        fixes = []

        for rel, source in py_files.items():
            try:
                tree = _ast.parse(source, rel)
            except SyntaxError:
                continue

            # Collect already-imported module names
            imported = set()
            last_import_line = 0
            for node in _ast.iter_child_nodes(tree):
                if isinstance(node, _ast.Import):
                    for alias in node.names:
                        imported.add(alias.name.split('.')[0])
                    last_import_line = max(last_import_line, node.end_lineno or node.lineno)
                elif isinstance(node, _ast.ImportFrom):
                    if node.module:
                        imported.add(node.module.split('.')[0])
                    last_import_line = max(last_import_line, node.end_lineno or node.lineno)

            # Walk AST for attribute access like datetime.date, os.path, etc.
            used_modules = set()
            for node in _ast.walk(tree):
                if isinstance(node, _ast.Attribute) and isinstance(node.value, _ast.Name):
                    name = node.value.id
                    if name in SAFE_STDLIB and name not in imported:
                        used_modules.add(name)

            if not used_modules:
                continue

            # Insert missing imports
            lines = source.splitlines(True)  # keep line endings
            insert_idx = last_import_line  # 0-based: insert after last import line
            new_imports = sorted(used_modules)
            import_block = ''.join(f'import {m}\n' for m in new_imports)

            new_lines = lines[:insert_idx] + [import_block] + lines[insert_idx:]
            new_source = ''.join(new_lines)

            # Verify it still parses
            try:
                compile(new_source, rel, 'exec')
            except SyntaxError:
                continue

            abs_path = os.path.join(workspace_path, rel.replace('/', os.sep))
            try:
                with open(abs_path, 'w', encoding='utf-8') as f:
                    f.write(new_source)
                for m in new_imports:
                    fixes.append({'path': rel, 'module': m})
            except Exception:
                pass

        return fixes

    @staticmethod
    def _fix_cross_module_imports(workspace_path, integrity_result):
        """Phase 0h: Fix imports that reference names in the wrong module.

        For each ``from X import Y`` where Y is not defined in module X,
        searches all other local modules. If Y is found in exactly one
        other module M, rewrites the import to ``from M import Y``.

        Returns list of ``{path, old_import, new_import}`` dicts.
        """
        import ast as _ast

        defined_names = integrity_result.get('defined_names', {})
        py_files = integrity_result.get('py_files', {})
        fixes = []

        # Build reverse lookup: name -> list of modules that define it
        name_to_modules = {}
        for mod, names in defined_names.items():
            for name in names:
                name_to_modules.setdefault(name, []).append(mod)

        for rel, source in py_files.items():
            try:
                tree = _ast.parse(source, rel)
            except SyntaxError:
                continue

            current_module = rel.replace('/', '.').replace('.py', '')
            if current_module.endswith('.__init__'):
                current_module = current_module[:-9]

            rewrites = []  # list of (old_line, new_line)
            lines = source.splitlines()

            for node in _ast.iter_child_nodes(tree):
                if not isinstance(node, _ast.ImportFrom) or not node.module:
                    continue

                source_mod = node.module.split('.')[0]

                # Check if source module is a local module
                if source_mod not in defined_names:
                    continue

                source_defs = defined_names.get(source_mod, set())
                misplaced = []
                correct = []

                for alias in (node.names or []):
                    name = alias.name
                    if name == '*':
                        correct.append(alias)
                        continue
                    if name in source_defs:
                        correct.append(alias)
                    else:
                        # Search for the correct module
                        candidates = name_to_modules.get(name, [])
                        # Filter out current module and the wrong source
                        candidates = [m for m in candidates if m != current_module]
                        if len(candidates) == 1:
                            misplaced.append((alias, candidates[0]))
                        else:
                            # Ambiguous or not found -- keep as-is
                            correct.append(alias)

                if not misplaced:
                    continue

                # Build the replacement lines
                line_no = node.lineno  # 1-based
                # Get the original line(s) for this import
                old_line = lines[line_no - 1] if line_no <= len(lines) else ''

                # Group misplaced names by target module
                target_groups = {}
                for alias, target_mod in misplaced:
                    target_groups.setdefault(target_mod, []).append(alias.name)

                # Build new import lines
                new_lines = []
                if correct:
                    # Keep the original import with only the correct names
                    correct_names = ', '.join(a.name for a in correct)
                    new_lines.append(f'from {node.module} import {correct_names}')
                for target_mod, names in sorted(target_groups.items()):
                    new_lines.append(f'from {target_mod} import {", ".join(names)}')

                new_text = '\n'.join(new_lines)
                rewrites.append((line_no, old_line, new_text, misplaced))

            if not rewrites:
                continue

            # Apply rewrites (in reverse line order to preserve line numbers)
            new_lines = lines[:]
            for line_no, old_line, new_text, misplaced in sorted(rewrites, reverse=True):
                idx = line_no - 1
                new_lines[idx] = new_text

            new_source = '\n'.join(new_lines)
            if not new_source.endswith('\n'):
                new_source += '\n'

            # Verify it parses
            try:
                compile(new_source, rel, 'exec')
            except SyntaxError:
                continue

            abs_path = os.path.join(workspace_path, rel.replace('/', os.sep))
            try:
                with open(abs_path, 'w', encoding='utf-8') as f:
                    f.write(new_source)
                for line_no, old_line, new_text, misplaced in rewrites:
                    for alias, target_mod in misplaced:
                        fixes.append({
                            'path': rel,
                            'old_import': f'from {old_line.strip().split(" import ")[0].split("from ")[-1] if " import " in old_line else "?"} import {alias.name}',
                            'new_import': f'from {target_mod} import {alias.name}',
                        })
            except Exception:
                pass

        return fixes

    @staticmethod
    def _run_recoder_agent(workspace_path, entry_point, command, is_server,
                           exec_history, all_fixes, spec_context,
                           integrity_issues, cancel_event,
                           failed_pip_packages=None):
        """Recoder Agent — holistic project rewriter (Phase 3.5).

        Called when Phase 3 (diagnose loop) exhausts MAX_ATTEMPTS without success.
        Reads ALL project files + ALL error history and rewrites broken files.

        This is a generator yielding SSE event strings.
        The caller must iterate and forward events, then check the last yielded
        dict for success status.

        Yields SSE event strings, and as final yield: a dict {'success': bool}.
        """
        from prompts.execution import build_recoder_prompt

        os_name = platform.system()
        _safe_log("[Recoder Agent] Starting holistic project rewrite")

        # 1. Snapshot for revert if recoder makes things worse
        snapshot = AgentService._snapshot_project_files(workspace_path)

        yield f"event: exec_status\ndata: {json.dumps({'status': 'Recoder Agent: Reading all project files and error history...'})}\n\n"

        # 2. Read ALL project source files (up to 60KB total)
        SKIP_DIRS = {'.git', '__pycache__', 'node_modules', '.venv', 'venv', '.sentinel'}
        SOURCE_EXTS = {'.py', '.txt', '.json', '.yaml', '.yml', '.toml', '.cfg'}
        all_sources = {}
        total_chars = 0
        MAX_CHARS = 60000
        for root, dirs, files in os.walk(workspace_path):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for fname in sorted(files):
                ext = os.path.splitext(fname)[1].lower()
                if ext not in SOURCE_EXTS:
                    continue
                abs_p = os.path.join(root, fname)
                rel_p = os.path.relpath(abs_p, workspace_path).replace('\\', '/')
                try:
                    with open(abs_p, 'r', encoding='utf-8', errors='replace') as f:
                        content = f.read(8000)
                    all_sources[rel_p] = content
                    total_chars += len(content)
                    if total_chars > MAX_CHARS:
                        break
                except Exception:
                    pass
            if total_chars > MAX_CHARS:
                break

        # 3. Build comprehensive error history from exec_history
        error_history_parts = []
        for i, entry in enumerate(exec_history, 1):
            error_str = entry.get('error', entry.get('error_type', 'unknown'))
            fixes = entry.get('fixes', [])
            reverted = entry.get('reverted', False)
            success = entry.get('success', False)
            error_history_parts.append(
                f"Attempt {i}: Error={error_str}"
                + (f" | Fixes={', '.join(str(f) for f in fixes[:3])}" if fixes else '')
                + (' [REVERTED]' if reverted else '')
                + (' [SUCCESS]' if success else ' [FAILED]')
            )
        error_history_str = '\n'.join(error_history_parts)

        # 4. Build fix history from all_fixes
        fix_history_parts = []
        for af in all_fixes:
            fix_history_parts.append(f"- [{af.get('tool', '?')}] {af.get('path', '?')}: {af.get('result', '')}")
        fix_history_str = '\n'.join(fix_history_parts[:20])

        # 5. Build the recoder system prompt
        system_prompt = build_recoder_prompt(
            os_name=os_name,
            spec_context=spec_context,
            error_history=error_history_str,
            fix_history=fix_history_str,
            integrity_issues=integrity_issues,
        )

        # 6. Build user message with ALL source files
        file_sections = []
        for rel_p, content in sorted(all_sources.items()):
            truncated = content[:6000] if len(content) > 6000 else content
            file_sections.append(f"### `{rel_p}`\n```\n{truncated}\n```")
        files_text = '\n\n'.join(file_sections)

        # Include last error output from exec_history
        last_error_output = ''
        for entry in reversed(exec_history):
            if entry.get('error_output'):
                last_error_output = entry['error_output'][:3000]
                break

        # Include failed pip packages so recoder knows to create local modules
        _failed_pkg_note = ''
        if failed_pip_packages:
            _pkg_list = ', '.join(sorted(failed_pip_packages))
            _failed_pkg_note = (
                f"\n\n## IMPORTANT: These are NOT pip packages\n"
                f"The following imports failed pip install — they are LOCAL MODULES that need to be CREATED:\n"
                f"**{_pkg_list}**\n"
                f"Do NOT try to pip install these. Instead, create the .py files for them with "
                f"the functions/classes that other files expect to import.\n"
            )

        user_msg = (
            f"## Project Files ({len(all_sources)} files)\n\n"
            f"{files_text}\n\n"
            f"## Latest Error Output\n```\n{last_error_output}\n```\n\n"
            f"{_failed_pkg_note}\n\n"
            f"Fix this project so it runs. Rewrite broken files using WriteFile. "
            f"Say DONE when finished."
        )

        # 7. Set up LLM session
        history = [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_msg},
        ]

        try:
            llm = get_llm_engine()
        except Exception as e:
            _safe_log(f"[Recoder Agent] LLM init error: {e}")
            yield {'success': False}
            return

        tool_service = ToolService(workspace_path, workspace_path=workspace_path)
        results = {}

        yield f"event: exec_status\ndata: {json.dumps({'status': 'Recoder Agent: Rewriting broken files...'})}\n\n"

        # 8. Run multi-turn LLM session
        for event_str in AgentService._run_review_pass(
            llm, history, tool_service, cancel_event, results,
            max_turns=8, max_tokens=4096, timeout_seconds=180,
            event_prefix='exec',
            allowed_tools={'WriteFile', 'EditFile', 'ReadFile', 'RunCommand'},
        ):
            yield event_str

        edits = results.get('edits', [])
        if edits:
            yield f"event: exec_status\ndata: {json.dumps({'status': f'Recoder Agent: Applied {len(edits)} file changes'})}\n\n"
            for edit in edits:
                _path = edit if isinstance(edit, str) else edit.get('path', '?')
                yield f"event: exec_fix\ndata: {json.dumps({'path': _path, 'tool': 'Recoder', 'result': 'Rewritten by Recoder Agent'})}\n\n"
        else:
            _safe_log("[Recoder Agent] No edits produced")
            yield f"event: exec_status\ndata: {json.dumps({'status': 'Recoder Agent: No changes made'})}\n\n"
            yield {'success': False}
            return

        # 9. Re-run the project to validate
        yield f"event: exec_status\ndata: {json.dumps({'status': 'Recoder Agent: Validating — re-running project...'})}\n\n"

        # Re-detect entry point (recoder may have changed file structure)
        from utils.entry_point import detect_entry_point
        new_entry_info = detect_entry_point(workspace_path)
        if new_entry_info.get('entryPoint'):
            run_cmd = new_entry_info.get('command', f'python {new_entry_info["entryPoint"]}')
            run_server = new_entry_info.get('isServer', False)
        else:
            run_cmd = command
            run_server = is_server

        timeout = 10 if run_server else 30
        exit_code, stdout, stderr = AgentService._run_project_subprocess(run_cmd, workspace_path, timeout=timeout)

        combined = (stdout + stderr).strip()
        for line in combined.splitlines()[:50]:
            yield f"event: exec_output\ndata: {json.dumps({'line': line[:2000]})}\n\n"

        # 10. Validate result
        success = False
        if exit_code == 0:
            is_valid, val_reason = AgentService._validate_execution_output(
                exit_code, stdout, stderr, new_entry_info, workspace_path
            )
            if is_valid:
                success = True
                yield f"event: exec_status\ndata: {json.dumps({'status': 'Recoder Agent: Project runs successfully!'})}\n\n"
        elif exit_code == -1 and 'timed out' in stderr.lower() and (
            run_server
            or 'Serving Flask app' in (stdout + stderr)
            or 'Running on http' in (stdout + stderr)
            or 'Uvicorn running on' in (stdout + stderr)
            or 'Starting development server' in (stdout + stderr)
            or 'Listening on' in (stdout + stderr)
            or re.search(r'(?:server|app)\s+(?:running|started|listening)\s+(?:on|at)', (stdout + stderr), re.IGNORECASE)
        ):
            success = True
            yield f"event: exec_status\ndata: {json.dumps({'status': 'Recoder Agent: Server started successfully!'})}\n\n"

        if not success:
            # Check if error count got worse — if so, revert
            new_error_count = AgentService._count_errors_in_output(stderr if stderr.strip() else stdout)
            # Get pre-recoder error count from last exec_history entry
            old_error_output = last_error_output
            old_error_count = AgentService._count_errors_in_output(old_error_output)

            if new_error_count > old_error_count:
                _safe_log(f"[Recoder Agent] Error count increased ({old_error_count} -> {new_error_count}). Reverting.")
                restored = AgentService._restore_snapshot(workspace_path, snapshot)
                yield f"event: exec_status\ndata: {json.dumps({'status': f'Recoder Agent: Made things worse ({old_error_count} -> {new_error_count} errors). Reverted {restored} files.'})}\n\n"
            else:
                yield f"event: exec_status\ndata: {json.dumps({'status': f'Recoder Agent: Still failing (exit code {exit_code}). Keeping changes.'})}\n\n"

        yield {'success': success}

    @staticmethod
    def _snapshot_project_files(workspace_path):
        """Take a lightweight snapshot of all source files for revert.

        Returns dict {rel_path: content_string} for all text source files.
        Used by smarter retry logic to revert if LLM makes things worse.
        """
        SKIP = {'.venv', 'venv', '__pycache__', '.git', 'node_modules', '.sentinel'}
        SOURCE_EXTS = {'.py', '.js', '.ts', '.jsx', '.tsx', '.html', '.css',
                       '.json', '.yaml', '.yml', '.toml', '.cfg', '.ini',
                       '.txt', '.md', '.sh', '.bat', '.sql'}
        snapshot = {}
        for root, dirs, files in os.walk(workspace_path):
            dirs[:] = [d for d in dirs if d not in SKIP]
            for fname in files:
                ext = os.path.splitext(fname)[1].lower()
                if ext not in SOURCE_EXTS:
                    continue
                fpath = os.path.join(root, fname)
                rel = os.path.relpath(fpath, workspace_path).replace('\\', '/')
                try:
                    with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                        snapshot[rel] = f.read()
                except Exception:
                    pass
        return snapshot

    @staticmethod
    def _restore_snapshot(workspace_path, snapshot):
        """Restore files from a snapshot dict. Returns count of files restored."""
        restored = 0
        for rel, content in snapshot.items():
            fpath = os.path.join(workspace_path, rel.replace('/', os.sep))
            try:
                with open(fpath, 'w', encoding='utf-8') as f:
                    f.write(content)
                restored += 1
            except Exception:
                pass
        return restored

    @staticmethod
    def _count_errors_in_output(output):
        """Count distinct error indicators in program output.

        Used to compare before/after LLM fix — if error count went up, revert.
        """
        if not output:
            return 0
        count = 0
        error_patterns = [
            r'Error:', r'Exception:', r'Traceback \(most recent',
            r'SyntaxError:', r'NameError:', r'TypeError:',
            r'ImportError:', r'ModuleNotFoundError:', r'ValueError:',
            r'AttributeError:', r'KeyError:', r'IndexError:',
            r'FileNotFoundError:', r'IndentationError:',
        ]
        for pat in error_patterns:
            count += len(re.findall(pat, output))
        return count

    @staticmethod
    def _validate_execution_output(exit_code, stdout, stderr, entry_info, workspace_path):
        """Validate execution output beyond just exit code.

        Catches false-positive successes: exit code 0 but project is broken.
        Returns (is_valid: bool, reason: str).
        """
        if exit_code != 0:
            return False, f'Non-zero exit code: {exit_code}'

        combined = (stdout + stderr).strip()

        # Server mode — timeout success handled upstream
        if entry_info.get('isServer'):
            return True, 'Server mode'

        # CLI with argparse — exit code 2 handled upstream
        if entry_info.get('hasArgparse'):
            return True, 'CLI loaded OK'

        # Script with print() calls but no output → likely broken
        if not stdout.strip() and not stderr.strip():
            entry_path = os.path.join(workspace_path, entry_info.get('entryPoint', ''))
            if os.path.isfile(entry_path):
                try:
                    with open(entry_path, 'r', encoding='utf-8', errors='replace') as f:
                        source = f.read(4000)
                    if 'print(' in source or 'sys.stdout' in source or 'logging.' in source:
                        return False, 'Script has print()/logging calls but produced no output'
                except Exception:
                    pass

        # Check for error indicators in output despite exit code 0
        error_count = AgentService._count_errors_in_output(combined)
        if error_count >= 3:
            return False, f'Exit code 0 but {error_count} error indicators in output'

        return True, 'OK'

    # ── Persistent error history ───────────────────────────────────

    @staticmethod
    def _load_exec_history(workspace_path, task_id):
        """Load execution history from disk. Returns list of attempt records."""
        hist_path = os.path.join(workspace_path, '.sentinel', 'tasks', task_id, 'exec-history.json')
        if os.path.isfile(hist_path):
            try:
                with open(hist_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    @staticmethod
    def _save_exec_history(workspace_path, task_id, history):
        """Save execution history to disk (last 20 entries max)."""
        hist_dir = os.path.join(workspace_path, '.sentinel', 'tasks', task_id)
        os.makedirs(hist_dir, exist_ok=True)
        try:
            with open(os.path.join(hist_dir, 'exec-history.json'), 'w', encoding='utf-8') as f:
                json.dump(history[-20:], f, indent=2)
        except Exception:
            pass

    @staticmethod
    def _build_history_context(exec_history):
        """Build a compact string summarizing past attempts for LLM context."""
        if not exec_history:
            return ''
        lines = ['## Previous Fix Attempts']
        for entry in exec_history[-5:]:
            # History entries use keys: error, fixes (list of path strings),
            # success (bool), reverted (bool, optional)
            error_sig = entry.get('error', entry.get('error_type', 'unknown'))
            fixes = entry.get('fixes', [])
            was_success = entry.get('success', False)
            was_reverted = entry.get('reverted', False)
            if was_reverted:
                outcome = 'reverted (made things worse)'
            elif was_success:
                outcome = 'success'
            else:
                outcome = entry.get('outcome', 'failed')
            # fixes can be list of strings or list of dicts
            if fixes and isinstance(fixes[0], dict):
                fix_desc = ', '.join(
                    (f.get('tool', '?') + ' ' + f.get('path', '?')) for f in fixes[:3]
                )
            elif fixes:
                fix_desc = ', '.join(str(f) for f in fixes[:3])
            else:
                fix_desc = 'no fixes applied'
            lines.append(f'- {error_sig}: {fix_desc} -> {outcome}')
        return '\n'.join(lines) + '\n'

    @staticmethod
    def _write_execution_log(workspace_path, task_id, success, attempts, fixes, final_output, warnings=None):
        """Persist execution summary for review agent and main agent consumption.

        The `warnings` list captures non-fatal issues like dependency install
        failures, version pin fixes, or import validation results so downstream
        agents (review, main agent) can reason about them.
        """
        log_dir = os.path.join(workspace_path, '.sentinel', 'tasks', task_id)
        os.makedirs(log_dir, exist_ok=True)
        try:
            log_data = {
                'timestamp': datetime.now().isoformat(),
                'success': success,
                'attempts': attempts,
                'fixes': [{'path': f.get('path', ''), 'tool': f.get('tool', '')} if isinstance(f, dict) else {'path': str(f), 'tool': ''} for f in fixes[:20]],
                'final_output': (final_output or '')[:2000],
                'warnings': (warnings or [])[:20],
            }
            with open(os.path.join(log_dir, 'execution.log'), 'w', encoding='utf-8') as f:
                json.dump(log_data, f, indent=2)
        except Exception:
            pass

    @staticmethod
    def run_execution_stream(task_id, cancel_event=None):
        """Run the execution agent: execute project, diagnose errors, fix, retry.

        Enhanced pipeline:
          Phase 0: Pre-scan — proactively fix diff markers, junk lines, __init__.py,
                   generate requirements.txt from imports
          Phase 1: Detect entry point
          Phase 2: Install dependencies
          Phase 3: Execute → Diagnose → Fix loop (deterministic first, LLM fallback)
                   With snapshot/revert if LLM makes things worse

        Generator yielding SSE event strings:
          exec_status, exec_output, exec_run, exec_diagnosis,
          exec_token, exec_fix, exec_done, exec_error, exec_files_changed,
          exec_integrity, exec_validate
        """
        import platform
        from utils.entry_point import detect_entry_point, _validate_imports
        from prompts.execution import build_diagnose_prompt, build_dependency_prompt, build_recoder_prompt, PIP_NAME_MAP

        MAX_ATTEMPTS = 5
        MAX_LLM_TURNS = 3

        def _fix_path(f):
            """Safely extract path from a fix entry (dict or string)."""
            return f.get('path', '') if isinstance(f, dict) else str(f)

        try:
            task = TaskService.get_task(task_id)
            if not task:
                yield f"event: exec_error\ndata: {json.dumps({'error': 'Task not found'})}\n\n"
                return
            workspace_path = task.get('workspacePath')
            if not workspace_path or not os.path.isdir(workspace_path):
                yield f"event: exec_error\ndata: {json.dumps({'error': 'Workspace not found'})}\n\n"
                return

            all_fixes = []
            exec_warnings = []  # Non-fatal warnings for downstream agents (review, main)
            files_changed = False  # Track whether we need to refresh file tree

            # ── Compute fingerprint once for all error-memory calls ──
            _exec_complexity = task.get('settings', {}).get('complexity', 5)
            exec_fingerprint = ErrorMemory.compute_fingerprint(
                workspace_path, step_type='execution', complexity=_exec_complexity
            )

            # ── LLM Activity Logger for execution agent ──
            exec_log = LLMLogger(task_id)
            exec_log.step_start('Execution Agent', 'execution')

            # ── Load context for smarter diagnosis ─────────────────
            # SDD artifacts (requirements, spec, plan)
            spec_context = AgentService._load_sdd_artifacts_for_exec(workspace_path, task_id)
            if spec_context:
                _safe_log(f"[Execution Agent] Loaded SDD artifacts ({len(spec_context)} chars)")

            # Error history from previous runs
            exec_history = AgentService._load_exec_history(workspace_path, task_id)
            history_context = AgentService._build_history_context(exec_history)
            if history_context:
                _safe_log(f"[Execution Agent] Loaded {len(exec_history)} previous attempts")

            # Review issues from review agent handoff
            integrity_issues = []
            try:
                review_issues_path = os.path.join(
                    workspace_path, '.sentinel', 'tasks', task_id, 'review-issues.json'
                )
                if os.path.isfile(review_issues_path):
                    with open(review_issues_path, 'r', encoding='utf-8') as f:
                        review_data = json.load(f)
                    integrity_issues = review_data.get('issues', [])
                    if integrity_issues:
                        _safe_log(f"[Execution Agent] Loaded {len(integrity_issues)} review issues")
            except Exception:
                pass

            # ── Phase 0: Pre-scan and proactive fixes ──────────────
            # Helper: bail early if cancelled
            def _cancelled():
                return cancel_event and cancel_event.is_set()

            yield f"event: exec_status\ndata: {json.dumps({'status': 'Pre-scanning project files...'})}\n\n"

            # 0-pre. Detect and fix shadowing files (e.g. flask.py shadowing pip's flask)
            try:
                shadow_fixes = AgentService._detect_shadowing_files(workspace_path)
                for sf in shadow_fixes:
                    msg = f"{sf['file']} renamed to {sf['renamed_to']} (was shadowing pip package)"
                    yield f"event: exec_fix\ndata: {json.dumps({'path': sf['file'], 'tool': 'ShadowFix', 'result': msg})}\n\n"
                    all_fixes.append({'path': sf['file'], 'tool': 'ShadowFix', 'result': msg})
                    if sf.get('updated_imports'):
                        imports_msg = 'Updated imports in: ' + ', '.join(sf['updated_imports'])
                        yield f"event: exec_status\ndata: {json.dumps({'status': imports_msg})}\n\n"
                    files_changed = True
                    exec_warnings.append(f"ShadowFix: {msg}")
            except Exception as e:
                _safe_log(f"[Execution Agent] Shadow detection error: {e}")

            # 0a. Scan all source files for diff markers / junk / syntax issues
            pre_fixes = AgentService._pre_scan_and_fix(workspace_path)
            for pf in pre_fixes:
                pf_file = pf['file']
                pf_lines = pf.get('lines', 0)
                pf_detail = pf.get('detail', '')
                if pf['fix'] == 'diff_markers':
                    msg = f'Cleaned {pf_lines} stray diff markers'
                    yield f"event: exec_fix\ndata: {json.dumps({'path': pf_file, 'tool': 'PreScan', 'result': msg})}\n\n"
                    all_fixes.append({'path': pf_file, 'tool': 'PreScan', 'result': msg})
                    files_changed = True
                elif pf['fix'] == 'syntax_error':
                    status_msg = f'Syntax issue in {pf_file}: {pf_detail}'
                    yield f"event: exec_status\ndata: {json.dumps({'status': status_msg})}\n\n"

            # 0b. Detect and create missing __init__.py files
            if _cancelled():
                yield f"event: exec_done\ndata: {json.dumps({'success': False, 'attempts': 0, 'fixes': [], 'output': 'Cancelled during pre-scan'})}\n\n"
                return
            created_inits = AgentService._detect_missing_init_files(workspace_path)
            for init_path in created_inits:
                yield f"event: exec_fix\ndata: {json.dumps({'path': init_path, 'tool': 'InitCreate', 'result': 'Created missing __init__.py'})}\n\n"
                all_fixes.append({'path': init_path, 'tool': 'InitCreate', 'result': 'created'})
                files_changed = True

            # 0c. Scan imports and generate/update requirements.txt
            if _cancelled():
                yield f"event: exec_done\ndata: {json.dumps({'success': False, 'attempts': 0, 'fixes': [], 'output': 'Cancelled during pre-scan'})}\n\n"
                return
            added_pkgs = AgentService._scan_and_generate_requirements(workspace_path)
            if added_pkgs:
                pkgs_str = ', '.join(added_pkgs)
                yield f"event: exec_status\ndata: {json.dumps({'status': 'Added to requirements.txt: ' + pkgs_str})}\n\n"
                yield f"event: exec_fix\ndata: {json.dumps({'path': 'requirements.txt', 'tool': 'RequirementsScan', 'result': 'Added: ' + pkgs_str})}\n\n"
                all_fixes.append({'path': 'requirements.txt', 'tool': 'RequirementsScan', 'result': pkgs_str})
                files_changed = True

            # 0d. Apply corrective fixes from error memory
            if _cancelled():
                yield f"event: exec_done\ndata: {json.dumps({'success': False, 'attempts': 0, 'fixes': [], 'output': 'Cancelled during pre-scan'})}\n\n"
                return
            try:
                yield f"event: exec_status\ndata: {json.dumps({'status': 'Applying corrective fixes...'})}\n\n"
                corrective_results = AgentService._apply_corrective_fixes(workspace_path)
                for cr in corrective_results:
                    yield f"event: exec_fix\ndata: {json.dumps({'path': cr['path'], 'tool': 'CorrectiveFix', 'result': cr['description']})}\n\n"
                    all_fixes.append({'path': cr['path'], 'tool': 'CorrectiveFix', 'result': cr['description']})
                    files_changed = True
            except Exception as e:
                _safe_log(f"[Execution Agent] Corrective fixes error: {e}")

            # Notify frontend to refresh file tree if any pre-scan changes were made
            if files_changed:
                yield f"event: exec_files_changed\ndata: {json.dumps({'changed': True})}\n\n"

            # ── Phase 0e: Integrity check ──────────────────────────
            if _cancelled():
                yield f"event: exec_done\ndata: {json.dumps({'success': False, 'attempts': 0, 'fixes': [], 'output': 'Cancelled during pre-scan'})}\n\n"
                return
            # Always run integrity check — Phase 0f/g/h need the full result
            # (py_files, defined_names, import_graph).  Even if review handoff
            # provided issue strings, we still need the structured data.
            integrity_result = None
            try:
                yield f"event: exec_status\ndata: {json.dumps({'status': 'Checking project integrity...'})}\n\n"
                integrity_result = AgentService._validate_project_integrity(workspace_path)
                # Merge review-handoff issues (kept for LLM context) with fresh scan
                fresh_issues = integrity_result.get('issues', [])
                if integrity_issues:
                    # Combine: fresh issues + any review-handoff issues not in fresh
                    fresh_set = set(fresh_issues)
                    for ri in integrity_issues:
                        if ri not in fresh_set:
                            fresh_issues.append(ri)
                integrity_issues = fresh_issues
            except Exception as e:
                _safe_log(f"[Execution Agent] Integrity check error: {e}")

            # Emit integrity results to frontend
            issue_preview = integrity_issues[:5] if integrity_issues else []
            yield f"event: exec_integrity\ndata: {json.dumps({'count': len(integrity_issues), 'issues': issue_preview})}\n\n"

            # ── Phase 0f: Fix corrupted/truncated files ───────────
            if integrity_issues and integrity_result:
                syntax_errors = [i for i in integrity_issues
                                 if 'Syntax error' in i or 'Compilation error' in i]
                if syntax_errors:
                    try:
                        yield f"event: exec_status\ndata: {json.dumps({'status': 'Checking for corrupted files...'})}\n\n"
                        for event_str in AgentService._fix_corrupted_files(
                            workspace_path, integrity_result, spec_context, cancel_event
                        ):
                            yield event_str
                        # Re-run integrity after rewrites
                        integrity_result = AgentService._validate_project_integrity(workspace_path)
                        integrity_issues = integrity_result.get('issues', [])
                        files_changed = True
                    except Exception as e:
                        _safe_log(f"[Execution Agent] Corrupted file fix error: {e}")

            # ── Phase 0g: Fix missing stdlib imports ──────────────
            if integrity_result:
                try:
                    missing_import_fixes = AgentService._fix_missing_stdlib_imports(
                        workspace_path, integrity_result)
                    if missing_import_fixes:
                        for fix in missing_import_fixes:
                            yield f"event: exec_fix\ndata: {json.dumps({'path': fix['path'], 'tool': 'ImportFix', 'result': 'Added import ' + fix['module']})}\n\n"
                            all_fixes.append({'path': fix['path'], 'tool': 'ImportFix',
                                              'result': 'import ' + fix['module']})
                        files_changed = True
                except Exception as e:
                    _safe_log(f"[Execution Agent] Missing import fix error: {e}")

            # ── Phase 0h: Fix cross-module import mismatches ──────
            if integrity_result:
                try:
                    import_fixes = AgentService._fix_cross_module_imports(
                        workspace_path, integrity_result)
                    if import_fixes:
                        for fix in import_fixes:
                            yield f"event: exec_fix\ndata: {json.dumps({'path': fix['path'], 'tool': 'ImportReroute', 'result': fix['new_import']})}\n\n"
                            all_fixes.append({'path': fix['path'], 'tool': 'ImportReroute',
                                              'result': fix['new_import']})
                        files_changed = True
                except Exception as e:
                    _safe_log(f"[Execution Agent] Cross-module import fix error: {e}")

            # ── Phase 1: Detect entry point ────────────────────────
            yield f"event: exec_status\ndata: {json.dumps({'status': 'Detecting entry point...'})}\n\n"
            entry_info = detect_entry_point(workspace_path)

            if not entry_info.get('entryPoint'):
                # Frontend-only projects: auto-generate a static file server
                if entry_info.get('isFrontend'):
                    _html_file = None
                    try:
                        for _f in os.listdir(workspace_path):
                            if _f.endswith('.html') and os.path.isfile(os.path.join(workspace_path, _f)):
                                _html_file = _f
                                if _f == 'index.html':
                                    break
                    except Exception:
                        pass

                    if _html_file:
                        _serve_py = os.path.join(workspace_path, 'serve.py')
                        _serve_code = (
                            '"""Auto-generated static file server for frontend project."""\n'
                            'import http.server\n'
                            'import socketserver\n'
                            'import webbrowser\n'
                            'import os\n\n'
                            'PORT = 8080\n'
                            f'HTML_FILE = {_html_file!r}\n\n'
                            'os.chdir(os.path.dirname(os.path.abspath(__file__)))\n\n'
                            'Handler = http.server.SimpleHTTPRequestHandler\n\n'
                            'print(f"Serving at http://localhost:{PORT}")\n'
                            'print(f"Open http://localhost:{PORT}/{HTML_FILE} in your browser")\n\n'
                            'with socketserver.TCPServer(("", PORT), Handler) as httpd:\n'
                            '    try:\n'
                            '        httpd.serve_forever()\n'
                            '    except KeyboardInterrupt:\n'
                            '        print("\\nServer stopped.")\n'
                        )
                        try:
                            with open(_serve_py, 'w', encoding='utf-8') as f:
                                f.write(_serve_code)
                            yield f"event: exec_fix\ndata: {json.dumps({'path': 'serve.py', 'tool': 'AutoGenerate', 'result': 'Created static file server for frontend project'})}\n\n"
                            all_fixes.append({'path': 'serve.py', 'tool': 'AutoGenerate',
                                              'result': 'Static file server for frontend project'})
                            _safe_log(f"[Execution Agent] Auto-generated serve.py for frontend project")
                            # Re-detect entry point now that serve.py exists
                            entry_info = detect_entry_point(workspace_path)
                        except Exception as e:
                            _safe_log(f"[Execution Agent] Failed to generate serve.py: {e}")

                # If still no entry point after frontend fix attempt
                if not entry_info.get('entryPoint'):
                    # Provide diagnostics: list what files DO exist so user understands why
                    _diag_files = []
                    _skip = {'.git', '__pycache__', 'node_modules', '.venv', 'venv', '.sentinel'}
                    try:
                        for _root, _dirs, _files in os.walk(workspace_path):
                            _dirs[:] = [d for d in _dirs if d not in _skip and not d.startswith('.')]
                            for _f in _files:
                                if _f.endswith(('.py', '.js', '.ts')):
                                    _rel = os.path.relpath(os.path.join(_root, _f), workspace_path).replace('\\', '/')
                                    _diag_files.append(_rel)
                            if len(_diag_files) > 20:
                                break
                    except Exception:
                        pass

                    if _diag_files:
                        _file_list = ', '.join(_diag_files[:10])
                        _more = f' (+{len(_diag_files) - 10} more)' if len(_diag_files) > 10 else ''
                        _diag_msg = (
                            f"No entry point found. Found these files but none are named "
                            f"main.py, app.py, cli.py, run.py, or server.py, and none have "
                            f"an if __name__ == '__main__' guard: {_file_list}{_more}"
                        )
                    else:
                        _diag_msg = "No entry point found — workspace contains no .py or .js files"

                    yield f"event: exec_error\ndata: {json.dumps({'error': _diag_msg})}\n\n"
                    _safe_log(f"[Execution Agent] {_diag_msg}")
                    return

            entry_point = entry_info['entryPoint']
            command = entry_info.get('command', f'python {entry_point}')
            is_server = entry_info.get('isServer', False)

            yield f"event: exec_status\ndata: {json.dumps({'status': f'Entry point: {entry_point}'})}\n\n"

            # ── Phase 2: Install dependencies ──────────────────────
            dep_install_failed = False
            dep_install_errors = []
            _phase2_failed_pkgs = set()  # Packages that pip couldn't find in Phase 2
            if entry_info.get('installCmd'):
                yield f"event: exec_status\ndata: {json.dumps({'status': 'Installing dependencies...'})}\n\n"
                tool_service = ToolService(workspace_path, workspace_path=workspace_path)
                install_result = tool_service.run_command(entry_info['installCmd'])
                for line in (install_result or '').splitlines()[:20]:
                    yield f"event: exec_output\ndata: {json.dumps({'line': line})}\n\n"
                # Detect pip install failures (version not found OR build failures)
                _pip_version_fail = install_result and (
                    'ERROR: No matching distribution' in install_result
                    or 'ERROR: Could not find a version' in install_result
                    or 'ERROR: Could not install' in install_result
                )
                _pip_build_fail = install_result and (
                    'subprocess-exited-with-error' in install_result
                    or 'Failed building wheel' in install_result
                    or 'error: command' in install_result.lower()
                )

                if _pip_version_fail or _pip_build_fail:
                    dep_install_failed = True
                    for ln in (install_result or '').splitlines():
                        if ln.strip().startswith('ERROR:') or 'Failed building' in ln:
                            dep_install_errors.append(ln.strip())
                            # Extract package names that pip couldn't find
                            _no_dist_match = re.search(r'No matching distribution found for (\S+)', ln)
                            _no_ver_match = re.search(r'Could not find a version that satisfies the requirement (\S+)', ln)
                            _pkg_match = _no_dist_match or _no_ver_match
                            if _pkg_match:
                                _failed_pkg = re.split(r'[>=<!\[\];]', _pkg_match.group(1))[0].strip().lower()
                                if _failed_pkg:
                                    _phase2_failed_pkgs.add(_failed_pkg)
                    exec_warnings.extend(dep_install_errors[:10])
                    yield f"event: exec_status\ndata: {json.dumps({'status': 'WARNING: Some dependencies failed to install — this may cause runtime errors'})}\n\n"

                    # Remove packages that don't exist on PyPI from requirements.txt
                    if _phase2_failed_pkgs:
                        for _bad_pkg in _phase2_failed_pkgs:
                            AgentService._remove_from_requirements_txt(workspace_path, _bad_pkg)
                        yield f"event: exec_status\ndata: {json.dumps({'status': f'Removed non-existent packages from requirements.txt: {", ".join(sorted(_phase2_failed_pkgs))}'})}\n\n"

                    _req_path = os.path.join(workspace_path, 'requirements.txt')
                    _needs_reinstall = False

                    # Fix 1: Substitute packages with known build failures → binary alternatives
                    if _pip_build_fail and os.path.isfile(_req_path):
                        try:
                            with open(_req_path, 'r', encoding='utf-8') as f:
                                req_lines = f.readlines()
                            new_lines = []
                            build_subs_applied = []
                            for line in req_lines:
                                stripped = line.strip()
                                if stripped and not stripped.startswith('#'):
                                    pkg = re.split(r'[>=<!\[\];]', stripped)[0].strip().lower()
                                    sub = AgentService._BUILD_SUBS.get(pkg)
                                    if sub and sub.lower() != pkg:
                                        new_lines.append(sub + '\n')
                                        build_subs_applied.append(f'{pkg} -> {sub}')
                                    else:
                                        new_lines.append(line)
                                else:
                                    new_lines.append(line)
                            if build_subs_applied:
                                with open(_req_path, 'w', encoding='utf-8') as f:
                                    f.writelines(new_lines)
                                subs_str = ', '.join(build_subs_applied)
                                yield f"event: exec_fix\ndata: {json.dumps({'path': 'requirements.txt', 'tool': 'DepBuildFix', 'result': f'Substituted: {subs_str}'})}\n\n"
                                all_fixes.append({'path': 'requirements.txt', 'tool': 'DepBuildFix', 'result': f'Substituted: {subs_str}'})
                                exec_warnings.append(f'Build substitutions applied: {subs_str}')
                                files_changed = True
                                _needs_reinstall = True
                        except Exception as e:
                            _safe_log(f"[Execution Agent] Build sub error: {e}")

                    # Fix 2: Relax pinned versions (existing logic)
                    if os.path.isfile(_req_path):
                        _fixed_deps = AgentService._fix_pinned_requirements(workspace_path, dep_install_errors)
                        if _fixed_deps:
                            yield f"event: exec_fix\ndata: {json.dumps({'path': 'requirements.txt', 'tool': 'DepVersionFix', 'result': f'Relaxed version pins for: {_fixed_deps}'})}\n\n"
                            all_fixes.append({'path': 'requirements.txt', 'tool': 'DepVersionFix', 'result': f'Relaxed: {_fixed_deps}'})
                            files_changed = True
                            _needs_reinstall = True

                    # Re-run pip install if any fixes were applied
                    if _needs_reinstall:
                        yield f"event: exec_status\ndata: {json.dumps({'status': 'Re-installing with fixed requirements...'})}\n\n"
                        install_result2 = tool_service.run_command(entry_info['installCmd'])
                        if install_result2 and 'ERROR:' not in install_result2:
                            dep_install_failed = False
                            dep_install_errors = []
                            exec_warnings.append('Dependencies installed successfully after auto-fix')
                            yield f"event: exec_status\ndata: {json.dumps({'status': 'Dependencies installed successfully after version fix'})}\n\n"
                        else:
                            for line in (install_result2 or '').splitlines()[:10]:
                                yield f"event: exec_output\ndata: {json.dumps({'line': line})}\n\n"

            # ── Phase 3: Execute + Diagnose loop ───────────────────
            prev_error_type = None
            same_error_count = 0
            prev_error_count = None  # For smarter retry / revert
            error_output = ''  # Last error output (for final report)
            error_class = None  # Initialized so max-attempts block doesn't NameError
            _failed_pip_installs = set(_phase2_failed_pkgs)  # Seed from Phase 2 pip failures

            for attempt in range(1, MAX_ATTEMPTS + 1):
                if cancel_event and cancel_event.is_set():
                    yield f"event: exec_status\ndata: {json.dumps({'status': 'Cancelled'})}\n\n"
                    break

                yield f"event: exec_run\ndata: {json.dumps({'attempt': attempt, 'command': command, 'status': 'running'})}\n\n"

                # Run the project
                timeout = 10 if is_server else 30
                exit_code, stdout, stderr = AgentService._run_project_subprocess(
                    command, workspace_path, timeout=timeout
                )

                # Stream output (cap at 200 lines to prevent browser flooding)
                combined = (stdout + stderr).strip()
                output_lines = combined.splitlines()
                if len(output_lines) > 200:
                    output_lines = output_lines[:100] + [f'... ({len(output_lines) - 200} lines truncated) ...'] + output_lines[-100:]
                for line in output_lines:
                    yield f"event: exec_output\ndata: {json.dumps({'line': line[:2000]})}\n\n"

                # ── Success checks ──
                if exit_code == 0:
                    # Validate output beyond just exit code
                    is_valid, val_reason = AgentService._validate_execution_output(
                        exit_code, stdout, stderr, entry_info, workspace_path
                    )
                    yield f"event: exec_validate\ndata: {json.dumps({'valid': is_valid, 'reason': val_reason})}\n\n"

                    if is_valid:
                        yield f"event: exec_run\ndata: {json.dumps({'attempt': attempt, 'command': command, 'status': 'success', 'exitCode': 0})}\n\n"
                        if files_changed:
                            yield f"event: exec_files_changed\ndata: {json.dumps({'changed': True})}\n\n"
                        # Save history + write log on successful exit
                        exec_history.append({'attempt': attempt, 'error': None, 'fixes': [_fix_path(f) for f in all_fixes], 'success': True})
                        AgentService._save_exec_history(workspace_path, task_id, exec_history)
                        AgentService._write_execution_log(workspace_path, task_id, True, attempt, all_fixes, combined[:3000], warnings=exec_warnings)
                        # RL: Score execution + fire reward agent
                        try:
                            _total_py = len([f for f in os.listdir(workspace_path) if f.endswith('.py')]) if os.path.isdir(workspace_path) else 0
                            _exec_sc = score_execution(attempts=attempt, success=True, integrity_issues=len(integrity_issues), review_issues=len(integrity_issues), fixes_applied=len(all_fixes), total_files=_total_py)
                            AgentService._fire_reward_agent_async(task_id, workspace_path, _exec_sc)
                        except Exception as _rl_e:
                            _safe_log(f"[RL] Execution scoring failed: {_rl_e}")
                        yield f"event: exec_done\ndata: {json.dumps({'success': True, 'attempts': attempt, 'fixes': [_fix_path(f) for f in all_fixes], 'output': combined[:3000]})}\n\n"
                        return
                    else:
                        # Exit code 0 but output looks wrong — fall through to diagnosis
                        yield f"event: exec_status\ndata: {json.dumps({'status': f'Exit code 0 but validation failed: {val_reason}'})}\n\n"
                        yield f"event: exec_run\ndata: {json.dumps({'attempt': attempt, 'command': command, 'status': 'error', 'exitCode': exit_code})}\n\n"
                        error_output = stderr if stderr.strip() else stdout
                        error_class = AgentService._classify_error(error_output)
                        error_class['message'] = val_reason
                        yield f"event: exec_diagnosis\ndata: {json.dumps(error_class)}\n\n"
                        # Don't count this attempt in the loop — let the LLM try to fix it below

                elif exit_code == -1 and 'timed out' in stderr.lower() and (
                    is_server
                    or 'Serving Flask app' in (stdout + stderr)
                    or 'Running on http' in (stdout + stderr)
                    or 'Uvicorn running on' in (stdout + stderr)
                    or 'Starting development server' in (stdout + stderr)
                    or 'Listening on' in (stdout + stderr)
                    or re.search(r'(?:server|app)\s+(?:running|started|listening)\s+(?:on|at)', (stdout + stderr), re.IGNORECASE)
                ):
                    # Server timeout = success (it's running)
                    yield f"event: exec_validate\ndata: {json.dumps({'valid': True, 'reason': 'Server started successfully'})}\n\n"
                    yield f"event: exec_run\ndata: {json.dumps({'attempt': attempt, 'command': command, 'status': 'success', 'exitCode': 0})}\n\n"
                    if files_changed:
                        yield f"event: exec_files_changed\ndata: {json.dumps({'changed': True})}\n\n"
                    exec_history.append({'attempt': attempt, 'error': None, 'fixes': [_fix_path(f) for f in all_fixes], 'success': True})
                    AgentService._save_exec_history(workspace_path, task_id, exec_history)
                    AgentService._write_execution_log(workspace_path, task_id, True, attempt, all_fixes, 'Server started successfully (timed out as expected)', warnings=exec_warnings)
                    # RL: Score execution + fire reward agent
                    try:
                        _total_py = len([f for f in os.listdir(workspace_path) if f.endswith('.py')]) if os.path.isdir(workspace_path) else 0
                        _exec_sc = score_execution(attempts=attempt, success=True, integrity_issues=len(integrity_issues), review_issues=len(integrity_issues), fixes_applied=len(all_fixes), total_files=_total_py)
                        AgentService._fire_reward_agent_async(task_id, workspace_path, _exec_sc)
                    except Exception as _rl_e:
                        _safe_log(f"[RL] Execution scoring failed: {_rl_e}")
                    yield f"event: exec_done\ndata: {json.dumps({'success': True, 'attempts': attempt, 'fixes': [_fix_path(f) for f in all_fixes], 'output': 'Server started successfully (timed out as expected)'})}\n\n"
                    return

                elif exit_code == 2 and ('usage:' in (stdout + stderr).lower() or 'the following arguments are required' in (stdout + stderr).lower()):
                    # CLI argparse exit code 2 = loaded OK, just needs args
                    # BUT if deps failed to install, validate imports first —
                    # argparse may fire before broken imports are hit
                    _cli_ok = True
                    if dep_install_failed:
                        import_err = _validate_imports(workspace_path, entry_point)
                        if import_err:
                            _cli_ok = False
                            yield f"event: exec_validate\ndata: {json.dumps({'valid': False, 'reason': f'Dependencies missing: {import_err}'})}\n\n"
                            yield f"event: exec_run\ndata: {json.dumps({'attempt': attempt, 'command': command, 'status': 'error', 'exitCode': exit_code})}\n\n"
                            error_output = f"Dependency install failed and imports are broken: {import_err}"
                            error_class = {'type': 'module_not_found', 'module': import_err.split("'")[-2] if "'" in import_err else '', 'message': import_err}
                            yield f"event: exec_diagnosis\ndata: {json.dumps(error_class)}\n\n"
                            # Fall through to the fix loop below
                        else:
                            yield f"event: exec_validate\ndata: {json.dumps({'valid': True, 'reason': 'CLI tool loaded successfully (some optional deps missing)'})}\n\n"
                            yield f"event: exec_run\ndata: {json.dumps({'attempt': attempt, 'command': command, 'status': 'success', 'exitCode': exit_code})}\n\n"
                            yield f"event: exec_status\ndata: {json.dumps({'status': 'CLI tool loaded successfully (needs arguments to run)'})}\n\n"
                    else:
                        yield f"event: exec_validate\ndata: {json.dumps({'valid': True, 'reason': 'CLI tool loaded successfully'})}\n\n"
                        yield f"event: exec_run\ndata: {json.dumps({'attempt': attempt, 'command': command, 'status': 'success', 'exitCode': exit_code})}\n\n"
                        yield f"event: exec_status\ndata: {json.dumps({'status': 'CLI tool loaded successfully (needs arguments to run)'})}\n\n"
                    if _cli_ok:
                        if files_changed:
                            yield f"event: exec_files_changed\ndata: {json.dumps({'changed': True})}\n\n"
                        exec_history.append({'attempt': attempt, 'error': None, 'fixes': [_fix_path(f) for f in all_fixes], 'success': True})
                        AgentService._save_exec_history(workspace_path, task_id, exec_history)
                        AgentService._write_execution_log(workspace_path, task_id, True, attempt, all_fixes, combined[:3000], warnings=exec_warnings)
                        # RL: Score execution + fire reward agent
                        try:
                            _total_py = len([f for f in os.listdir(workspace_path) if f.endswith('.py')]) if os.path.isdir(workspace_path) else 0
                            _exec_sc = score_execution(attempts=attempt, success=True, integrity_issues=len(integrity_issues), review_issues=len(integrity_issues), fixes_applied=len(all_fixes), total_files=_total_py)
                            AgentService._fire_reward_agent_async(task_id, workspace_path, _exec_sc)
                        except Exception as _rl_e:
                            _safe_log(f"[RL] Execution scoring failed: {_rl_e}")
                        yield f"event: exec_done\ndata: {json.dumps({'success': True, 'attempts': attempt, 'fixes': [_fix_path(f) for f in all_fixes], 'output': combined[:3000]})}\n\n"
                        return

                else:
                    yield f"event: exec_run\ndata: {json.dumps({'attempt': attempt, 'command': command, 'status': 'error', 'exitCode': exit_code})}\n\n"

                    # ── Classify the error ──
                    error_output = stderr if stderr.strip() else stdout
                    error_class = AgentService._classify_error(error_output)
                    yield f"event: exec_diagnosis\ndata: {json.dumps(error_class)}\n\n"

                # At this point error_output and error_class are set
                # (either from validation-failed branch or from else branch above)
                cur_error_count = AgentService._count_errors_in_output(error_output)

                # Repeated-error bail (3 identical → give up)
                error_sig = f"{error_class['type']}:{error_class.get('file')}:{error_class.get('line')}"
                if error_sig == prev_error_type:
                    same_error_count += 1
                    if same_error_count >= 3:
                        yield f"event: exec_status\ndata: {json.dumps({'status': 'Same error repeated 3 times. Giving up.'})}\n\n"
                        break
                else:
                    same_error_count = 1
                    prev_error_type = error_sig

                # ── Deterministic fix: ModuleNotFoundError → pip install ──
                if error_class['type'] == 'module_not_found' and error_class.get('module'):
                    mod = error_class['module'].split('.')[0]
                    pkg = PIP_NAME_MAP.get(mod, mod)

                    # Check if we already tried and failed to pip install this package
                    _pip_already_failed = pkg.lower() in _failed_pip_installs

                    if not _pip_already_failed:
                        yield f"event: exec_status\ndata: {json.dumps({'status': f'Installing missing package: {pkg}'})}\n\n"

                        ts = ToolService(workspace_path, workspace_path=workspace_path)
                        install_out = ts.run_command(f'pip install {pkg}')
                        yield f"event: exec_output\ndata: {json.dumps({'line': (install_out or '')[:500]})}\n\n"

                        # Check if pip install actually succeeded
                        _pip_failed = install_out and (
                            'ERROR: No matching distribution' in install_out
                            or 'ERROR: Could not find a version' in install_out
                            or 'ERROR: Could not install' in install_out
                            or 'subprocess-exited-with-error' in install_out
                        )

                        if _pip_failed:
                            # This is NOT a real pip package — track it and fall through to LLM
                            _failed_pip_installs.add(pkg.lower())
                            # Remove from requirements.txt so it doesn't poison future installs
                            AgentService._remove_from_requirements_txt(workspace_path, pkg)
                            exec_warnings.append(f'pip install {pkg} failed — not a real package, likely a missing local module')
                            yield f"event: exec_status\ndata: {json.dumps({'status': f'Package {pkg} not found on PyPI — treating as missing local module'})}\n\n"
                            yield f"event: exec_fix\ndata: {json.dumps({'path': 'requirements.txt', 'tool': 'RunCommand', 'result': f'pip install {pkg} FAILED — removed from requirements.txt'})}\n\n"
                            # Reset same_error_count so the LLM gets a fresh chance
                            same_error_count = 0
                            prev_error_type = None
                            # DON'T continue — fall through to LLM diagnosis below
                        else:
                            yield f"event: exec_fix\ndata: {json.dumps({'path': 'requirements.txt', 'tool': 'RunCommand', 'result': f'pip install {pkg}'})}\n\n"
                            AgentService._add_to_requirements_txt(workspace_path, pkg)
                            all_fixes.append({'path': 'requirements.txt', 'tool': 'pip install', 'result': pkg})
                            ErrorMemory.record(error_class, f"pip install {pkg}", success=True,
                                               tags=['execution'], context='python',
                                               fingerprint=exec_fingerprint)
                            prev_error_count = cur_error_count
                            continue
                    else:
                        # Already failed before — skip pip, reset error tracking, fall through to LLM
                        yield f"event: exec_status\ndata: {json.dumps({'status': f'Package {pkg} already failed to install — sending to LLM for local module creation'})}\n\n"
                        same_error_count = 0
                        prev_error_type = None
                        # Fall through to LLM diagnosis

                # ── Deterministic fix: SyntaxError → diff markers ──
                if error_class['type'] == 'syntax' and error_class.get('file'):
                    err_file = error_class['file']
                    if os.path.isfile(err_file):
                        fixed = AgentService._fix_diff_markers(err_file)
                        if fixed:
                            short_path = os.path.relpath(err_file, workspace_path).replace('\\', '/')
                            yield f"event: exec_status\ndata: {json.dumps({'status': f'Cleaned {len(fixed)} stray diff markers from {short_path}'})}\n\n"
                            yield f"event: exec_fix\ndata: {json.dumps({'path': short_path, 'tool': 'DiffMarkerFix', 'result': f'Stripped {len(fixed)} lines'})}\n\n"
                            all_fixes.append({'path': short_path, 'tool': 'DiffMarkerFix', 'result': f'{len(fixed)} lines fixed'})
                            files_changed = True
                            # Also scan ALL .py files for stray markers
                            for root, dirs, files in os.walk(workspace_path):
                                dirs[:] = [d for d in dirs if d not in ('.venv', 'venv', '__pycache__', '.git', 'node_modules')]
                                for fname in files:
                                    if fname.endswith('.py'):
                                        fpath = os.path.join(root, fname)
                                        if fpath != err_file:
                                            extra_fixed = AgentService._fix_diff_markers(fpath)
                                            if extra_fixed:
                                                sp = os.path.relpath(fpath, workspace_path).replace('\\', '/')
                                                yield f"event: exec_fix\ndata: {json.dumps({'path': sp, 'tool': 'DiffMarkerFix', 'result': f'Stripped {len(extra_fixed)} lines'})}\n\n"
                                                all_fixes.append({'path': sp, 'tool': 'DiffMarkerFix', 'result': f'{len(extra_fixed)} lines fixed'})
                            yield f"event: exec_files_changed\ndata: {json.dumps({'changed': True})}\n\n"
                            prev_error_count = cur_error_count
                            continue

                # ── Deterministic fix: ImportError + missing __init__.py ──
                if error_class['type'] == 'import':
                    new_inits = AgentService._detect_missing_init_files(workspace_path)
                    if new_inits:
                        for ip in new_inits:
                            yield f"event: exec_fix\ndata: {json.dumps({'path': ip, 'tool': 'InitCreate', 'result': 'Created missing __init__.py'})}\n\n"
                            all_fixes.append({'path': ip, 'tool': 'InitCreate', 'result': 'created'})
                        files_changed = True
                        yield f"event: exec_files_changed\ndata: {json.dumps({'changed': True})}\n\n"
                        prev_error_count = cur_error_count
                        continue

                # ── LLM-assisted fix (with snapshot for revert) ──
                exec_log.exec_error(error_class)
                exec_log.turn_start('LLM Diagnosis', attempt)
                yield f"event: exec_status\ndata: {json.dumps({'status': f'Diagnosing error with LLM (attempt {attempt})...'})}\n\n"

                # Snapshot files before LLM touches them
                snapshot = AgentService._snapshot_project_files(workspace_path)

                # Read project files focused on the error file
                focus_file = error_class.get('file')
                file_contents = AgentService._read_project_files_for_exec(workspace_path, focus_file=focus_file)

                # Get project listing
                try:
                    ts = ToolService(workspace_path, workspace_path=workspace_path)
                    listing = ts.list_files('.')
                except Exception:
                    listing = ''

                # Build LLM context (enhanced with spec, integrity, history)
                os_name = platform.system()

                # Look up known solutions from error memory
                known_solutions_entries = ErrorMemory.lookup(
                    step_type='execution', error_class=error_class, max_entries=3,
                    fingerprint=exec_fingerprint,
                )
                known_solutions_text = ErrorMemory.format_for_prompt(
                    known_solutions_entries, header='## Known Solutions',
                    compact_mode=False,
                ) if known_solutions_entries else ''

                # Build fix_history string from deterministic fixes applied in pre-scan
                _fix_history_lines = []
                for af in all_fixes:
                    tool = af.get('tool', '')
                    if tool in ('ShadowFix', 'DepVersionFix', 'DepBuildFix', 'PreScan',
                                'InitCreate', 'RequirementsScan', 'ImportFix', 'ImportReroute',
                                'CorrectiveFix'):
                        _fix_history_lines.append(f"- [{tool}] {af.get('result', '')}")
                _fix_history_str = '\n'.join(_fix_history_lines[:15])

                system_prompt = build_diagnose_prompt(
                    os_name=os_name,
                    spec_context=spec_context,
                    integrity_issues=integrity_issues,
                    history_context=history_context,
                    known_solutions=known_solutions_text,
                    fix_history=_fix_history_str,
                )
                user_msg = AgentService._build_execution_user_message(
                    error_output=error_output,
                    file_contents=file_contents,
                    entry_point=entry_point,
                    project_listing=listing,
                    error_class=error_class,
                    spec_context=spec_context,
                    integrity_issues=integrity_issues,
                    failed_pip_packages=_failed_pip_installs,
                )

                llm_history = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_msg},
                ]

                # Run LLM pass
                llm = get_llm_engine()
                exec_tool_service = ToolService(workspace_path, workspace_path=workspace_path)
                pass_results = {'text': '', 'edits': []}

                for event_str in AgentService._run_review_pass(
                    llm, llm_history, exec_tool_service, cancel_event, pass_results,
                    max_turns=MAX_LLM_TURNS, max_tokens=2048, timeout_seconds=90,
                    event_prefix='exec',
                    allowed_tools={'EditFile', 'WriteFile', 'ReadFile', 'RunCommand'}
                ):
                    yield event_str

                # Record fixes
                for edit in pass_results.get('edits', []):
                    all_fixes.append(edit)

                if not pass_results.get('edits'):
                    yield f"event: exec_status\ndata: {json.dumps({'status': 'No fixes applied by LLM'})}\n\n"
                else:
                    files_changed = True
                    # ── Smarter retry: verify LLM didn't make it worse ──
                    # Quick re-run to count errors AFTER the LLM fix
                    verify_code, verify_out, verify_err = AgentService._run_project_subprocess(
                        command, workspace_path, timeout=timeout
                    )
                    new_error_count = AgentService._count_errors_in_output(
                        verify_err if verify_err.strip() else verify_out
                    )

                    if prev_error_count is not None and new_error_count > prev_error_count:
                        # LLM made things WORSE — revert!
                        yield f"event: exec_status\ndata: {json.dumps({'status': f'LLM fix increased errors ({prev_error_count} → {new_error_count}). Reverting...'})}\n\n"
                        restored = AgentService._restore_snapshot(workspace_path, snapshot)
                        yield f"event: exec_status\ndata: {json.dumps({'status': f'Reverted {restored} files to pre-fix state'})}\n\n"
                        # Remove the bad fixes from the list
                        for _ in pass_results.get('edits', []):
                            if all_fixes:
                                all_fixes.pop()
                        # Record reverted attempt in history
                        exec_history.append({
                            'attempt': attempt, 'error': error_sig,
                            'fixes': [_fix_path(e) for e in pass_results.get('edits', [])],
                            'success': False, 'reverted': True,
                            'error_output': (error_output or '')[:2000],
                        })
                        # Record to global error memory (fix failed)
                        fix_desc = ', '.join(_fix_path(e) for e in pass_results.get('edits', [])[:3])
                        ErrorMemory.record(error_class, fix_desc, success=False, tags=['execution'],
                                           fingerprint=exec_fingerprint)
                    else:
                        prev_error_count = new_error_count
                        yield f"event: exec_files_changed\ndata: {json.dumps({'changed': True})}\n\n"
                        # Record successful LLM attempt in history
                        exec_history.append({
                            'attempt': attempt, 'error': error_sig,
                            'fixes': [_fix_path(e) for e in pass_results.get('edits', [])],
                            'success': False, 'reverted': False,
                            'error_output': (error_output or '')[:2000],
                        })
                        # Record to global error memory (fix kept)
                        fix_desc = ', '.join(_fix_path(e) for e in pass_results.get('edits', [])[:3])
                        ErrorMemory.record(error_class, fix_desc, success=True, tags=['execution'],
                                           fingerprint=exec_fingerprint)

                # Rebuild history context for next iteration
                history_context = AgentService._build_history_context(exec_history)

            # ── Phase 3.5: Recoder Agent ─────────────────────────
            # When Phase 3 exhausts all attempts, try a holistic rewrite before
            # falling through to step-fix. The recoder reads ALL files + ALL errors.
            recoder_success = False
            if error_class and not (cancel_event and cancel_event.is_set()):
                yield f"event: exec_status\ndata: {json.dumps({'status': 'Launching Recoder Agent for holistic project fix...'})}\n\n"
                try:
                    for event_or_result in AgentService._run_recoder_agent(
                        workspace_path=workspace_path,
                        entry_point=entry_point,
                        command=command,
                        is_server=is_server,
                        exec_history=exec_history,
                        all_fixes=all_fixes,
                        spec_context=spec_context,
                        integrity_issues=integrity_issues,
                        cancel_event=cancel_event,
                        failed_pip_packages=_failed_pip_installs,
                    ):
                        if isinstance(event_or_result, dict):
                            recoder_success = event_or_result.get('success', False)
                        else:
                            yield event_or_result
                except Exception as e:
                    _safe_log(f"[Recoder Agent] Error: {e}")
                    yield f"event: exec_status\ndata: {json.dumps({'status': f'Recoder Agent error: {e}'})}\n\n"

                if recoder_success:
                    # Recoder fixed it — emit success and return
                    exec_history.append({
                        'attempt': MAX_ATTEMPTS + 1,
                        'error': None,
                        'fixes': [f.get('result', '') for f in all_fixes],
                        'success': True,
                        'recoder': True,
                    })
                    AgentService._save_exec_history(workspace_path, task_id, exec_history)
                    AgentService._write_execution_log(
                        workspace_path, task_id, True, MAX_ATTEMPTS + 1,
                        all_fixes, 'Fixed by Recoder Agent', warnings=exec_warnings
                    )
                    yield f"event: exec_files_changed\ndata: {json.dumps({'changed': True})}\n\n"
                    try:
                        _total_py = len([f for f in os.listdir(workspace_path) if f.endswith('.py')]) if os.path.isdir(workspace_path) else 0
                        _exec_sc = score_execution(attempts=MAX_ATTEMPTS + 1, success=True,
                                                   integrity_issues=len(integrity_issues),
                                                   review_issues=len(integrity_issues),
                                                   fixes_applied=len(all_fixes), total_files=_total_py)
                        AgentService._fire_reward_agent_async(task_id, workspace_path, _exec_sc)
                    except Exception:
                        pass
                    yield f"event: exec_done\ndata: {json.dumps({'success': True, 'attempts': MAX_ATTEMPTS + 1, 'fixes': [f.get('result', '') for f in all_fixes], 'output': 'Fixed by Recoder Agent'})}\n\n"
                    return
                else:
                    yield f"event: exec_status\ndata: {json.dumps({'status': 'Recoder Agent could not fix the project. Trying step-fix...'})}\n\n"

            # ── Phase 4: Step-Fix Attempt ──────────────────────────
            # Before giving up, try to trace the error to the implementation
            # step that produced it and have that step's LLM fix its own code.
            step_fix_success = False

            if error_class and error_class.get('file'):
                yield f"event: exec_status\ndata: {json.dumps({'status': 'Tracing error to implementation step...'})}\n\n"

                source_step = AgentService._trace_error_to_step(workspace_path, task_id, error_class)

                if source_step:
                    _safe_log(f"[Execution Agent] Traced error to step: {source_step.get('name', '')} ({source_step.get('id', '')})")

                    # Run the step-fix agent
                    for event_str in AgentService._run_step_fix(
                        workspace_path, task_id, source_step,
                        error_class, error_output, cancel_event
                    ):
                        yield event_str

                    # After step-fix: retry execution ONE more time
                    yield f"event: exec_status\ndata: {json.dumps({'status': 'Step fix applied — retrying execution...'})}\n\n"
                    yield f"event: exec_files_changed\ndata: {json.dumps({'changed': True})}\n\n"
                    files_changed = True

                    # Re-detect entry point (fix may have changed file structure)
                    entry_info_retry = detect_entry_point(workspace_path)
                    if entry_info_retry.get('entryPoint'):
                        retry_cmd = entry_info_retry.get('command', f'python {entry_info_retry["entryPoint"]}')
                        retry_timeout = 10 if entry_info_retry.get('isServer', False) else 30

                        yield f"event: exec_run\ndata: {json.dumps({'attempt': MAX_ATTEMPTS + 1, 'command': retry_cmd, 'status': 'running'})}\n\n"

                        retry_code, retry_out, retry_err = AgentService._run_project_subprocess(
                            retry_cmd, workspace_path, timeout=retry_timeout
                        )

                        retry_combined = (retry_out + retry_err).strip()
                        for line in retry_combined.splitlines()[:100]:
                            yield f"event: exec_output\ndata: {json.dumps({'line': line[:2000]})}\n\n"

                        if retry_code == 0:
                            is_valid, val_reason = AgentService._validate_execution_output(
                                retry_code, retry_out, retry_err, entry_info_retry, workspace_path
                            )
                            if is_valid:
                                step_fix_success = True
                                yield f"event: exec_run\ndata: {json.dumps({'attempt': MAX_ATTEMPTS + 1, 'command': retry_cmd, 'status': 'success', 'exitCode': 0})}\n\n"
                                yield f"event: exec_validate\ndata: {json.dumps({'valid': True, 'reason': val_reason})}\n\n"

                                # Save history + log success
                                exec_history.append({'attempt': MAX_ATTEMPTS + 1, 'error': None, 'fixes': [_fix_path(f) for f in all_fixes], 'success': True, 'step_fix': source_step.get('id')})
                                AgentService._save_exec_history(workspace_path, task_id, exec_history)
                                AgentService._write_execution_log(workspace_path, task_id, True, MAX_ATTEMPTS + 1, all_fixes, retry_combined[:3000], warnings=exec_warnings)

                                # RL scoring
                                try:
                                    _total_py = len([f for f in os.listdir(workspace_path) if f.endswith('.py')]) if os.path.isdir(workspace_path) else 0
                                    _exec_sc = score_execution(attempts=MAX_ATTEMPTS + 1, success=True, integrity_issues=len(integrity_issues), review_issues=len(integrity_issues), fixes_applied=len(all_fixes), total_files=_total_py)
                                    AgentService._fire_reward_agent_async(task_id, workspace_path, _exec_sc)
                                except Exception:
                                    pass

                                yield f"event: exec_done\ndata: {json.dumps({'success': True, 'attempts': MAX_ATTEMPTS + 1, 'fixes': [_fix_path(f) for f in all_fixes], 'output': retry_combined[:3000]})}\n\n"
                                return
                            else:
                                yield f"event: exec_run\ndata: {json.dumps({'attempt': MAX_ATTEMPTS + 1, 'command': retry_cmd, 'status': 'error', 'exitCode': retry_code})}\n\n"
                                yield f"event: exec_status\ndata: {json.dumps({'status': f'Step fix retry failed validation: {val_reason}'})}\n\n"
                        elif retry_code == -1 and 'timed out' in retry_err.lower() and (
                            entry_info_retry.get('isServer')
                            or 'Serving Flask app' in (retry_out + retry_err)
                            or 'Running on http' in (retry_out + retry_err)
                            or 'Uvicorn running on' in (retry_out + retry_err)
                            or 'Starting development server' in (retry_out + retry_err)
                            or 'Listening on' in (retry_out + retry_err)
                            or re.search(r'(?:server|app)\s+(?:running|started|listening)\s+(?:on|at)', (retry_out + retry_err), re.IGNORECASE)
                        ):
                            # Server timeout after fix = success
                            step_fix_success = True
                            yield f"event: exec_run\ndata: {json.dumps({'attempt': MAX_ATTEMPTS + 1, 'command': retry_cmd, 'status': 'success', 'exitCode': 0})}\n\n"
                            exec_history.append({'attempt': MAX_ATTEMPTS + 1, 'error': None, 'fixes': [_fix_path(f) for f in all_fixes], 'success': True, 'step_fix': source_step.get('id')})
                            AgentService._save_exec_history(workspace_path, task_id, exec_history)
                            AgentService._write_execution_log(workspace_path, task_id, True, MAX_ATTEMPTS + 1, all_fixes, 'Server started after step fix', warnings=exec_warnings)
                            yield f"event: exec_done\ndata: {json.dumps({'success': True, 'attempts': MAX_ATTEMPTS + 1, 'fixes': [_fix_path(f) for f in all_fixes], 'output': 'Server started after step fix'})}\n\n"
                            return
                        else:
                            yield f"event: exec_run\ndata: {json.dumps({'attempt': MAX_ATTEMPTS + 1, 'command': retry_cmd, 'status': 'error', 'exitCode': retry_code})}\n\n"
                            yield f"event: exec_status\ndata: {json.dumps({'status': f'Step fix retry still failed (exit code {retry_code})'})}\n\n"
                else:
                    yield f"event: exec_status\ndata: {json.dumps({'status': 'Could not trace error to a specific implementation step'})}\n\n"

            # ── Give up — save history + write log ──────────────────
            if not step_fix_success:
                if error_class:
                    ErrorMemory.record(error_class, 'unresolved', success=False, tags=['execution'],
                                       fingerprint=exec_fingerprint)
                AgentService._save_exec_history(workspace_path, task_id, exec_history)
                last_output = error_output[:3000] if error_output else ''
                AgentService._write_execution_log(workspace_path, task_id, False, MAX_ATTEMPTS, all_fixes, last_output, warnings=exec_warnings)
                if files_changed:
                    yield f"event: exec_files_changed\ndata: {json.dumps({'changed': True})}\n\n"
                # RL: Score failed execution + fire reward agent
                try:
                    _total_py = len([f for f in os.listdir(workspace_path) if f.endswith('.py')]) if os.path.isdir(workspace_path) else 0
                    _exec_sc = score_execution(attempts=MAX_ATTEMPTS, success=False, integrity_issues=len(integrity_issues), review_issues=len(integrity_issues), fixes_applied=len(all_fixes), total_files=_total_py)
                    AgentService._fire_reward_agent_async(task_id, workspace_path, _exec_sc)
                except Exception as _rl_e:
                    _safe_log(f"[RL] Execution scoring failed: {_rl_e}")
                yield f"event: exec_done\ndata: {json.dumps({'success': False, 'attempts': MAX_ATTEMPTS, 'fixes': [_fix_path(f) for f in all_fixes], 'output': last_output})}\n\n"

        except Exception as e:
            _safe_log(f"[Execution Agent] Fatal error: {e}")
            yield f"event: exec_error\ndata: {json.dumps({'error': str(e)})}\n\n"

    @staticmethod
    def _generate_handoff_if_sdd(step_for_chat, workspace_path, task_id):
        """Generate a handoff note after an SDD step completes.

        Reads the artifact from disk, extracts key decisions/scope deterministically,
        and writes a compact .handoff JSON file alongside the artifact.
        """
        SDD_STEPS = {'requirements', 'technical-specification', 'planning'}
        step_id = step_for_chat.get('id', '')
        if step_id not in SDD_STEPS:
            return

        artifact_map = {
            'requirements': 'requirements.md',
            'technical-specification': 'spec.md',
            'planning': 'implementation-plan.md',
        }
        artifact_name = artifact_map.get(step_id)
        if not artifact_name:
            return

        artifacts_dir = os.path.join(workspace_path, '.sentinel', 'tasks', task_id)
        artifact_path = os.path.join(artifacts_dir, artifact_name)
        if not os.path.isfile(artifact_path):
            return

        try:
            from prompts.handoff import generate_handoff_note
            with open(artifact_path, 'r', encoding='utf-8') as f:
                content = f.read()
            if not content.strip():
                return
            note = generate_handoff_note(step_id, content)
            if note:
                handoff_path = os.path.join(artifacts_dir, f"{step_id}.handoff")
                with open(handoff_path, 'w', encoding='utf-8') as hf:
                    json.dump(note, hf)
                _safe_log(f"[Handoff] Generated handoff for {step_id}: {list(note.keys())}")
        except Exception as e:
            _safe_log(f"[Handoff] Error generating handoff for {step_id}: {e}")

    @staticmethod
    def _build_step_summary(step_for_chat, workspace_path, task_id, written_files=None):
        """Build a step completion summary with both markdown and structured data.

        Returns a dict with:
          - 'markdown': Markdown string for chat persistence/reload
          - 'structured': Dict with stepName, files[], totalAdded, totalRemoved
        """
        step_name = step_for_chat.get('name', 'Step')
        step_id = step_for_chat['id']
        artifacts_dir = os.path.join(workspace_path, '.sentinel', 'tasks', task_id)

        # Map of SDD step IDs to their expected artifact files
        artifact_map = {
            'requirements': 'requirements.md',
            'technical-specification': 'spec.md',
            'planning': 'implementation-plan.md',
        }

        SDD_STEPS = {'requirements', 'technical-specification', 'planning'}

        files_data = []
        total_added = 0
        total_removed = 0
        artifact_content = ''

        if step_id in SDD_STEPS:
            # SDD step — show the artifact created
            expected_file = artifact_map.get(step_id, f'{step_id}.md')
            artifact_path = os.path.join(artifacts_dir, expected_file)
            if os.path.exists(artifact_path):
                line_count = 0
                try:
                    with open(artifact_path, 'r', encoding='utf-8') as f:
                        artifact_content = f.read()
                        line_count = artifact_content.count('\n') + (1 if artifact_content and not artifact_content.endswith('\n') else 0)
                except Exception:
                    pass
                # Check written_files dict for metadata from this path
                meta = (written_files or {}).get(expected_file, {})
                is_new = meta.get('is_new', True)
                added = meta.get('added', line_count)
                removed = meta.get('removed', 0)
                dir_path = os.path.dirname(os.path.join('.sentinel', 'tasks', task_id, expected_file)).replace('\\', '/')
                files_data.append({
                    'name': expected_file,
                    'path': dir_path + '/' if dir_path else '',
                    'isNew': is_new,
                    'added': added,
                    'removed': removed,
                })
                total_added += added
                total_removed += removed
        else:
            # Implementation step — show files the agent actually wrote
            if written_files:
                for fpath in sorted(written_files.keys()):
                    meta = written_files[fpath]
                    name = os.path.basename(fpath)
                    dir_path = os.path.dirname(fpath).replace('\\', '/')
                    added = meta.get('added', 0)
                    removed = meta.get('removed', 0)
                    files_data.append({
                        'name': name,
                        'path': dir_path + '/' if dir_path else '',
                        'isNew': meta.get('is_new', True),
                        'added': added,
                        'removed': removed,
                    })
                    total_added += added
                    total_removed += removed

        # Also include plan.md if it was written (step completion updates it)
        # Check written_files for plan.md entry
        plan_key = None
        for k in (written_files or {}):
            if k.endswith('plan.md') and k not in [f.get('_key') for f in files_data]:
                plan_key = k
                break
        if plan_key and plan_key not in [fd.get('name') for fd in files_data]:
            meta = written_files[plan_key]
            files_data.append({
                'name': os.path.basename(plan_key),
                'path': os.path.dirname(plan_key).replace('\\', '/') + '/',
                'isNew': meta.get('is_new', False),
                'added': meta.get('added', 0),
                'removed': meta.get('removed', 0),
            })
            total_added += meta.get('added', 0)
            total_removed += meta.get('removed', 0)

        structured = {
            'stepName': step_name,
            'files': files_data,
            'totalFiles': len(files_data),
            'totalAdded': total_added,
            'totalRemoved': total_removed,
            'artifactContent': artifact_content if step_id in SDD_STEPS else None,
            'artifactName': artifact_map.get(step_id) if step_id in SDD_STEPS else None,
        }

        # Build markdown for persistence (shown on reload when structured data unavailable)
        md_parts = [f"**Committed changes** &nbsp; {len(files_data)} files &nbsp; +{total_added} -{total_removed}\n"]
        for fd in files_data:
            badge = "New" if fd['isNew'] else f"+{fd['added']} -{fd['removed']}"
            md_parts.append(f"- `{fd['name']}` {fd['path']} &nbsp; {badge}")

        # Enhancement #1: Generate handoff note for SDD steps
        if step_id in SDD_STEPS:
            try:
                AgentService._generate_handoff_if_sdd(step_for_chat, workspace_path, task_id)
            except Exception:
                pass  # Non-critical — don't block step completion

        return {
            'markdown': '\n'.join(md_parts),
            'structured': structured,
        }

    @staticmethod
    def _extract_tasks_from_impl_plan(content):
        """Extract task names and descriptions from implementation-plan.md.

        Supports the formats the Qwen 3B model actually produces:
        1. ## headings: "## Setup Environment" or "## Database Models"
        2. ### Task N: headings: "### Task 1: Project Setup"
        3. Numbered list items as fallback: "1. Create database models"

        Returns a list of (name, description) tuples (max 10).
        The description is the body text below each heading until the next heading.
        """
        lines = content.split('\n')
        tasks = []
        current_name = None
        current_desc_lines = []

        # Meta headings to skip (not actual tasks)
        skip_names = {
            'overview', 'implementation plan', 'tasks', 'summary',
            'verification', 'verification steps', 'notes', 'context',
            'introduction', 'conclusion', 'references', 'appendix',
            'saving to implementation-plan.md', 'saving to implementation-plan',
            'file structure', 'project structure', 'directory structure',
            'high-level categories', 'high level categories',
            'categories', 'implementation steps', 'steps',
            'overview of requirements', 'overview of technical specifications',
            'technical specifications', 'requirements overview',
        }

        for line in lines:
            stripped = line.strip()

            # Match ONLY ## headings as top-level tasks.
            # ### and #### headings are sub-headings — fold them into the
            # parent ##'s description text (they become guidance, not steps).
            h2_match = re.match(r'^##\s+(?:Task\s+\d+[:.]\s*)?(.+)$', stripped)
            h3_match = re.match(r'^#{3,4}\s+(?:(?:Task|Sub[- ]?Step)\s+\d+[:.]\s*)?(.+)$', stripped)

            if h2_match:
                # Finalize previous task
                if current_name:
                    desc = '\n'.join(current_desc_lines).strip()
                    tasks.append((current_name, desc))

                name = h2_match.group(1).strip().rstrip(':').strip('*').strip()
                name = AgentService._sanitize_category_name(name)
                if name.lower() not in skip_names and len(name) > 2:
                    current_name = name
                    current_desc_lines = []
                else:
                    current_name = None
                    current_desc_lines = []
            elif h3_match and current_name:
                # ### sub-headings fold into the current ## task as description text
                sub_name = h3_match.group(1).strip().rstrip(':').strip('*').strip()
                current_desc_lines.append(f"- {sub_name}")
            elif current_name:
                current_desc_lines.append(line)

        # Finalize last task
        if current_name:
            desc = '\n'.join(current_desc_lines).strip()
            tasks.append((current_name, desc))

        # Fallback 1: if no ## headings found, try ### headings as top-level tasks
        if not tasks:
            current_name = None
            current_desc_lines = []
            for line in lines:
                stripped = line.strip()
                h3_match = re.match(r'^#{3,4}\s+(?:(?:Task|Sub[- ]?Step)\s+\d+[:.]\s*)?(.+)$', stripped)
                if h3_match:
                    if current_name:
                        desc = '\n'.join(current_desc_lines).strip()
                        tasks.append((current_name, desc))
                    name = h3_match.group(1).strip().rstrip(':').strip('*').strip()
                    name = AgentService._sanitize_category_name(name)
                    if name.lower() not in skip_names and len(name) > 2:
                        current_name = name
                        current_desc_lines = []
                    else:
                        current_name = None
                        current_desc_lines = []
                elif current_name:
                    current_desc_lines.append(line)
            if current_name:
                desc = '\n'.join(current_desc_lines).strip()
                tasks.append((current_name, desc))

        # Fallback 2: try numbered list items if no headings found (name only)
        if not tasks:
            for line in lines:
                stripped = line.strip()
                num_match = re.match(r'^\d+[.)]\s+(.+)$', stripped)
                if num_match:
                    name = num_match.group(1).strip().rstrip(':').strip('*').strip()
                    name = AgentService._sanitize_category_name(name)
                    if len(name) > 5 and not name.startswith('-'):
                        tasks.append((name, ''))

        # Cap at 11 steps (up to 8 code steps + 3 mandatory ending steps: env, tests, guide)
        if len(tasks) > 11:
            tasks = tasks[:11]

        return tasks

    # Common acronyms that should stay UPPERCASE after Title Case
    _ACRONYMS = {
        'cli': 'CLI', 'api': 'API', 'ui': 'UI', 'db': 'DB', 'sql': 'SQL',
        'css': 'CSS', 'html': 'HTML', 'http': 'HTTP', 'https': 'HTTPS',
        'url': 'URL', 'json': 'JSON', 'xml': 'XML', 'csv': 'CSV',
        'io': 'IO', 'id': 'ID', 'jwt': 'JWT', 'oauth': 'OAuth',
        'sdk': 'SDK', 'orm': 'ORM', 'crud': 'CRUD', 'rest': 'REST',
        'gpu': 'GPU', 'cpu': 'CPU', 'ram': 'RAM', 'ssd': 'SSD',
        'aws': 'AWS', 'gcp': 'GCP', 'ssh': 'SSH', 'tcp': 'TCP',
        'udp': 'UDP', 'dns': 'DNS', 'pdf': 'PDF', 'yaml': 'YAML',
        'toml': 'TOML', 'ini': 'INI', 'env': 'ENV', 'ci': 'CI', 'cd': 'CD',
    }

    @staticmethod
    def _fix_acronyms(text):
        """Restore common acronyms to UPPERCASE after Title Case mangles them.
        e.g. 'Cli Interface' → 'CLI Interface', 'Api Integration' → 'API Integration'
        """
        words = text.split()
        fixed = []
        for w in words:
            lower = w.lower()
            if lower in AgentService._ACRONYMS:
                fixed.append(AgentService._ACRONYMS[lower])
            else:
                fixed.append(w)
        return ' '.join(fixed)

    @staticmethod
    def _sanitize_category_name(name):
        """Clean up a category name (## heading) extracted from the implementation plan.

        Removes file extensions, Task N: prefixes, complexity labels, and
        normalizes whitespace. Truncates to max 5 words.
        """
        # Strip file extensions from the name
        # e.g., "Create app.py" -> "Create app", "Setup config.yaml" -> "Setup config"
        name = re.sub(
            r'\b\w+\.(py|js|ts|tsx|jsx|css|html|json|yaml|yml|toml|md|txt|cfg|ini|sql|sh|bat)\b',
            lambda m: m.group(0).rsplit('.', 1)[0], name
        )

        # Strip "Task N:" or "Task N." prefix the model sometimes adds
        name = re.sub(r'^Task\s+\d+[:.]\s*', '', name)

        # Strip parenthetical complexity/difficulty labels the LLM embeds
        # e.g. "(Complex)", "(Medium)", "(Simple)", "(Advanced)", etc.
        name = re.sub(
            r'\s*\((?:complex|medium|simple|intermediate|basic|advanced|expert|beginner)\)\s*',
            ' ', name, flags=re.IGNORECASE
        )

        # Also strip non-parenthetical complexity suffixes
        # e.g. "Model Training - Complex", "Testing — Simple"
        name = re.sub(
            r'\s*[-–—]\s*(?:complex|medium|simple|intermediate|basic|advanced|expert|beginner)\s*$',
            '', name, flags=re.IGNORECASE
        )

        # Normalize whitespace
        name = ' '.join(name.split())

        # Truncate to max 6 words — keep first 5 meaningful words (verb + up to 4 noun words)
        words = name.split()
        if len(words) > 6:
            name = ' '.join(words[:5])

        return name.strip()

    # Words that are too low-level / mechanical to be used alone as labels.
    # When a label is ONLY these words (1-2 words total), it needs enrichment.
    _BANNED_SOLO_WORDS = {
        'templates', 'template', 'function', 'functions', 'variable', 'variables',
        'loop', 'loops', 'file', 'files', 'script', 'scripts', 'module', 'modules',
        'class', 'classes', 'method', 'methods', 'output', 'input', 'inputs',
        'outputs', 'data', 'config', 'configs', 'setup', 'main', 'app',
        'results', 'result', 'logic', 'code', 'test', 'tests', 'utils',
        'helpers', 'constants', 'models', 'views', 'routes', 'handlers',
    }

    @staticmethod
    def _sanitize_substep_text(text):
        """Clean up a checklist sub-step line by replacing known filenames with
        descriptive text and stripping unknown file extensions.

        Preserves the original sentence structure and wording.

        Examples:
          "Create app.py with Flask factory"              → "Create application entry point with Flask factory"
          "Create models.py with Contact model"           → "Create data models with Contact model"
          "Create routes.py with CRUD endpoints"          → "Create API routes with CRUD endpoints"
          "Create requirements.txt with Flask"            → "Create Python dependencies with Flask"
          "Create config.py with settings"                → "Create configuration with settings"
          "Create validators.py with input checks"        → "Create validators with input checks"
          "Set up the main application entry point..."    → unchanged
        """
        result = text.strip()

        # Known filename → descriptive text replacements
        KNOWN_FILES = {
            'app.py': 'application entry point',
            'models.py': 'data models',
            'routes.py': 'API routes',
            'requirements.txt': 'Python dependencies',
            'package.json': 'project dependencies',
            'index.html': 'main page',
            'config.py': 'configuration',
            'database.py': 'database setup',
        }

        for filename, replacement in KNOWN_FILES.items():
            if filename in result:
                result = result.replace(filename, replacement)

        # Strip unknown file extensions: "validators.py" -> "validators"
        result = re.sub(
            r'\b(\w+)\.(py|js|ts|tsx|jsx|css|html|json|yaml|yml|toml|md|txt|cfg|ini|sql|sh|bat)\b',
            r'\1', result
        )

        # Fix redundancy: "Python dependencies with dependencies" → "Python dependencies"
        # Also catches: "API routes with all API endpoints" → "API routes"
        # General pattern: if any significant word from the replacement reappears
        # after "with (all|...)?", the trailing clause is redundant.
        STOP_WORDS = {'with', 'and', 'the', 'a', 'an', 'all', 'for', 'of', 'in', 'on', 'to'}
        for filename, replacement in KNOWN_FILES.items():
            if replacement not in result:
                continue
            rep_words = [w.lower() for w in replacement.split() if w.lower() not in STOP_WORDS]
            # Look for "replacement with ..." where the with-clause repeats a key word
            pattern = re.compile(
                re.escape(replacement) + r'\s+with\s+(.+)',
                re.IGNORECASE
            )
            match = pattern.search(result)
            if match:
                trailing = match.group(1).lower()
                for rw in rep_words:
                    if rw in trailing:
                        # Redundant — strip the "with ..." clause
                        result = result[:match.start()] + replacement + result[match.end():]
                        break

        # Clean up double spaces
        result = re.sub(r'\s{2,}', ' ', result)

        return result.strip()

    @staticmethod
    def _enrich_vague_heading(name, desc):
        """If a heading is too vague (one word, or a known spec-section name),
        enrich it using context from the Files: line or first checkbox item.

        Returns (enriched_name, desc) tuple.
        """
        # Known spec-section names that should never be step names
        VAGUE_NAMES = {
            'technology', 'structure', 'how it works', 'overview', 'complexity',
            'scope check', 'scope', 'specifications', 'specification',
            'technical specification', 'technical specifications',
            'requirements', 'architecture', 'design', 'setup', 'configuration',
            'implementation', 'testing', 'deployment', 'summary', 'notes',
        }

        name_lower = name.strip().lower()
        word_count = len(name.split())

        is_vague = (
            word_count <= 1
            or name_lower in VAGUE_NAMES
        )

        if not is_vague:
            return (name, desc)

        # Try to extract context from the description
        context_noun = None

        if desc:
            # Try Files: line first — most specific
            files_match = re.search(r'Files?:\s*(.+)', desc)
            if files_match:
                files_text = files_match.group(1).strip().split(',')[0].strip()
                # Strip extension for display
                file_base = re.sub(r'\.\w+$', '', files_text).strip()
                if file_base and len(file_base) > 1:
                    # Title-case the file base: "app" -> "App", "task_model" -> "Task Model"
                    context_noun = file_base.replace('_', ' ').replace('-', ' ').title()

            # Fallback: first checkbox item
            if not context_noun:
                checkbox_match = re.search(r'-\s*\[[ xX\->!]\]\s+(.+)', desc)
                if checkbox_match:
                    # Take first 4-5 meaningful words from the checkbox
                    words = checkbox_match.group(1).strip().split()
                    # Skip leading verbs like "Create", "Build", "Set up"
                    skip_verbs = {'create', 'build', 'set', 'add', 'implement', 'write', 'define', 'configure', 'install', 'up'}
                    meaningful = []
                    started = False
                    for w in words:
                        if not started and w.lower() in skip_verbs:
                            continue
                        started = True
                        meaningful.append(w)
                        if len(meaningful) >= 4:
                            break
                    if meaningful:
                        context_noun = ' '.join(meaningful).strip().rstrip('.,;:')

        if context_noun:
            # Combine: "Technology" + "Flask App" -> "Technology — Flask App"
            # But if the original name is truly useless, just use the context
            if name_lower in VAGUE_NAMES:
                enriched = f"{name} — {context_noun}"
            else:
                enriched = f"{name} & {context_noun}"
            return (enriched, desc)

        # Couldn't enrich — return as-is
        return (name, desc)

    # ── Action-verb heading enrichment ──────────────────────────
    # Verb forms for heading enrichment: bare verb → present participle
    _ING_VERBS = {
        'create': 'Creating', 'build': 'Building', 'implement': 'Implementing',
        'configure': 'Configuring', 'integrate': 'Integrating', 'craft': 'Crafting',
        'initialize': 'Initializing', 'design': 'Designing', 'add': 'Adding',
        'set': 'Setting Up', 'setup': 'Setting Up', 'define': 'Defining',
        'develop': 'Developing', 'establish': 'Establishing', 'write': 'Writing',
        'install': 'Installing', 'connect': 'Connecting', 'generate': 'Generating',
        'make': 'Creating', 'prepare': 'Preparing', 'construct': 'Constructing',
    }

    # Present participles that indicate the heading already has a verb
    _ING_PREFIXES = {
        'creating', 'building', 'implementing', 'configuring', 'integrating',
        'crafting', 'initializing', 'designing', 'adding', 'setting',
        'defining', 'developing', 'establishing', 'writing', 'installing',
        'connecting', 'generating', 'preparing', 'constructing',
    }

    # Mapping from first noun → a contextually appropriate default verb
    _NOUN_TO_VERB = {
        'core': 'Building', 'application': 'Building', 'app': 'Building',
        'project': 'Initializing', 'setup': 'Setting Up', 'environment': 'Configuring',
        'config': 'Configuring', 'configuration': 'Configuring', 'settings': 'Configuring',
        'database': 'Implementing', 'db': 'Implementing', 'storage': 'Implementing',
        'api': 'Creating', 'routes': 'Creating', 'endpoints': 'Creating',
        'cli': 'Crafting', 'interface': 'Crafting', 'ui': 'Crafting',
        'output': 'Implementing', 'formatting': 'Implementing', 'display': 'Building',
        'error': 'Integrating', 'handling': 'Integrating', 'logging': 'Integrating',
        'test': 'Writing', 'tests': 'Writing', 'testing': 'Writing',
        'auth': 'Implementing', 'authentication': 'Implementing',
        'data': 'Implementing', 'models': 'Implementing', 'model': 'Implementing',
        'rendering': 'Building', 'visualization': 'Building',
        'input': 'Implementing', 'parser': 'Building', 'parsing': 'Implementing',
        'utility': 'Creating', 'utilities': 'Creating', 'helpers': 'Creating',
        'server': 'Building', 'client': 'Building', 'frontend': 'Building',
        'backend': 'Building', 'middleware': 'Implementing',
        'report': 'Generating', 'reports': 'Generating', 'reporting': 'Generating',
        'web': 'Building', 'page': 'Building', 'pages': 'Building',
        'file': 'Creating', 'files': 'Creating',
    }

    @staticmethod
    def _ensure_action_verb(name):
        """Ensure a heading contains an action verb. Returns the name as-is
        if any word is already a verb form. Only prepends a verb if the
        heading is purely nouns.

        The prompt allows verbs at the START or END of the phrase, so we
        check ALL words — not just the first.

        Examples:
            'Building Data Layer'      -> 'Building Data Layer'  (unchanged — starts with -ing)
            'Page Styling'             -> 'Page Styling'         (unchanged — ends with -ing)
            'Weather API Integration'  -> 'Weather API Integration' (unchanged — has action noun)
            'Create API Routes'        -> 'Creating API Routes'  (bare verb → -ing)
            'Application Core'         -> 'Building Application Core' (no verb → prepend)
        """
        if not name or not name.strip():
            return name

        words = name.strip().split()

        # Check if ANY word is already an -ing verb (not just the first)
        for w in words:
            wl = w.lower()
            # Known -ing prefix
            if wl in AgentService._ING_PREFIXES:
                return name
            # Any word ending in -ing that's 5+ chars (avoids "king", "ring")
            if wl.endswith('ing') and len(wl) >= 5:
                return name

        # Check if ANY word is an action-related noun (integration, setup, etc.)
        _ACTION_NOUNS = {
            'integration', 'setup', 'configuration', 'implementation',
            'processing', 'validation', 'formatting', 'rendering',
            'handling', 'generation', 'migration', 'optimization',
        }
        for w in words:
            if w.lower() in _ACTION_NOUNS:
                return name

        # First word is a bare verb we know — convert to -ing form
        first = words[0].lower()
        if first in AgentService._ING_VERBS:
            ing_form = AgentService._ING_VERBS[first]
            if ing_form == 'Setting Up':
                rest = words[1:]
                if rest and rest[0].lower() == 'up':
                    rest = rest[1:]
                return f"Setting Up {' '.join(rest)}".strip()
            return f"{ing_form} {' '.join(words[1:])}".strip()

        # No verb found — look up first noun for a suitable verb
        verb = AgentService._NOUN_TO_VERB.get(first, 'Building')
        return f"{verb} {name}".strip()

    @staticmethod
    def _inject_subtasks_into_plan(workspace_path, task_id):
        """After Planning completes, parse implementation-plan.md and rewrite
        plan.md — replace the flat 'Implementation' step with individual
        top-level steps, each with its own description.

        Preserves all prior steps (Requirements [x], Tech Spec [x], Planning [x])
        and their chat-id comments verbatim.
        """
        from services.plan_engine import parse_plan, _atomic_write

        artifacts_dir = os.path.join(workspace_path, '.sentinel', 'tasks', task_id)
        impl_plan_path = os.path.join(artifacts_dir, 'implementation-plan.md')
        plan_path = os.path.join(artifacts_dir, 'plan.md')

        if not os.path.exists(impl_plan_path):
            return

        with open(impl_plan_path, 'r', encoding='utf-8') as f:
            impl_content = f.read()

        task_entries = AgentService._extract_tasks_from_impl_plan(impl_content)

        if not task_entries:
            return

        # Parse existing plan.md to find the Implementation step
        plan = parse_plan(plan_path)
        impl_step = plan.find_step('implementation')

        if impl_step is None:
            return

        lines = list(plan.raw_lines)
        impl_line = impl_step.line_number

        # Find where the Implementation step's content ends
        # (next root step's line, or end of file)
        impl_end = len(lines)
        for s in plan.steps:
            if s.line_number > impl_line:
                impl_end = s.line_number
                break

        # Build new top-level steps to REPLACE Implementation
        # Each heading becomes a flat, executable step (no children).
        # Checklist items from the impl plan are converted to plain description
        # bullets — guidance text for the agent, NOT parseable child steps.
        new_lines = []
        for name, desc in task_entries:
            # Apply post-processing helpers
            name = AgentService._fix_acronyms(name)
            name, desc = AgentService._enrich_vague_heading(name, desc)
            # Note: _ensure_action_verb() removed — the planning prompt guides
            # the LLM to write good action-oriented headings naturally.
            new_lines.append(f"### [ ] Step: {name}")
            new_lines.append("")
            if desc:
                # Format description as clean, professional bullet points.
                # Merge checkbox items with their Notes: lines into single
                # bullets: "**Label** — description text" for a polished UI look.
                # The raw technical detail stays in the description for the LLM.
                desc_lines = desc.split('\n')
                i = 0
                first_line = True
                while i < len(desc_lines):
                    stripped = desc_lines[i].strip()
                    if not stripped:
                        i += 1
                        continue

                    # Check for checkbox item (sub-step label)
                    checkbox_match = re.match(r'^-\s*\[[ xX\->!]\]\s+(.+)$', stripped)
                    if checkbox_match:
                        label = AgentService._sanitize_substep_text(checkbox_match.group(1).strip())
                        # Look ahead for a Notes: line
                        notes_text = ''
                        if i + 1 < len(desc_lines):
                            next_line = desc_lines[i + 1].strip()
                            notes_match = re.match(r'^-?\s*Notes?:\s*(.+)$', next_line)
                            if notes_match:
                                notes_text = notes_match.group(1).strip()
                                i += 1  # consume the Notes line
                        if notes_text:
                            new_lines.append(f"- **{label}** — {notes_text}")
                        else:
                            new_lines.append(f"- **{label}**")
                    elif re.match(r'^-?\s*Notes?:\s*(.+)$', stripped):
                        # Orphan Notes: line (no preceding checkbox) — keep as-is
                        notes_match = re.match(r'^-?\s*Notes?:\s*(.+)$', stripped)
                        new_lines.append(f"  {notes_match.group(1).strip()}")
                    elif first_line or re.match(r'^(?:Files?:|Modifies?:|Depends on:|Entry point:)', stripped):
                        # First line (description sentence) or metadata — keep verbatim
                        new_lines.append(stripped)
                    else:
                        new_lines.append(stripped)
                    first_line = False
                    i += 1
                new_lines.append("")

        # Splice: keep lines before Implementation, insert new steps,
        # keep any lines after (shouldn't be any normally)
        final_lines = lines[:impl_line] + new_lines + lines[impl_end:]

        _atomic_write(plan_path, final_lines)

    @staticmethod
    def _seed_prior_artifacts(workspace_path, task_id, step_id, artifacts_path, max_seed_chars=4000, step_description=''):
        """Read key artifacts from disk and return them as pre-seeded context messages.

        This injects artifact content directly into the conversation history so the
        3B model doesn't need to discover/read them via tool calls (which it often skips).

        IMPORTANT: plan.md MUST be seeded for the Requirements step. It contains the
        task description and workflow steps that the agent needs to follow. Without it,
        the agent has no context about what to build. The agent's ListFiles should also
        show plan.md in the artifacts directory — if it doesn't, the step_id matching
        is broken (see the name-based fallback in continue_chat_stream).
        """
        seeded_messages = []
        abs_artifacts = os.path.join(workspace_path, '.sentinel', 'tasks', task_id)

        # Define which files to pre-read for each step.
        # plan.md is the dynamic master document containing task scope, boundaries,
        # and agent rules. It goes FIRST so the agent reads it before any artifacts.
        files_to_seed = {
            'requirements': ['plan.md'],
            'technical-specification': ['plan.md', 'requirements.md'],
            'planning': ['plan.md', 'requirements.md', 'spec.md'],
        }
        # Default for implementation/dynamic steps — seed ALL prior artifacts
        seed_list = files_to_seed.get(step_id, ['implementation-plan.md', 'spec.md', 'requirements.md'])

        _safe_log(f"[Seed] Step '{step_id}': seeding {seed_list} from {abs_artifacts}")

        for filename in seed_list:
            filepath = os.path.join(abs_artifacts, filename)
            if os.path.exists(filepath):
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        content = f.read()
                    if content.strip():
                        # For plan.md in early steps, strip future step descriptions
                        # to prevent the model from proactively creating files for later steps
                        if filename == 'plan.md' and step_id in ('requirements', 'technical-specification', 'planning'):
                            filtered_lines = []
                            found_current = False
                            past_current = False
                            for line in content.split('\n'):
                                # Detect step headings like "### [ ] Step: Requirements"
                                if '### [' in line and 'Step:' in line:
                                    if step_id.replace('-', ' ') in line.lower():
                                        found_current = True
                                    elif found_current:
                                        past_current = True
                                if not past_current:
                                    filtered_lines.append(line)
                            content = '\n'.join(filtered_lines)

                        # Enhancement #6: Cross-reference spec complexity with user slider
                        if filename == 'spec.md' and step_id == 'planning':
                            spec_complexity_match = re.search(r'Complexity:\s*(SIMPLE|MEDIUM|COMPLEX)', content)
                            if spec_complexity_match:
                                try:
                                    _task_data = TaskService.get_task(task_id)
                                    _user_val = _task_data.get('settings', {}).get('complexity', 5) if _task_data else 5
                                    _user_label = "SIMPLE" if _user_val <= 3 else "MEDIUM" if _user_val <= 7 else "COMPLEX"
                                    if spec_complexity_match.group(1) != _user_label:
                                        content += (
                                            f"\n\n*** COMPLEXITY MISMATCH: spec says {spec_complexity_match.group(1)}, "
                                            f"user rated {_user_val}/10 (={_user_label}). "
                                            f"Use the HIGHER of the two when deciding step count. ***"
                                        )
                                        _safe_log(f"[Seed] Complexity mismatch: spec={spec_complexity_match.group(1)}, user={_user_label}")
                                except Exception:
                                    pass

                        # Enhancement #1: Prepend handoff note from the step that produced this artifact
                        _artifact_to_step = {
                            'requirements.md': 'requirements',
                            'spec.md': 'technical-specification',
                            'implementation-plan.md': 'planning',
                        }
                        _source_step = _artifact_to_step.get(filename)
                        if _source_step:
                            _handoff_path = os.path.join(abs_artifacts, f"{_source_step}.handoff")
                            if os.path.exists(_handoff_path):
                                try:
                                    from prompts.handoff import format_handoff_note
                                    with open(_handoff_path, 'r', encoding='utf-8') as _hf:
                                        _handoff_data = json.load(_hf)
                                    _handoff_text = format_handoff_note(_handoff_data)
                                    if _handoff_text:
                                        content = f"{_handoff_text}\n\n---\n\n{content}"
                                        _safe_log(f"[Seed] Prepended handoff note for {filename} ({len(_handoff_text)} chars)")
                                except Exception:
                                    pass

                        if len(content) > max_seed_chars:
                            content = content[:max_seed_chars] + "\n...(truncated)"
                        display_path = filename if artifacts_path == '.' else f"{artifacts_path}/{filename}"
                        seeded_messages.append({
                            "role": "user",
                            "content": f"I read {display_path} for you. Here is the content:\n\n{content}"
                        })
                        seeded_messages.append({
                            "role": "assistant",
                            "content": f"Thank you. I have reviewed {filename}. I'll use this as context for my work on this step."
                        })
                        _safe_log(f"[Seed] Seeded {filename} ({len(content)} chars)")

                        # Enhancement #3: Extract relevant acceptance criteria for impl steps
                        if filename == 'requirements.md' and step_id not in ('requirements', 'technical-specification', 'planning'):
                            try:
                                from prompts.context_wiring import extract_relevant_criteria
                                criteria_text = extract_relevant_criteria(step_description, content)
                                if criteria_text:
                                    seeded_messages.append({"role": "user", "content": criteria_text})
                                    seeded_messages.append({
                                        "role": "assistant",
                                        "content": "Understood. I will focus on implementing these specific acceptance criteria for this step."
                                    })
                                    _safe_log(f"[Seed] Injected relevant acceptance criteria ({len(criteria_text)} chars)")
                            except Exception as e:
                                _safe_log(f"[Seed] Error extracting criteria: {e}")

                    else:
                        _safe_log(f"[Seed] {filename} exists but is empty!")
                except Exception as e:
                    _safe_log(f"[Seed] Error reading {filename}: {e}")
            else:
                _safe_log(f"[Seed] {filename} not found at {filepath}")

        # ── Seed existing CODE files for implementation steps ──
        # This is the key fix: each implementation sub-step runs in its own
        # chat session and has NO knowledge of what previous steps wrote.
        # By pre-loading the actual code files, the model can build on them
        # instead of rewriting from scratch each time.
        # Uses os.walk() to find files in subdirectories too (e.g. src/app.py).
        SDD_STEPS = {'requirements', 'technical-specification', 'planning'}
        if step_id not in SDD_STEPS:
            # Enhancement #5: Inject step completion ledger
            try:
                from prompts.context_wiring import build_completion_ledger
                _ledger_task = TaskService.get_task(task_id)
                if _ledger_task:
                    _chats_dir = os.path.join(Config.STORAGE_DIR, 'chats')
                    _ledger = build_completion_ledger(
                        _ledger_task.get('steps', []), step_id, task_id, _chats_dir
                    )
                    if _ledger:
                        seeded_messages.append({"role": "user", "content": _ledger})
                        seeded_messages.append({
                            "role": "assistant",
                            "content": "Understood. I can see what previous steps produced. I will build on their work."
                        })
                        _safe_log(f"[Seed] Injected completion ledger ({len(_ledger)} chars)")
            except Exception as e:
                _safe_log(f"[Seed] Error building completion ledger: {e}")

            # ── Seed execution log warnings for implementation steps ──
            # If the execution agent ran previously and recorded warnings
            # (dep failures, runtime errors, auto-fixes), inject them so the
            # main agent can reason about and fix those issues in its code.
            try:
                _exec_log_path = os.path.join(abs_artifacts, 'execution.log')
                if os.path.isfile(_exec_log_path):
                    with open(_exec_log_path, 'r', encoding='utf-8') as _ef:
                        _exec_data = json.load(_ef)
                    _exec_lines = []
                    if not _exec_data.get('success'):
                        _exec_lines.append(f"- Project execution FAILED after {_exec_data.get('attempts', '?')} attempts")
                    for _w in _exec_data.get('warnings', []):
                        _exec_lines.append(f"- WARNING: {_w}")
                    for _fix in _exec_data.get('fixes', [])[:5]:
                        _fp = _fix.get('path', '')
                        _ft = _fix.get('tool', '')
                        if _fp:
                            _exec_lines.append(f"- Auto-fix applied: {_ft} on {_fp}")
                    _final_out = _exec_data.get('final_output', '')
                    if _final_out and not _exec_data.get('success'):
                        _exec_lines.append(f"- Last error output: {_final_out[:300]}")
                    if _exec_lines:
                        _exec_seed = (
                            "## Execution Agent Results (from previous run)\n"
                            "The execution agent tested this project and found the following:\n"
                            + '\n'.join(_exec_lines) + '\n\n'
                            "If there are warnings or failures, address them in your implementation. "
                            "Fix broken dependencies in requirements.txt (remove invalid version pins). "
                            "Fix any runtime errors in the source code."
                        )
                        seeded_messages.append({"role": "user", "content": _exec_seed})
                        seeded_messages.append({
                            "role": "assistant",
                            "content": "I see the execution results. I will address any warnings and fix any runtime issues in my implementation."
                        })
                        _safe_log(f"[Seed] Injected execution log ({len(_exec_lines)} items, success={_exec_data.get('success')})")
            except Exception as e:
                _safe_log(f"[Seed] Error reading execution log: {e}")

            # ── Seed review summary for implementation steps ──
            # If the review agent ran on a previous step and found issues,
            # inject the summary so the main agent can avoid repeating mistakes.
            try:
                _review_summary_path = os.path.join(abs_artifacts, 'review-summary.json')
                if os.path.isfile(_review_summary_path):
                    with open(_review_summary_path, 'r', encoding='utf-8') as _rsf:
                        _review_data = json.load(_rsf)
                    _review_lines = []
                    _n_issues = _review_data.get('issues_found', 0)
                    _n_edits = _review_data.get('edits_made', 0)
                    if _n_issues > 0 or _n_edits > 0:
                        _review_lines.append(f"- Review found {_n_issues} issue(s) and made {_n_edits} edit(s)")
                    for _ri in _review_data.get('issues', [])[:8]:
                        _review_lines.append(f"- Issue: {_ri}")
                    for _rw in _review_data.get('warnings', [])[:5]:
                        _review_lines.append(f"- Warning: {_rw}")
                    _edited = _review_data.get('edited_files', [])
                    if _edited:
                        _review_lines.append(f"- Files edited by review: {', '.join(_edited[:10])}")
                    if _review_lines:
                        _review_seed = (
                            "## Review Agent Findings (from previous review pass)\n"
                            "The review agent found the following issues in this project. "
                            "Avoid these patterns in your implementation:\n"
                            + '\n'.join(_review_lines) + '\n'
                        )
                        seeded_messages.append({"role": "user", "content": _review_seed})
                        seeded_messages.append({
                            "role": "assistant",
                            "content": "I see the review findings. I will avoid these issues and ensure my code passes review."
                        })
                        _safe_log(f"[Seed] Injected review summary ({len(_review_lines)} items)")
            except Exception as e:
                _safe_log(f"[Seed] Error reading review summary: {e}")

            from prompts.context_wiring import CODE_EXTENSIONS
            code_files = {}
            SKIP_DIRS = {'.git', '__pycache__', 'node_modules', '.venv', 'venv', '.sentinel', '.DS_Store'}
            try:
                for root, dirs, files in os.walk(workspace_path):
                    dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith('.')]
                    for fname in sorted(files):
                        if fname.startswith('.'):
                            continue
                        _, ext = os.path.splitext(fname)
                        if ext.lower() not in CODE_EXTENSIONS:
                            continue
                        fpath = os.path.join(root, fname)
                        rel = os.path.relpath(fpath, workspace_path).replace('\\', '/')
                        try:
                            with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                                code_files[rel] = f.read()
                        except Exception:
                            pass
            except Exception as e:
                _safe_log(f"[Seed] Error scanning workspace for code files: {e}")

            if code_files:
                # Enhancement #4: Prioritize files from Depends-on/Modifies metadata
                _priority_files = []
                if step_description:
                    for _pat in [r'Depends?\s*on:\s*(.+)', r'Modifies?:\s*(.+)']:
                        _dep_match = re.search(_pat, step_description)
                        if _dep_match:
                            _parts = re.split(r'\s*,\s*', _dep_match.group(1))
                            _priority_files.extend(
                                p.strip().strip('`') for p in _parts if '.' in p
                            )
                code_context = build_code_context(code_files, priority_files=_priority_files or None)
                if code_context:
                    seeded_messages.append({
                        "role": "user",
                        "content": code_context
                    })
                    seeded_messages.append({
                        "role": "assistant",
                        "content": (
                            "Thank you. I have carefully reviewed all existing code files. "
                            "I will build on top of this existing code — I will NOT rewrite "
                            "files from scratch. When I modify an existing file, I will use "
                            "EditFile with the exact old_string to find and new_string to replace."
                        )
                    })
                    _safe_log(f"[Seed] Seeded {len(code_files)} code files: {list(code_files.keys())}")
            else:
                _safe_log(f"[Seed] No existing code files found in workspace (first implementation step)")

        return seeded_messages

    # ── Micro-task helpers ──────────────────────────────────────────────

    @staticmethod
    def _extract_json_from_response(response: str) -> dict | None:
        """Extract a JSON object from an LLM response.

        Handles GPT-OSS quirks: markdown fencing, commentary before/after,
        single quotes, trailing commas, etc.

        Strategies tried in order:
        1. Direct json.loads() on stripped response
        2. Extract from ```json ... ``` fenced block
        3. Extract from ``` ... ``` fenced block
        4. First { to last } substring
        5. _sanitize_tool_json() then retry 1-4
        """
        if not response or not response.strip():
            return None

        text = response.strip()

        def _try_parse(s):
            try:
                result = json.loads(s)
                if isinstance(result, dict):
                    return result
            except (json.JSONDecodeError, ValueError):
                pass
            return None

        # Strategy 1: direct parse
        r = _try_parse(text)
        if r:
            return r

        # Strategy 2: ```json fenced block
        for block in re.findall(r'```json\s*\n?(.*?)```', text, re.DOTALL):
            r = _try_parse(block.strip())
            if r:
                return r

        # Strategy 3: ``` fenced block (no language tag)
        for block in re.findall(r'```\s*\n?(.*?)```', text, re.DOTALL):
            r = _try_parse(block.strip())
            if r:
                return r

        # Strategy 4: first { to last }
        first_brace = text.find('{')
        last_brace = text.rfind('}')
        if first_brace >= 0 and last_brace > first_brace:
            candidate = text[first_brace:last_brace + 1]
            r = _try_parse(candidate)
            if r:
                return r

        # Strategy 5: sanitize then retry
        sanitized = AgentService._sanitize_tool_json(text)
        r = _try_parse(sanitized)
        if r:
            return r

        # Strategy 5b: sanitize the { to } substring
        if first_brace >= 0 and last_brace > first_brace:
            sanitized_sub = AgentService._sanitize_tool_json(
                text[first_brace:last_brace + 1]
            )
            r = _try_parse(sanitized_sub)
            if r:
                return r

        return None

    @staticmethod
    def _default_scope(task_details: str) -> dict:
        """Fallback scope data when LLM fails to produce valid JSON.

        Uses regex-based detection from the legacy requirements prompt module.
        """
        from prompts.requirements import _detect_deliverable_type, _detect_quality_level
        return {
            'complexity': 'medium',
            'components': ['Core Functionality'],
            'risks': ['Requirements may need clarification'],
            'deliverable_type': _detect_deliverable_type(task_details),
            'quality_level': _detect_quality_level(task_details).lower(),
            'summary': task_details[:200],
        }

    @staticmethod
    def _run_json_phase(
        *,
        phase_name: str,
        prompt: str,
        history: list,
        llm,
        cancel_event,
        stream_state: dict,
        chat_id: str,
        task_id: str,
        required_keys: list,
        max_retries: int = 2,
    ):
        """Run a single micro-phase expecting JSON output.

        Injects `prompt` as a user message, streams the LLM response,
        extracts JSON, validates required keys. Retries on failure.

        Yields SSE events (thinking, message tokens).
        Returns the parsed JSON dict via a mutable result wrapper.

        NOTE: This is a generator — call it with `yield from`. The parsed
        result is returned via a mutable container passed in and out, because
        Python generators can't return values through `yield from` in the
        SSE streaming pattern. Instead, we use a convention: the caller reads
        the result from `_json_phase_result` attribute set on the class.
        """
        TPFX = LLMEngine.THINK_PREFIX
        result_data = [None]  # mutable container for the result

        for attempt in range(1, max_retries + 2):  # +1 for initial try
            if cancel_event and cancel_event.is_set():
                break

            # Inject phase prompt as user message
            AgentService.add_message(task_id, chat_id, "user", prompt,
                                     meta={"is_micro_phase": True, "phase": phase_name})
            history.append({"role": "user", "content": prompt})

            # Compute output budget
            input_tokens = llm.count_tokens(history)
            model_ctx = llm.context_size or 32768
            max_output = min(4096, max(512, model_ctx - input_tokens - 256))

            _safe_log(
                f"[MicroTask] Phase '{phase_name}' attempt {attempt}/{max_retries + 1} | "
                f"input={input_tokens} max_out={max_output}"
            )

            full_response = ""
            yield f"event: start\ndata: {json.dumps({'chatId': chat_id})}\n\n"
            yield ": heartbeat\n\n"

            try:
                for token in llm.stream_chat(history, max_new_tokens=max_output,
                                              temperature=0.3, cancel_event=cancel_event, read_timeout=120):
                    if token.startswith(TPFX):
                        yield f"event: thinking\ndata: {json.dumps({'token': token[len(TPFX):]})}\n\n"
                        continue
                    full_response += token
                    stream_state["unsaved"] = full_response
                    # JSON phase output goes to thinking — NOT visible chat text
                    yield f"event: thinking\ndata: {json.dumps({'token': token})}\n\n"
            except Exception as e:
                _safe_log(f"[MicroTask] LLM error in phase '{phase_name}': {e}")
                break

            if not full_response.strip():
                _safe_log(f"[MicroTask] Empty response in phase '{phase_name}'")
                break

            # Save assistant response (mark as internal micro-phase so UI hides it)
            AgentService.add_message(task_id, chat_id, "assistant", full_response,
                                     meta={"is_micro_phase": True, "phase": phase_name})
            history.append({"role": "assistant", "content": full_response})

            # Extract and validate JSON
            parsed = AgentService._extract_json_from_response(full_response)
            if parsed:
                missing = [k for k in required_keys if k not in parsed]
                if not missing:
                    _safe_log(f"[MicroTask] Phase '{phase_name}' succeeded: {list(parsed.keys())}")
                    result_data[0] = parsed
                    break
                else:
                    _safe_log(f"[MicroTask] Phase '{phase_name}' missing keys: {missing}")
            else:
                _safe_log(f"[MicroTask] Phase '{phase_name}' failed to extract JSON")

            # Retry with terse correction prompt
            if attempt <= max_retries:
                keys_str = ', '.join(required_keys)
                prompt = (
                    f"Your response was not valid JSON or was missing required keys. "
                    f"Output ONLY a JSON object with these keys: {keys_str}. "
                    f"No markdown fencing, no commentary, no explanation. Just the JSON."
                )

        # Store result for caller to retrieve
        AgentService._json_phase_result = result_data[0]
        return

    @staticmethod
    def _run_assemble_phase(
        *,
        prompt: str,
        history: list,
        llm,
        tool_service,
        cancel_event,
        stream_state: dict,
        chat_id: str,
        task_id: str,
        step_for_chat: dict,
        workspace_path: str,
        artifacts_dir: str,
        artifacts_path: str,
        written_files: dict,
        all_steps: list,
    ):
        """Phase 3: Assemble requirements.md from structured data.

        Runs a mini agent loop (max 5 turns) that handles WriteFile tool calls
        and step completion. Reuses existing tool extraction and validation logic.

        Yields SSE events for the full streaming experience.
        """
        TPFX = LLMEngine.THINK_PREFIX
        SDD_STEPS = {'requirements', 'technical-specification', 'planning'}

        # Inject the assemble prompt
        AgentService.add_message(task_id, chat_id, "user", prompt,
                                 meta={"is_micro_phase": True, "phase": "assemble"})
        history.append({"role": "user", "content": prompt})

        best_writefile_content = ""
        nudge_count = 0
        tool_call_index = 0

        for turn in range(1, 6):  # max 5 turns
            if cancel_event and cancel_event.is_set():
                break

            input_tokens = llm.count_tokens(history)
            model_ctx = llm.context_size or 32768
            max_output = min(16384, max(2048, model_ctx - input_tokens - 256))

            _safe_log(
                f"[MicroTask] Assemble turn {turn}/5 | "
                f"input={input_tokens} max_out={max_output}"
            )

            if max_output < 1024:
                error_msg = f"Prompt too large for model context ({input_tokens} tokens)"
                yield f"event: error\ndata: {json.dumps({'error': error_msg})}\n\n"
                break

            full_response = ""
            yield f"event: start\ndata: {json.dumps({'chatId': chat_id})}\n\n"
            yield ": heartbeat\n\n"

            try:
                for token in llm.stream_chat(history, max_new_tokens=max_output,
                                              temperature=0.4, cancel_event=cancel_event, read_timeout=120):
                    if token.startswith(TPFX):
                        yield f"event: thinking\ndata: {json.dumps({'token': token[len(TPFX):]})}\n\n"
                        continue
                    full_response += token
                    stream_state["unsaved"] = full_response
                    # Assemble narration is visible in chat (like tech-spec/planning).
                    # The frontend's parseSegments() handles <tool_code> blocks.
                    yield f"data: {json.dumps({'token': token})}\n\n"
            except Exception as e:
                _safe_log(f"[MicroTask] Assemble LLM error: {e}")
                break

            if not full_response.strip():
                _safe_log(f"[MicroTask] Empty response in assemble turn {turn}")
                break

            # Save assistant response
            AgentService.add_message(task_id, chat_id, "assistant", full_response)
            history.append({"role": "assistant", "content": full_response})

            # ── Extract tool calls ──
            tool_matches = re.findall(r'<tool_code>(.*?)</tool_code>', full_response, re.DOTALL)
            # GPT-OSS format — accept any channel type (commentary, analysis, code, etc.)
            gptoss_matches = re.findall(
                r'<\|channel\|>\w+\s+to=(\w+)\s*(?:<\|constrain\|>json)?[^<]*<\|message\|>(.*?)(?=<\|channel\|>|\Z)',
                full_response, re.DOTALL
            )
            for tool_name_hint, tool_body in gptoss_matches:
                body = tool_body.strip()
                try:
                    parsed = json.loads(body)
                    if 'name' not in parsed:
                        body = json.dumps({"name": tool_name_hint, "arguments": parsed})
                except (json.JSONDecodeError, ValueError):
                    if '"name"' not in body:
                        body = '{"name": "' + tool_name_hint + '", "arguments": ' + body + '}'
                tool_matches.append(body)

            # Bare JSON fallback
            if not tool_matches:
                for m in re.finditer(
                    r'\{"name"\s*:\s*"(WriteFile|EditFile|ReadFile|ListFiles|RunCommand)"'
                    r'\s*,\s*"arguments"\s*:\s*\{',
                    full_response
                ):
                    start = m.start()
                    depth = 0
                    end = start
                    in_string = False
                    i = start
                    while i < len(full_response):
                        ch = full_response[i]
                        if in_string:
                            if ch == '\\' and i + 1 < len(full_response):
                                i += 2
                                continue
                            elif ch == '"':
                                in_string = False
                        else:
                            if ch == '"':
                                in_string = True
                            elif ch == '{':
                                depth += 1
                            elif ch == '}':
                                depth -= 1
                                if depth == 0:
                                    end = i + 1
                                    break
                        i += 1
                    if end > start:
                        candidate = full_response[start:end]
                        try:
                            p = json.loads(candidate)
                            if 'name' in p and 'arguments' in p:
                                tool_matches.append(candidate)
                        except (json.JSONDecodeError, ValueError):
                            pass

            # ── Truncated WriteFile salvage ──
            # If no complete tool JSON was found, try to extract content from a
            # truncated WriteFile call (LLM hit max tokens mid-JSON).
            if not tool_matches and '"WriteFile"' in full_response:
                trunc_match = re.search(
                    r'"name"\s*:\s*"WriteFile".*?"path"\s*:\s*"([^"]+)".*?"content"\s*:\s*"((?:[^"\\]|\\.)*)',
                    full_response, re.DOTALL
                )
                if trunc_match:
                    trunc_path = trunc_match.group(1)
                    trunc_content = trunc_match.group(2)
                    # Unescape JSON string escapes
                    try:
                        trunc_content = trunc_content.encode().decode('unicode_escape')
                    except Exception:
                        trunc_content = trunc_content.replace('\\n', '\n').replace('\\t', '\t').replace('\\"', '"')
                    if len(trunc_content) > 200 and len(trunc_content) > len(best_writefile_content):
                        best_writefile_content = trunc_content
                        _safe_log(f"[MicroTask] Salvaged {len(trunc_content)} chars from truncated WriteFile JSON (path={trunc_path})")

            # ── Execute tool calls ──
            for tool_raw in tool_matches:
                tool_json = tool_raw.strip()
                tool_json = re.sub(r'^```json\s*', '', tool_json)
                tool_json = re.sub(r'```$', '', tool_json).strip()
                tool_json = AgentService._sanitize_tool_json(tool_json)

                tool_call = None
                try:
                    tool_call = json.loads(tool_json)
                except json.JSONDecodeError:
                    tool_call = AgentService._extract_tool_call_fallback(tool_raw.strip())
                    if tool_call is None:
                        tool_call = AgentService._extract_tool_call_fallback(tool_json)

                if tool_call is None:
                    continue

                tool_name = tool_call.get('name')
                tool_args = tool_call.get('arguments', {})

                # Only allow WriteFile for requirements step
                if tool_name not in ('WriteFile',):
                    _safe_log(f"[MicroTask] Blocked tool '{tool_name}' in assemble phase")
                    continue

                # Emit tool call event
                yield f"event: tool_call\ndata: {json.dumps({'tool': tool_name, 'args': tool_args, 'index': tool_call_index})}\n\n"

                # Track content for fallback
                content = tool_args.get('content', '')
                if len(content) > len(best_writefile_content):
                    best_writefile_content = content

                # Execute
                result = tool_service.execute_tool(tool_name, tool_args)
                yield ": heartbeat\n\n"
                yield f"event: tool_result\ndata: {json.dumps({'result': result, 'index': tool_call_index})}\n\n"
                tool_call_index += 1

                if result.startswith('Successfully'):
                    written_path = tool_args.get('path', '')
                    yield f"event: file_written\ndata: {json.dumps({'path': written_path})}\n\n"
                    meta = AgentService._parse_write_meta(result)
                    written_files[written_path] = meta

                    # ── Auto-complete: if the written file IS the expected artifact and valid, complete now ──
                    expected_artifact = AgentService._get_expected_artifact(
                        step_for_chat['id'],
                        os.path.join(workspace_path, '.sentinel', 'tasks', task_id)
                    )
                    if expected_artifact:
                        written_basename = os.path.basename(written_path)
                        expected_basename = os.path.basename(expected_artifact)
                        if written_basename == expected_basename and os.path.exists(expected_artifact):
                            try:
                                with open(expected_artifact, 'r', encoding='utf-8', errors='replace') as f:
                                    artifact_content = f.read()
                                is_valid, _reason = AgentService._validate_artifact_content(
                                    artifact_content, expected_basename
                                )
                                if is_valid:
                                    _safe_log(f"[MicroTask] AutoComplete: artifact '{expected_basename}' written and valid, completing step")
                                    yield f"event: thinking\ndata: {json.dumps({'token': chr(10) + chr(10) + chr(9989) + ' Step complete ' + chr(8212) + ' artifact saved and validated.' + chr(10)})}\n\n"
                                    # Add tool result to history before completing
                                    history.append({"role": "user", "content": f"Tool Result: {result}"})
                                    AgentService.add_message(task_id, chat_id, "user", f"Tool Result: {result}",
                                                             meta={"is_tool_result": True})
                                    # Mark step completed
                                    try:
                                        fresh_task = TaskService.get_task(task_id)
                                        fresh_step = AgentService._find_step_by_chat_id(
                                            fresh_task.get('steps', []), chat_id
                                        )
                                        if fresh_step and fresh_step['status'] == 'in_progress':
                                            TaskService.update_step_in_plan(
                                                workspace_path, task_id, step_for_chat['id'],
                                                {'status': 'completed'}
                                            )
                                            _safe_log(f"[MicroTask] Step {step_for_chat['id']} marked completed")
                                            try:
                                                summary_data = AgentService._build_step_summary(
                                                    step_for_chat, workspace_path, task_id, written_files
                                                )
                                                if summary_data:
                                                    AgentService.add_message(
                                                        task_id, chat_id, "assistant",
                                                        summary_data['markdown'],
                                                        meta={"is_summary": True, "structured": summary_data['structured']}
                                                    )
                                                    yield f"event: step_summary\ndata: {json.dumps({'content': summary_data['markdown'], 'structured': summary_data['structured']})}\n\n"
                                            except Exception as e:
                                                _safe_log(f"[MicroTask] Summary error: {e}")
                                            yield f"event: step_completed\ndata: {json.dumps({'stepId': step_for_chat['id']})}\n\n"
                                    except Exception as e:
                                        _safe_log(f"[MicroTask] AutoComplete step error: {e}")
                                    if cancel_event:
                                        cancel_event.set()
                                    yield f"event: done\ndata: {json.dumps({'full_content': full_response})}\n\n"
                                    return
                            except Exception as e:
                                _safe_log(f"[MicroTask] AutoComplete check error: {e}")

                # Add tool result to history
                history.append({"role": "user", "content": f"Tool Result: {result}"})
                AgentService.add_message(task_id, chat_id, "user", f"Tool Result: {result}",
                                         meta={"is_tool_result": True})

            # ── Check for [STEP_COMPLETE] ──
            has_step_complete = '[STEP_COMPLETE]' in full_response

            if has_step_complete:
                expected_artifact = AgentService._get_expected_artifact(
                    step_for_chat['id'],
                    os.path.join(workspace_path, '.sentinel', 'tasks', task_id)
                )

                artifact_exists = False
                if expected_artifact and os.path.exists(expected_artifact):
                    try:
                        size = os.path.getsize(expected_artifact)
                        artifact_exists = size > 200
                        if artifact_exists:
                            with open(expected_artifact, 'r', encoding='utf-8', errors='replace') as f:
                                existing = f.read()
                            is_valid, reason = AgentService._validate_artifact_content(
                                existing, os.path.basename(expected_artifact)
                            )
                            if not is_valid:
                                artifact_exists = False
                    except Exception:
                        pass

                # Try auto-save if artifact missing
                if expected_artifact and not artifact_exists:
                    artifact_name = os.path.basename(expected_artifact)
                    save_content = best_writefile_content or ''

                    if not save_content and artifact_name.endswith('.md'):
                        extracted = AgentService._extract_markdown_from_narration(full_response)
                        if extracted:
                            save_content = extracted
                            _safe_log(f"[MicroTask] Rescued {len(extracted)} chars from narration")

                    if save_content:
                        is_valid, reason = AgentService._validate_artifact_content(save_content, artifact_name)
                        if is_valid:
                            # Unescape literal \n in markdown (narration rescue/fallback may leave these)
                            if artifact_name.endswith('.md'):
                                save_content = save_content.replace('\\n', '\n').replace('\\t', '\t')
                            try:
                                os.makedirs(os.path.dirname(expected_artifact), exist_ok=True)
                                with open(expected_artifact, 'w', encoding='utf-8') as f:
                                    f.write(save_content)
                                _safe_log(f"[MicroTask] Auto-saved {artifact_name} ({len(save_content)} chars)")
                                written_files[artifact_name] = {
                                    'is_new': True,
                                    'added': len(save_content.splitlines()),
                                    'removed': 0,
                                }
                                yield f"event: file_written\ndata: {json.dumps({'path': artifact_name})}\n\n"
                                artifact_exists = True
                            except Exception as e:
                                _safe_log(f"[MicroTask] Auto-save failed: {e}")

                    if not artifact_exists and nudge_count < 1:
                        nudge_count += 1
                        from prompts import nudges
                        nudge = nudges.missing_artifact(artifact_name=os.path.basename(expected_artifact))
                        AgentService.add_message(task_id, chat_id, "user", nudge, meta={"is_tool_result": True})
                        history.append({"role": "user", "content": nudge})
                        yield f"event: tool_result\ndata: {json.dumps({'result': nudge})}\n\n"
                        continue
                    elif not artifact_exists:
                        _safe_log(f"[MicroTask] Force-completing after max nudges")
                        artifact_exists = True

                # ── Missing-files check (impl steps only) ──
                # Cross-check step's Files: list against written_files.
                # If files are missing, nudge the LLM to create them.
                if artifact_exists or not expected_artifact:
                    _step_desc_mf = step_for_chat.get('description', '')
                    _expected_mf = AgentService._extract_owned_files(_step_desc_mf)
                    if _expected_mf and written_files:
                        from services.micro_agents import track_progress as _track_mf
                        _pct_mf, _remaining_mf, _msg_mf = _track_mf(_step_desc_mf, written_files)
                        if _remaining_mf and nudge_count < 2:
                            nudge_count += 1
                            from prompts import nudges
                            _written_names = [
                                os.path.basename(w) for w in written_files
                                if any(os.path.basename(w) == os.path.basename(ef) or ef in w for ef in _expected_mf)
                            ]
                            _mf_nudge = nudges.missing_files(
                                written=_written_names,
                                expected=_expected_mf,
                                remaining=_remaining_mf,
                            )
                            AgentService.add_message(task_id, chat_id, "user", _mf_nudge,
                                                     meta={"is_tool_result": True})
                            history.append({"role": "user", "content": _mf_nudge})
                            yield f"event: tool_result\ndata: {json.dumps({'result': _mf_nudge})}\n\n"
                            _safe_log(f"[MissingFiles] Nudge: {len(_written_names)}/{len(_expected_mf)} files, missing: {_remaining_mf}")
                            continue

                # ── Mark step completed ──
                if artifact_exists or not expected_artifact:
                    try:
                        fresh_task = TaskService.get_task(task_id)
                        fresh_step = AgentService._find_step_by_chat_id(
                            fresh_task.get('steps', []), chat_id
                        )
                        if fresh_step and fresh_step['status'] == 'in_progress':
                            TaskService.update_step_in_plan(
                                workspace_path, task_id, step_for_chat['id'],
                                {'status': 'completed'}
                            )
                            _safe_log(f"[MicroTask] Step {step_for_chat['id']} marked completed")

                            # Step summary
                            try:
                                summary_data = AgentService._build_step_summary(
                                    step_for_chat, workspace_path, task_id, written_files
                                )
                                if summary_data:
                                    AgentService.add_message(
                                        task_id, chat_id, "assistant",
                                        summary_data['markdown'],
                                        meta={"is_summary": True, "structured": summary_data['structured']}
                                    )
                                    yield f"event: step_summary\ndata: {json.dumps({'content': summary_data['markdown'], 'structured': summary_data['structured']})}\n\n"
                            except Exception as e:
                                _safe_log(f"[MicroTask] Summary error: {e}")

                            yield f"event: step_completed\ndata: {json.dumps({'stepId': step_for_chat['id']})}\n\n"
                    except Exception as e:
                        _safe_log(f"[MicroTask] Step completion error: {e}")

                    if cancel_event:
                        cancel_event.set()
                    yield f"event: done\ndata: {json.dumps({'full_content': full_response})}\n\n"
                    return

            # No STEP_COMPLETE and no tool calls — stall, nudge once
            if not tool_matches and not has_step_complete:
                if nudge_count < 1:
                    nudge_count += 1
                    from prompts import nudges
                    stall_msg = nudges.stall_sdd(target_file='requirements.md')
                    AgentService.add_message(task_id, chat_id, "user", stall_msg,
                                             meta={"is_tool_result": True, "is_system_nudge": True})
                    history.append({"role": "user", "content": stall_msg})
                    continue
                else:
                    _safe_log(f"[MicroTask] Assemble stalled after max nudges")
                    break

        # If we reach here without completing, try force-save and complete
        _safe_log(f"[MicroTask] Assemble phase ended without STEP_COMPLETE, attempting force-save")
        expected_artifact = AgentService._get_expected_artifact(
            step_for_chat['id'],
            os.path.join(workspace_path, '.sentinel', 'tasks', task_id)
        )
        if expected_artifact:
            # Try to recover content if best_writefile_content is still empty
            if not best_writefile_content:
                # Scan all assistant messages for narration rescue
                for msg in history:
                    if msg.get('role') == 'assistant':
                        extracted = AgentService._extract_markdown_from_narration(msg['content'])
                        if extracted and len(extracted) > len(best_writefile_content or ''):
                            best_writefile_content = extracted
                            _safe_log(f"[MicroTask] Force-save: rescued {len(extracted)} chars from narration")

            if not best_writefile_content:
                # Scan all assistant messages for truncated WriteFile JSON
                for msg in history:
                    if msg.get('role') == 'assistant' and '"WriteFile"' in msg.get('content', ''):
                        trunc_m = re.search(
                            r'"name"\s*:\s*"WriteFile".*?"content"\s*:\s*"((?:[^"\\]|\\.)*)',
                            msg['content'], re.DOTALL
                        )
                        if trunc_m:
                            salvaged = trunc_m.group(1)
                            try:
                                salvaged = salvaged.encode().decode('unicode_escape')
                            except Exception:
                                salvaged = salvaged.replace('\\n', '\n').replace('\\t', '\t').replace('\\"', '"')
                            if len(salvaged) > 200 and len(salvaged) > len(best_writefile_content or ''):
                                best_writefile_content = salvaged
                                _safe_log(f"[MicroTask] Force-save: salvaged {len(salvaged)} chars from truncated WriteFile")

            if best_writefile_content:
                try:
                    _force_content = best_writefile_content
                    if os.path.basename(expected_artifact).endswith('.md'):
                        _force_content = _force_content.replace('\\n', '\n').replace('\\t', '\t')
                    os.makedirs(os.path.dirname(expected_artifact), exist_ok=True)
                    with open(expected_artifact, 'w', encoding='utf-8') as f:
                        f.write(_force_content)
                    written_files[os.path.basename(expected_artifact)] = {
                        'is_new': True,
                        'added': len(_force_content.splitlines()),
                        'removed': 0,
                    }
                    _safe_log(f"[MicroTask] Force-saved {os.path.basename(expected_artifact)} ({len(_force_content)} chars)")
                except Exception as e:
                    _safe_log(f"[MicroTask] Force-save failed: {e}")

        # Mark completed regardless
        try:
            TaskService.update_step_in_plan(
                workspace_path, task_id, step_for_chat['id'],
                {'status': 'completed'}
            )
            summary_data = AgentService._build_step_summary(
                step_for_chat, workspace_path, task_id, written_files
            )
            if summary_data:
                AgentService.add_message(
                    task_id, chat_id, "assistant",
                    summary_data['markdown'],
                    meta={"is_summary": True, "structured": summary_data['structured']}
                )
                yield f"event: step_summary\ndata: {json.dumps({'content': summary_data['markdown'], 'structured': summary_data['structured']})}\n\n"
            yield f"event: step_completed\ndata: {json.dumps({'stepId': step_for_chat['id']})}\n\n"
        except Exception as e:
            _safe_log(f"[MicroTask] Force-completion error: {e}")

        if cancel_event:
            cancel_event.set()
        yield f"event: done\ndata: {json.dumps({'full_content': ''})}\n\n"

    @staticmethod
    def _run_requirements_micro_tasks(
        *,
        task_id: str,
        chat_id: str,
        task_details: str,
        history: list,
        llm,
        tool_service,
        cancel_event,
        stream_state: dict,
        step_for_chat: dict,
        workspace_path: str,
        artifacts_dir: str,
        artifacts_path: str,
        all_steps: list,
        llm_log=None,
    ):
        """Micro-task orchestrated requirements step.

        Replaces the standard agent loop for step_id='requirements'.
        Runs 3 phases: Scope → Deep Dive → Assemble.
        Yields SSE events for the full streaming experience.
        """
        from prompts.requirements_phases import (
            build_scope_prompt,
            build_deep_dive_prompt,
            build_interface_prompt,
            build_assemble_prompt,
        )

        os_name = platform.system()

        # LLM Activity Logger — passed from continue_chat_stream
        _log = llm_log  # may be None if caller didn't provide it

        # Build minimal system prompt for JSON phases (saves tokens)
        minimal_system = (
            f"You are Sentinel, an AI software engineer running on {os_name}. "
            "Follow the instructions in the user message exactly. "
            "When asked for JSON, output ONLY valid JSON. "
            "No markdown, no commentary, no explanation."
        )

        # Start with minimal history for JSON phases
        json_history = [{"role": "system", "content": minimal_system}]
        # Copy any seeded messages from the original history (skip system prompt)
        for msg in history[1:]:
            json_history.append(msg)

        written_files = {}

        def _artifact_path(filename):
            if artifacts_path == '.':
                return filename
            return f"{artifacts_path}/{filename}"

        # ── Phase 1: SCOPE ──
        _safe_log(f"[MicroTask] === Phase 1: SCOPE ===")
        if _log: _log.turn_start('Requirements/Scope', 1)
        yield f"event: micro_phase\ndata: {json.dumps({'phase': 'scope', 'status': 'in_progress'})}\n\n"
        yield f"event: thinking\ndata: {json.dumps({'token': chr(10) + chr(10) + chr(128203) + ' Analyzing task scope and complexity...' + chr(10)})}\n\n"

        scope_prompt = build_scope_prompt(task_details=task_details)
        yield from AgentService._run_json_phase(
            phase_name='scope',
            prompt=scope_prompt,
            history=json_history,
            llm=llm,
            cancel_event=cancel_event,
            stream_state=stream_state,
            chat_id=chat_id,
            task_id=task_id,
            required_keys=['complexity', 'components', 'risks', 'deliverable_type', 'quality_level'],
            max_retries=2,
        )
        scope_data = AgentService._json_phase_result

        if scope_data is None:
            _safe_log(f"[MicroTask] Scope failed, using fallback")
            scope_data = AgentService._default_scope(task_details)

        if _log:
            _log.response(json.dumps(scope_data, default=str)[:500] if scope_data else 'fallback')
            _log.turn_end('scope_done')
        yield f"event: micro_phase\ndata: {json.dumps({'phase': 'scope', 'status': 'done'})}\n\n"

        if cancel_event and cancel_event.is_set():
            yield f"event: done\ndata: {json.dumps({'full_content': '', 'cancelled': True})}\n\n"
            return

        # ── Phase 2: DEEP DIVE (conditional) ──
        complexity = scope_data.get('complexity', 'medium')
        _safe_log(f"[MicroTask] Complexity: {complexity} | Components: {scope_data.get('components', [])}")

        deep_dive_data = None
        interface_data = None

        if complexity != 'simple':
            _safe_log(f"[MicroTask] === Phase 2: DEEP DIVE ===")
            if _log: _log.turn_start('Requirements/DeepDive', 2)
            yield f"event: micro_phase\ndata: {json.dumps({'phase': 'deep_dive', 'status': 'in_progress'})}\n\n"
            yield f"event: thinking\ndata: {json.dumps({'token': chr(10) + chr(10) + chr(128269) + ' Deep-diving into component requirements...' + chr(10)})}\n\n"

            dd_prompt = build_deep_dive_prompt(
                task_details=task_details,
                scope_data=scope_data,
            )
            yield from AgentService._run_json_phase(
                phase_name='deep_dive',
                prompt=dd_prompt,
                history=json_history,
                llm=llm,
                cancel_event=cancel_event,
                stream_state=stream_state,
                chat_id=chat_id,
                task_id=task_id,
                required_keys=['components'],
                max_retries=2,
            )
            deep_dive_data = AgentService._json_phase_result

            if deep_dive_data is None:
                _safe_log(f"[MicroTask] Deep dive failed, using scope components")
                # Build minimal deep_dive_data from scope
                deep_dive_data = {
                    'components': [
                        {'name': c, 'requirements': [], 'constraints': [],
                         'inputs': '', 'outputs': '', 'edge_cases': []}
                        for c in scope_data.get('components', [])
                    ]
                }

            # Phase 2b: INTERFACES (complex only)
            if complexity == 'complex' and deep_dive_data:
                if cancel_event and cancel_event.is_set():
                    yield f"event: done\ndata: {json.dumps({'full_content': '', 'cancelled': True})}\n\n"
                    return

                _safe_log(f"[MicroTask] === Phase 2b: INTERFACES ===")
                yield f"event: thinking\ndata: {json.dumps({'token': chr(10) + chr(10) + chr(128279) + ' Mapping component interfaces...' + chr(10)})}\n\n"
                intf_prompt = build_interface_prompt(
                    task_details=task_details,
                    scope_data=scope_data,
                    deep_dive_data=deep_dive_data,
                )
                yield from AgentService._run_json_phase(
                    phase_name='interfaces',
                    prompt=intf_prompt,
                    history=json_history,
                    llm=llm,
                    cancel_event=cancel_event,
                    stream_state=stream_state,
                    chat_id=chat_id,
                    task_id=task_id,
                    required_keys=['interfaces'],
                    max_retries=2,
                )
                interface_data = AgentService._json_phase_result
                # interface_data being None is fine — we just skip it
                if _log:
                    _log.response(json.dumps(interface_data, default=str)[:500] if interface_data else 'skipped')

            if _log:
                _log.response(json.dumps(deep_dive_data, default=str)[:500] if deep_dive_data else 'fallback')
                _log.turn_end('deep_dive_done')
            yield f"event: micro_phase\ndata: {json.dumps({'phase': 'deep_dive', 'status': 'done'})}\n\n"
        else:
            _safe_log(f"[MicroTask] Skipping Phase 2 (simple task)")

        if cancel_event and cancel_event.is_set():
            yield f"event: done\ndata: {json.dumps({'full_content': '', 'cancelled': True})}\n\n"
            return

        # ── Phase 3: ASSEMBLE ──
        _safe_log(f"[MicroTask] === Phase 3: ASSEMBLE ===")
        if _log: _log.turn_start('Requirements/Assemble', 3)
        yield f"event: micro_phase\ndata: {json.dumps({'phase': 'assemble', 'status': 'in_progress'})}\n\n"
        yield f"event: thinking\ndata: {json.dumps({'token': chr(10) + chr(10) + chr(128221) + ' Assembling requirements document...' + chr(10)})}\n\n"

        assemble_prompt = build_assemble_prompt(
            task_details=task_details,
            scope_data=scope_data,
            deep_dive_data=deep_dive_data,
            interface_data=interface_data,
            artifact_path=_artifact_path('requirements.md'),
        )

        # Phase 3 needs the FULL history with tool definitions (from original history's system prompt)
        # Replace the minimal system prompt with the full one
        assemble_history = list(history)  # copy original history with full system prompt
        # Append the JSON phase messages so the model has context
        for msg in json_history[1:]:  # skip minimal system prompt
            if msg not in assemble_history:
                assemble_history.append(msg)

        yield from AgentService._run_assemble_phase(
            prompt=assemble_prompt,
            history=assemble_history,
            llm=llm,
            tool_service=tool_service,
            cancel_event=cancel_event,
            stream_state=stream_state,
            chat_id=chat_id,
            task_id=task_id,
            step_for_chat=step_for_chat,
            workspace_path=workspace_path,
            artifacts_dir=artifacts_dir,
            artifacts_path=artifacts_path,
            written_files=written_files,
            all_steps=all_steps,
        )

        if _log:
            _log.turn_end('assemble_done')
            _log.step_complete('Requirements', list(written_files.keys()) if written_files else [])
        yield f"event: micro_phase\ndata: {json.dumps({'phase': 'assemble', 'status': 'done'})}\n\n"

    @staticmethod
    def _sanitize_tool_json(raw_json):
        """Fix common 3B model JSON errors before parsing.

        5-pass pipeline:
        1. Triple-quoted strings (\"\"\"...\"\"\") → escaped JSON strings
        2. Literal newlines inside JSON string values → \\n
        3. All control chars (U+0000–U+001F) inside strings → escaped
        4. Trailing commas before } or ]
        5. Single-quoted JSON → double-quoted (only if no double quotes exist)
        """
        s = raw_json

        # --- Pass 1: Triple double-quotes → escaped JSON string ---
        triple_quote_pattern = re.compile(r'"""(.*?)"""', re.DOTALL)
        def replace_triple_quotes(match):
            inner = match.group(1)
            inner = inner.replace('\\', '\\\\')
            inner = inner.replace('"', '\\"')
            inner = inner.replace('\n', '\\n')
            inner = inner.replace('\r', '\\r')
            inner = inner.replace('\t', '\\t')
            return f'"{inner}"'
        s = triple_quote_pattern.sub(replace_triple_quotes, s)

        # --- Pass 1.5: Fix WriteFile content with raw newlines ---
        # The model often outputs the content field with actual newlines and
        # unescaped quotes. Use a targeted approach: find "content": "..." and
        # re-escape the entire value instead of relying on the char-by-char parser.
        content_match = re.search(r'"content"\s*:\s*"', s)
        if content_match and '"WriteFile"' in s:
            content_start = content_match.end()
            # Find the closing: look for "}} at the end (content is always last field)
            end_match = re.search(r'"\s*\}\s*\}\s*$', s[content_start:])
            if end_match:
                raw_content = s[content_start:content_start + end_match.start()]
                # Escape the raw content properly for JSON
                escaped = raw_content
                # Replace backslash first (before adding new ones)
                escaped = escaped.replace('\\n', '\x00NEWLINE\x00')  # Preserve existing \n
                escaped = escaped.replace('\\t', '\x00TAB\x00')      # Preserve existing \t
                escaped = escaped.replace('\\"', '\x00QUOTE\x00')    # Preserve existing \"
                escaped = escaped.replace('\\\\', '\x00BSLASH\x00')  # Preserve existing \\
                escaped = escaped.replace('\\', '\\\\')  # Escape remaining backslashes
                escaped = escaped.replace('"', '\\"')     # Escape unescaped quotes
                escaped = escaped.replace('\n', '\\n')    # Escape literal newlines
                escaped = escaped.replace('\r', '\\r')    # Escape literal CRs
                escaped = escaped.replace('\t', '\\t')    # Escape literal tabs
                # Restore preserved sequences
                escaped = escaped.replace('\x00NEWLINE\x00', '\\n')
                escaped = escaped.replace('\x00TAB\x00', '\\t')
                escaped = escaped.replace('\x00QUOTE\x00', '\\"')
                escaped = escaped.replace('\x00BSLASH\x00', '\\\\')
                s = s[:content_start] + escaped + s[content_start + end_match.start():]

        # --- Pass 2+3: Fix literal newlines and control chars inside strings ---
        s = AgentService._fix_control_chars_in_strings(s)

        # --- Pass 4: Trailing commas ---
        s = re.sub(r',\s*([}\]])', r'\1', s)

        # --- Pass 5: Single quotes → double quotes (full single-quoted JSON) ---
        if '"' not in s and "'" in s:
            s = s.replace("'", '"')

        return s

    @staticmethod
    def _fix_control_chars_in_strings(s):
        """Walk JSON text char-by-char. Inside double-quoted strings,
        replace any literal control character (U+0000–U+001F) with its
        JSON escape sequence. Handles already-escaped sequences correctly
        by skipping the char after each backslash."""
        CONTROL_ESCAPES = {
            '\x00': '\\u0000', '\x01': '\\u0001', '\x02': '\\u0002',
            '\x03': '\\u0003', '\x04': '\\u0004', '\x05': '\\u0005',
            '\x06': '\\u0006', '\x07': '\\u0007', '\x08': '\\b',
            '\x09': '\\t',     '\x0a': '\\n',     '\x0b': '\\u000b',
            '\x0c': '\\f',     '\x0d': '\\r',     '\x0e': '\\u000e',
            '\x0f': '\\u000f', '\x10': '\\u0010', '\x11': '\\u0011',
            '\x12': '\\u0012', '\x13': '\\u0013', '\x14': '\\u0014',
            '\x15': '\\u0015', '\x16': '\\u0016', '\x17': '\\u0017',
            '\x18': '\\u0018', '\x19': '\\u0019', '\x1a': '\\u001a',
            '\x1b': '\\u001b', '\x1c': '\\u001c', '\x1d': '\\u001d',
            '\x1e': '\\u001e', '\x1f': '\\u001f',
        }
        result = []
        in_string = False
        i = 0
        while i < len(s):
            c = s[i]
            if in_string:
                if c == '\\' and i + 1 < len(s):
                    # Already-escaped char — keep both as-is
                    result.append(c)
                    result.append(s[i + 1])
                    i += 2
                    continue
                elif c == '"':
                    in_string = False
                    result.append(c)
                elif c in CONTROL_ESCAPES:
                    result.append(CONTROL_ESCAPES[c])
                else:
                    result.append(c)
            else:
                if c == '"':
                    in_string = True
                result.append(c)
            i += 1
        return ''.join(result)

    @staticmethod
    def _extract_tool_call_fallback(raw_json):
        """Last-resort extraction when json.loads() fails even after sanitization.
        Uses known tool schemas to extract fields via regex.
        Returns {"name": ..., "arguments": {...}} or None."""
        TOOL_SCHEMAS = {
            'ListFiles': ['path'],
            'ReadFile': ['path'],
            'WriteFile': ['path', 'content'],
            'EditFile': ['path', 'old_string', 'new_string'],
            'Glob': ['pattern'],
            'RunCommand': ['command', 'cwd'],
        }

        # Extract tool name
        name_match = re.search(r'"name"\s*:\s*"(\w+)"', raw_json)
        if not name_match:
            return None
        tool_name = name_match.group(1)
        if tool_name not in TOOL_SCHEMAS:
            return None

        arguments = {}

        if tool_name == 'WriteFile':
            # Extract path (short, clean value)
            path_match = re.search(r'"path"\s*:\s*"([^"]*)"', raw_json)
            if path_match:
                arguments['path'] = path_match.group(1)

            # Extract content: find "content": then grab everything up to final }}
            content_start = re.search(r'"content"\s*:\s*', raw_json)
            if content_start:
                remainder = raw_json[content_start.end():]
                # Strip leading quotes
                if remainder.startswith('"""'):
                    remainder = remainder[3:]
                    # Find closing triple-quote
                    end_idx = remainder.find('"""')
                    if end_idx >= 0:
                        arguments['content'] = remainder[:end_idx]
                    else:
                        # No closing triple — take up to final }}
                        arguments['content'] = re.sub(r'[\s"]*\}\s*\}\s*$', '', remainder)
                elif remainder.startswith('"'):
                    remainder = remainder[1:]
                    # Find the end: work backwards from the last }} or single }
                    end_match = re.search(r'"\s*\}\s*\}\s*$', remainder)
                    if not end_match:
                        # Model may have omitted the outer closing brace
                        end_match = re.search(r'"\s*\}\s*$', remainder)
                    if end_match:
                        raw_content = remainder[:end_match.start()]
                        # Unescape JSON escapes — backslash MUST be first to avoid
                        # corrupting sequences like \\n (literal \n) into a newline.
                        raw_content = raw_content.replace('\\\\', '\x00BSLASH\x00')
                        raw_content = raw_content.replace('\\n', '\n')
                        raw_content = raw_content.replace('\\t', '\t')
                        raw_content = raw_content.replace('\\r', '\r')
                        raw_content = raw_content.replace('\\"', '"')
                        raw_content = raw_content.replace('\x00BSLASH\x00', '\\')
                        arguments['content'] = raw_content
                    else:
                        # Truncated JSON: no closing "}} found.
                        # Take the full remainder and unescape it properly.
                        raw_content = re.sub(r'[\s"]*\}\s*\}\s*$', '', remainder)
                        raw_content = raw_content.replace('\\\\', '\x00BSLASH\x00')
                        raw_content = raw_content.replace('\\n', '\n')
                        raw_content = raw_content.replace('\\t', '\t')
                        raw_content = raw_content.replace('\\r', '\r')
                        raw_content = raw_content.replace('\\"', '"')
                        raw_content = raw_content.replace('\x00BSLASH\x00', '\\')
                        arguments['content'] = raw_content
                else:
                    # No quote at all — grab until }}
                    raw_content = re.sub(r'\s*\}\s*\}\s*$', '', remainder)
                    raw_content = raw_content.replace('\\\\', '\x00BSLASH\x00')
                    raw_content = raw_content.replace('\\n', '\n')
                    raw_content = raw_content.replace('\\t', '\t')
                    raw_content = raw_content.replace('\\r', '\r')
                    raw_content = raw_content.replace('\\"', '"')
                    raw_content = raw_content.replace('\x00BSLASH\x00', '\\')
                    arguments['content'] = raw_content

            if 'path' not in arguments:
                return None
        else:
            # Simple tools — extract each expected arg
            for arg_key in TOOL_SCHEMAS[tool_name]:
                match = re.search(rf'"{arg_key}"\s*:\s*"([^"]*)"', raw_json)
                if match:
                    val = match.group(1)
                    val = val.replace('\\n', '\n').replace('\\t', '\t')
                    val = val.replace('\\"', '"').replace('\\\\', '\\')
                    arguments[arg_key] = val

            # Validate required args
            required = TOOL_SCHEMAS[tool_name][:1]  # First arg is always required
            if required and required[0] not in arguments:
                return None

        return {"name": tool_name, "arguments": arguments}

    @staticmethod
    def _build_json_retry_feedback(raw_json, error_message):
        """Build targeted retry feedback with a concrete corrected example."""
        name_match = re.search(r'"name"\s*:\s*"(\w+)"', raw_json)
        tool_name = name_match.group(1) if name_match else "WriteFile"

        # Detect specific error type
        err_lower = error_message.lower()
        if 'control character' in err_lower or 'invalid' in err_lower:
            hint = (
                "ERROR: You put actual newline characters inside a JSON string. "
                "You MUST use the two-character sequence \\n instead of pressing Enter. "
                "The ENTIRE JSON must be on a single line."
            )
        elif '"""' in raw_json:
            hint = "ERROR: You used triple quotes (\"\"\"). JSON only allows regular double quotes. Use \\n for newlines inside strings."
        elif "'" in raw_json[:50] and '"' not in raw_json[:50]:
            hint = "ERROR: JSON requires double quotes (\"), not single quotes ('). Change all single quotes to double quotes."
        else:
            hint = "ERROR: Invalid JSON. Use double quotes for all strings. Use \\n for newlines. Use \\\" for quotes inside strings."

        # Concrete example for the tool
        examples = {
            'WriteFile': '{"name": "WriteFile", "arguments": {"path": "file.md", "content": "# Title\\n\\nParagraph one.\\nParagraph two.\\n"}}',
            'RunCommand': '{"name": "RunCommand", "arguments": {"command": "pip install flask"}}',
            'ReadFile': '{"name": "ReadFile", "arguments": {"path": "requirements.md"}}',
            'ListFiles': '{"name": "ListFiles", "arguments": {"path": "."}}',
            'Glob': '{"name": "Glob", "arguments": {"pattern": "*.py"}}',
        }
        example = examples.get(tool_name, examples['WriteFile'])

        return (
            f"{hint}\n\n"
            f"Correct format:\n<tool_code>\n{example}\n</tool_code>\n\n"
            f"Try again. ALL newlines in content must be \\n, not actual line breaks."
        )

    # Context management constants
    TARGET_INPUT_TOKENS = 20000  # Trim history when input exceeds this
    TOOL_RESULT_MAX_CHARS = 8000  # Truncate tool results in LLM history

    # ── Agent Confusion Detection Constants ──────────────────────
    _MAX_RESPONSE_CHARS = 50_000          # Max chars before runaway detection
    _REPETITION_SIMILARITY_THRESHOLD = 0.85  # Jaccard similarity threshold for repetitive responses
    _MAX_NO_PROGRESS_TURNS = 4            # Turns without new files or tool success before abort
    _CODE_BLOCK_MIN_LINES = 6            # Min lines of code in prose to trigger code-in-prose nudge
    _VALID_TOOL_NAMES = {'WriteFile', 'ReadFile', 'EditFile', 'ListFiles', 'Glob', 'RunCommand'}

    # ── RL: step scores accumulator (class-level, persists across steps) ──
    _task_step_scores = {}  # task_id -> list of step score dicts
    _task_step_scores_lock = __import__('threading').Lock()

    @staticmethod
    def _stash_step_score(task_id, step_score):
        """Thread-safe accumulation of step scores for task-level aggregation."""
        with AgentService._task_step_scores_lock:
            step_score['_ts'] = time.time()  # Timestamp for TTL cleanup
            AgentService._task_step_scores.setdefault(task_id, []).append(step_score)
            # Prune stale entries (tasks abandoned > 2 hours ago)
            stale_cutoff = time.time() - 7200
            stale_keys = [
                tid for tid, scores in AgentService._task_step_scores.items()
                if scores and scores[-1].get('_ts', 0) < stale_cutoff
            ]
            for tid in stale_keys:
                del AgentService._task_step_scores[tid]

    @staticmethod
    def _pop_step_scores(task_id):
        """Thread-safe retrieval + cleanup of accumulated step scores."""
        with AgentService._task_step_scores_lock:
            return AgentService._task_step_scores.pop(task_id, [])

    @staticmethod
    def _fire_reward_agent_async(task_id, workspace_path, exec_score=None):
        """Fire the reward agent in a background thread (non-blocking).

        Aggregates step scores with execution score, generates lessons,
        records them to ExperienceMemory. Safe to call from generator context.
        """
        import threading

        def _run():
            try:
                step_scores = AgentService._pop_step_scores(task_id)
                task_score = score_task(step_scores, exec_score)
                _safe_log(
                    f"[RL] Task {task_id} final score: {task_score['grade']} "
                    f"({task_score['composite']:.3f}) — "
                    f"{task_score['total_files']} files, {task_score['total_turns']} turns"
                )

                # Build fingerprint for lesson context matching
                fingerprint = None
                try:
                    task = TaskService.get_task(task_id)
                    complexity = task.get('settings', {}).get('complexity', 5) if task else 5
                    fingerprint = ErrorMemory.compute_fingerprint(
                        workspace_path, step_type='implementation',
                        complexity=complexity,
                    )
                except Exception:
                    pass

                # Generate lessons (LLM call or fallback)
                try:
                    llm = get_llm_engine()
                except Exception:
                    llm = None

                recorded_lessons = _generate_reward_lessons(
                    llm=llm,
                    task_score=task_score,
                    workspace_path=workspace_path,
                    task_id=task_id,
                    fingerprint=fingerprint,
                )

                # Write RL learning report to workspace
                AgentService._write_rl_report(
                    workspace_path, task_id, task_score,
                    step_scores, exec_score, recorded_lessons, fingerprint,
                )
            except Exception as e:
                _safe_log(f"[RL] Reward agent failed: {e}")

        t = threading.Thread(target=_run, daemon=True, name=f'reward-agent-{task_id}')
        t.start()
        _safe_log(f"[RL] Reward agent fired in background for task {task_id}")

    @staticmethod
    def generate_rl_report_for_task(task_id, workspace_path):
        """Generate an RL learning report on demand (no reward agent needed).

        Gathers existing step scores, execution log, and RL memory data,
        then writes rl-learning-report.txt to the workspace.
        """
        try:
            # Collect step scores (may be empty if already popped by reward agent)
            step_scores = list(AgentService._task_step_scores.get(task_id, []))

            # Try to load execution log for exec_score reconstruction
            exec_score = None
            try:
                log_path = os.path.join(
                    workspace_path, '.sentinel', 'tasks', task_id, 'execution.log'
                )
                if os.path.isfile(log_path):
                    with open(log_path, 'r', encoding='utf-8') as f:
                        log_data = json.load(f)
                    exec_score = {
                        'success': log_data.get('success', False),
                        'attempts': log_data.get('attempts', 0),
                        'grade': '?',
                        'signals': {},
                    }
                    # Re-score if we have enough data
                    from services.reward_scorer import score_execution
                    _total_py = len([
                        f for f in os.listdir(workspace_path)
                        if f.endswith('.py')
                    ]) if os.path.isdir(workspace_path) else 0
                    exec_score = score_execution(
                        attempts=log_data.get('attempts', 1),
                        success=log_data.get('success', False),
                        integrity_issues=0,
                        review_issues=0,
                        fixes_applied=len(log_data.get('fixes', [])),
                        total_files=_total_py,
                    )
                else:
                    # No execution.log — check if task completed successfully
                    # (all steps done = terminal ran without auto-fix agent).
                    # Synthesize a "clean run" execution score.
                    task_data = TaskService.get_task(task_id)
                    if task_data and task_data.get('status') in ('Completed', 'In Progress'):
                        all_steps = task_data.get('steps', [])
                        flat_steps = []
                        for s in all_steps:
                            flat_steps.append(s)
                            flat_steps.extend(s.get('children', []))
                        all_done = flat_steps and all(
                            s.get('status') == 'completed' for s in flat_steps
                        )
                        if all_done:
                            from services.reward_scorer import score_execution
                            _total_py = len([
                                f for f in os.listdir(workspace_path)
                                if f.endswith('.py')
                            ]) if os.path.isdir(workspace_path) else 0
                            exec_score = score_execution(
                                attempts=1,
                                success=True,
                                integrity_issues=0,
                                review_issues=0,
                                fixes_applied=0,
                                total_files=_total_py,
                            )
                            _safe_log(f"[RL] Synthesized clean-run exec_score for task {task_id}")
            except Exception:
                pass

            # Build task score
            task_score = score_task(step_scores, exec_score)

            # Build fingerprint
            fingerprint = None
            try:
                task = TaskService.get_task(task_id)
                complexity = task.get('settings', {}).get('complexity', 5) if task else 5
                fingerprint = ErrorMemory.compute_fingerprint(
                    workspace_path, step_type='execution', complexity=complexity,
                )
            except Exception:
                pass

            # Load any existing lessons from experience memory
            recorded_lessons = []
            try:
                from services.experience_memory import ExperienceMemory
                exp_db = ExperienceMemory.load()
                # Get lessons from this task
                for entry in exp_db.get('entries', []):
                    if entry.get('source_task') == task_id:
                        recorded_lessons.append({
                            'lesson': entry.get('lesson', ''),
                            'type': entry.get('type', 'unknown'),
                            'tags': entry.get('tags', []),
                            'context': entry.get('context', ''),
                            'reward': entry.get('reward_score', 0),
                        })
            except Exception:
                pass

            AgentService._write_rl_report(
                workspace_path, task_id, task_score,
                step_scores, exec_score, recorded_lessons, fingerprint,
            )
            _safe_log(f"[RL] On-demand report generated for task {task_id}")
        except Exception as e:
            _safe_log(f"[RL] On-demand report failed: {e}")
            raise

    @staticmethod
    def _write_rl_report(workspace_path, task_id, task_score, step_scores,
                         exec_score, recorded_lessons, fingerprint):
        """Write an RL learning report to the workspace as a .txt file.

        Summarizes: task grade, signal breakdown, per-step scores, execution
        outcome, lessons learned, and relevant error memory entries.
        """
        try:
            from services.reward_agent import (
                _format_signal_breakdown, _format_step_summaries,
                _format_execution_outcome,
            )

            lines = []
            lines.append("=" * 60)
            lines.append("  RL LEARNING REPORT")
            lines.append(f"  Task: {task_id}")
            lines.append(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            lines.append("=" * 60)
            lines.append("")

            # ── Overall Grade ──
            grade = task_score.get('grade', '?')
            composite = task_score.get('composite', 0.0)
            total_files = task_score.get('total_files', 0)
            total_turns = task_score.get('total_turns', 0)
            lines.append(f"OVERALL GRADE: {grade} ({composite:.3f})")
            lines.append(f"Total files written: {total_files}")
            lines.append(f"Total LLM turns: {total_turns}")
            lines.append("")

            # ── Signal Breakdown ──
            lines.append("-" * 40)
            lines.append("SIGNAL BREAKDOWN")
            lines.append("-" * 40)
            lines.append(_format_signal_breakdown(task_score))
            lines.append("")

            # ── Per-Step Scores ──
            if step_scores:
                lines.append("-" * 40)
                lines.append("PER-STEP SCORES")
                lines.append("-" * 40)
                lines.append(_format_step_summaries(step_scores))
                lines.append("")

            # ── Execution Outcome ──
            lines.append("-" * 40)
            lines.append("EXECUTION OUTCOME")
            lines.append("-" * 40)
            lines.append(_format_execution_outcome(task_score))
            if exec_score:
                attempts = exec_score.get('attempts', 0)
                success = exec_score.get('success', False)
                exec_grade = exec_score.get('grade', '?')
                lines.append(f"  Attempts: {attempts}")
                lines.append(f"  Success: {'Yes' if success else 'No'}")
                lines.append(f"  Execution Grade: {exec_grade}")
            lines.append("")

            # ── Lessons Learned This Task ──
            lines.append("-" * 40)
            lines.append("LESSONS LEARNED (this task)")
            lines.append("-" * 40)
            if recorded_lessons:
                for i, lesson in enumerate(recorded_lessons, 1):
                    ltype = lesson.get('type', 'unknown').upper()
                    text = lesson.get('lesson', '')
                    tags = ', '.join(lesson.get('tags', []))
                    ctx = lesson.get('context', '')
                    reward = lesson.get('reward', 0)
                    lines.append(f"  {i}. [{ltype}] {text}")
                    if tags:
                        lines.append(f"     Tags: {tags}")
                    if ctx:
                        lines.append(f"     Context: {ctx}")
                    lines.append(f"     Reward: {reward:.3f}" if isinstance(reward, float) else f"     Reward: {reward}")
                    lines.append("")
            else:
                lines.append("  No lessons generated for this task.")
                lines.append("")

            # ── Error Memory (relevant entries) ──
            lines.append("-" * 40)
            lines.append("ERROR MEMORY (relevant entries)")
            lines.append("-" * 40)
            try:
                relevant_errors = ErrorMemory.lookup(
                    step_type='execution', fingerprint=fingerprint, max_entries=10,
                )
                if relevant_errors:
                    for entry in relevant_errors:
                        sig = entry.get('sig', '?')
                        tier = entry.get('_tier', ErrorMemory.compute_tier(entry))
                        tier_label = {1: 'Note', 2: 'WARNING', 3: 'CRITICAL'}.get(tier, 'Note')
                        hits = entry.get('hits', 0)
                        conf = entry.get('confidence', 0)
                        mistake = entry.get('mistake', '')
                        fix = ErrorMemory.sample_best_fix(entry)
                        source = entry.get('source', 'auto')
                        lines.append(f"  [{tier_label}] {sig}")
                        lines.append(f"    Mistake: {mistake}")
                        lines.append(f"    Fix: {fix}")
                        lines.append(f"    Hits: {hits} | Confidence: {conf:.2f} | Source: {source}")
                        # Show bandit arm stats
                        fixes = entry.get('fixes', [])
                        if len(fixes) > 1:
                            lines.append(f"    Strategies ({len(fixes)}):")
                            for arm in fixes[:3]:
                                alpha = arm.get('alpha', 1)
                                beta = arm.get('beta', 1)
                                expected = alpha / (alpha + beta) if (alpha + beta) > 0 else 0
                                lines.append(f"      - {arm.get('strategy', '?')[:80]} (a={alpha}, b={beta}, E={expected:.2f})")
                        lines.append("")
                else:
                    lines.append("  No relevant error memory entries.")
                    lines.append("")
            except Exception:
                lines.append("  Error loading error memory entries.")
                lines.append("")

            # ── Experience Memory (all lessons) ──
            lines.append("-" * 40)
            lines.append("EXPERIENCE MEMORY (cumulative lessons)")
            lines.append("-" * 40)
            try:
                from services.experience_memory import ExperienceMemory
                exp_db = ExperienceMemory.load()
                exp_entries = exp_db.get('entries', [])
                if exp_entries:
                    # Sort by alpha/(alpha+beta) descending for most confident first
                    sorted_exp = sorted(
                        exp_entries,
                        key=lambda e: e.get('alpha', 1) / (e.get('alpha', 1) + e.get('beta', 1)),
                        reverse=True,
                    )
                    for entry in sorted_exp[:20]:
                        ltype = entry.get('type', 'unknown').upper()
                        lesson = entry.get('lesson', '')
                        alpha = entry.get('alpha', 1)
                        beta = entry.get('beta', 1)
                        expected = alpha / (alpha + beta) if (alpha + beta) > 0 else 0
                        source_grade = entry.get('source_grade', '?')
                        source = entry.get('source', 'auto')
                        lines.append(f"  [{ltype}] {lesson}")
                        lines.append(f"    Confidence: {expected:.2f} (a={alpha}, b={beta}) | From: {source} grade={source_grade}")
                        lines.append("")
                else:
                    lines.append("  No experience memory entries yet.")
                    lines.append("")

                # Aggregate stats
                stats = exp_db.get('stats', {})
                if stats:
                    lines.append("  Aggregate Stats:")
                    lines.append(f"    Tasks scored: {stats.get('tasks_scored', 0)}")
                    lines.append(f"    Avg composite: {stats.get('avg_composite', 0):.3f}")
                    lines.append(f"    Best grade: {stats.get('best_grade', '?')}")
                    lines.append(f"    Worst grade: {stats.get('worst_grade', '?')}")
                    lines.append("")
            except Exception:
                lines.append("  Error loading experience memory.")
                lines.append("")

            # ── Context Fingerprint ──
            if fingerprint:
                lines.append("-" * 40)
                lines.append("CONTEXT FINGERPRINT")
                lines.append("-" * 40)
                lines.append(f"  Tech stack: {', '.join(fingerprint.get('tech_stack', []))}")
                lines.append(f"  Libraries: {', '.join(fingerprint.get('libraries', []))}")
                lines.append(f"  File extensions: {', '.join(fingerprint.get('file_exts', []))}")
                lines.append(f"  Step type: {fingerprint.get('step_type', '?')}")
                lines.append(f"  Complexity: {fingerprint.get('complexity_bucket', '?')}")
                lines.append("")

            lines.append("=" * 60)
            lines.append("  END OF RL LEARNING REPORT")
            lines.append("=" * 60)

            report_text = '\n'.join(lines)

            # Write to workspace
            report_path = os.path.join(workspace_path, 'rl-learning-report.txt')
            with open(report_path, 'w', encoding='utf-8') as f:
                f.write(report_text)

            _safe_log(f"[RL] Learning report written to {report_path} ({len(report_text)} chars)")

        except Exception as e:
            _safe_log(f"[RL] Failed to write learning report: {e}")

    @staticmethod
    def _detect_code_in_prose(response_text):
        """Detect if the agent wrote code in prose instead of using WriteFile.

        Returns (detected: bool, language: str).
        Looks for fenced code blocks (```python ... ```) with substantial code.
        Only triggers if NO tool calls were also present in the response.
        """
        # Skip if tool calls are present — agent is using tools correctly
        if '<tool_code>' in response_text or '<|channel|>' in response_text:
            return False, ''
        # Skip if response is short — might just be explanation with inline code
        if len(response_text) < 200:
            return False, ''

        # Detect fenced code blocks with substantial code
        code_blocks = re.findall(r'```(\w*)\n(.*?)```', response_text, re.DOTALL)
        for lang, code in code_blocks:
            lines = [l for l in code.strip().splitlines() if l.strip()]
            if len(lines) >= AgentService._CODE_BLOCK_MIN_LINES:
                # Check if this looks like real application code (not an example/template)
                has_def = 'def ' in code or 'class ' in code or 'function ' in code
                has_import = 'import ' in code or 'from ' in code or 'require(' in code
                if has_def or has_import:
                    return True, lang or 'python'

        return False, ''

    @staticmethod
    def _detect_repetitive_response(current_response, previous_responses):
        """Detect if the agent is generating the same response repeatedly.

        Uses Jaccard similarity on word-level bigrams.
        Returns True if the current response is too similar to a recent response.
        """
        if not previous_responses or len(current_response) < 100:
            return False

        def _bigrams(text):
            words = text.lower().split()
            return set(zip(words, words[1:])) if len(words) > 1 else set()

        current_bg = _bigrams(current_response)
        if not current_bg:
            return False

        # Check against last 3 responses
        for prev in previous_responses[-3:]:
            prev_bg = _bigrams(prev)
            if not prev_bg:
                continue
            intersection = current_bg & prev_bg
            union = current_bg | prev_bg
            similarity = len(intersection) / len(union) if union else 0
            if similarity >= AgentService._REPETITION_SIMILARITY_THRESHOLD:
                return True

        return False

    @staticmethod
    def _validate_tool_args(tool_name, tool_args):
        """Validate tool arguments for corruption / missing required fields.

        Returns (valid: bool, issue: str).
        """
        if not isinstance(tool_args, dict):
            return False, f"arguments must be a dict, got {type(tool_args).__name__}"

        if tool_name == 'WriteFile':
            path = tool_args.get('path')
            content = tool_args.get('content')
            if not path or not isinstance(path, str):
                return False, "missing or invalid 'path'"
            if content is None:
                return False, "missing 'content'"
            if not isinstance(content, str):
                return False, f"'content' must be a string, got {type(content).__name__}"
            if path.strip() == '':
                return False, "'path' is empty"
            # Reject suspicious paths
            if '..' in path or path.startswith('/') or ':' in path:
                return False, f"suspicious path '{path}' — use relative paths only"
        elif tool_name == 'EditFile':
            path = tool_args.get('path')
            if not path or not isinstance(path, str):
                return False, "missing or invalid 'path'"
            old_string = tool_args.get('old_string')
            new_string = tool_args.get('new_string')
            if old_string is None:
                return False, "missing 'old_string'"
            if new_string is None:
                return False, "missing 'new_string'"
            if not isinstance(old_string, str) or not isinstance(new_string, str):
                return False, "'old_string' and 'new_string' must be strings"
        elif tool_name == 'ReadFile':
            path = tool_args.get('path')
            if not path or not isinstance(path, str):
                return False, "missing or invalid 'path'"
        elif tool_name == 'Glob':
            pattern = tool_args.get('pattern')
            if not pattern or not isinstance(pattern, str):
                return False, "missing or invalid 'pattern'"
        elif tool_name == 'RunCommand':
            command = tool_args.get('command')
            if not command or not isinstance(command, str):
                return False, "missing or invalid 'command'"
        elif tool_name == 'ListFiles':
            pass  # path is optional, defaults to "."

        return True, ''

    @staticmethod
    def _check_wrong_step_write(step_id, file_path):
        """Check if a file write is appropriate for the current step.

        SDD steps should only write their artifact. Implementation steps
        should NOT write SDD artifacts.

        Returns (blocked: bool, allowed_pattern: str).
        """
        SDD_ARTIFACT_MAP = {
            'requirements': 'requirements.md',
            'technical-specification': 'spec.md',
            'planning': 'implementation-plan.md',
        }
        SDD_STEPS = {'requirements', 'technical-specification', 'planning'}
        ALL_SDD_ARTIFACTS = set(SDD_ARTIFACT_MAP.values())

        if not step_id or not file_path:
            return False, ''

        basename = os.path.basename(file_path)

        if step_id in SDD_STEPS:
            # SDD steps should ONLY write their specific artifact
            expected = SDD_ARTIFACT_MAP.get(step_id, '')
            if expected and basename != expected:
                # Allow reading/listing, but block writes to wrong files
                return True, expected
        elif step_id not in SDD_STEPS and step_id != 'implementation':
            # Implementation child steps should NOT overwrite SDD artifacts
            if basename in ALL_SDD_ARTIFACTS:
                return True, 'application source files (not SDD artifacts)'

        return False, ''

    @staticmethod
    def _trim_history(history, llm, keep_recent=2):
        """Trim history to fit within context budget using a rolling window.

        Preserves:
        - history[0]: system prompt
        - Seeded artifact messages (right after system prompt)
        - Last `keep_recent` exchange pairs (assistant + tool_result)
        - A 1-line summary bridging the gap
        """
        if len(history) <= 4:
            return history

        # Find anchor boundary: system prompt + seeded messages
        anchor_end = 1  # At minimum, keep system prompt
        for i in range(1, len(history)):
            msg = history[i]
            if msg['role'] == 'user' and msg['content'].startswith('I read '):
                anchor_end = i + 2  # Include assistant acknowledgment
            elif msg['role'] == 'assistant' and 'I have reviewed' in msg['content']:
                anchor_end = i + 1
            else:
                break

        anchor = history[:anchor_end]
        rest = history[anchor_end:]

        if len(rest) <= keep_recent * 2:
            return history  # Not enough to trim

        tail_count = keep_recent * 2
        tail = rest[-tail_count:] if tail_count > 0 else []
        middle = rest[:-tail_count] if tail_count > 0 else rest

        # Count dropped tool calls and find last tool name
        tool_calls_dropped = sum(
            1 for m in middle
            if m['role'] == 'user' and m['content'].startswith('Tool Result:')
        )
        last_tool = "unknown"
        for m in reversed(middle):
            if m['role'] == 'assistant':
                tool_match = re.search(r'"name":\s*"(\w+)"', m['content'])
                if tool_match:
                    last_tool = tool_match.group(1)
                    break

        summary = {
            "role": "user",
            "content": (
                f"[Context: You have completed {tool_calls_dropped} tool calls. "
                f"Last tool used: {last_tool}. "
                f"Continue working on the current step. Do not repeat work already done.]"
            )
        }

        trimmed = anchor + [summary] + tail

        # If still over budget, reduce keep_recent
        token_count = llm.count_tokens(trimmed)
        if token_count > AgentService.TARGET_INPUT_TOKENS and keep_recent > 1:
            return AgentService._trim_history(
                anchor + [summary] + rest[-(keep_recent - 1) * 2:],
                llm, keep_recent - 1
            )

        _safe_log(
            f"[Trim] Dropped {len(middle)} messages, kept {len(anchor)} anchor + "
            f"1 summary + {len(tail)} recent. Tokens: {token_count}"
        )
        return trimmed

    @staticmethod
    def continue_chat_stream(task_id, chat_id, cancel_event=None, stream_state=None):
        # Load task to get workspace
        task = TaskService.get_task(task_id)
        chat = AgentService.get_chat(task_id, chat_id)

        if not chat or not task:
            yield f"event: error\ndata: {json.dumps({'error': 'Chat or Task not found'})}\n\n"
            return

        workspace_path = task.get('workspacePath')
        if not workspace_path or not os.path.exists(workspace_path):
             yield f"event: error\ndata: {json.dumps({'error': 'Task workspace not found'})}\n\n"
             return

        # Find which step this chat belongs to (if any).
        # Primary: match step.chatId == chat_id (searches roots AND children).
        # Fallback: if no step matched by chatId (can happen due to race conditions
        # during auto-start), match by chat name == step name. This ensures the agent
        # always runs with the correct step context even if the chatId linking is broken.
        all_steps = task.get('steps', [])
        step_for_chat = AgentService._find_step_by_chat_id(all_steps, chat_id)
        if not step_for_chat and chat:
            chat_name = chat.get('name', '').strip()
            step_for_chat = AgentService._find_step_by_name(all_steps, chat_name)
            if step_for_chat:
                _safe_log(f"[Agent] Step matched by name fallback: chat '{chat_name}' → step '{step_for_chat['id']}'")
                # Fix the link: update plan.md so future lookups don't need fallback
                try:
                    TaskService.update_step_in_plan(workspace_path, task_id, step_for_chat['id'], {'chatId': chat_id})
                except Exception:
                    pass

        step_id = step_for_chat['id'] if step_for_chat else None
        artifacts_dir = os.path.join(workspace_path, '.sentinel', 'tasks', task_id)
        os.makedirs(artifacts_dir, exist_ok=True)

        # ── LLM Activity Logger ──
        llm_log = LLMLogger(task_id)
        _step_name_for_log = (step_for_chat.get('name', '') if step_for_chat else '') or step_id or 'unknown'
        llm_log.step_start(_step_name_for_log, step_id or '')

        # SDD doc steps → scoped to artifacts dir so agent's ListFiles shows plan.md,
        # requirements.md, etc. Without this, ListFiles returns empty (workspace root
        # has no files for file-copy workspaces from empty projects).
        # IMPORTANT: plan.md MUST be visible via ListFiles for SDD steps — the agent
        # relies on it to understand what to build.
        SDD_STEPS = {'requirements', 'technical-specification', 'planning'}
        if step_id and step_id in SDD_STEPS:
            agent_root = artifacts_dir
            artifacts_path = '.'
        else:
            agent_root = workspace_path
            artifacts_path = os.path.join('.sentinel', 'tasks', task_id)

        # SDD steps only need file tools (no RunCommand/EditFile — prevents agent from installing/coding during planning)
        excluded = {'RunCommand', 'EditFile'} if step_id and step_id in SDD_STEPS else set()
        tool_service = ToolService(agent_root, current_step_id=step_id, workspace_path=workspace_path, excluded_tools=excluded)
        tools_def = tool_service.get_tool_definitions(exclude=excluded)

        # Build step-aware system prompt
        os_name = platform.system()  # "Windows", "Linux", "Darwin"

        # Check if we need compact prompts (small context model)
        llm = get_llm_engine()
        compact_mode = llm.context_size is not None and llm.context_size <= 8192

        # Gather step-level context needed by the prompt builder
        parent_context = None
        existing_files = []
        step_instructions = ''
        artifact_name = 'output.md'

        if step_for_chat:
            all_steps = task.get('steps', [])

            # Look up parent context for child steps
            if '::' in step_for_chat.get('id', ''):
                parent_id = step_for_chat['id'].split('::')[0]
                for s in all_steps:
                    if s['id'] == parent_id:
                        parent_context = {
                            'name': s.get('name', ''),
                            'description': s.get('description', '')
                        }
                        break

            # Determine the expected artifact file
            expected_artifact = AgentService._get_expected_artifact(step_for_chat['id'], artifacts_path)
            artifact_name = os.path.basename(expected_artifact) if expected_artifact else "output.md"

            # List existing workspace files recursively
            try:
                SKIP_DIRS = {'.git', '__pycache__', 'node_modules', '.venv', 'venv', '.sentinel', '.DS_Store'}
                for root, dirs, files in os.walk(workspace_path):
                    dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith('.')]
                    for fname in files:
                        if not fname.startswith('.'):
                            rel = os.path.relpath(os.path.join(root, fname), workspace_path).replace('\\', '/')
                            existing_files.append(rel)
            except Exception:
                pass

            # Step-specific instructions (delegates to prompts package)
            task_complexity = task.get('settings', {}).get('complexity', 5)

            # Compute fingerprint once for error-memory calls in this chat turn
            chat_fingerprint = ErrorMemory.compute_fingerprint(
                workspace_path, step_type=step_id or 'implementation',
                complexity=task_complexity,
            )

            step_instructions = AgentService._get_step_read_instructions(
                step_for_chat['id'], artifacts_path,
                step_name=step_for_chat.get('name', ''),
                step_description=step_for_chat.get('description', ''),
                parent_name=parent_context['name'] if parent_context else '',
                parent_description=parent_context['description'] if parent_context else '',
                task_details=task.get('details', ''),
                existing_files=existing_files,
                complexity=task_complexity,
                _fingerprint=chat_fingerprint,
                _compact_mode=compact_mode,
            )

        # Look up known pitfalls for the system prompt
        pitfalls_for_system = ''
        if step_for_chat:
            sys_pitfalls = ErrorMemory.lookup(
                step_type=step_id or '',
                task_details=task.get('details', ''),
                max_entries=3,
                fingerprint=chat_fingerprint,
            )
            pitfalls_for_system = ErrorMemory.format_for_prompt(
                sys_pitfalls, compact_mode=compact_mode,
            ) if sys_pitfalls else ''

            # Inject ExperienceMemory lessons (behavioral RL from past tasks)
            try:
                _exp_tags = [step_id or 'implementation']
                if step_id and step_id not in ('requirements', 'technical-specification', 'planning'):
                    _exp_tags.append('implementation')
                _exp_lessons = ExperienceMemory.lookup(
                    tags=_exp_tags,
                    fingerprint=chat_fingerprint,
                    max_results=5,
                )
                if _exp_lessons:
                    _exp_text = ExperienceMemory.format_for_injection(_exp_lessons, budget=600)
                    if _exp_text:
                        pitfalls_for_system += ('\n' if pitfalls_for_system else '') + _exp_text
                        _safe_log(f"[ExperienceMemory] Injected {len(_exp_lessons)} lessons into system prompt")
            except Exception as _exp_e:
                _safe_log(f"[ExperienceMemory] Injection error: {_exp_e}")

        system_prompt = build_system_prompt(
            os_name=os_name,
            compact_mode=compact_mode,
            step_id=step_id,
            workspace_path=workspace_path,
            artifacts_path=artifacts_path,
            task_details=task.get('details', 'No description.'),
            tools_def=tools_def,
            step_for_chat=step_for_chat,
            all_steps=task.get('steps', []) if step_for_chat else None,
            parent_context=parent_context,
            step_instructions=step_instructions,
            artifact_name=artifact_name,
            existing_files=existing_files,
            known_pitfalls=pitfalls_for_system,
        )

        # Pre-seed artifact content so the model doesn't have to discover it via tool calls
        seeded = []
        if step_for_chat:
            seed_limit = 1500 if compact_mode else 4000
            seeded = AgentService._seed_prior_artifacts(
                workspace_path, task_id, step_for_chat['id'], artifacts_path,
                max_seed_chars=seed_limit,
                step_description=step_for_chat.get('description', '')
            )

        # Reconstruct history with seeded artifacts inserted before actual chat messages
        history = [{"role": "system", "content": system_prompt}]
        for msg in seeded:
            history.append(msg)
        for msg in chat['messages']:
            history.append({"role": msg['role'], "content": msg['content']})

        # ── Micro-task delegation for requirements step ──
        # The requirements step uses a structured 3-phase pipeline instead
        # of the standard open-ended agent loop. Delegate and return early.
        if step_id == 'requirements':
            yield from AgentService._run_requirements_micro_tasks(
                task_id=task_id,
                chat_id=chat_id,
                task_details=task.get('details', 'No description.'),
                history=history,
                llm=llm,
                tool_service=tool_service,
                cancel_event=cancel_event,
                stream_state=stream_state or {},
                step_for_chat=step_for_chat,
                workspace_path=workspace_path,
                artifacts_dir=artifacts_dir,
                artifacts_path=artifacts_path,
                all_steps=task.get('steps', []),
                llm_log=llm_log,
            )
            return

        # For SDD steps on the first turn, inject a "think first" reminder
        # as the last user message so the model sees it right before generating.
        # (Requirements is handled by micro-tasks above, so excluded here.)
        _sdd_first_turn = False
        if len(chat['messages']) == 1 and step_for_chat:
            sid = step_for_chat.get('id', '')
            if sid in ('technical-specification', 'planning'):
                _sdd_first_turn = True
                history.append({"role": "user", "content": (
                    f"IMPORTANT: Before you call WriteFile, you MUST write your analysis first. "
                    f"Analyze the task step by step: What are the core features? What constraints exist? "
                    f"What is NOT requested? What are the key decisions? "
                    f"Write at least 5 sentences of reasoning, THEN call WriteFile."
                )})

        MAX_STEPS = 15
        current_step = 0
        nudge_count = 0  # Track how many times we've nudged for missing artifact
        stall_nudge_count = 0  # Track nudges when agent responds without tool call
        json_error_count = 0  # Track JSON parse retries (max 2)
        best_writefile_content = ""  # Track best content from WriteFile attempts
        written_files = {}  # Track files the agent wrote: path → {is_new, added, removed}
        blocked_write_count = 0  # Track duplicate WriteFile blocks — force-complete after 2
        tool_call_index = 0  # Monotonic counter so frontend can pair tool_result → tool_card
        tool_failure_tracker = []  # Track (tool_name, path, error_type) for repeated failure detection
        # ── Agent confusion tracking ──
        previous_responses = []  # Track recent responses for repetition detection
        no_progress_turns = 0  # Turns without new file writes or successful tool results
        code_in_prose_count = 0  # Track how many times agent dumped code in prose
        confusion_nudge_count = 0  # Total confusion-related nudges (cap to prevent infinite nudge loops)
        # ── Step completion wiring safeguard counters ──
        missing_files_nudge_count = 0   # Check #0: missing files from Files: list
        integrity_nudge_count = 0       # Check #1: project integrity at step completion
        import_smoke_nudge_count = 0    # Check #2: python import smoke test
        modifies_nudge_count = 0        # Check #4: Modifies: enforcement
        depends_nudge_count = 0         # Check #5: Depends-on wiring validation
        # ── RL scoring accumulators ──
        _step_micro_warnings = []  # Accumulate post-write warnings for reward scoring
        _step_tool_failures = 0  # Count tool failures for reward scoring
        _injected_lesson_ids = []  # Track which lessons were injected for confirm/penalize

        # ── Micro-agent initialization ──
        # Initialize ImportGraph for cycle detection during this step
        _import_graph = ImportGraph()
        try:
            _import_graph.load_workspace(workspace_path)
        except Exception:
            pass  # Non-critical — cycle detection degrades gracefully

        # Build signature index and downstream deps for implementation steps
        _micro_context = ''
        if step_for_chat and step_id and step_id not in SDD_STEPS and step_id != 'implementation':
            try:
                _sig_idx = build_signature_index(workspace_path)
                if _sig_idx:
                    _micro_context += '\n' + _sig_idx + '\n'
            except Exception:
                pass
            try:
                _all_steps = task.get('steps', [])
                _downstream = scan_downstream_dependencies(
                    step_for_chat.get('id', ''), _all_steps,
                    written_files_so_far=written_files,
                )
                if _downstream:
                    _micro_context += _downstream
            except Exception:
                pass

        if stream_state is None:
            stream_state = {}

        def _done_event(content='', error=False, cancelled=False, stalled=False):
            """Build a consistent done SSE event string."""
            payload = {'full_content': content}
            if error:
                payload['error'] = True
            if cancelled:
                payload['cancelled'] = True
            if stalled:
                payload['stalled'] = True
            return f"event: done\ndata: {json.dumps(payload)}\n\n"

        # ── Synthetic thinking label for step start ──
        _SDD_STEP_LABELS = {
            'requirements': '\U0001f4cb Starting requirements analysis...',
            'technical-specification': '\U0001f3d7\ufe0f Designing technical architecture...',
            'planning': '\U0001f4d0 Creating implementation plan...',
        }
        _step_display_name = (step_for_chat.get('name', '') if step_for_chat else '') or step_id or 'Building'
        if step_id and step_id in SDD_STEPS:
            _start_label = _SDD_STEP_LABELS.get(step_id, f'\u26a1 Working on {_step_display_name}...')
            yield f"event: thinking\ndata: {json.dumps({'token': chr(10) + _start_label + chr(10)})}\n\n"
        elif step_id and step_id not in SDD_STEPS:
            yield f"event: thinking\ndata: {json.dumps({'token': chr(10) + chr(9889) + ' ' + _step_display_name + '...' + chr(10)})}\n\n"

        # Inject micro-agent context (signature index + downstream deps) into system prompt
        if _micro_context and history and history[0]['role'] == 'system':
            history[0]['content'] += '\n' + _micro_context
            _safe_log(f"[MicroAgent] Injected {len(_micro_context)} chars of API index + downstream deps into system prompt")

        # ── Experience injection: learned rules from past tasks ──
        if history and history[0]['role'] == 'system':
            try:
                _exp_tags = ['implementation']
                if step_id and step_id in SDD_STEPS:
                    _exp_tags = [step_id.replace('-', '_')]
                _exp_fp = None
                try:
                    _exp_complexity = task.get('settings', {}).get('complexity', 5)
                    _exp_fp = ErrorMemory.compute_fingerprint(
                        workspace_path, step_type=step_id or 'implementation',
                        complexity=_exp_complexity,
                    )
                except Exception:
                    pass
                _exp_entries = ExperienceMemory.lookup(tags=_exp_tags, fingerprint=_exp_fp, max_results=8)
                if _exp_entries:
                    _exp_block = ExperienceMemory.format_for_injection(_exp_entries)
                    if _exp_block:
                        history[0]['content'] += '\n' + _exp_block + '\n'
                        _injected_lesson_ids = [e.get('id') for e in _exp_entries if e.get('id')]
                        _safe_log(f"[Experience] Injected {len(_exp_entries)} lessons ({len(_exp_block)} chars) into system prompt")
            except Exception as _exp_e:
                _safe_log(f"[Experience] Injection failed: {_exp_e}")

        while current_step < MAX_STEPS:
            current_step += 1

            # Brief cooldown between consecutive LLM calls to avoid overwhelming local GPU
            if current_step > 1:
                time.sleep(0.5)

            # Token-aware history management: trim if context is getting full
            # First pass: smart compression (dedup nudges, compress tool results)
            if len(history) > 6 and current_step > 2:
                try:
                    history = optimize_history(history, written_files)
                except Exception:
                    pass  # Non-critical — fall back to blunt trim below

            token_count = llm.count_tokens(history)
            # Context-aware trim target: don't use 20K for an 8K model
            _model_ctx = llm.context_size or 32768
            _trim_target = min(AgentService.TARGET_INPUT_TOKENS, max(2000, _model_ctx - 2048))
            _safe_log(
                f"[Agent] Turn {current_step}/{MAX_STEPS} | "
                f"History: {len(history)} msgs | Tokens: {token_count} (trim@{_trim_target})"
            )
            if token_count > _trim_target:
                history = AgentService._trim_history(history, llm)

            llm_log.turn_start(_step_name_for_log, current_step, context_tokens=token_count)

            full_response = ""
            stream_state["unsaved"] = ""
            yield f"event: start\ndata: {json.dumps({'chatId': chat_id})}\n\n"
            # SSE heartbeat — keeps connection alive during slow LLM startup / between turns
            yield ": heartbeat\n\n"

            try:
                # Check cancellation at the top of each turn
                if cancel_event and cancel_event.is_set():
                    _safe_log(f"[Agent] Cancelled before turn {current_step}")
                    yield _done_event('', cancelled=True)
                    break

                dup_write_aborted = False
                error_in_stream = False
                thinking_start_time = time.time()
                thinking_content = ""  # Accumulate thinking for display
                TPFX = LLMEngine.THINK_PREFIX

                # ── Proactive context trim ──
                # If we're above 80% of model context and have enough history, trim early
                # to avoid wasting an LLM call that will fail with context overflow.
                _pre_tokens = llm.count_tokens(history)
                _pre_ctx = llm.context_size or 32768
                _usage_pct = int(100 * _pre_tokens / _pre_ctx)
                _safe_log(f"[Agent] Turn {current_step} context: {_pre_tokens}/{_pre_ctx} tokens ({_usage_pct}%)")
                if _pre_tokens > 0.8 * _pre_ctx and len(history) > 4:
                    _safe_log(f"[Agent] Proactive trim: {_usage_pct}% context used, trimming history")
                    history = AgentService._trim_history(history, llm)

                # ── Pre-flight context budget ──
                # Compute max_new_tokens dynamically so input + output fits the model's context window.
                # SDD steps (especially planning) produce large artifacts — use higher minimum.
                input_tokens = llm.count_tokens(history)
                model_ctx = llm.context_size or 32768  # generous fallback if unknown
                _min_output = 4096 if (step_id and step_id in SDD_STEPS) else 2048
                max_output = min(16384, max(_min_output, model_ctx - input_tokens - 256))
                _safe_log(
                    f"[Agent] Budget: {input_tokens} in + {max_output} out "
                    f"= {input_tokens + max_output} / {model_ctx} ctx"
                )

                if max_output < 1024:
                    error_msg = (
                        f"Prompt too large for model context window "
                        f"({input_tokens} tokens input, model max {model_ctx}). "
                        f"Try a model with a larger context window, or increase n_ctx in LM Studio."
                    )
                    _safe_log(f"[Agent] {error_msg}")
                    yield f"event: error\ndata: {json.dumps({'error': error_msg})}\n\n"
                    AgentService.add_message(task_id, chat_id, "assistant", f"[Error: {error_msg}]")
                    yield _done_event('', error=True)
                    break

                _read_timeout = 300
                _last_heartbeat = time.time()
                for token in llm.stream_chat(history, max_new_tokens=max_output, temperature=0.4, cancel_event=cancel_event, read_timeout=_read_timeout):
                    # Periodic heartbeat to keep SSE connection alive during slow generation
                    _now = time.time()
                    if _now - _last_heartbeat > 10:
                        yield ": heartbeat\n\n"
                        _last_heartbeat = _now

                    # Check if this is a thinking token (prefixed by LLMEngine)
                    if token.startswith(TPFX):
                        think_text = token[len(TPFX):]
                        thinking_content += think_text
                        llm_log.thinking(think_text)
                        # Emit as a separate SSE event for the frontend
                        yield f"event: thinking\ndata: {json.dumps({'token': think_text})}\n\n"
                        continue  # Don't add thinking to full_response

                    full_response += token
                    llm_log.token(token)
                    stream_state["unsaved"] = full_response

                    # ── Early abort: LLM error token mid-stream ──
                    # Error messages arrive as the very first tokens. Don't stream
                    # them to the user as normal content — the post-generation
                    # error handlers will emit a proper SSE error event instead.
                    if len(full_response) < 400 and '[Error from LLM:' in full_response:
                        error_in_stream = True
                        if cancel_event:
                            cancel_event.set()
                        break
                    if len(full_response) < 400 and '[Error:' in full_response and full_response.strip().startswith('[Error:'):
                        error_in_stream = True
                        if cancel_event:
                            cancel_event.set()
                        break

                    yield f"data: {json.dumps({'token': token})}\n\n"

                    # ── Early abort: runaway response detection ──
                    # If the response exceeds _MAX_RESPONSE_CHARS without any tool_code
                    # block, the agent is generating unbounded prose. Kill it.
                    if (len(full_response) > AgentService._MAX_RESPONSE_CHARS
                            and '<tool_code>' not in full_response
                            and '<|channel|>' not in full_response
                            and '[STEP_COMPLETE]' not in full_response.upper()):
                        _safe_log(f"[Agent] ABORT: runaway response ({len(full_response)} chars, no tool calls)")
                        llm_log.abort(f"Runaway response: {len(full_response)} chars without tool calls")
                        if cancel_event:
                            cancel_event.set()
                        break

                    # ── Early abort: duplicate WriteFile detection mid-stream ──
                    # If we already wrote files this step, check if the model is
                    # starting another WriteFile to the same path. Kill it immediately.
                    if written_files and ('<tool_code>' in full_response or '<|channel|>' in full_response):
                        # Check the latest (possibly incomplete) tool_code block
                        last_open = max(full_response.rfind('<tool_code>'), full_response.rfind('<|channel|>'))
                        tail = full_response[last_open:]
                        # Look for WriteFile + path before the block is fully closed
                        dup_match = re.search(r'"name"\s*:\s*"WriteFile".*?"path"\s*:\s*"([^"]+)"', tail, re.DOTALL)
                        if dup_match and dup_match.group(1) in written_files:
                            dup_path = dup_match.group(1)
                            _safe_log(f"[Agent] ABORT: duplicate WriteFile to '{dup_path}' detected mid-stream, cancelling generation")
                            llm_log.abort(f"Duplicate WriteFile to '{dup_path}' mid-stream")
                            if cancel_event:
                                cancel_event.set()
                            # Trim the response back to before this tool_code block
                            # Find the preamble text like "Saving spec.md" before <tool_code>
                            trim_point = last_open
                            lookback = full_response[max(0, trim_point - 300):trim_point]
                            preamble = re.search(r'(?:Now I will|Let me|I will now|I\'ll now|Saving|Let me save|I\'ll save|Writing).*$', lookback, re.DOTALL | re.IGNORECASE)
                            if preamble:
                                trim_point = max(0, trim_point - len(lookback) + preamble.start())
                            full_response = full_response[:trim_point].rstrip()
                            dup_write_aborted = True
                            break

                # End of generation turn
                # ── Reset cancel event after mid-stream aborts ──
                # The mid-stream abort guards (error, runaway, dup-write) set cancel_event
                # to kill the LLM stream. Clear it here so post-generation handlers and
                # the next turn can proceed normally.
                if cancel_event and cancel_event.is_set():
                    cancel_event.clear()

                # ── Handle duplicate write abort ──
                if dup_write_aborted:
                    # Save trimmed response (minus the duplicate tool_code)
                    if full_response.strip():
                        AgentService.add_message(task_id, chat_id, "assistant", full_response)
                        stream_state["unsaved"] = ""
                        history.append({"role": "assistant", "content": full_response})
                    # Tell the model to stop and complete
                    dup_nudge = nudges.duplicate_write()
                    AgentService.add_message(task_id, chat_id, "user", dup_nudge, meta={"is_tool_result": True})
                    history.append({"role": "user", "content": dup_nudge})
                    # Reset cancel event so the next turn can proceed
                    if cancel_event:
                        cancel_event.clear()
                    continue  # Next turn — model should say [STEP_COMPLETE]

                # ── Empty response detection ──
                # If the LLM produced nothing (OOM, crash, GPU issue), don't silently
                # continue — surface an error so the user knows what happened.
                if not full_response.strip():
                    _safe_log(f"[Agent] LLM returned empty response on turn {current_step}")
                    error_msg = "The AI model failed to generate a response. This may be due to a GPU memory issue. Try again."
                    yield f"event: error\ndata: {json.dumps({'error': error_msg})}\n\n"
                    AgentService.add_message(task_id, chat_id, "assistant", f"[Error: {error_msg}]")
                    if cancel_event:
                        cancel_event.set()
                    yield _done_event('', error=True)
                    break

                # ── Context overflow detection ──
                # LM Studio returns "Cannot truncate prompt with n_keep >= n_ctx"
                # when the prompt exceeds the model's context window. Do NOT nudge
                # (nudging adds more tokens, making it worse). Halt immediately.
                if '[Error from LLM:' in full_response and 'n_ctx' in full_response:
                    # Extract n_ctx value for the error message
                    ctx_match = re.search(r'n_ctx\s*\((\d+)\)', full_response)
                    keep_match = re.search(r'n_keep\s*\((\d+)\)', full_response)
                    n_ctx = ctx_match.group(1) if ctx_match else '?'
                    n_keep = keep_match.group(1) if keep_match else '?'
                    # Store context size for future prompt trimming
                    if ctx_match:
                        try:
                            llm.set_context_size(int(ctx_match.group(1)))
                        except (ValueError, AttributeError):
                            pass
                    _safe_log(f"[Agent] Context overflow: prompt {n_keep} tokens > model context {n_ctx} tokens")
                    error_msg = (
                        f"Prompt too large for model context window ({n_keep} tokens > {n_ctx} max). "
                        f"Try a model with a larger context window, or increase n_ctx in LM Studio settings."
                    )
                    yield f"event: error\ndata: {json.dumps({'error': error_msg})}\n\n"
                    AgentService.add_message(task_id, chat_id, "assistant", f"[Error: {error_msg}]")
                    if cancel_event:
                        cancel_event.set()
                    yield _done_event('', error=True)
                    break

                # ── Generic LLM error detection ──
                # If the entire response is just an error message from the LLM,
                # don't treat it as real content — halt instead of stall-nudging.
                if full_response.strip().startswith('[Error from LLM:') or full_response.strip().startswith('\n\n[Error from LLM:'):
                    _safe_log(f"[Agent] LLM returned error: {full_response.strip()[:200]}")
                    error_msg = full_response.strip().replace('[Error from LLM:', '').rstrip(']').strip()
                    yield f"event: error\ndata: {json.dumps({'error': f'LLM error: {error_msg}'})}\n\n"
                    AgentService.add_message(task_id, chat_id, "assistant", f"[Error: {error_msg}]")
                    if cancel_event:
                        cancel_event.set()
                    yield _done_event('', error=True)
                    break

                # ── Strip duplicate tool_code blocks before saving ──
                # The model often generates 2 WriteFile calls for the same file
                # in one response. We keep only the FIRST tool_code block per file path
                # so the UI doesn't show ghost tool cards for blocked duplicates.
                clean_response = full_response
                # Match both <tool_code>...</tool_code> AND <|channel|>...<|message|>... formats
                all_tool_blocks = list(re.finditer(r'<tool_code>(.*?)</tool_code>|<\|channel\|>[^<]*<\|(?:constrain\|>[^<]*<\|)?message\|>(.*?)(?=<\|channel\|>|\Z)', full_response, re.DOTALL))
                if len(all_tool_blocks) > 1:
                    seen_paths = set()
                    blocks_to_remove = []
                    for m in all_tool_blocks:
                        block_text = m.group(1) or m.group(2) or ''
                        # Quick check: is this a WriteFile with a path we've already seen?
                        path_match = re.search(r'"name"\s*:\s*"WriteFile".*?"path"\s*:\s*"([^"]+)"', block_text, re.DOTALL)
                        if path_match:
                            fpath = path_match.group(1)
                            if fpath in seen_paths:
                                blocks_to_remove.append(m)
                                _safe_log(f"[Agent] Stripping duplicate WriteFile block for '{fpath}' from response text")
                            else:
                                seen_paths.add(fpath)
                    # Remove duplicate blocks from the response (in reverse to preserve offsets)
                    for m in reversed(blocks_to_remove):
                        # Also strip any text between the previous tool_code and this one
                        # that says "Now I will save..." — it's the model's preamble to the duplicate
                        start = m.start()
                        # Look back up to 200 chars for "Now I will save" or "Let me save" preamble
                        lookback = clean_response[max(0, start - 200):start]
                        preamble_match = re.search(r'(?:Now I will|Let me|I will now|I\'ll now)\s+(?:save|write|create).*$', lookback, re.DOTALL | re.IGNORECASE)
                        trim_start = start - len(lookback) + preamble_match.start() if preamble_match else start
                        clean_response = clean_response[:trim_start] + clean_response[m.end():]

                thinking_duration = round(time.time() - thinking_start_time, 1) if thinking_start_time else None
                msg_meta = {}
                if thinking_duration and thinking_duration >= 1:
                    msg_meta["thinkingDuration"] = thinking_duration
                if thinking_content.strip():
                    msg_meta["thinkingContent"] = thinking_content.strip()
                AgentService.add_message(task_id, chat_id, "assistant", clean_response, meta=msg_meta if msg_meta else None)
                llm_log.response(clean_response)
                stream_state["unsaved"] = ""
                history.append({"role": "assistant", "content": clean_response})

                # ── Agent Confusion Guardrails (post-generation) ──────────

                # G1: Runaway response — force-inject a nudge
                if (len(full_response) > AgentService._MAX_RESPONSE_CHARS
                        and '<tool_code>' not in full_response
                        and '<|channel|>' not in full_response
                        and confusion_nudge_count < 3):
                    confusion_nudge_count += 1
                    _safe_log(f"[Guardrail] Runaway response: {len(full_response)} chars, no tool calls (nudge {confusion_nudge_count})")
                    _runaway_msg = nudges.runaway_response(char_count=len(full_response))
                    AgentService.add_message(task_id, chat_id, "user", _runaway_msg,
                                              meta={"is_tool_result": True, "is_system_nudge": True})
                    history.append({"role": "user", "content": _runaway_msg})
                    continue

                # G2: Code-in-prose detection — agent wrote code blocks instead of using WriteFile
                _code_detected, _code_lang = AgentService._detect_code_in_prose(full_response)
                if _code_detected and confusion_nudge_count < 3:
                    code_in_prose_count += 1
                    confusion_nudge_count += 1
                    _safe_log(f"[Guardrail] Code-in-prose detected ({_code_lang}), nudging (count={code_in_prose_count})")
                    _code_nudge = nudges.code_in_prose(language=_code_lang)
                    AgentService.add_message(task_id, chat_id, "user", _code_nudge,
                                              meta={"is_tool_result": True, "is_system_nudge": True})
                    history.append({"role": "user", "content": _code_nudge})
                    if code_in_prose_count >= 3:
                        # Agent is incapable of using tools — force-complete to avoid burning turns
                        _safe_log(f"[Guardrail] Code-in-prose {code_in_prose_count}x — force-completing step")
                        break
                    continue

                # G3: Repetitive response detection — same content repeated
                if AgentService._detect_repetitive_response(full_response, previous_responses):
                    if confusion_nudge_count < 3:
                        confusion_nudge_count += 1
                        _safe_log(f"[Guardrail] Repetitive response on turn {current_step}")
                        _rep_msg = nudges.repetitive_response(turn=current_step)
                        AgentService.add_message(task_id, chat_id, "user", _rep_msg,
                                                  meta={"is_tool_result": True, "is_system_nudge": True})
                        history.append({"role": "user", "content": _rep_msg})
                        continue
                    else:
                        # Agent is stuck in a loop — force abort
                        _safe_log(f"[Guardrail] Repetitive response {confusion_nudge_count}x — aborting")
                        yield f"event: error\ndata: {json.dumps({'error': 'Agent stuck in a loop — generating repetitive responses. Try restarting the step.'})}\n\n"
                        if cancel_event:
                            cancel_event.set()
                        yield _done_event('', error=True)
                        break

                # Track for future repetition detection
                previous_responses.append(full_response[:2000])  # Store a prefix only to save memory
                if len(previous_responses) > 5:
                    previous_responses.pop(0)

                # ── End confusion guardrails ──────────────────────────────

                # Check for explicit step completion signal and tool calls
                # Flexible STEP_COMPLETE detection — the 3B model produces many variants:
                # [STEP_COMPLETE], [STEP_COMPLETE]., [STEP COMPLETE], Step Completed, etc.
                has_step_complete_signal = bool(re.search(r'\[STEP[_ -]?COMPLETE\]', full_response, re.IGNORECASE))
                if not has_step_complete_signal:
                    has_step_complete_signal = bool(re.search(r'\bstep\s+completed?\b', full_response, re.IGNORECASE))
                # Find ALL tool_code blocks — the model often puts 2+ in one response
                # Support both <tool_code>...</tool_code> AND GPT-OSS <|channel|>...<|message|>... format
                tool_matches = re.findall(r'<tool_code>(.*?)</tool_code>', full_response, re.DOTALL)
                # Also extract GPT-OSS style: <|channel|>TYPE to=ToolName <|constrain|>json<|message|>{...}
                # The model uses multiple channel types: "commentary", "analysis", "code", etc.
                # Accept any word after <|channel|> to catch all variants.
                gptoss_matches = re.findall(r'<\|channel\|>\w+\s+to=(\w+)\s*(?:<\|constrain\|>json)?[^<]*<\|message\|>(.*?)(?=<\|channel\|>|\Z)', full_response, re.DOTALL)
                for tool_name_hint, tool_body in gptoss_matches:
                    body = tool_body.strip()
                    # Normalize: GPT-OSS sometimes outputs {"name":...,"arguments":...}
                    # and sometimes just the raw arguments like {"path":"..."}
                    try:
                        parsed = json.loads(body)
                        if 'name' not in parsed:
                            # Wrap raw args: {"path":"x"} → {"name":"ToolName","arguments":{"path":"x"}}
                            body = json.dumps({"name": tool_name_hint, "arguments": parsed})
                    except (json.JSONDecodeError, ValueError):
                        # If body already has "name" key, don't double-wrap — pass as-is
                        # for downstream _sanitize_tool_json + _extract_tool_call_fallback
                        if '"name"' not in body:
                            body = '{"name": "' + tool_name_hint + '", "arguments": ' + body + '}'
                    tool_matches.append(body)

                # Fallback: detect bare JSON tool calls in narration text (no wrapper tags)
                # GPT-OSS sometimes dumps {"name":"WriteFile","arguments":{...}} inline
                if not tool_matches:
                    bare_json_pat = re.finditer(
                        r'\{"name"\s*:\s*"(WriteFile|EditFile|ReadFile|ListFiles|RunCommand)"'
                        r'\s*,\s*"arguments"\s*:\s*\{',
                        full_response)
                    for m in bare_json_pat:
                        # Try to extract the complete JSON object starting from this match
                        # Use string-aware bracket matching to handle { } inside JSON strings
                        start = m.start()
                        depth = 0
                        end = start
                        in_string = False
                        i = start
                        while i < len(full_response):
                            ch = full_response[i]
                            if in_string:
                                if ch == '\\' and i + 1 < len(full_response):
                                    i += 2  # skip escaped char
                                    continue
                                elif ch == '"':
                                    in_string = False
                            else:
                                if ch == '"':
                                    in_string = True
                                elif ch == '{':
                                    depth += 1
                                elif ch == '}':
                                    depth -= 1
                                    if depth == 0:
                                        end = i + 1
                                        break
                            i += 1
                        if end > start:
                            candidate = full_response[start:end]
                            try:
                                parsed = json.loads(candidate)
                                if 'name' in parsed and 'arguments' in parsed:
                                    tool_matches.append(candidate)
                                    _safe_log(f"[Agent] Rescued bare JSON tool call: {parsed['name']}")
                            except (json.JSONDecodeError, ValueError):
                                pass

                # ── Truncated tool_code salvage ────────────────────────────
                # When the model hits max_tokens mid-WriteFile JSON, the closing
                # </tool_code> tag is never emitted, so the regex above misses it.
                # Detect unclosed <tool_code> / <|channel|> blocks containing a
                # WriteFile call and salvage the truncated JSON content.
                if not tool_matches and (
                    ('<tool_code>' in full_response and '</tool_code>' not in full_response) or
                    ('<|channel|>' in full_response and '"WriteFile"' in full_response)
                ):
                    # Extract everything after the last <tool_code> or <|channel|>...<|message|>
                    trunc_start = max(
                        full_response.rfind('<tool_code>'),
                        full_response.rfind('<|message|>')
                    )
                    if trunc_start >= 0:
                        tag_len = len('<tool_code>') if full_response[trunc_start:].startswith('<tool_code>') else len('<|message|>')
                        trunc_body = full_response[trunc_start + tag_len:].strip()

                        # Try fallback extraction on the truncated JSON
                        salvaged_call = AgentService._extract_tool_call_fallback(trunc_body)
                        if salvaged_call and salvaged_call.get('name') == 'WriteFile':
                            salvaged_content = salvaged_call.get('arguments', {}).get('content', '')
                            salvaged_path = salvaged_call.get('arguments', {}).get('path', '')
                            if salvaged_content and len(salvaged_content) > 200:
                                _safe_log(
                                    f"[Agent] TRUNCATED WriteFile salvage: {salvaged_path} "
                                    f"({len(salvaged_content)} chars recovered from unclosed tool_code)"
                                )
                                # Track as best content for auto-save fallback
                                if len(salvaged_content) > len(best_writefile_content):
                                    best_writefile_content = salvaged_content
                                # Push into tool_matches so it gets executed normally
                                tool_matches.append(json.dumps(salvaged_call))
                            else:
                                _safe_log(f"[Agent] Truncated WriteFile detected but content too short ({len(salvaged_content)} chars)")
                        elif '"WriteFile"' in trunc_body:
                            # Fallback extraction failed — try raw regex salvage for best_writefile_content
                            raw_salvage = re.search(
                                r'"content"\s*:\s*"((?:[^"\\]|\\.)*)',
                                trunc_body, re.DOTALL
                            )
                            if raw_salvage:
                                raw_text = raw_salvage.group(1)
                                try:
                                    raw_text = raw_text.replace('\\n', '\n').replace('\\t', '\t').replace('\\"', '"').replace('\\\\', '\\')
                                except Exception:
                                    pass
                                if len(raw_text) > 200 and len(raw_text) > len(best_writefile_content):
                                    best_writefile_content = raw_text
                                    _safe_log(f"[Agent] Raw salvage: {len(raw_text)} chars for best_writefile_content")
                # ── End truncated tool_code salvage ───────────────────────

                # Handle tool calls FIRST — always execute tools even if [STEP_COMPLETE] is present
                # The agent often writes the artifact file AND says [STEP_COMPLETE] in the same response
                if tool_matches:
                  # Process each tool call found in this response
                  tool_execution_failed = False
                  for tool_match_idx, tool_raw in enumerate(tool_matches):
                    tool_json = tool_raw.strip()

                    # Clean up markdown fencing
                    tool_json = re.sub(r'^```json\s*', '', tool_json)
                    tool_json = re.sub(r'```$', '', tool_json).strip()

                    # Sanitize common 3B model JSON errors (triple-quoted strings, etc.)
                    tool_json = AgentService._sanitize_tool_json(tool_json)

                    # Parse JSON — separate try block so we can retry on parse errors
                    tool_call = None
                    try:
                        tool_call = json.loads(tool_json)
                    except json.JSONDecodeError as e:
                        # Try structured extraction fallback before asking model to retry
                        raw_text = tool_raw.strip()
                        _safe_log(f"[Agent] json.loads failed: {e}. Trying fallback extraction...")

                        tool_call = AgentService._extract_tool_call_fallback(raw_text)
                        if tool_call is None:
                            tool_call = AgentService._extract_tool_call_fallback(tool_json)

                        if tool_call is not None:
                            _safe_log(f"[Agent] Fallback extraction succeeded: {tool_call.get('name')}")
                            # Fall through to tool execution below
                        else:
                            json_error_count += 1
                            if json_error_count <= 2:
                                feedback = AgentService._build_json_retry_feedback(raw_text, str(e))
                                yield f"event: tool_result\ndata: {json.dumps({'result': feedback})}\n\n"
                                AgentService.add_message(task_id, chat_id, "user", feedback, meta={"is_tool_result": True})
                                history.append({"role": "user", "content": feedback})
                                tool_execution_failed = True
                                break  # Break tool loop, will continue outer while
                            else:
                                error_msg = f"JSON parse failed after {json_error_count} attempts: {str(e)}"
                                yield f"event: error\ndata: {json.dumps({'error': error_msg})}\n\n"
                                AgentService.add_message(task_id, chat_id, "user", f"System Error: {error_msg}")
                                if cancel_event:
                                    cancel_event.set()
                                tool_execution_failed = True
                                break

                    if tool_call is None:
                        continue  # Skip this tool_code block

                    # Execute tool — separate try block for actual execution errors
                    try:
                        tool_name = tool_call.get('name')
                        tool_args = tool_call.get('arguments', {})

                        # ── G4: Hallucinated tool name guard ──────────────────
                        if tool_name and tool_name not in AgentService._VALID_TOOL_NAMES:
                            _safe_log(f"[Guardrail] Hallucinated tool: '{tool_name}'")
                            _hall_msg = nudges.hallucinated_tool(tool_name=tool_name)
                            yield f"event: tool_result\ndata: {json.dumps({'result': _hall_msg})}\n\n"
                            AgentService.add_message(task_id, chat_id, "user", _hall_msg,
                                                      meta={"is_tool_result": True})
                            history.append({"role": "user", "content": _hall_msg})
                            tool_execution_failed = True
                            break

                        # ── G5: Tool argument validation ──────────────────────
                        _args_valid, _args_issue = AgentService._validate_tool_args(tool_name, tool_args)
                        if not _args_valid:
                            _safe_log(f"[Guardrail] Corrupted args for {tool_name}: {_args_issue}")
                            _corrupt_msg = nudges.corrupted_args(tool_name=tool_name, issue=_args_issue)
                            yield f"event: tool_result\ndata: {json.dumps({'result': _corrupt_msg})}\n\n"
                            AgentService.add_message(task_id, chat_id, "user", _corrupt_msg,
                                                      meta={"is_tool_result": True})
                            history.append({"role": "user", "content": _corrupt_msg})
                            tool_execution_failed = True
                            break

                        # ── G6: Wrong-step write protection ───────────────────
                        if tool_name == 'WriteFile' and step_id:
                            _blocked, _allowed = AgentService._check_wrong_step_write(step_id, tool_args.get('path', ''))
                            if _blocked:
                                _safe_log(f"[Guardrail] Wrong-step write: step={step_id}, path={tool_args.get('path')}")
                                _wrong_msg = nudges.wrong_step_write(
                                    step_id=step_id, path=tool_args.get('path', ''),
                                    allowed_pattern=_allowed
                                )
                                yield f"event: tool_result\ndata: {json.dumps({'result': _wrong_msg})}\n\n"
                                AgentService.add_message(task_id, chat_id, "user", _wrong_msg,
                                                          meta={"is_tool_result": True})
                                history.append({"role": "user", "content": _wrong_msg})
                                tool_execution_failed = True
                                break
                        # ── End pre-execution guardrails ──────────────────────

                        # Track WriteFile content for auto-save fallback
                        if tool_name == 'WriteFile' and tool_args.get('content'):
                            content = tool_args['content']
                            if len(content) > len(best_writefile_content):
                                best_writefile_content = content

                        # ── Duplicate WriteFile guard ──────────────────────────
                        # If the model already wrote this exact file path in this
                        # step, block it and tell the model to stop.
                        if tool_name == 'WriteFile' and tool_args.get('path') in written_files:
                            dup_path = tool_args['path']
                            blocked_write_count += 1
                            _safe_log(f"[Agent] BLOCKED duplicate WriteFile to '{dup_path}' (count={blocked_write_count})")

                            if blocked_write_count >= 2:
                                # Model won't stop rewriting — force-complete the step
                                _safe_log(f"[Agent] Force-completing step after {blocked_write_count} blocked writes")
                                has_step_complete_signal = True
                                break  # Break tool loop, fall through to completion handling

                            dup_msg = (
                                f"BLOCKED: You already saved '{dup_path}' successfully. "
                                f"Do NOT save it again. Say [STEP_COMPLETE] now."
                            )
                            AgentService.add_message(task_id, chat_id, "user", dup_msg, meta={"is_tool_result": True})
                            history.append({"role": "user", "content": dup_msg})
                            tool_execution_failed = True
                            break  # Break tool loop, continue outer while to let model respond
                        # ── End duplicate guard ────────────────────────────────

                        yield f"event: tool_call\ndata: {json.dumps({'tool': tool_name, 'args': tool_args, 'index': tool_call_index})}\n\n"
                        # Log tool call (summarize args — path for file ops, command for RunCommand)
                        _tc_summary = tool_args.get('path', '') or tool_args.get('command', '') or str(tool_args)[:100]
                        llm_log.tool_call(tool_name, _tc_summary)

                        # ── Micro-agent: capture old content for EditFile dead-ref detection ──
                        _edit_old_content = None
                        if tool_name == 'EditFile' and tool_args.get('path'):
                            try:
                                _edit_fpath = os.path.join(agent_root, tool_args['path'])
                                if os.path.isfile(_edit_fpath):
                                    with open(_edit_fpath, 'r', encoding='utf-8', errors='replace') as _ef:
                                        _edit_old_content = _ef.read(100_000)
                            except Exception:
                                pass

                        result = tool_service.execute_tool(tool_name, tool_args)

                        yield ": heartbeat\n\n"  # Keep SSE alive after tool execution
                        yield f"event: tool_result\ndata: {json.dumps({'result': result, 'index': tool_call_index})}\n\n"
                        llm_log.tool_result(tool_name, result[:300])
                        tool_call_index += 1

                        # Notify frontend when a file is written/edited so Files tab can auto-refresh
                        if tool_name in ('WriteFile', 'EditFile') and result.startswith('Successfully'):
                            written_path = tool_args.get('path', '')
                            yield f"event: file_written\ndata: {json.dumps({'path': written_path})}\n\n"
                            # Parse diff metadata from result string
                            meta = AgentService._parse_write_meta(result)
                            written_files[written_path] = meta
                            no_progress_turns = 0  # Reset: agent made progress

                            # ── Micro-agent: post-write checks ──────────────────
                            # Run syntax check, import resolver, pattern matcher,
                            # circular import detector, dead reference watchdog
                            try:
                                _pw_warnings = post_write_checks(
                                    written_path, workspace_path,
                                    import_graph=_import_graph,
                                    old_content=_edit_old_content,
                                    is_edit=(tool_name == 'EditFile'),
                                )
                                if _pw_warnings:
                                    _pw_text = '\n'.join(_pw_warnings)
                                    result += '\n' + _pw_text
                                    _step_micro_warnings.extend(_pw_warnings)  # Accumulate for RL scoring
                                    _safe_log(f"[MicroAgent] Post-write warnings for {written_path}: {_pw_text[:200]}")
                                    # Emit warnings to frontend so user sees them too
                                    yield f"event: tool_result\ndata: {json.dumps({'result': _pw_text, 'index': tool_call_index - 1, 'isWarning': True})}\n\n"
                            except Exception as _pw_e:
                                _safe_log(f"[MicroAgent] Post-write check error: {_pw_e}")

                            # ── Micro-agent: progress tracking ──────────────────
                            if step_for_chat:
                                try:
                                    _step_desc = step_for_chat.get('description', '')
                                    _pct, _remaining, _prog_msg = track_progress(_step_desc, written_files)
                                    if _prog_msg:
                                        result += f'\n📊 {_prog_msg}'
                                except Exception:
                                    pass
                            # ── End micro-agent post-write ──────────────────────

                        # G7: Track no-progress turns (all tool results are errors)
                        if result.startswith('Error:') or result.startswith('Error '):
                            # Tool failed — don't count this as progress
                            pass
                        elif not result.startswith('Error'):
                            no_progress_turns = 0  # Successful tool result = progress

                        result_msg = f"Tool Result: {result}"
                        AgentService.add_message(task_id, chat_id, "user", result_msg, meta={"is_tool_result": True})
                        # Truncate tool results in LLM history to save context budget
                        # Full result is still persisted via add_message above for UI display
                        history_msg = result_msg
                        if len(history_msg) > AgentService.TOOL_RESULT_MAX_CHARS:
                            history_msg = history_msg[:AgentService.TOOL_RESULT_MAX_CHARS] + "\n...(truncated)"
                        history.append({"role": "user", "content": history_msg})

                        # ── Repeated tool failure detection ──
                        # Track errors by (tool, path, error_type) signature.
                        # At 3 repeats: nudge to change approach. At 5: hard redirect.
                        if result.startswith('Error:'):
                            _fail_path = tool_args.get('path', '')
                            # Extract error type: text between "Error: " and first period or " in "
                            _err_match = re.match(r'Error:\s*(.+?)(?:\s+in\s+\S+)?(?:\.|$)', result)
                            _err_type = _err_match.group(1).strip() if _err_match else 'unknown'
                            _fail_sig = (tool_name, _fail_path, _err_type)
                            tool_failure_tracker.append(_fail_sig)
                            _step_tool_failures += 1  # Accumulate for RL scoring
                            _same_count = sum(1 for f in tool_failure_tracker if f == _fail_sig)

                            if _same_count >= 3:
                                _safe_log(f"[Agent] HARD REDIRECT: {tool_name} failed {_same_count}x on '{_fail_path}' ({_err_type})")
                                _hard_msg = nudges.repeated_tool_failure_hard(
                                    tool_name=tool_name, path=_fail_path, fail_count=_same_count,
                                )
                                AgentService.add_message(task_id, chat_id, "user", _hard_msg,
                                                          meta={"is_tool_result": True, "is_system_nudge": True})
                                history.append({"role": "user", "content": _hard_msg})
                                tool_execution_failed = True
                                break  # Break tool loop, model gets one more turn with redirect
                            elif _same_count >= 2:
                                _safe_log(f"[Agent] Repetition nudge: {tool_name} failed {_same_count}x on '{_fail_path}' ({_err_type})")
                                # For EditFile, compute fuzzy hint from actual file content
                                _fuzzy_hint = ''
                                if tool_name == 'EditFile' and tool_args.get('old_string'):
                                    try:
                                        _target_file = os.path.join(agent_root, _fail_path)
                                        if os.path.isfile(_target_file):
                                            with open(_target_file, 'r', encoding='utf-8') as _fh:
                                                _file_lines = _fh.read().splitlines()
                                            _old_first = tool_args['old_string'].strip().splitlines()[0] if tool_args['old_string'].strip() else ''
                                            if _old_first:
                                                from difflib import get_close_matches
                                                _matches = get_close_matches(_old_first, _file_lines, n=1, cutoff=0.5)
                                                if _matches:
                                                    _fuzzy_hint = _matches[0]
                                    except Exception:
                                        pass
                                _nudge_msg = nudges.repeated_tool_failure(
                                    tool_name=tool_name, path=_fail_path, fail_count=_same_count,
                                    fuzzy_hint=_fuzzy_hint,
                                )
                                AgentService.add_message(task_id, chat_id, "user", _nudge_msg,
                                                          meta={"is_tool_result": True, "is_system_nudge": True})
                                history.append({"role": "user", "content": _nudge_msg})
                        # ── End repeated failure detection ──

                    except Exception as e:
                        error_msg = f"Tool execution failed: {str(e)}"
                        yield f"event: error\ndata: {json.dumps({'error': error_msg})}\n\n"
                        AgentService.add_message(task_id, chat_id, "user", f"System Error: {error_msg}")
                        if cancel_event:
                            cancel_event.set()
                        tool_execution_failed = True
                        break  # Break tool loop

                  # End of tool loop — handle outer control flow
                  if tool_execution_failed:
                    no_progress_turns += 1  # G7: failed tool execution = no progress
                    if cancel_event and cancel_event.is_set():
                      break  # Break outer while
                    # G7: Too many turns without progress — abort
                    if no_progress_turns >= AgentService._MAX_NO_PROGRESS_TURNS:
                      _safe_log(f"[Guardrail] No progress for {no_progress_turns} turns (tool failures) — force-aborting")
                      yield f"event: error\ndata: {json.dumps({'error': f'Agent made no progress for {no_progress_turns} consecutive turns due to tool failures. Try restarting the step.'})}\n\n"
                      if cancel_event:
                        cancel_event.set()
                      yield _done_event('', error=True, stalled=True)
                      break
                    continue  # Continue outer while (retry)

                  # If [STEP_COMPLETE] was also in this response, fall through to validation.
                  # Otherwise, check if we can auto-complete:
                  #   - SDD steps: single .md artifact written → skip extra LLM turn
                  #   - Impl steps: all Files:-listed files written → auto-complete
                  if not has_step_complete_signal and step_for_chat:
                    expected = AgentService._get_expected_artifact(
                      step_for_chat['id'], os.path.join(workspace_path, '.sentinel', 'tasks', task_id)
                    )
                    if expected:
                      # SDD step (requirements/tech-spec/planning): produces exactly one .md artifact.
                      # If it was just written, skip the extra LLM turn.
                      artifact_basename = os.path.basename(expected)
                      if any(artifact_basename in p for p in written_files):
                        _safe_log(f"[AutoComplete] SDD artifact '{artifact_basename}' written — auto-completing step without extra LLM turn")
                        has_step_complete_signal = True
                        yield f"event: thinking\ndata: {json.dumps({'token': chr(10) + chr(10) + chr(9989) + ' Artifact saved and validated ' + chr(8212) + ' completing step.' + chr(10)})}\n\n"
                        # Fall through to step completion validation below
                      else:
                        continue
                    else:
                      # Implementation child step: check if ALL expected files are written.
                      # If so, auto-complete instead of waiting for the LLM.
                      _impl_desc = step_for_chat.get('description', '')
                      if _impl_desc and written_files:
                        _expected_files = AgentService._extract_owned_files(_impl_desc)
                        if _expected_files and all(
                          any(ef in wf or os.path.basename(wf) == ef for wf in written_files)
                          for ef in _expected_files
                        ):
                          _safe_log(f"[AutoComplete] Impl step: all expected files written ({_expected_files}) — auto-completing")
                          has_step_complete_signal = True
                          yield f"event: thinking\ndata: {json.dumps({'token': chr(10) + chr(10) + chr(9989) + ' All files for this step saved ' + chr(8212) + ' completing.' + chr(10)})}\n\n"
                          # Fall through to step completion validation
                        else:
                          continue
                      else:
                        continue
                  elif not has_step_complete_signal:
                    continue

                # Handle [STEP_COMPLETE] signal — validate artifact exists before marking done
                if has_step_complete_signal and step_for_chat:
                    # Zero-files nudge: for implementation steps, agent must have written at least one file
                    if step_for_chat['id'] not in SDD_STEPS and len(written_files) == 0 and nudge_count < 1:
                        nudge_count += 1
                        zero_nudge = nudges.zero_files(
                            step_description=step_for_chat.get('description', '')
                        )
                        yield f"data: {json.dumps({'token': ''})}\n\n"
                        AgentService.add_message(task_id, chat_id, "user", zero_nudge, meta={"is_tool_result": True})
                        history.append({"role": "user", "content": zero_nudge})
                        yield f"event: tool_result\ndata: {json.dumps({'result': zero_nudge})}\n\n"
                        _safe_log(f"[ZeroFiles] Nudge: step {step_for_chat['id']} has 0 written files")
                        continue

                    expected_artifact = AgentService._get_expected_artifact(
                        step_for_chat['id'], os.path.join(workspace_path, '.sentinel', 'tasks', task_id)
                    )
                    _safe_log(f"[Complete] Step {step_for_chat['id']} | expected: {expected_artifact} | nudge_count: {nudge_count} | best_writefile: {len(best_writefile_content)} chars")

                    artifact_exists = False
                    if expected_artifact and os.path.exists(expected_artifact):
                        try:
                            size = os.path.getsize(expected_artifact)
                            artifact_exists = size > 200
                            _safe_log(f"[Complete] File exists, size={size}, artifact_exists={artifact_exists}")
                            # Extra quality check on existing file content
                            if artifact_exists:
                                with open(expected_artifact, 'r', encoding='utf-8', errors='replace') as f:
                                    existing_content = f.read()
                                is_valid, reason = AgentService._validate_artifact_content(existing_content, os.path.basename(expected_artifact))
                                if not is_valid:
                                    _safe_log(f"[Complete] Existing artifact FAILED validation: {reason}")
                                    artifact_exists = False  # Treat as missing so nudge fires
                        except Exception:
                            pass

                    if expected_artifact and not artifact_exists:
                        artifact_name = os.path.basename(expected_artifact)

                        # Try to auto-save from WriteFile content first
                        save_content = best_writefile_content if best_writefile_content else ''

                        # Fallback: if the model narrated the content in chat instead of
                        # calling WriteFile, try to extract it from the response text.
                        # This commonly happens with small models (7B) that dump markdown
                        # in the chat response instead of using tool calls.
                        if not save_content and artifact_name.endswith('.md'):
                            extracted = AgentService._extract_markdown_from_narration(full_response)
                            if extracted:
                                save_content = extracted
                                _safe_log(f"[Rescue] Extracted {len(extracted)} chars of markdown from narration for {artifact_name}")

                        # Fallback 3: scan all assistant messages for truncated WriteFile content
                        # This handles cases where the model output WriteFile JSON that was
                        # truncated (no closing tag/braces) across multiple turns.
                        if not save_content:
                            _best_trunc = ''
                            for _msg in history:
                                if _msg.get('role') != 'assistant':
                                    continue
                                _msg_text = _msg.get('content', '')
                                if '"WriteFile"' not in _msg_text or f'"{artifact_name}"' not in _msg_text:
                                    continue
                                # Try extracting content from truncated WriteFile JSON
                                _trunc_m = re.search(
                                    r'"content"\s*:\s*"((?:[^"\\]|\\.)*)',
                                    _msg_text, re.DOTALL
                                )
                                if _trunc_m:
                                    _raw = _trunc_m.group(1)
                                    try:
                                        _raw = _raw.replace('\\\\', '\x00B\x00')
                                        _raw = _raw.replace('\\n', '\n').replace('\\t', '\t')
                                        _raw = _raw.replace('\\"', '"')
                                        _raw = _raw.replace('\x00B\x00', '\\')
                                    except Exception:
                                        pass
                                    if len(_raw) > 200 and len(_raw) > len(_best_trunc):
                                        _best_trunc = _raw
                            if _best_trunc:
                                save_content = _best_trunc
                                _safe_log(f"[Rescue] Salvaged {len(_best_trunc)} chars from truncated WriteFile across chat history for {artifact_name}")

                        if save_content:
                            # Validate content quality before auto-saving
                            is_valid, reason = AgentService._validate_artifact_content(save_content, artifact_name)
                            if is_valid:
                                # Unescape literal \n in markdown (narration rescue/fallback may leave these)
                                if artifact_name.endswith('.md'):
                                    save_content = save_content.replace('\\n', '\n').replace('\\t', '\t')
                                try:
                                    os.makedirs(os.path.dirname(expected_artifact), exist_ok=True)
                                    with open(expected_artifact, 'w', encoding='utf-8') as f:
                                        f.write(save_content)
                                    _safe_log(f"Auto-saved content as {artifact_name} ({len(save_content)} chars)")
                                    # Track in written_files so step summary shows it
                                    written_files[artifact_name] = {
                                        'is_new': True,
                                        'added': len(save_content.splitlines()),
                                        'removed': 0,
                                    }
                                    yield f"event: file_written\ndata: {json.dumps({'path': artifact_name})}\n\n"
                                    yield f"event: tool_result\ndata: {json.dumps({'result': f'Auto-saved to {artifact_name}'})}\n\n"
                                    artifact_exists = True
                                except Exception as e:
                                    _safe_log(f"Auto-save failed: {e}")
                            else:
                                _safe_log(f"Auto-save BLOCKED for {artifact_name}: {reason}")

                        if not artifact_exists and nudge_count < 1:
                            # First failure — nudge the agent once to try again
                            nudge_count += 1
                            nudge = nudges.missing_artifact(artifact_name=artifact_name)
                            yield f"data: {json.dumps({'token': ''})}\n\n"
                            AgentService.add_message(task_id, chat_id, "user", nudge, meta={"is_tool_result": True})
                            history.append({"role": "user", "content": nudge})
                            yield f"event: tool_result\ndata: {json.dumps({'result': nudge})}\n\n"
                            _safe_log(f"Nudge: artifact missing for step {step_for_chat['id']}")
                            continue
                        elif not artifact_exists:
                            # Already nudged once — force-complete with whatever we have
                            _safe_log(f"Max nudges reached for {step_for_chat['id']}, force-completing")
                            artifact_exists = True  # Force through to completion

                    # ── Step completion wiring safeguards (implementation child steps only) ──
                    # These checks run AFTER artifact validation but BEFORE marking the step completed.
                    # Each check nudges the agent once; on the second encounter, force-completes.
                    _is_impl_child = (
                        step_for_chat['id'] not in SDD_STEPS
                        and step_for_chat['id'] != 'implementation'
                    )
                    _wiring_block = False  # Set True if any check fires a nudge

                    # Check #0: Missing files from the step's Files: list
                    # This is the FIRST check because there's no point running
                    # integrity/import checks on an incomplete file set.
                    if _is_impl_child and not _wiring_block and missing_files_nudge_count < 2:
                        _step_desc_mf = step_for_chat.get('description', '')
                        _expected_mf = AgentService._extract_owned_files(_step_desc_mf)
                        if _expected_mf and written_files:
                            from services.micro_agents import track_progress as _track_mf
                            _pct_mf, _remaining_mf, _msg_mf = _track_mf(_step_desc_mf, written_files)
                            if _remaining_mf:
                                missing_files_nudge_count += 1
                                _written_names = [
                                    os.path.basename(w) for w in written_files
                                    if any(os.path.basename(w) == os.path.basename(ef) or ef in w for ef in _expected_mf)
                                ]
                                _mf_nudge = nudges.missing_files(
                                    written=_written_names,
                                    expected=_expected_mf,
                                    remaining=_remaining_mf,
                                )
                                yield f"data: {json.dumps({'token': ''})}\n\n"
                                AgentService.add_message(task_id, chat_id, "user", _mf_nudge,
                                                         meta={"is_tool_result": True})
                                history.append({"role": "user", "content": _mf_nudge})
                                yield f"event: tool_result\ndata: {json.dumps({'result': _mf_nudge})}\n\n"
                                _safe_log(f"[MissingFiles] Nudge #{missing_files_nudge_count}: "
                                          f"{len(_written_names)}/{len(_expected_mf)} files, missing: {_remaining_mf}")
                                _wiring_block = True

                    # Check #1: Project integrity at step completion
                    if _is_impl_child and not _wiring_block and integrity_nudge_count < 1:
                        try:
                            _integrity_result = AgentService._validate_project_integrity(workspace_path)
                            _integrity_issues = _integrity_result.get('issues', [])
                            if _integrity_issues:
                                integrity_nudge_count += 1
                                _integrity_nudge = nudges.integrity_check_failed(issues=_integrity_issues)
                                yield f"data: {json.dumps({'token': ''})}\n\n"
                                AgentService.add_message(task_id, chat_id, "user", _integrity_nudge,
                                                         meta={"is_tool_result": True})
                                history.append({"role": "user", "content": _integrity_nudge})
                                yield f"event: tool_result\ndata: {json.dumps({'result': _integrity_nudge})}\n\n"
                                _safe_log(f"[Integrity] Nudge: {len(_integrity_issues)} issues at step completion")
                                # Persist for cross-step injection (Check #3)
                                try:
                                    _integrity_path = os.path.join(
                                        workspace_path, '.sentinel', 'tasks', task_id, 'last_integrity.json'
                                    )
                                    os.makedirs(os.path.dirname(_integrity_path), exist_ok=True)
                                    with open(_integrity_path, 'w', encoding='utf-8') as _if:
                                        json.dump({'issues': _integrity_issues[:10],
                                                   'step_id': step_for_chat['id']}, _if)
                                except Exception:
                                    pass
                                _wiring_block = True
                            else:
                                # No issues — clean up any stale integrity file
                                try:
                                    _integrity_path = os.path.join(
                                        workspace_path, '.sentinel', 'tasks', task_id, 'last_integrity.json'
                                    )
                                    if os.path.exists(_integrity_path):
                                        os.remove(_integrity_path)
                                except Exception:
                                    pass
                        except Exception as _ie:
                            _safe_log(f"[Integrity] Check failed with error: {_ie}")

                    # Check #2: Import smoke test on step's owned .py files
                    if _is_impl_child and not _wiring_block and import_smoke_nudge_count < 1:
                        _step_desc_smoke = step_for_chat.get('description', '')
                        _owned_smoke = AgentService._extract_owned_files(_step_desc_smoke)
                        _py_owned = [f for f in _owned_smoke if f.endswith('.py')][:3]

                        if _py_owned:
                            # Resolve venv python
                            _venv_dir = os.path.join(workspace_path, '.venv')
                            _venv_python = None
                            if os.path.isdir(_venv_dir):
                                _scripts = 'Scripts' if platform.system() == 'Windows' else 'bin'
                                _py_exe = 'python.exe' if platform.system() == 'Windows' else 'python'
                                _candidate = os.path.join(_venv_dir, _scripts, _py_exe)
                                if os.path.isfile(_candidate):
                                    _venv_python = _candidate
                            _python_bin = _venv_python or sys.executable

                            _import_failures = []
                            for _pyf in _py_owned:
                                # Convert file path to module name: "api/routes.py" -> "api.routes"
                                _mod_name = _pyf.replace('/', '.').replace('\\', '.')
                                if _mod_name.endswith('.py'):
                                    _mod_name = _mod_name[:-3]
                                if _mod_name.endswith('.__init__'):
                                    _mod_name = _mod_name[:-9]
                                try:
                                    _smoke_result = subprocess.run(
                                        [_python_bin, '-c', f'import {_mod_name}'],
                                        capture_output=True, text=True, timeout=10,
                                        cwd=workspace_path
                                    )
                                    if _smoke_result.returncode != 0:
                                        _err_lines = _smoke_result.stderr.strip().split('\n')
                                        _err_msg = _err_lines[-1] if _err_lines else 'Unknown error'
                                        _import_failures.append((_pyf, _err_msg))
                                except subprocess.TimeoutExpired:
                                    _import_failures.append((_pyf, 'Import timed out (>10s)'))
                                except Exception:
                                    pass

                            if _import_failures:
                                import_smoke_nudge_count += 1
                                _smoke_nudge = nudges.import_smoke_failed(failures=_import_failures)
                                yield f"data: {json.dumps({'token': ''})}\n\n"
                                AgentService.add_message(task_id, chat_id, "user", _smoke_nudge,
                                                         meta={"is_tool_result": True})
                                history.append({"role": "user", "content": _smoke_nudge})
                                yield f"event: tool_result\ndata: {json.dumps({'result': _smoke_nudge})}\n\n"
                                _safe_log(f"[ImportSmoke] Nudge: {len(_import_failures)} import failures")
                                _wiring_block = True

                    # Check #4: Verify Modifies: files were actually edited
                    if _is_impl_child and not _wiring_block and modifies_nudge_count < 1:
                        _step_desc_mod = step_for_chat.get('description', '')
                        _modifies_expected = AgentService._extract_modifies_files(_step_desc_mod)

                        if _modifies_expected and written_files:
                            _written_basenames = set()
                            for _wf_path in written_files:
                                _written_basenames.add(os.path.basename(_wf_path))
                                _written_basenames.add(_wf_path.replace('\\', '/'))

                            _missing_modifies = []
                            for _mf in _modifies_expected:
                                _mf_basename = os.path.basename(_mf)
                                if (_mf not in _written_basenames
                                        and _mf_basename not in _written_basenames
                                        and not any(_mf_basename in wf for wf in written_files)):
                                    _missing_modifies.append(_mf)

                            if _missing_modifies:
                                modifies_nudge_count += 1
                                _mod_nudge = nudges.modifies_not_edited(
                                    missing_files=_missing_modifies,
                                    step_name=step_for_chat.get('name', '')
                                )
                                yield f"data: {json.dumps({'token': ''})}\n\n"
                                AgentService.add_message(task_id, chat_id, "user", _mod_nudge,
                                                         meta={"is_tool_result": True})
                                history.append({"role": "user", "content": _mod_nudge})
                                yield f"event: tool_result\ndata: {json.dumps({'result': _mod_nudge})}\n\n"
                                _safe_log(f"[Modifies] Nudge: {_missing_modifies} not edited")
                                _wiring_block = True

                    # Check #5: Depends-on wiring validation
                    if _is_impl_child and not _wiring_block and depends_nudge_count < 1:
                        _step_desc_dep = step_for_chat.get('description', '')
                        _depends_match = re.search(r'Depends?\s*on:\s*(.+)', _step_desc_dep)

                        if _depends_match:
                            _dep_names = re.split(r'\s*,\s*', _depends_match.group(1).strip())
                            _dep_names = [d.strip().strip('"').strip("'") for d in _dep_names if d.strip()]

                            # Resolve dependency step names to their expected output files
                            try:
                                _task_data = TaskService.get_task(task_id)
                                _all_steps = _task_data.get('steps', []) if _task_data else []
                            except Exception:
                                _all_steps = []

                            _dep_files = []
                            for _dep_name in _dep_names:
                                # Skip "none" or empty
                                if _dep_name.lower() in ('none', 'n/a', ''):
                                    continue
                                _dep_step = AgentService._find_step_by_name(_all_steps, _dep_name)
                                if _dep_step:
                                    _dep_desc = _dep_step.get('description', '')
                                    _dep_owned = AgentService._extract_owned_files(_dep_desc)
                                    _dep_py = [f for f in _dep_owned if f.endswith('.py')]
                                    _dep_files.extend(_dep_py)

                            # Check if current step's written .py files import from dependency modules
                            if _dep_files:
                                _dep_modules = set()
                                for _df in _dep_files:
                                    _mod = os.path.basename(_df).replace('.py', '')
                                    _dep_modules.add(_mod)

                                _has_import = False
                                for _wf_path in written_files:
                                    if not _wf_path.endswith('.py'):
                                        continue
                                    _abs_wf = os.path.join(workspace_path, _wf_path.replace('/', os.sep))
                                    if not os.path.isfile(_abs_wf):
                                        continue
                                    try:
                                        with open(_abs_wf, 'r', encoding='utf-8', errors='replace') as _wf:
                                            _wf_source = _wf.read()
                                        for _dm in _dep_modules:
                                            if re.search(
                                                rf'\bimport\s+{re.escape(_dm)}\b|\bfrom\s+{re.escape(_dm)}\b',
                                                _wf_source
                                            ):
                                                _has_import = True
                                                break
                                    except Exception:
                                        pass
                                    if _has_import:
                                        break

                                if not _has_import and _dep_modules:
                                    depends_nudge_count += 1
                                    _dep_nudge = nudges.depends_on_not_wired(
                                        dep_modules=list(_dep_modules),
                                        step_name=step_for_chat.get('name', '')
                                    )
                                    yield f"data: {json.dumps({'token': ''})}\n\n"
                                    AgentService.add_message(task_id, chat_id, "user", _dep_nudge,
                                                             meta={"is_tool_result": True})
                                    history.append({"role": "user", "content": _dep_nudge})
                                    yield f"event: tool_result\ndata: {json.dumps({'result': _dep_nudge})}\n\n"
                                    _safe_log(f"[DependsOn] Nudge: no imports from {_dep_modules}")
                                    _wiring_block = True

                    # If any wiring check fired a nudge, re-enter the agent loop
                    if _wiring_block:
                        continue

                    # Artifact exists (written by agent, auto-saved, or step doesn't need one) — mark step completed
                    if artifact_exists or not expected_artifact:
                        try:
                            fresh_task = TaskService.get_task(task_id)
                            fresh_step = AgentService._find_step_by_chat_id(
                                fresh_task.get('steps', []), chat_id
                            )
                            if fresh_step and fresh_step['status'] == 'in_progress':
                                TaskService.update_step_in_plan(
                                    workspace_path, task_id, step_for_chat['id'],
                                    {'status': 'completed'}
                                )
                                _safe_log(f"Step {step_for_chat['id']} marked completed (artifact verified)")

                                # Post-Planning hook: rewrite plan.md with implementation subtasks
                                # Must run BEFORE step_completed event so frontend sees updated plan
                                if step_for_chat['id'] == 'planning':
                                    try:
                                        AgentService._inject_subtasks_into_plan(workspace_path, task_id)
                                        _safe_log(f"[Planning] Injected implementation subtasks into plan.md")
                                    except Exception as e:
                                        _safe_log(f"[Planning] Failed to inject subtasks: {e}")
                                        import traceback as tb
                                        tb.print_exc()

                                # Post-Implementation hook: auto-install third-party dependencies
                                # Runs after each implementation child step to ensure pip packages
                                # are installed in .venv before the next step or review runs.
                                # 100% hardcoded — no LLM involved.
                                if step_for_chat['id'] not in SDD_STEPS and step_for_chat['id'] != 'implementation':
                                    try:
                                        install_result = AgentService._auto_install_dependencies(workspace_path)
                                        if install_result['installed']:
                                            pkg_list = ', '.join(install_result['installed'])
                                            _safe_log(f"[AutoInstall] Post-step installed: {pkg_list}")
                                            yield f"event: auto_install\ndata: {json.dumps({'packages': install_result['installed'], 'status': 'success'})}\n\n"
                                        if install_result['requirements_updated']:
                                            _safe_log("[AutoInstall] requirements.txt was updated with missing packages")
                                        if install_result['errors']:
                                            for err in install_result['errors']:
                                                _safe_log(f"[AutoInstall] Error: {err}")
                                            yield f"event: auto_install\ndata: {json.dumps({'errors': install_result['errors'], 'status': 'error'})}\n\n"
                                    except Exception as e:
                                        _safe_log(f"[AutoInstall] Hook failed: {e}")
                                        import traceback as tb
                                        tb.print_exc()

                                # Post-Implementation hook: run tests if any exist
                                if step_for_chat['id'] not in SDD_STEPS and step_for_chat['id'] != 'implementation':
                                    try:
                                        test_result = run_tests(workspace_path, timeout=30)
                                        if test_result['ran']:
                                            _test_status = 'passed' if test_result['failed'] == 0 else 'failed'
                                            _safe_log(
                                                f"[TestRunner] Tests {_test_status}: "
                                                f"{test_result['passed']} passed, {test_result['failed']} failed"
                                            )
                                            yield f"event: test_result\ndata: {json.dumps({'passed': test_result['passed'], 'failed': test_result['failed'], 'errors': test_result['errors'][:5], 'status': _test_status})}\n\n"
                                    except Exception as _te:
                                        _safe_log(f"[TestRunner] Error: {_te}")

                                # Send step summary BEFORE step_completed so the frontend
                                # renders it into the current chat before auto-start switches view
                                try:
                                    summary_data = AgentService._build_step_summary(
                                        step_for_chat, workspace_path, task_id, written_files
                                    )
                                    if summary_data:
                                        markdown = summary_data['markdown']
                                        structured = summary_data['structured']
                                        AgentService.add_message(task_id, chat_id, "assistant", markdown,
                                                                  meta={"is_summary": True, "structured": structured})
                                        yield f"event: step_summary\ndata: {json.dumps({'content': markdown, 'structured': structured})}\n\n"
                                except Exception as e:
                                    _safe_log(f"[Summary] Error generating step summary: {e}")

                                # NOTE: integrity_warning SSE removed — replaced by Code Check Agent
                                # which runs client-side via /api/tasks/<id>/code-check endpoint

                                yield f"event: step_completed\ndata: {json.dumps({'stepId': step_for_chat['id']})}\n\n"

                        except Exception as e:
                            _safe_log(f"Error marking step complete: {e}")
                            import traceback
                            traceback.print_exc()

                        # Signal cancellation so the LLM worker thread releases the GPU lock
                        # immediately, rather than waiting for the token queue to fill up.
                        if cancel_event:
                            cancel_event.set()

                        llm_log.turn_end('step_complete')
                        llm_log.step_complete(_step_name_for_log, list(written_files.keys()) if written_files else [])

                        # ── RL: Score this step + confirm/penalize injected lessons ──
                        try:
                            _expected_fc = len(AgentService._extract_owned_files(
                                step_for_chat.get('description', ''))) if step_for_chat else 0
                            _step_score = score_step(
                                step_id=step_for_chat.get('id', '') if step_for_chat else 'unknown',
                                written_files=written_files,
                                turn_count=current_step,
                                nudge_count=nudge_count,
                                code_in_prose_count=code_in_prose_count,
                                tool_failure_count=_step_tool_failures,
                                micro_agent_warnings=_step_micro_warnings,
                                expected_file_count=_expected_fc,
                            )
                            _safe_log(
                                f"[RL] Step scored: {_step_score['grade']} "
                                f"({_step_score['composite']:.3f}) — "
                                f"files={_step_score['file_count']}, turns={_step_score['turn_count']}"
                            )
                            # Confirm or penalize injected lessons based on step score
                            for _lid in _injected_lesson_ids:
                                try:
                                    if _step_score['composite'] >= 0.6:
                                        ExperienceMemory.confirm(_lid)
                                    elif _step_score['composite'] < 0.4:
                                        ExperienceMemory.penalize(_lid)
                                except Exception:
                                    pass
                            # Stash step score for task-level aggregation (thread-safe)
                            AgentService._stash_step_score(task_id, _step_score)
                        except Exception as _rl_e:
                            _safe_log(f"[RL] Step scoring failed: {_rl_e}")

                        yield _done_event(full_response)
                        break

                elif not tool_matches:
                    # No tool call and no [STEP_COMPLETE]
                    no_progress_turns += 1  # G7: no tool calls = no progress
                    # Guard: if the response is an error message, don't stall-nudge
                    # (nudging would add more tokens, making context overflow worse)
                    if '[Error from LLM:' in full_response or '[Error:' in full_response:
                        _safe_log(f"[Agent] Skipping stall nudge — response contains error")
                        break

                    # G7: If agent has made no progress for too many turns, force-abort
                    if no_progress_turns >= AgentService._MAX_NO_PROGRESS_TURNS:
                        _safe_log(f"[Guardrail] No progress for {no_progress_turns} turns — force-aborting")
                        yield f"event: error\ndata: {json.dumps({'error': f'Agent made no progress for {no_progress_turns} consecutive turns. The model may be confused — try restarting the step.'})}\n\n"
                        if cancel_event:
                            cancel_event.set()
                        yield _done_event('', error=True, stalled=True)
                        break

                    if step_for_chat and stall_nudge_count < 2:
                        # Step-based chat: agent may have stalled. Nudge with step-specific instructions.
                        stall_nudge_count += 1
                        step_sid = step_for_chat['id']
                        artifact_map = {
                            'requirements': 'requirements.md',
                            'technical-specification': 'spec.md',
                            'planning': 'implementation-plan.md',
                        }
                        if step_sid in artifact_map:
                            nudge_msg = nudges.stall_sdd(target_file=artifact_map[step_sid])
                        else:
                            nudge_msg = nudges.stall_implementation()
                        AgentService.add_message(task_id, chat_id, "user", nudge_msg, meta={"is_tool_result": True, "is_system_nudge": True})
                        history.append({"role": "user", "content": nudge_msg})
                        # Don't yield to SSE — stall nudges are internal, not shown to user
                        continue
                    elif step_for_chat:
                        # Step-based chat: max stall nudges reached — force-complete
                        _safe_log(f"[Agent] Max stall nudges reached for step {step_for_chat['id']}, force-completing")

                        # Try to save artifact from best available content
                        expected_artifact = AgentService._get_expected_artifact(
                            step_for_chat['id'], os.path.join(workspace_path, '.sentinel', 'tasks', task_id)
                        )
                        quality_warning = None
                        if expected_artifact:
                            artifact_basename = os.path.basename(expected_artifact)
                            artifact_ok = False
                            try:
                                artifact_ok = os.path.exists(expected_artifact) and os.path.getsize(expected_artifact) > 200
                            except Exception:
                                pass
                            # Try WriteFile content first, then narration extraction
                            force_content = best_writefile_content if best_writefile_content else ''
                            if not force_content and artifact_basename.endswith('.md'):
                                force_content = AgentService._extract_markdown_from_narration(full_response)
                                if force_content:
                                    _safe_log(f"[Rescue] Extracted {len(force_content)} chars from narration for force-save")
                            if not artifact_ok and force_content and len(force_content) > 200:
                                is_valid, reason = AgentService._validate_artifact_content(force_content, artifact_basename)
                                if is_valid:
                                    # Unescape literal \n in markdown
                                    if artifact_basename.endswith('.md'):
                                        force_content = force_content.replace('\\n', '\n').replace('\\t', '\t')
                                    try:
                                        os.makedirs(os.path.dirname(expected_artifact), exist_ok=True)
                                        with open(expected_artifact, 'w', encoding='utf-8') as f:
                                            f.write(force_content)
                                        written_files[artifact_basename] = {
                                            'is_new': True,
                                            'added': len(force_content.splitlines()),
                                            'removed': 0,
                                        }
                                        _safe_log(f"[Agent] Force-saved content as {artifact_basename}")
                                    except Exception as e:
                                        _safe_log(f"[Agent] Force-save failed: {e}")
                                else:
                                    quality_warning = f"Step completed but {artifact_basename} may have low quality: {reason}"
                                    _safe_log(f"[Agent] Force-save BLOCKED for {artifact_basename}: {reason}")

                        # Mark step completed
                        try:
                            fresh_task = TaskService.get_task(task_id)
                            fresh_step = AgentService._find_step_by_chat_id(
                                fresh_task.get('steps', []), chat_id
                            )
                            if fresh_step and fresh_step['status'] == 'in_progress':
                                TaskService.update_step_in_plan(
                                    workspace_path, task_id, step_for_chat['id'],
                                    {'status': 'completed'}
                                )
                                yield f"event: step_completed\ndata: {json.dumps({'stepId': step_for_chat['id']})}\n\n"
                                _safe_log(f"[Agent] Step {step_for_chat['id']} force-completed after stall")
                        except Exception as e:
                            _safe_log(f"[Agent] Error force-completing step: {e}")

                        # Generate summary for force-completed step
                        try:
                            summary_data = AgentService._build_step_summary(
                                step_for_chat, workspace_path, task_id, written_files
                            )
                            if summary_data:
                                markdown = summary_data['markdown']
                                structured = summary_data['structured']
                                AgentService.add_message(task_id, chat_id, "assistant", markdown,
                                                          meta={"is_summary": True, "structured": structured})
                                yield f"event: step_summary\ndata: {json.dumps({'content': markdown, 'structured': structured})}\n\n"
                        except Exception as e:
                            _safe_log(f"[Summary] Error generating force-complete summary: {e}")

                        # Emit quality warning if artifact failed validation
                        if quality_warning:
                            yield f"event: warning\ndata: {json.dumps({'message': quality_warning})}\n\n"

                        # ── RL: Score force-completed step (poor outcome = learning signal) ──
                        if step_for_chat:
                            try:
                                _expected_fc2 = len(AgentService._extract_owned_files(
                                    step_for_chat.get('description', '')))
                                _step_score = score_step(
                                    step_id=step_for_chat.get('id', 'unknown'),
                                    written_files=written_files,
                                    turn_count=current_step,
                                    nudge_count=nudge_count,
                                    code_in_prose_count=code_in_prose_count,
                                    tool_failure_count=_step_tool_failures,
                                    micro_agent_warnings=_step_micro_warnings,
                                    expected_file_count=_expected_fc2,
                                )
                                _safe_log(f"[RL] Force-complete step scored: {_step_score['grade']} ({_step_score['composite']:.3f})")
                                for _lid in _injected_lesson_ids:
                                    try:
                                        if _step_score['composite'] >= 0.6:
                                            ExperienceMemory.confirm(_lid)
                                        elif _step_score['composite'] < 0.4:
                                            ExperienceMemory.penalize(_lid)
                                    except Exception:
                                        pass
                                AgentService._stash_step_score(task_id, _step_score)
                            except Exception as _rl_e:
                                _safe_log(f"[RL] Force-complete scoring failed: {_rl_e}")

                        if cancel_event:
                            cancel_event.set()
                        yield _done_event(full_response)
                        break
                    else:
                        # Free chat — just stop
                        if cancel_event:
                            cancel_event.set()
                        yield _done_event(full_response)
                        break

            except Exception as e:
                _safe_log(f"[Agent] Error in stream: {e}")
                llm_log.error(f'Exception in stream: {e}')
                llm_log.turn_end('error')
                import traceback
                traceback.print_exc()
                if cancel_event:
                    cancel_event.set()
                yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
                yield _done_event('', error=True)
                break
        else:
            # while loop exhausted MAX_STEPS without break — agent stalled
            _safe_log(f"[Agent] WARNING: Exhausted {MAX_STEPS} turns without [STEP_COMPLETE]")
            llm_log.turn_end('max_turns_exhausted')
            llm_log.error(f'Exhausted {MAX_STEPS} turns without [STEP_COMPLETE]')
            if cancel_event:
                cancel_event.set()
            # Persist hasStalled so the UI shows the restart banner on next visit
            try:
                from services.storage import StorageService
                raw = StorageService.load_json('tasks', f"{task_id}.json")
                if raw and not raw.get('hasStalled'):
                    raw['hasStalled'] = True
                    StorageService.save_json('tasks', f"{task_id}.json", raw)
            except Exception:
                pass
            yield f"event: error\ndata: {json.dumps({'error': f'Agent exhausted {MAX_STEPS} turns without completing. The step may be too complex — try breaking it into smaller sub-steps.'})}\n\n"
            yield _done_event(full_response, stalled=True)
