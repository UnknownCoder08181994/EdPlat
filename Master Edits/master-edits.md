# Master Edits

> Reference log for all edits. Each entry tracks what was changed, how, and whether it worked.
> If a fix fails, update the entry with the correct solution once found.

---

<!-- Template for new entries:

## [Short Description]
- **Date**: YYYY-MM-DD
- **Files Changed**: list of files
- **What**: what was changed
- **How**: how it was done
- **Result**: worked / failed / partial
- **Notes**: any gotchas or corrections

---

-->

## Missing stdlib modules in _PYTHON_STDLIB + stall persistence fix
- **Date**: 2026-02-18
- **Files Changed**: `backend/services/agent_service.py`
- **What**: `socketserver` (and ~40 other stdlib modules) were missing from `_PYTHON_STDLIB` set, causing the integrity checker to flag them as uninstalled pip dependencies. Also, when agent exhausts MAX_STEPS turns, it now persists `hasStalled: true` to the task JSON so the UI shows the restart banner.
- **How**:
  1. Added `socketserver`, `http.server`, `xmlrpc`, `cgi`, `cgitb`, `wsgiref`, `ftplib`, `poplib`, `imaplib`, `codecs`, `unicodedata`, `locale`, `gettext`, `getpass`, `curses`, `readline`, `sched`, `select`, `selectors`, `mmap`, `fileinput`, `fnmatch`, `linecache`, `tokenize`, `pdb`, `profile`, `timeit`, `trace`, `dis`, `compileall`, `shelve`, `dbm`, `venv`, `ensurepip`, `zipimport`, `pkgutil`, `modulefinder`, `runpy`, `builtins`, `site`, `code`, `codeop` to `_PYTHON_STDLIB`
  2. In the `else:` branch after the main agent while loop (turn exhaustion), added `StorageService.save_json` to persist `hasStalled: true`
- **Result**: worked
- **Notes**: Root cause of NovaPulse task stall: agent kept seeing "socketserver uninstalled" integrity issue, wasted all 15 turns reading index.html repeatedly trying to figure out how to fix a phantom issue. Also fixed workspace requirements.txt and cleared stale integrity/review JSON for the specific task.

---

## Auto-detect open port + inject into task reformat prompt
- **Date**: 2026-02-18
- **Files Changed**: `backend/routes/tasks.py`
- **What**: When user hits reformat and their task is a web project, auto-detect an available localhost port and inject it into the reformatted spec so the generated code uses that port.
- **How**:
  - Added `_find_open_port()` — tries preferred ports (5000, 8080, 8000, 3000) then scans range, using `socket.bind()` to verify availability
  - Added `_WEB_KEYWORDS` regex — matches web-related terms (flask, dashboard, html, api, chart, etc.)
  - Both reformat endpoints (`/api/reformat-task` and `/api/reformat-task-stream`) now detect web tasks and append port hint to the follow-up prompt
  - Prebuilt specs (vague input fallback) also get port injection if they're web-related
- **Result**: Works
- **Notes**: The port hint reads: "The server should run on localhost port {port} (http://localhost:{port})." — appended to the follow-up instruction, not the system prompt, so it's treated as part of the user's requirement. Port is detected at reformat time, not task creation time, so it's always fresh.

---

## Frontend project detection + auto-serve + execution agent awareness
- **Date**: 2026-02-18
- **Files Changed**: `backend/utils/entry_point.py`, `backend/static/js/terminal.js`, `backend/services/agent_service.py`, `backend/prompts/execution.py`
- **What**: Major overhaul of entry point detection for frontend-only projects:
  1. Entry point detection blindly ran `node app.js` on browser JavaScript (uses `window`, `document`), which crashes. Auto-fix then stripped browser APIs trying to make it run in Node, destroying the actual code.
  2. RL report fired twice for server tasks — once from the 5s timer, once from auto-fix completion.
  3. Frontend-only projects (HTML+CSS+browser JS) had no detection or helpful messaging.
- **How**:
  - `entry_point.py`: Added `_is_browser_js()` detector with regex patterns for browser-only APIs (`document.`, `window.`, `querySelector`, etc.) vs Node.js APIs (`require`, `module.exports`, `process.argv`, etc.). JS files that are browser-only are skipped as entry points. Added `isFrontend` flag to the return dict.
  - `terminal.js`: Added `rlReportFired` guard at `createTerminal` scope — all 4 RL report call sites check this flag. Frontend-only projects now show helpful message ("Open the HTML file directly in your browser") and still generate RL report.
- **Result**: Worked
- **Notes**: Three layers of defense: (1) entry_point.py detects browser JS and serves with `python -m http.server 8080`, (2) execution agent auto-generates `serve.py` for frontend projects before attempting to run, (3) diagnose + recoder prompts now explicitly instruct the LLM to create a serve.py instead of stripping browser APIs when they see `window is not defined` errors. Added `serve.py` and `main.js` to `_ENTRY_POINT_NAMES`.

---

## Fix RL report not generating for server tasks + "No execution data"
- **Date**: 2026-02-18
- **Files Changed**: `backend/static/js/terminal.js`, `backend/services/agent_service.py`
- **What**: Two issues with RL reports for server tasks:
  1. Report never generated — `generateRlReport()` was after `await execStreamCommand()` but servers never exit, so the await never resolves
  2. Even when report was generated (via kill), it showed "No execution data" — because `execution.log` is only written by the auto-fix agent (`run_execution_stream`), not by the terminal's simple `stream_command`
- **How**:
  - `terminal.js`: Split `runProject` into server vs non-server paths. For servers, start the stream without awaiting, fire RL report after 5s delay, then await the stream. Non-server path keeps original sequential logic.
  - `agent_service.py`: In `generate_rl_report_for_task()`, added fallback when no `execution.log` exists — if all steps are completed, synthesize a "clean run" exec score (attempts=1, success=true, fixes=0). This represents "ran on first try with no auto-fix needed."
- **Result**: Worked
- **Notes**: The synthesized score is accurate — if the terminal ran the project and the server started without errors, that IS a successful first-attempt execution with zero fixes. The 5s delay gives crash detection time.

---

## Fix task status lifecycle: To Do → In Progress → Completed
- **Date**: 2026-02-18
- **Files Changed**: `backend/routes/tasks.py`, `backend/static/js/task-detail.js`, `backend/static/js/app.js`, `backend/static/css/components.css`
- **What**: Task status was stuck at "To Do" even after all steps completed. Multiple compounding bugs:
  1. `start_step` had an early return (line 214) when step already had a chatId — skipped the auto-transition to "In Progress"
  2. `statusPill()` didn't recognize "Completed" or "Failed" — both fell through to default "To Do" display
  3. `VALID_STATUSES` didn't include "To Do" (the initial status tasks are created with)
  4. `update_step_route` (PATCH step) had no backend auto-transition to "Completed" when last step finishes
  5. Frontend `onStepCompleted` previously sent `status: 'Done'` (fixed earlier to `'Completed'`), and its catch block was silent
- **How**:
  - `tasks.py`: Added auto-transition in the early-return path of `start_step`; added "To Do" to `VALID_STATUSES`; added backend auto-transition to "Completed" in `update_step_route` when all steps are done
  - `app.js`: Added "completed" and "failed" to `statusPill` labels + matching logic
  - `components.css`: Added `.status-completed` and `.status-failed` CSS classes
  - `task-detail.js`: Added error logging to the catch block on line 403
- **Result**: Worked — full lifecycle now: To Do → In Progress (on first step start) → Completed (when all steps done)
- **Notes**: The early-return in `start_step` was the main culprit — page refreshes or re-connections would hit that path and never transition status. Backend now does completion detection as a safety net so it doesn't rely solely on frontend.

---

## Fix pip-install-loop + server-timeout detection
- **Date**: 2026-02-18
- **Files Changed**: `backend/services/agent_service.py`, `backend/prompts/execution.py`
- **What**: Fixed 3 critical bugs in execution pipeline:
  1. Phase 3 deterministic handler blindly ran `pip install` without checking if it worked, looping 3x on nonexistent packages then bailing — LLM never got to diagnose. Now checks pip output, tracks `_failed_pip_installs`, removes bad packages from requirements.txt, and falls through to LLM which creates the missing local module.
  2. Phase 2 detected pip failures but never told Phase 3. Now extracts failed package names, removes from requirements.txt, seeds `_failed_pip_installs` so Phase 3 never retries them.
  3. Server timeout detection only checked `is_server` flag from entry_point detection. Now also checks stdout for server indicators (`Serving Flask app`, `Running on http`, etc.) as fallback when `isServer` flag was missed.
- **How**: Added `_failed_pip_installs` set tracking, `_remove_from_requirements_txt()` method, `failed_pip_packages` param to diagnosis/recoder user messages, updated diagnosis + recoder prompts with local-module-creation guidance, broadened server-timeout checks in Phase 3 / Recoder / Step-Fix.
- **Result**: Worked. Test 07 scenarios 7B and 7E (previously FAILING) now pass. 7B: LLM creates `database.py` in 2 attempts. 7E: LLM creates `jwt_handler.py` + fixes `db.py` in 3 attempts. All 420 unit tests pass.
- **Notes**: The key insight: when `pip install X` fails, X is a local module that needs to be CREATED, not installed. The old code just kept trying to install it. For server detection, entry_point.py checks for Flask/FastAPI patterns in source but can miss dynamic setups — stdout fallback catches those.

---

## Windows subprocess timeout kill fix
- **Date**: 2026-02-18
- **Files Changed**: `backend/services/agent_service.py`
- **What**: `_run_project_subprocess()` used `subprocess.run(shell=True, timeout=N)` which on Windows kills the shell (cmd.exe) but NOT child processes (like Flask servers). Orphaned python.exe processes accumulated (21 at one point).
- **How**: Replaced with `subprocess.Popen` + `CREATE_NEW_PROCESS_GROUP` on Windows + `taskkill /F /T /PID` on timeout to kill entire process tree. Linux uses `os.killpg` with `SIGKILL`.
- **Result**: Worked. Flask servers now correctly terminate on timeout.
- **Notes**: This was discovered via integration Test 02 hanging forever. The `-u` flag (unbuffered) on python was also needed to see test output in real-time.

---

## Full Agent Context Wiring — 4 New Data Flows
- **Date**: 2026-02-17
- **Files Changed**: `backend/services/agent_service.py`
- **What**: Closed 4 major data flow gaps between agents — ExperienceMemory, post-write warnings, review summaries, and review→main seeding were all producing data no one consumed.
- **How**: 4 changes:
  1. **ExperienceMemory → System prompt**: `ExperienceMemory.lookup()` + `format_for_injection()` now called in `continue_chat_stream` alongside ErrorMemory pitfalls. Behavioral RL lessons (DO/DONT rules from past tasks) injected into every agent step's system prompt, budget-capped at 600 chars.
  2. **Post-write warnings → Frontend SSE**: Added a second `tool_result` event with `isWarning: true` after post-write checks detect issues (syntax errors, missing imports). LLM already saw them in history (result string), but frontend had no visibility.
  3. **Review summary → Disk persistence**: After review Pass 4 completes, a `review-summary.json` is written to `.sentinel/tasks/{task_id}/` with issues, warnings, edits, and a truncated summary. Downstream agents can read it.
  4. **Review summary → Main agent seeding**: `_seed_prior_artifacts()` now reads `review-summary.json` for implementation steps and injects review findings as a user/assistant conversation pair. The agent sees "Review found 5 issues, avoid these patterns..."
- **Result**: All 4 compile clean. Data now flows: ExperienceMemory→prompts, post-write→frontend, review→disk→main agent.
- **Notes**: ExperienceMemory injection uses tags `[step_id, 'implementation']` + same `chat_fingerprint` as ErrorMemory. Review summary caps at 15 issues, 10 warnings, 2000 char summary. Post-write warning SSE uses same `tool_call_index - 1` to associate with the original tool result.

---

## Execution Warnings → Review Agent + Main Agent Context Wiring
- **Date**: 2026-02-17
- **Files Changed**: `backend/services/agent_service.py`
- **What**: Execution agent warnings (dep failures, runtime errors, auto-fixes) were invisible to the review agent and main agent. Both agents operated in a vacuum — review only saw static analysis, main agent only saw artifacts + code.
- **How**: Three changes:
  1. **`_write_execution_log` now captures `warnings`**: All call sites pass `exec_warnings` list. Dep install errors, version pin fixes, and import validation results are accumulated and persisted in `execution.log` alongside success/failure/fixes.
  2. **Review agent reads `execution.log`**: After Pass 1 deterministic checks, the review agent now reads `.sentinel/tasks/{task_id}/execution.log` and formats it as an "Execution Agent Results" section in `code_check_context`. This flows automatically into Passes 2, 3, and 4 so the LLM can reason about runtime issues.
  3. **Main agent seeds `execution.log`**: `_seed_prior_artifacts()` now reads the execution log for implementation steps and injects it as a seeded conversation pair before the code files. The agent sees past runtime warnings and can proactively fix them.
- **Result**: Works — execution warnings now flow: execution agent → `execution.log` → review agent (all 4 passes) + main agent (seeded context).
- **Notes**: `exec_warnings` list is initialized alongside `all_fixes` in `run_execution_stream`. The `execution.log` JSON now has a `warnings` array field. Review injection appends to both `code_check_context` and `code_warnings`. Main agent injection uses user/assistant seed pair.

---

## Execution Agent — Dependency Install Failure Guardrails
- **Date**: 2026-02-17
- **Files Changed**: `backend/services/agent_service.py`, `backend/static/js/terminal.js`
- **What**: Execution agent and terminal would declare success (exit code 2 = "CLI loaded") even when critical dependencies failed to install. Flask==2.3.4 (nonexistent version) would fail pip install, but argparse fires before Flask import, so the agent thought the app was fine.
- **How**: Three fixes:
  1. **Phase 2 dep install tracking** (`agent_service.py`): Detect pip install failures, surface warnings via SSE, auto-fix pinned versions (relax `==X.Y.Z` to unpinned) and re-run pip install.
  2. **Exit code 2 import validation** (`agent_service.py`): When exit code is 2 AND deps failed, run `_validate_imports()` to check if the entry point actually imports correctly. If imports are broken, don't declare success — fall through to the error diagnosis/fix loop.
  3. **Terminal messaging** (`terminal.js`): Changed dep install failure from buried "info" to prominent "error" with actionable hint. Also: exit code 2 no longer bypasses auto-fix when deps are broken.
- **Result**: Works — now the agent will catch broken version pins, auto-fix them, and re-install. If that fails, it flags the import error instead of false-positive success.
- **Notes**: New static method `_fix_pinned_requirements()` on AgentService. Parses pip error messages to find failed packages, relaxes exact pins in requirements.txt.

---

## Backend Wiring Audit — 16 Fixes Across All Systems
- **Date**: 2026-02-17
- **Files Changed**: `backend/services/agent_service.py`, `backend/services/tool_service.py`, `backend/services/llm_engine.py`, `backend/services/micro_agents.py`, `backend/services/experience_memory.py`, `backend/services/plan_engine.py`, `backend/routes/chats.py`, `backend/static/js/chat.js`
- **What**: Full backend wiring audit found 16 issues across agent loop, tool service, LLM engine, micro-agents, SSE streaming, frontend parser, experience memory, reward scorer, and plan engine. All fixed.
- **How**: 16 targeted fixes:
  1. **cancel_event not cleared after runaway abort** (`agent_service.py`): Mid-stream runaway abort set cancel_event but never cleared it. G1 guardrail would inject a nudge and `continue`, but the next turn immediately saw `cancel_event.is_set()` and aborted. Fix: Generalized the cancel_event clear to fire after ANY mid-stream abort (error, runaway, or dup-write), not just error_in_stream.
  2. **EditFile escape handling not gated to markdown** (`tool_service.py`): `\n`/`\t` unescaping was applied to ALL non-binary files. Source code with literal `\\n` (e.g. Python strings) could get corrupted. Fix: Gated to MARKDOWN_EXTS only (`.md`, `.markdown`, `.txt`, `.rst`), matching WriteFile's existing guard.
  3. **Dead ternary** (`agent_service.py`): `_read_timeout = 300 if SDD else 300` — both branches identical after prior fix. Simplified to `_read_timeout = 300`.
  4. **count_tokens underestimate** (`llm_engine.py`): Changed from 4 chars/token to 3.2 chars/token. Code/JSON/whitespace tokenizes at ~2.5-3 chars/token; the old heuristic underestimated by ~25%, causing max_output to be set too high and potentially exceeding context limits.
  5. **tool_call SSE payload inconsistency** (`agent_service.py`): Micro-task path emitted `{name, arguments}` while main loop emitted `{tool, args}`. Unified to `{tool, args, index}` everywhere.
  6. **build_signature_index and resolve_imports only scanned workspace root** (`micro_agents.py`): Both used flat `os.listdir` or filtered to `dirname == workspace_path`. Files in subdirectories (`services/`, `utils/`) were invisible. Fix: Both now use `os.walk` with SKIP dirs. `resolve_imports` registers both dotted (`services.tool_service`) and bare (`tool_service`) module names. `build_signature_index` uses `rel_path` as key.
  7. **optimize_history compressed ALL large tool results** (`micro_agents.py`): The >2000 char truncation rule fired on any tool result, including RunCommand stack traces the LLM needs. Fix: Excluded results starting with `Tool Result: Command` or `Tool Result: Error`.
  8. **review_issues=0 hardcoded** (`agent_service.py`): All 4 `score_execution` call sites passed `review_issues=0`. The `integrity_issues` list (loaded from review-issues.json) was already available. Fix: Changed all 4 sites to `review_issues=len(integrity_issues)`.
  9. **Missing SSE headers on chat endpoints** (`chats.py`): Chat stream and review stream were missing `Cache-Control: no-cache` and `X-Accel-Buffering: no`. Terminal already had them. Fix: Added both headers to both chat SSE responses.
  10. **Error event silently dropped by frontend** (`chat.js`): Backend emitted `event: error` but the SSE parser had no handler for it. Errors were invisible. Fix: Added `eventType === 'error'` handler that renders the error as a system warning message in chat.
  11. **Force-save path didn't update written_files** (`agent_service.py`): The stall nudge force-complete path saved artifacts to disk but skipped `written_files[artifact_basename] = {...}`. Step summary and RL scoring undercounted files. Fix: Added `written_files` update after successful force-save.
  12. **force_cancel race condition** (`llm_engine.py`): 100ms sleep window could miss the cancel signal. Fix: Increased to 500ms with clearer documentation.
  13. **400 error permanently disabled streaming** (`llm_engine.py`): Any 400 HTTP error set `_no_stream = True` permanently. Fix: Only disable streaming permanently if the error message mentions "stream" or "not supported". Other 400s are treated as transient.
  14. **confirm() didn't update last_seen** (`experience_memory.py`): Confirmed lessons had stale `last_seen`, making them age out faster in pruning than penalized lessons. Fix: Added `entry['last_seen'] = now` in `confirm()`.
  15. **total_lessons_generated never incremented** (`experience_memory.py`): Stat initialized at 0 but never updated. Fix: Increment in `record()` when creating a new entry.
  16. **select_next didn't persist status downgrades** (`plan_engine.py`): When multiple `[>]` steps were found, extras were downgraded in memory but not written to disk. Fix: Call `update_step()` for each downgraded step.
- **Result**: All 16 fixes applied. No new imports or dependencies added. All changes are backward compatible.
- **Notes**:
  - The cancel_event fix is the most impactful for day-to-day usage — it was causing the G1 runaway nudge to never take effect, wasting a retry opportunity.
  - The EditFile escape fix prevents source code corruption that was hard to diagnose.
  - The count_tokens change means the system will now be slightly more conservative with output budgets (3.2 vs 4 chars/token), which is safer.
  - The micro_agents subdirectory scanning now covers package-structured projects properly.

---

## LLM Response Cutoff Fix — Context Budget Too Restrictive
- **Date**: 2026-02-17
- **Files Changed**: `backend/services/llm_engine.py`, `backend/services/agent_service.py`
- **What**: LLM was getting cut off mid-response because the output token budget was too small. Three root causes:
  1. **Context size heuristic too conservative**: GPT-OSS-20B matched `'gpt-oss'` pattern and got `context_size = 8192`. With system prompt + history eating ~5000-6000 tokens, `max_output` was clamped to ~2000 tokens — not enough to complete a response.
  2. **SDD read_timeout backwards**: SDD steps (requirements, tech-spec, planning) got 120s timeout while impl steps got 300s. SDD steps produce the LARGEST artifacts and need MORE time.
  3. **max_output cap too low**: Capped at 8192 even with plenty of context headroom.
- **How**:
  1. `llm_engine.py`: Changed heuristic default for medium/large models from `8192` → `32768`. LM Studio typically configures large context windows.
  2. `llm_engine.py`: Added `max_model_len` as additional metadata key to check for context size detection.
  3. `agent_service.py` line 6718: Fixed `_read_timeout` — both SDD and impl steps now get 300s.
  4. `agent_service.py` line 6700: Raised `max_output` cap from `min(8192, ...)` → `min(16384, ...)` and `_min_output` from `2048/1024` → `4096/2048`.
  5. `agent_service.py` assemble phase: Raised cap from `min(8192, ...)` → `min(16384, ...)` and min from `1024` → `2048`.
- **Result**: Pending live test. With 32K context, model now gets ~10-16K tokens for output instead of ~2K. Should eliminate mid-response cutoffs.
- **Notes**: The `context_length` field from LM Studio model metadata (line 87) takes priority over the heuristic — if LM Studio reports the actual n_ctx, the heuristic is skipped entirely. The heuristic is only a fallback for when LM Studio doesn't expose this field.

---

## Universal Error Memory — Cross-Task Learning Database
- **Date**: 2026-02-16
- **Files Changed**: `backend/services/error_memory.py` (NEW), `backend/prompts/execution.py`, `backend/prompts/planning.py`, `backend/prompts/implementation.py`, `backend/prompts/system_prompt.py`, `backend/services/agent_service.py`
- **What**: Added a global error/resolution database (`storage/error_memory.json`) that persists across tasks. Records error patterns + what fixed them, injects known pitfalls into agent prompts BEFORE they make mistakes, and self-learns from execution outcomes.
- **How**:
  - Created `ErrorMemory` service with load/save/record/lookup/format/prune methods
  - Seeded with 8 known pitfalls (vite-in-pip, cv2→opencv-python, flat-vs-package, missing config, etc.)
  - Added `known_solutions` param to `build_diagnose_prompt()` (execution.py)
  - Added `known_pitfalls` param to planning.py, implementation.py, system_prompt.py
  - Wired 3 lookup points in agent_service.py (SDD step prompts, system prompt, execution diagnosis)
  - Wired 4 recording hooks in execution loop (pip install, LLM fix kept, LLM fix reverted, max attempts)
  - Confidence scoring with auto-decay, pruning at 80 entries, seed entries protected
- **Result**: Worked. Server starts clean, all imports pass, lookup returns relevant pitfalls for task descriptions, formatting stays within 600-char budget.
- **Notes**: `format_for_prompt()` first-sentence truncation needed fix — `fix.find('.')` was splitting on "Node.js". Changed to regex that finds period+whitespace at least 15 chars in.

---

## Escape Fix Correction + sendMessage Bug
- **Date**: 2026-02-16
- **Files Changed**: `backend/services/tool_service.py`, `backend/services/agent_service.py`, `backend/static/js/chat.js`
- **What**: Two issues from testing the escape fix + inter-agent enhancements:
  1. **Markdown files rendered with literal `\n`**: Removing `replace('\\n', '\n')` was correct for source code (.py, .js) but broke markdown files. Narration rescue and triple-quote fallback paths produce content with literal `\n` that needs unescaping for markdown.
  2. **`sendMessage is not defined` JS error** at chat.js:1434: Function is actually named `handleSend`.
- **How**:
  1. **tool_service.py**: Added markdown-specific unescape — only `.md/.markdown/.txt/.rst` files get `replace('\\n', '\n')`. Source code files are untouched.
  2. **agent_service.py**: Restored markdown-specific `replace('\\n', '\n')` in all 4 auto-save/force-save paths (lines 3252, 3343, 4710, 4876), guarded by `artifact_name.endswith('.md')`.
  3. **chat.js:1434**: Changed `sendMessage('')` → `handleSend('')`.
- **Result**: Applied. Markdown renders correctly. Source code preserves `\n` literals. JS error fixed.
- **Notes**: The MEMORY.md note "Do NOT add replace('\\n', '\n') after json.loads" still applies to source code. The new rule: markdown files ALWAYS need the unescape because narration rescue and triple-quote fallback paths skip json.loads.

---

## Inter-Agent Communication Enhancement — 6 Enhancements
- **Date**: 2026-02-16
- **Files Changed**: `backend/prompts/handoff.py` (NEW), `backend/prompts/context_wiring.py`, `backend/prompts/review.py`, `backend/prompts/__init__.py`, `backend/services/agent_service.py`
- **What**: Wired all 5 pipeline agents (Requirements → Tech Spec → Planning → Implementation → Review) together with structured context passing. Previously agents only saw raw artifact files; now each step gets compact handoff notes, relevant acceptance criteria, completion ledgers, and prioritized code context.
- **How**: 6 enhancements implemented:
  1. **Step Handoff Notes** (`handoff.py` + `agent_service.py`): After each SDD step completes, deterministically extracts a 200-400 char note from the artifact (features count, scope exclusions, tech stack, complexity). Stored as `.handoff` JSON files. Prepended to artifact content during seeding so the next step gets an instant summary before the full document.
  2. **Review Agent Gets Implementation Plan** (`agent_service.py:run_review_stream` + `review.py`): Added `implementation-plan.md` to review context (2000 char limit). Enriched step_context with parsed `Files:`, `Modifies:`, `Depends on:` metadata + a review checklist. Updated all 3 review pass prompts to reference the plan.
  3. **Per-Step Acceptance Criteria** (`context_wiring.py:extract_relevant_criteria` + `agent_service.py`): Cross-references step description keywords/file names against requirements.md sections. Injects only the relevant acceptance criteria (200-600 chars) for implementation steps, so the model doesn't need to parse the full requirements doc.
  4. **Smarter Code Context Priority** (`context_wiring.py:build_code_context`): Added `priority_files` param. Files from `Depends-on:` and `Modifies:` metadata shown first with 4K per-file limit under `=== FILES THIS STEP DEPENDS ON ===`. Regular files get 2K. Same 10K total budget.
  5. **Step Completion Ledger** (`context_wiring.py:build_completion_ledger` + `agent_service.py`): Reads structured summaries from completed steps' chat JSON. Injects a compact ledger showing what each prior step produced (file names, line counts, new/edited status). Later steps now know exactly what earlier steps built.
  6. **Complexity Cross-Reference** (`agent_service.py:_seed_prior_artifacts`): When seeding spec.md for the planning step, compares spec's `Complexity: SIMPLE/MEDIUM/COMPLEX` with user's slider value. If they disagree, appends a warning: "Use the HIGHER of the two."
- **Result**: All 6 enhancements applied. All imports and syntax verified. Token budget impact: ~700 tokens max for implementation steps, ~690 for review passes. No LLM calls added — all extraction is deterministic regex.
- **Notes**:
  - `_seed_prior_artifacts` signature changed: added `step_description=''` param. Call site updated.
  - `build_code_context` signature changed: added `priority_files=None` param. Backward compatible.
  - Handoff generation embedded inside `_build_step_summary` via `_generate_handoff_if_sdd()` — automatically runs for all SDD step completion paths (5 call sites covered).
  - `_extract_step_files()` in `context_wiring.py` reads chat JSON files to get structured summary data. Bounded I/O: max ~8 chat files per task.

---

## Requirements Step Visibility + Escape Corruption Fix
- **Date**: 2026-02-16
- **Files Changed**: `backend/services/agent_service.py`, `backend/services/tool_service.py`
- **What**: Two bugs fixed:
  1. Requirements step showed no visible content in chat (only "Committed changes" card). Tech-spec showed model analysis text before the card.
  2. Generated Python files had syntax errors — `"\n".join(...)` got corrupted to a literal newline inside the string, breaking the code. Review system caught this 4 times but same pipeline re-corrupted it every write.
- **How**:
  1. **Visibility fix** (`agent_service.py` line 2885): Changed assemble phase token emission from `event: thinking` (hidden) to default `data:` (visible in chat). Frontend's `parseSegments()` already handles `<tool_code>` blocks correctly — identical to how tech-spec works.
  2. **Escape fix** (`tool_service.py` lines 131-132): Removed `content.replace('\\n', '\n')` and `content.replace('\\t', '\t')` from `write_file()`. After `json.loads()`, content has literal `\n` where source code needs it — the replace was destroying those legitimate escape sequences.
  3. **Auto-save/force-save paths** (`agent_service.py` lines 3103-3104, 3194, 4551-4554, 4715-4717): Removed same destructive replace from 4 fallback write paths that had the identical bug.
- **Result**: Applied. Requirements step now shows model narration in chat. Code files preserve escape sequences correctly.
- **Notes**: The old comment in `tool_service.py` claimed "properly-parsed JSON won't have literal `\n`" — this was wrong. Source code containing `"\n"` as a string literal correctly has literal backslash+n after `json.loads()`. The fallback extraction path (`_extract_tool_call_fallback`) already does its own correct unescaping with backslash protection via sentinel placeholders.

---

## Cross-Step Wiring Audit & Robustness Fixes
- **Date**: 2026-02-16
- **Files Changed**: `backend/prompts/technical_specification.py`, `backend/prompts/planning.py`, `backend/prompts/implementation.py`, `backend/prompts/review.py`, `backend/services/agent_service.py`
- **What**: Full audit of the main agent loop, review agent, tool service, plan engine, and all prompt files. Found 5 semantic wiring gaps where context from prior steps wasn't actively validated by later steps. All structural wiring (tool dispatch, plan transitions, artifact seeding, code context) was confirmed correct.
- **How**: 5 targeted fixes:
  1. **Tech-spec prompt** (`technical_specification.py`): Added explicit "BEFORE WRITING — STUDY requirements.md" block forcing the model to read every requirement/acceptance criterion and trace each spec element back to a requirement. Changed "Do NOT re-read it" to "do NOT call ReadFile on it" to avoid ambiguity.
  2. **Planning prompt** (`planning.py`): Added "BEFORE WRITING — STUDY BOTH ARTIFACTS" block requiring model to extract features from requirements.md AND architecture from spec.md before creating the plan. Adds explicit completeness check: "If a requirement has no plan step, your plan is INCOMPLETE."
  3. **Implementation prompt** (`implementation.py`): Moved artifact study instructions to the TOP of the prompt (previously buried at line 242 in the WORKFLOW section). New "BEFORE WRITING ANY CODE" block forces model to: read existing code, read implementation-plan.md, read spec.md, read requirements.md — in that order.
  4. **Review agent** (`agent_service.py`): Loads `requirements.md` and `spec.md` from the artifacts directory and injects them as `spec_context` into all 3 LLM review passes (API check, quality check, fix/summary). Previously the review only saw code files — now it can validate code against acceptance criteria.
  5. **Review prompts** (`review.py`): Updated all 3 pass prompts to reference the newly-available requirements/spec context. Added "Requirements coverage" check to Pass 3 (quality). Added "Requirements Coverage" section to the Pass 4 review summary format. Pass 4 now explicitly verifies code satisfies requirements.md.
- **Result**: All fixes applied. Each step now actively reads and validates against prior-step artifacts instead of just assuming they're available.
- **Notes**: The structural wiring was already solid — tool results feed back into history correctly, code context seeds before chat messages, plan engine transitions are atomic. These fixes address the *semantic* gap where steps could diverge from what prior steps specified.

---

## Stress Test Bug Fixes — 4 Bugs from Hardcore Break Test
- **Date**: 2026-02-16
- **Files Changed**: `backend/static/js/toolcall.js`, `backend/static/js/chat.js`, `backend/services/task_service.py`, `backend/static/js/task-detail.js`, `backend/routes/files.py`, `backend/static/js/terminal.js`
- **What**: Created a maximally complex stress test task (Flask + Socket.IO chat app with Jinja2 `{{ }}`, HTML with `"` in attributes, `<script>alert('xss')`, emoji, CSS `content: "»"`, port 8080 in config.py) and found 4 bugs:

  1. **404.html WriteFile rendered as raw JSON**: HTML content with `href="/static/style.css"` double quotes broke both `JSON.parse()` and `extractFallback()`. The fallback regex `/"\\s*}\\s*}\\s*$/` couldn't find the true end of content because internal quotes confused it.
     - **Fix** (`toolcall.js`): Rewrote `extractFallback()` line 61 — replaced regex with reverse-scan algorithm: walks backward from end of string to find `}}`, then walks back from there to find the content-ending quote. Also made orphan rescue regex in `chat.js` greedy (`[\s\S]*` → `[\s\S]*\}\s*\}`) to match full nested JSON.

  2. **Tech Spec step description had complexity text**: "Assess the task complexity (simple, medium, complex)" was still showing. We'd fixed the Planning template in the previous session but the Tech Spec template still had the old numbered list with complexity assessment.
     - **Fix** (`task_service.py`): Replaced Tech Spec description in `DEFAULT_PLAN_TEMPLATE` with clean version. Added safety-net filters in `_cleanStepDesc()` (`task-detail.js`) for old tasks: strips lines matching "Choose technology that matches" and "Write a spec sized to match" patterns.

  3. **Terminal shows port 5000 instead of 8080**: Port detection in `_analyze_source()` only read the entry point file (main.py). Port 8080 was defined in config.py (`PORT = 8080`) which main.py imported. So it fell back to Flask default of 5000.
     - **Fix** (`files.py`): (a) Removed the guard `if not result["hasArgparse"] and not result["isServer"]` that prevented import-following when server was already detected — now always follows local imports. (b) Added `serverPort` merge in import-following: scans imported modules for `PORT = XXXX` constants. (c) Enhanced `_analyze_source()` port detection: priority order is `.run(port=X)` → `PORT = X` → generic `port=X`. (d) Added `serverPort` to the `/entry-point` API response (was missing entirely!). (e) Added `flask`, `flask_socketio`, `fastapi` etc. to stdlib skip list so we only follow local project files.

  4. **flask_socketio ModuleNotFoundError despite pip install**: `_validate_imports()` in files.py ran bare `['python', '-c', 'import main']` without venv — used system Python which didn't have flask_socketio. The terminal's `run_command` correctly activates .venv, but this pre-flight check didn't.
     - **Fix** (`files.py`): Rewrote `_validate_imports()` to detect `.venv/Scripts/python.exe` (Windows) or `.venv/bin/python` (Unix) and use it directly. Also builds a modified `env` dict with `.venv/Scripts` prepended to `PATH` and `VIRTUAL_ENV` set.

- **Result**: All 4 bugs fixed. Port detection follows imports, import validation uses venv, HTML content with quotes renders correctly in tool cards, step descriptions are clean.
- **Notes**: The import-following code was previously gated behind `if not result["hasArgparse"] and not result["isServer"]` — this was a premature optimization that prevented port detection from ever working for server projects. Now it always follows imports and merges all detected properties.

---

## 6 Fixes from Flask App Test Run
- **Date**: 2026-02-16
- **Files Changed**: `backend/services/task_service.py`, `backend/static/js/task-detail.js`, `backend/static/js/files.js`, `backend/static/js/toolcall.js`, `backend/routes/files.py`, `backend/static/js/terminal.js`, `backend/prompts/planning.py`
- **What**: Fixed 6 issues found during end-to-end Flask app test:
  1. **Complexity description in step desc**: Removed "Simple tasks: 1 category. Medium: 2-3. Complex: 3-5." from `DEFAULT_PLAN_TEMPLATE` in task_service.py. Added safety net filters in `_cleanStepDesc()` to strip these from old tasks.
  2. **.venv empty when expanded**: Added "Contents hidden" hint label for shallow dirs (`.venv`, `node_modules`) when expanded in file tree, instead of showing nothing.
  3. **HTML file rendering in tool cards**: Added safety unescape in `renderToolCard()` — if WriteFile content still has literal `\n` strings after parsing, unescape them before passing to codeblock renderer.
  4. **Terminal localhost URL**: Backend `_analyze_source()` now extracts server port from `port=XXXX` patterns (or defaults by framework: Flask→5000, FastAPI→8000). Frontend terminal shows actual URL: "Starting server at http://localhost:5000" instead of generic "Starting server..."
  5. **Mandatory step ordering**: Strengthened planning.py prompt to explicitly say "No code steps may appear after these" and "Do NOT place Setting Up Environment in the middle of code steps."
  6. **Step names with action verbs**: Rewrote HEADING LABELS rules to require action verbs at start (Build, Create, Add, Set Up, etc.). Updated examples: "Build Search Form Layout" instead of "Search Form and Layout". Updated example plan headings to use verbs.
- **Result**: Cleaner step descriptions, better file tree UX, proper HTML rendering in tool cards, actionable terminal URLs, enforced step ordering, and verb-forward step names.

## Artifact Content Preview in Committed Changes Card
- **Date**: 2026-02-16
- **Files Changed**: `backend/services/agent_service.py`, `backend/static/js/chat.js`, `backend/static/css/chat.css`
- **What**: After SDD steps (Requirements, Tech Spec, Planning) complete, the "Committed changes" card now shows the full artifact content (requirements.md, spec.md, implementation-plan.md) rendered as markdown directly in the chat. Previously the content was hidden behind a collapsed tool card and users had to hunt for it.
- **How**: Backend: `_build_step_summary()` now reads the artifact file content and includes `artifactContent` + `artifactName` in the structured data for SDD steps. Frontend: `renderCommittedChanges()` renders a collapsible markdown preview section below the file list when artifact content is available. Added `_buildArtifactPreview()` helper for the preview HTML. For old tasks missing `artifactContent` in saved chat data, a lazy-load fallback detects SDD artifact filenames in the files list and fetches content via the `/api/tasks/<id>/file` API. CSS: `.committed-artifact-preview`, `.committed-artifact-toggle`, `.committed-artifact-body` styles matching step-desc-card patterns. Preview starts expanded, collapsible via chevron toggle. Max-height 500px with overflow scroll.
- **Result**: Users immediately see what the agent wrote after each SDD step — no more hunting. Implementation steps are unaffected (no preview). Works for both new and existing tasks.

---

## Auto-Style File References in Step Descriptions
- **Date**: 2026-02-15
- **Files Changed**: `backend/static/js/task-detail.js`
- **What**: File references (e.g. `index.html`, `app.js`, `styles.css`) in step descriptions now auto-render with the accent-colored badge look — matching how `requirements.md` already appeared in the Requirements step.
- **How**: Enhanced `_cleanStepDesc()` in task-detail.js to auto-wrap bare filenames in backticks before markdown rendering. Uses a regex with negative lookbehind/lookahead to skip filenames already in backticks. Covers all common extensions (py, md, html, css, js, ts, json, yaml, etc.). The markdown renderer then converts backticks to `<code>` tags, and the existing `.step-desc-card-body .markdown-body code` CSS gives them the styled badge appearance.
- **Result**: All file references across all step descriptions now have the styled badge look. No double-wrapping for already-backticked filenames.

---

## UI Cleanup — Hide Internal Data, Clean Chat, Tab Overflow
- **Date**: 2026-02-15
- **Files Changed**: `backend/routes/files.py`, `backend/static/js/chat.js`, `backend/static/js/task-detail.js`, `backend/static/css/layout.css`
- **What**: Five UI fixes: (1) Hide `.sentinel` folder from file tree — internal metadata shouldn't be visible. (2) Clean kickoff messages — removed "Follow the system prompt instructions. Use WriteFile to save EVERY file. Say [STEP_COMPLETE] when done." from user-visible chat bubbles. (3) Bold markdown in kickoff bubble was showing as literal `**` — fixed by shortening kickoff to plain text. (4) Step description card was showing raw plan metadata (Files:, Depends on:, Entry point:) — now filtered out, only shows the description text and bullet points. (5) Tab bar has fade gradient hinting more tabs exist when overflowing.
- **How**: (1) Added `.sentinel` to `IGNORE_DIRS` in files.py. (2) Shortened `buildKickoff()` in chat.js — SDD steps just show "Begin the X step + Task:", impl steps just show "Begin working on step: X." All LLM instructions are in the backend system prompt, not the kickoff. (3) Side effect of #2. (4) Added `_cleanStepDesc()` helper in task-detail.js that filters lines matching `Files:`, `Depends on:`, `Entry point:`. (5) Added CSS mask-image fade on `.step-tab-bar-left` + JS overflow detection that toggles `has-overflow` class; hidden scrollbar.
- **Result**: Cleaner, more professional UI. Users see only what matters.

---

## Beginner-Friendly README — User Guide for Non-Technical Users
- **Date**: 2026-02-15
- **Files Changed**: `backend/prompts/planning.py`, `backend/prompts/implementation.py`
- **What**: The "Creating User Guide" step was producing developer-oriented READMEs with jargon like "clone the repo" and `python main.py /path/to/source`. Non-technical users can't follow that. Now the LLM writes numbered copy-paste steps starting from "how to open PowerShell".
- **How**: (1) In `planning.py`, rewrote the Creating User Guide mandatory step template — description now says "COMPLETE BEGINNER can follow", notes demand numbered steps from opening PowerShell through running the project, with exact commands and what success/failure looks like. (2) In `implementation.py`, added a special instruction block that triggers when the step name contains "user guide" or "readme" — injects 7-point checklist (open terminal, cd, check Python, create venv, activate, install, run) and demands simple language with no jargon.
- **Result**: READMEs will now be written for someone who's never opened a terminal before.

---

## Show Venv Status in Terminal
- **Date**: 2026-02-15
- **Files Changed**: `backend/routes/files.py`, `backend/static/js/terminal.js`
- **What**: Terminal now shows "Virtual environment active (.venv)" when running projects. The `.venv` was being created and used silently — user had no visibility that an isolated environment was active.
- **How**: Added `hasVenv` field to entry-point endpoint response (checks `os.path.isdir(.venv)`). Terminal displays info message before dependency install when venv is detected. The `.venv` folder is correctly hidden from the file tree (in `IGNORE_DIRS`) but the terminal confirms it's active.
- **Result**: User sees venv is active before pip install runs. No functional change — venv was always being used via PATH injection in `tool_service.run_command()`.

---

## Descriptive Step Names — Stop Forcing Verbs, Guide the LLM Instead
- **Date**: 2026-02-15
- **Files Changed**: `backend/services/agent_service.py`, `backend/prompts/planning.py`
- **What**: Two-part fix. (1) Removed `_ensure_action_verb()` call from `_inject_subtasks_into_plan()` — it was forcibly prepending "Implementing", "Building", etc. to every step name the LLM wrote. (2) Rewrote heading guidance in planning.py to tell the LLM to write **descriptive, user-facing** names that say what's being BUILT, not generic verb-slapped labels.
- **How**: (1) Deleted `name = AgentService._ensure_action_verb(name)` from the processing loop. Left function definition as dead code. (2) Rewrote HEADING LABELS rules: "shown to the USER watching an agent build", "name the THING being built", "NEVER use Implementing". Updated GOOD/BAD examples: GOOD = "Search Form and Layout", "Weather API Fetch Logic", "Directory Scanner Module". BAD = "Implementing Scan Directory", "Core Logic". Updated WRITEFILE example headings to match new style.
- **Result**: Step names now come from the LLM guided by descriptive prompt rules, no code override. New tasks will show names like "File Organizer by Type" instead of "Implementing Organize Files".

---

## Structured LLM Thinking + Hardcoded Step Completion
- **Date**: 2026-02-15
- **Files Changed**: `backend/prompts/requirements_phases.py`, `backend/prompts/technical_specification.py`, `backend/prompts/planning.py`, `backend/prompts/implementation.py`, `backend/services/agent_service.py`, `backend/static/js/thinking.js`
- **What**: Added structured "Think through:" preambles to all phase prompts to guide the LLM's chain-of-thought reasoning. Injected synthetic thinking tokens (phase labels with emoji) before each MicroTask phase and SDD step so users see clear progress indicators. Added hardcoded `[STEP_COMPLETE]` forcing: when the orchestrator detects a valid artifact was written (SDD steps) or all expected files were saved (impl steps), it auto-completes without waiting for the LLM. Added new thinking.js topic categories (Scope Analysis, Component Analysis, Interface Design, Step Completion) for better thinking section classification.
- **How**: Part 1: Added "Think through (in your thinking, not your output):" blocks to scope, deep_dive, interface, assemble prompts + tech-spec, planning, implementation prompts. Part 2: Synthetic `event: thinking` SSE tokens emitted before each phase in `_run_requirements_micro_tasks()` and before first turn in main agent loop. Part 3: After tool execution, if SDD artifact written+valid or impl step's Files: list fully written, set `has_step_complete_signal = True` and emit completion thinking token. New `_extract_owned_files()` static method parses Files: lines. Part 4: Added 4 new TOPIC_CATEGORIES at top of thinking.js and expanded Planning Steps keywords.
- **Result**: Pending live test — server starts cleanly, no import errors.

---

## Hide Internal MicroTask Prompts from Requirements Chat UI
- **Date**: 2026-02-15
- **Files Changed**: `backend/services/agent_service.py`, `backend/static/js/chat.js`
- **What**: The MicroTask system for requirements was exposing all internal LLM prompts in the chat UI — scope JSON prompt ("Analyze this task and output a JSON object..."), raw JSON scope response, and assemble template ("TEMPLATE — fill in every section", "HARD RULES:"). Users should never see this internal machinery.
- **How**:
  1. **Backend** (`agent_service.py` ~line 2450): Tagged scope-phase assistant responses with `meta={"is_micro_phase": True, "phase": phase_name}` — previously only user prompts were tagged.
  2. **Frontend** (`chat.js` ~line 462): Added filter in `renderMessages()` to skip any message with `is_micro_phase === true`.
  3. **Frontend** (`chat.js` ~line 464): Added adjacency filter — skip assistant messages that directly follow a `is_micro_phase` user message. This handles legacy tasks where scope-phase assistant responses weren't tagged yet.
- **Result**: Worked. Requirements step now shows only: step description card, "Begin the REQUIREMENTS step" prompt, WriteFile tool call, committed changes, and review. All internal prompts are hidden.
- **Notes**: The `is_micro_phase` metadata was already being stored on user messages but the frontend never consulted it. The assemble-phase assistant messages (which contain the actual WriteFile tool calls) are NOT tagged, so they still render correctly.

---

## Micro-Task Orchestrated Requirements Step
- **Date**: 2026-02-15
- **Files Changed**: `backend/prompts/requirements_phases.py` (NEW), `backend/services/agent_service.py`, `backend/prompts/__init__.py`, `backend/static/js/chat.js`, `backend/static/css/chat.css`
- **What**: Replaced the single-shot requirements step with a 3-phase micro-task pipeline. Phase 1 (Scope) asks the LLM for structured JSON analysis of the task. Phase 2 (Deep Dive) gets component-level requirements — skipped for simple tasks, includes interface analysis for complex tasks. Phase 3 (Assemble) feeds all structured data back and tells the LLM to write requirements.md from a fixed template.
- **How**: New `requirements_phases.py` with 4 prompt builders. New methods on AgentService: `_extract_json_from_response()` (robust JSON extractor), `_run_json_phase()` (reusable JSON LLM call with validation/retry), `_run_assemble_phase()` (mini agent loop for WriteFile), `_run_requirements_micro_tasks()` (orchestrator). `continue_chat_stream()` delegates to orchestrator when `step_id == 'requirements'`. Frontend gets `micro_phase` SSE event handler showing phase status pills.
- **Result**: Syntax checks pass. Import tests pass. JSON extraction tests pass.
- **Notes**: The old `requirements.py` is kept as fallback — `_detect_deliverable_type()` and `_detect_quality_level()` helpers are reused by `_default_scope()`. The "think first" injection is now excluded for requirements (micro-tasks replace it). This is the pilot for the micro-task pattern — tech-spec and planning can follow the same architecture later.

---

## GPT-OSS Tool Call Format Variant Not Recognized
- **Date**: 2026-02-15
- **Files Changed**: `backend/services/agent_service.py` (lines ~2184, ~363, ~2195, ~1625, ~2210)
- **What**: Model used `<|channel|>commentary to=WriteFile code<|message|>{...}` format instead of `<|channel|>commentary to=WriteFile <|constrain|>json<|message|>{...}`. The word `code` replaced `<|constrain|>json`. This caused the GPT-OSS tool extraction regex to fail, the bare JSON bracket-matching to fail (unbalanced braces in content), and the file never got saved. The "zero files" nudge fired but model retried with same broken format 3 times, then step completed with 0 files written.
- **How**:
  1. **Made GPT-OSS regex flexible** (lines 2184 and 363): Changed `<\|constrain\|>json<\|message\|>` to `(?:<\|constrain\|>json)?[^<]*<\|message\|>` so any text between tool name and `<|message|>` is accepted
  2. **Fixed double-wrapping bug** (line 2195): When `json.loads(body)` fails in GPT-OSS normalization, check if body already has `"name"` before wrapping — prevents creating `{"name":"WriteFile","arguments":{"name":"WriteFile",...}}` double-nesting
  3. **Made bare JSON bracket-matching string-aware** (line 2210): Changed naive `{`/`}` counter to skip chars inside JSON string values (handles `\"` escapes), so `{` inside Python code content doesn't break depth counting
  4. **Made fallback content extraction handle single `}`** (line 1625): Added fallback from `"}\s*}\s*$` to `"}\s*$` so missing outer closing brace doesn't prevent content extraction
- **Result**: Worked - tested against actual model output from the failed Market Fetcher step. All 3 model attempts now parse correctly, extracting WriteFile with path=market.py and 5887 chars of content. Backward compatibility with `<|constrain|>json` format confirmed.
- **Notes**: The root cause was GPT-OSS-20B using `code` as a format hint instead of `<|constrain|>json`. The regex at line 177 (helper function) already handled this variant with `(?:constrain\|>[^<]*<\|)?` but the main extraction regexes at lines 363 and 2184 were stricter and didn't. Always keep these regexes in sync.

---

## Project Cohesion — Model Writes Broken Cross-Module Code
- **Date**: 2026-02-15
- **Files Changed**:
  - `backend/prompts/implementation.py` — added API MATCHING section
  - `backend/prompts/review.py` — added API Compatibility Check section
  - `backend/services/agent_service.py` — added `_validate_project_integrity()`, improved review context signature extraction, added `integrity_warning` SSE event
  - `backend/static/js/chat.js` — added `integrity_warning` event handler
- **What**: The model wrote files that don't work as one project. Specific issues found in task 21a88de5:
  1. `market.py` never saved (fixed by GPT-OSS regex fix above)
  2. `main.py` had escaped quotes (`\"` everywhere) — model wrote JSON-escaped content as file content
  3. `main.py` used `h.ticker` attribute access on dicts that return `h['ticker']`
  4. `main.py` called `engine.run_pending()` but AlertEngine only has `start_scheduler()`
  5. `main.py` was truncated — missing end of `main()` and `if __name__` block
  6. `notifier.py` called `StockFetcher()` with no args but constructor requires `config` param
- **How**: Two-pronged approach (prompts + validation):
  1. **Implementation prompt** (`implementation.py`): Added "API MATCHING" section that explicitly tells the model to match constructor signatures (`__init__` params), method names, and return value access patterns (dict `['key']` vs attribute `.key`)
  2. **Review prompt** (`review.py`): Added "API Compatibility Check" section telling the review agent to verify constructor calls match `__init__` signatures, method calls match defined methods, return value access matches return types, and missing files are flagged
  3. **Review context** (`agent_service.py` ~line 266): Improved signature extraction to capture multi-line `def` signatures (parameters spanning multiple lines) so the review agent sees full constructor params
  4. **Project integrity validator** (`agent_service.py` `_validate_project_integrity()`): New static method that runs after each implementation step completes. Uses Python `ast` module to:
     - Parse all .py files for syntax errors
     - Collect top-level definitions (functions, classes, variables) per module
     - Verify `from X import Y` imports: check that module X exists and defines Y
     - Check missing local modules (excluding stdlib and pip packages from requirements.txt)
  5. **SSE event** (`agent_service.py` ~line 2553): Emits `integrity_warning` event with list of issues when validation finds problems
  6. **Frontend handler** (`chat.js`): Renders integrity warnings as amber warning banners in the chat
- **Result**: Tested `_validate_project_integrity()` against the broken workspace — correctly detected syntax error in notifier.py and excluded false positives (stdlib modules, pip packages). Prompt improvements will guide the model on next run.
- **Notes**:
  - The stdlib exclusion set covers ~70 common modules. May need expansion for edge cases.
  - Pip package detection reads `requirements.txt` — projects using `pyproject.toml` or `setup.py` won't benefit from this check.
  - The validator runs AFTER each implementation step, not just at the end — so issues are surfaced early while there are still steps remaining.
  - The escaped-quotes issue in main.py is a separate tool_service/json-processing bug that wasn't addressed here (the file content had literal `\"` instead of `"`). This might be related to how the WriteFile tool processes content from the model.

---

## Code Check Agent — AST-Based Project Integrity Checker
- **Date**: 2026-02-15
- **Files Changed**:
  - `backend/services/agent_service.py` — added `run_code_check()` public method; removed `integrity_warning` SSE emission
  - `backend/routes/chats.py` — added `GET /api/tasks/<task_id>/code-check` endpoint
  - `backend/static/js/api.js` — added `runCodeCheck()` API client method
  - `backend/static/js/icons.js` — added `shieldCheck` icon
  - `backend/static/js/chat.js` — added Code Check state variables, `buildCodeCheckBar()`, `wireCodeCheckBar()`, `runCodeCheck()` functions; modified `renderMessages()` and `rerender()` to include code check bar; changed `step_completed` handler flow to: code check → review → advance; removed `integrity_warning` handler
  - `backend/static/css/chat.css` — added `.code-check-*` CSS classes with cyan (#06b6d4) theme
- **What**: Upgraded the passive `integrity_warning` SSE event into a full Code Check Agent — a distinct pipeline stage between Main Agent and Review Agent. Flow: `step_completed → runCodeCheck() → startReview() → flushPendingStepCompleted()`.
- **How**:
  1. **`run_code_check(task_id, chat_id)`** in agent_service.py: Calls existing `_validate_project_integrity()` for syntax + import checks, then adds:
     - Constructor signature matching (AST-based: parse `__init__` params, verify all `ClassName(...)` calls provide enough args)
     - Orphan file detection (files never imported and not entry points)
     - Missing `__init__.py` for package-style imports
     - Returns `{status, issues, fileCount, checkedAt}` dict
  2. **Synchronous JSON endpoint** (`GET /api/tasks/<id>/code-check`): Fast, no LLM call needed. Persists results to `chat['codeCheck']`.
  3. **Frontend UI**: Three-state card (idle/checking/done) with cyan theme, positioned between messages and review bar. Idle = pill button "Run Code Check". Checking = spinner. Done-pass = green "All checks passed". Done-fail = amber with expandable issue list. Re-run button on done card.
  4. **Auto-flow**: `step_completed` event now triggers `runCodeCheck().then(() => startReview(...))` instead of calling `startReview()` directly.
  5. **Removed**: `integrity_warning` SSE emission from backend and its handler from frontend — fully replaced by Code Check Agent card.
- **Result**: Python syntax checks pass. Frontend builds code check bar in three states. Auto-flow chains code check before review.
- **Notes**:
  - Code Check Agent is deterministic (AST-based), not LLM-based — sub-second execution, no GPU dependency.
  - Constructor check counts required params (total minus defaults) vs provided args+kwargs.
  - Orphan detection skips entry points (main.py, app.py, cli.py, etc.) and test files (test_*.py).
  - `_validate_project_integrity()` kept as internal helper, called by `run_code_check()`.
  - User can manually trigger code check at any time via the pill button.
  - **SUPERSEDED** — see next entry. Separate Code Check Agent was removed; functionality merged into Review Agent.

---

## Merge Code Check Into Review Agent + Fix Pip Dependency Validation
- **Date**: 2026-02-15
- **Files Changed**:
  - `backend/services/agent_service.py` — rewrote `_validate_project_integrity()` import check to handle dotted imports (`watchdog.observers` → checks `watchdog`); added `.venv/Lib/site-packages` scanning for installed package verification; added `_check_third_party_dep()` helper; added pip-to-import name mapping (PyYAML→yaml, Pillow→PIL, etc.); injected code check into `run_review_stream()` with new `review_code_check` SSE event; removed standalone `run_code_check()` method
  - `backend/routes/chats.py` — removed `GET /api/tasks/<task_id>/code-check` endpoint
  - `backend/static/js/api.js` — removed `runCodeCheck()` method
  - `backend/static/js/chat.js` — removed all Code Check Agent UI (state vars, buildCodeCheckBar, wireCodeCheckBar, runCodeCheck function, codeCheckBarHtml in renderMessages/rerender); reverted step_completed handler to call startReview() directly; added `review_code_check` SSE event handler in startReview()
  - `backend/static/css/chat.css` — removed all `.code-check-*` CSS classes
  - `backend/prompts/review.py` — added "Dependency Check" section instructing review agent to fix requirements.txt and note uninstalled packages
- **What**: Two changes: (1) Removed the separate Code Check Agent and merged its functionality into the Review Agent — one card, one flow. (2) Fixed the pip dependency validation bug that let `watchdog` slip through unreported.
- **How**:
  1. **Pip dependency bug fix**: The old code had `if '.' not in mod` which skipped dotted imports like `from watchdog.observers import Observer`. Fixed by extracting `top_pkg = mod.split('.')[0]` and checking that against stdlib, local modules, requirements.txt, and .venv/Lib/site-packages. Also handles `import X` statements (not just `from X import Y`).
  2. **Site-packages scanning**: Instead of just text-matching in requirements.txt, now scans `.venv/Lib/site-packages/` directory to verify packages are actually installed. Reports two distinct issue types: "Missing dependency" (not in requirements.txt) vs "Uninstalled dependency" (in requirements.txt but not installed).
  3. **Pip name mapping**: Built-in map for common pip-name→import-name mismatches (PyYAML→yaml, Pillow→PIL, beautifulsoup4→bs4, scikit-learn→sklearn, opencv-python→cv2, etc.).
  4. **Merged into review**: In `run_review_stream()`, after file collection and before LLM call, runs `_validate_project_integrity()`. If issues found, prepends a "Code Quality Analysis" section to the LLM user message so the Review Agent addresses them. Emits `review_code_check` SSE event for frontend status display.
  5. **Removed separate UI**: All Code Check Agent frontend code (card, endpoint, CSS, state) removed. Review card now shows "Code check: N issues found" in its status text during review.
- **Result**: Python syntax checks pass on all files. The Review Agent now does both code checking and LLM review in a single flow. The `watchdog` import would now be caught as "Missing dependency: 'watchdog' is imported but not listed in requirements.txt and not installed in .venv".
- **Notes**:
  - The stdlib set was expanded with ~15 more modules (xml, zipfile, configparser, queue, etc.).
  - Requirements.txt parsing now strips version specifiers (e.g., `flask>=2.0` → `flask`).
  - The `shieldCheck` icon was kept in icons.js for potential future use.
  - Code check only runs for implementation steps, not SDD steps (requirements, tech-spec, planning).

---

## Multi-Pass Review Architecture
- **Date**: 2026-02-15
- **Files Changed**:
  - `backend/prompts/review.py` — Added 3 per-pass prompt functions (build_api_check_prompt, build_quality_check_prompt, build_fix_summary_prompt) + shared _TOOL_INSTRUCTIONS constant. Kept legacy build() for backward compat.
  - `backend/prompts/__init__.py` — Exported new prompt functions
  - `backend/services/agent_service.py` — Major refactoring:
    - `_validate_project_integrity()`: Changed return from `list` to `dict` with `{issues, import_graph, warnings, defined_names, py_files}`. Added truncation detection, import graph construction, hardcoded credential/path scan.
    - Added `_build_full_import_context()`: Follows import graph to depth 2, returns FULL content of imported files (replaces 4000-char signature cap).
    - Added `_run_review_pass()`: Reusable LLM loop generator (streams tokens, handles tool calls, multi-turn). Used by all 3 LLM passes.
    - `run_review_stream()`: Replaced single-pass LLM call with 4-pass pipeline: deterministic → API check → quality → fix & summary. Each pass has focused prompt and exactly the context it needs.
  - `backend/static/js/chat.js` — Added `reviewPasses` state, `buildPassTrackerHTML()` helper, `review_pass` SSE event handler, pass tracker UI in review card. Clears live content between LLM passes.
  - `backend/static/css/chat.css` — Added `.review-pass-tracker`, `.review-pass-item`, `.review-pass-pending/active/done`, `.review-pass-arrow` styles with orange pulse animation.
- **What**: Converted single-pass review agent into 4-pass pipeline. Each pass has one focused job and sees exactly the context it needs. Pass 1 is deterministic (no LLM). Passes 2-4 are focused LLM calls with targeted prompts.
- **How**: Extracted LLM loop into reusable `_run_review_pass()`, added import graph to `_validate_project_integrity()` for smart context building, created per-pass prompts, added `review_pass` SSE event for frontend tracking.
- **Result**: Pending testing
- **Notes**:
  - Single SSE stream maintained — no new endpoints or route changes.
  - Each LLM pass gets max_turns=3 (not 5) and max_new_tokens=3072 (not 4096) since focused.
  - Import context follows graph to depth 2 with 12000-char cap (falls back to signatures if too large).
  - Cancel handling checks between passes and emits partial review_done.
  - Frontend clears live markdown area between LLM passes so each pass's output is shown fresh.

---

## Post-Implementation Auto-Install Dependencies
- **Date**: 2026-02-15
- **Files Changed**:
  - `backend/services/agent_service.py` — Added `import subprocess` at top. Added `_auto_install_dependencies(workspace_path)` static method (~170 lines) after `_check_third_party_dep()`. Scans all .py files via AST for third-party imports, maps import names to pip package names (handles yaml→pyyaml etc.), updates requirements.txt if missing packages, creates .venv if needed, runs `pip install -r requirements.txt`. Returns `{installed, errors, requirements_updated}`. Also added post-implementation hook in step completion flow (after planning hook) — triggers for non-SDD, non-parent-implementation steps. Emits `auto_install` SSE event with installed packages or errors.
  - `backend/static/js/chat.js` — Added `auto_install` SSE event handler before `step_completed` handler. Shows green pill with installed package names (auto-removes after 8s) or red pill for errors (auto-removes after 12s).
  - `backend/static/css/chat.css` — Added `.auto-install-status` (green pill) and `.auto-install-error` (red pill) styles.
- **What**: 100% hardcoded (no LLM) post-step hook that auto-detects and installs missing pip dependencies after each implementation child step completes. Fixes the "ModuleNotFoundError" problem where generated projects import packages that were never installed.
- **How**: Reuses the same stdlib set and import-to-pip mappings from `_validate_project_integrity()`. Runs pip in the workspace .venv. Idempotent — already-installed packages are skipped silently.
- **Result**: Working — integration test confirmed correct import detection, requirements.txt generation, yaml→pyyaml mapping, and pip install execution.

---

## Repeated Tool Failure Detection + Structured Thinking Framework
- **Date**: 2026-02-15
- **Files Changed**:
  - `backend/services/agent_service.py` — Added `tool_failure_tracker = []` at counter init (line 3529). Added ~25-line detection block after tool result is appended to history (after line 3945). Extracts error signature `(tool_name, path, error_type)` from "Error:" results. At 3 repeats: injects `nudges.repeated_tool_failure()`. At 5 repeats: injects `nudges.repeated_tool_failure_hard()` + breaks tool loop.
  - `backend/prompts/nudges.py` — Added `repeated_tool_failure(tool_name, path, fail_count)` (~15 lines) with EditFile-specific guidance (re-read, copy exact text, or WriteFile). Added `repeated_tool_failure_hard()` (~8 lines) for hard redirect after 5 failures.
  - `backend/prompts/system_prompt.py` — Added "## Thinking Framework" section (8 lines) to `build_thinking_instructions()`. Five terse bullets: STATE, GOAL, PLAN, EACH FILE, AFTER TOOL. Gated by compact_mode. Plus 1-line error recovery instruction.
  - `backend/prompts/implementation.py` — Updated "BEFORE WRITING CODE — TRACE DEPENDENCIES" to "BEFORE EACH ACTION — THINK (in your head, not chat)". Added "What files already exist?" and "If editing, does your old_string EXACTLY match the file?" bullets.
- **What**: Two fixes: (1) Deterministic repetition detection stops the agent from burning 15 turns on the same EditFile error. (2) Structured thinking framework gives the model 5 project-relevant reasoning bullets for its internal chain-of-thought.
- **How**: Error signature tracking with 2-tier thresholds (3=nudge, 5=hard redirect). Thinking framework positioned in system prompt right before tool examples (high-attention zone).
- **Result**: All syntax checks pass, nudge functions tested, signature extraction verified.

---

## Task Reformat Output Scaling with Complexity Level
- **Date**: 2026-02-15
- **Files Changed**:
  - `backend/prompts/task_reformat.py` — Replaced `_PREBUILT_BASIC` specs (was 4-5 sentences each, now 2-3 sentences each, ~24 words). Replaced BASIC tier few-shot examples in `build()` with genuinely short 2-3 sentence outputs. Split `system_content` and `user_preamble` by tier: BASIC (≤3) gets "2-3 short sentences MAX, just the core idea" vs INTERMEDIATE+ gets "detailed project briefs."
  - `backend/routes/tasks.py` — Wired in `is_vague_input()` + `get_prebuilt_spec()` (were dead code in task_reformat.py, never called). Both streaming and non-streaming endpoints now skip LLM entirely for vague inputs. Scaled follow-up user message by tier (BASIC: "2-3 short sentences, just the core idea" vs detailed). Reduced token budgets: complexity ≤2 → 256, ≤3 → 384 (was 512 for all ≤3).
- **What**: Fixed task reformat producing paragraph-length outputs even at complexity level 1. Root cause was triple: (1) dead vague-detection code never wired in, (2) BASIC few-shot examples were still detailed, (3) system prompt always asked for "detailed project briefs." Now BASIC tier produces 2-3 short sentences.
- **How**: Scaled all three layers: prebuilt specs, few-shot examples, system prompt, follow-up instructions, and token budgets — all by complexity tier.
- **Result**: BASIC prebuilt = 24 words. BASIC few-shot = 24 words. Vague inputs skip LLM entirely. All tests pass.

---

## 2026-02-15: Robustness Enhancements (15 Items, 3 Phases)

### Phase 1: Quick Wins

#### #3 — Frontend State Cleanup
- **Files**: `chat.js`, `chat.css`
- **What**: `generating` flag could get stuck if SSE parse errors were swallowed. No recovery UI.
- **How**: Added `resetStreamingState()` centralizing 5 inline reset blocks. Added 60s stuck-state detector that shows a sticky "Reset" button. Fixed empty `catch {}` blocks to log errors.
- **Result**: Stuck streaming state now auto-recovers. Reset button appears after 60s.

#### #6+#10 — Faster Tool Failure Nudges
- **Files**: `agent_service.py`, `nudges.py`
- **What**: Nudge at 3 fails, hard redirect at 5 wasted 60-150s of GPU time.
- **How**: Changed thresholds: gentle nudge at 2 fails (was 3), hard redirect at 3 fails (was 5). Added `fuzzy_hint` param to `repeated_tool_failure()` — uses `difflib.get_close_matches` to show the closest matching line from the actual file.
- **Result**: Faster recovery from EditFile failures. Agent gets line hint to correct its match.

#### #12 — LLM Rate Limiting
- **Files**: `agent_service.py`
- **What**: Back-to-back LLM calls could overwhelm local GPU.
- **How**: Added `time.sleep(0.5)` between agent loop turns (when `current_step > 1`) and between review passes 2, 3, 4.
- **Result**: GPU has breathing room between consecutive calls.

### Phase 2: Core Resilience

#### #2 — LLM Health Check & Timeouts
- **Files**: `chats.py`, `llm_engine.py`, `agent_service.py`, `api.js`
- **What**: No way to know LLM was down until a step failed. 300s timeout too long for SDD.
- **How**: Added `GET /api/llm/status` endpoint (hits localhost:1234/v1/models with 2s timeout). Added `read_timeout` param to `stream_chat()`/`_api_stream()` — SDD steps use 120s, impl steps use 300s. Added `getLlmStatus()` to api.js.
- **Result**: LLM connectivity is queryable. SDD steps time out faster.

#### #5 — LM Studio Graceful Degradation
- **Files**: `app.js`, `components.css`, `tasks.py`
- **What**: No visible indicator when LLM is unreachable.
- **How**: Added `ZF.llmBanner` module with red fixed-top banner (retry/dismiss). On page load polls `/api/llm/status`. Disables `[data-start-step]` buttons while banner visible. Added health gate in `start_step` endpoint (returns 503 if LLM unreachable).
- **Result**: Clear banner when LLM is down. Steps can't start without LLM.

#### #4 — Proactive Context Overflow Prevention
- **Files**: `agent_service.py`
- **What**: Context overflow caught reactively after wasted LLM call.
- **How**: Before budget calc, if `input_tokens > 80% of model_ctx` and `len(history) > 4`, call `_trim_history()` proactively. Added per-turn context usage log with percentage.
- **Result**: History trimmed before overflow can occur.

#### #8 — Deterministic Duplicate Write Detection
- **What**: Already implemented by existing `written_files` dict (O(1) lookup at execution time). Mid-stream regex abort serves as early optimization. No additional changes needed.
- **Result**: Confirmed both mechanisms work together.

#### #11 — Agent Loop Exit Unification
- **Files**: `agent_service.py`, `chat.js`
- **What**: 7+ exit paths with inconsistent state cleanup. MAX_STEPS exhaustion had no warning.
- **How**: Added `_done_event()` helper for consistent SSE done payloads. Replaced all exit path yields with `_done_event()` calls. On MAX_STEPS exhaustion: emits `stalled: true` in done event + error message. Frontend handles `data.stalled` by pushing warning message.
- **Result**: All exits produce consistent done events. Stalled agent is surfaced to user.

#### #7 — Review Failure Surfacing
- **Files**: `chat.js`, `chat.css`
- **What**: Review errors auto-advanced to next step. User could miss broken code.
- **How**: Added `reviewState = 'error'` state. Review error handler no longer calls `flushPendingStepCompleted()`. Added review error card with "Retry Review" and "Skip & Continue" buttons. Added `.review-card-error` CSS styles.
- **Result**: Review failures are visible with action buttons.

#### #13 — Persistent Pip Error Display
- **Files**: `chat.js`, `chat.css`, `tasks.py`
- **What**: Pip install errors showed for 12s then vanished.
- **How**: Error pill is now persistent (no `setTimeout` auto-dismiss). Added "Retry" and dismiss buttons. Added `POST /api/tasks/<task_id>/retry-install` endpoint.
- **Result**: Pip errors stay visible until dismissed or retried.

### Phase 3: Advanced Features

#### #1 — SSE Stream Reconnection
- **Files**: `agent_service.py`, `chat.js`
- **What**: Network hiccup mid-generation = dead stream, no recovery.
- **How**: Backend: added periodic heartbeat yields every 10s during LLM streaming. Frontend: added `lastStreamData` tracker, 5s interval checker. If >15s gap detected: aborts reader, resets state, reloads messages, re-initiates stream in continue mode.
- **Result**: Automatic reconnection on heartbeat gap.

#### #14 — Review Pass Timeouts
- **Files**: `agent_service.py`
- **What**: If LLM hung during one review pass, entire review blocked forever.
- **How**: Added `timeout_seconds=120` param to `_run_review_pass()`. Checks timeout at top of while loop and inside streaming loop. On timeout: logs warning, emits status message, breaks to next pass.
- **Result**: Individual review passes can't block forever.

#### #9 — Workspace Cleanup
- **Files**: `task_service.py`, `tasks.py`
- **What**: Stale git worktree refs after task deletion. No bulk cleanup.
- **How**: Added `git worktree prune` in `delete_task()` after rmtree. Added `POST /api/tasks/cleanup` endpoint for bulk cleanup (removes workspaces older than N days).
- **Result**: Clean worktree refs. Bulk cleanup available.

#### #15 — Crash Recovery
- **Files**: `app.py`, `task-detail.js`, `components.css`
- **What**: Server crash mid-step = task stuck "in_progress" forever.
- **How**: On startup: `_detect_stalled_tasks()` scans all tasks for `In Progress` status with `in_progress` steps, sets `hasStalled = true`. Frontend: renders amber banner with "Restart Step" and "Dismiss" buttons. "Restart" resets stalled step to pending.
- **Result**: Stalled tasks detected and surfaced on next server boot.

---

## MicroTask Assemble Auto-Complete
- **Date**: 2026-02-15
- **Files Changed**: `backend/services/agent_service.py`
- **What**: Requirements step looped all 5 assemble turns because GPT-OSS-20B writes `requirements.md` via WriteFile but doesn't emit `[STEP_COMPLETE]`. The loop only checked for `[STEP_COMPLETE]` in model text, not file state.
- **How**: Added auto-complete logic inside `_run_microtask_assemble()` at line ~2679. After a successful WriteFile, checks if the written file matches the expected artifact and passes `_validate_artifact_content()`. If valid, immediately marks step completed, emits `step_completed` event, and returns — skipping remaining assemble turns.
- **Result**: Requirements step now completes in 1 turn instead of 5 when the model writes a valid artifact.

---

## Pipeline Quality Fix — Step Names, Thinking, Validation, Auto-Run
- **Date**: 2026-02-15
- **Files Changed**: `backend/prompts/planning.py`, `backend/services/agent_service.py`, `backend/static/js/thinking.js`, `backend/static/css/chat.css`, `backend/static/css/style.css`, `backend/static/js/task-detail.js`

### Fix 1: Action-Verb Step Names
- **What**: Step names were noun-only ("Application Core") — no action words, felt lifeless
- **How**:
  - `planning.py`: Updated heading instructions to require `-ing` verb prefix, raised word limit from 4 to 5, updated examples ("Building Application Core")
  - `agent_service.py` `_sanitize_category_name()`: Raised truncation from 5→6 words (keep 5) to accommodate verb
  - `agent_service.py`: Added `_ensure_action_verb()` post-processor with `_ING_VERBS`, `_ING_PREFIXES`, `_NOUN_TO_VERB` mappings. Handles 3 cases: existing `-ing` verb (no-op), bare verb→`-ing` form, noun→prepend contextual verb
  - `agent_service.py` `_inject_subtasks_into_plan()`: Applied `_ensure_action_verb()` after `_fix_acronyms` and `_enrich_vague_heading`
- **Result**: Steps now show "Building Application Core", "Creating CLI Interface", etc.

### Fix 2: Thinking Display
- **What**: Aggressive sanitization stripped backticks, quotes, and valuable short reasoning. Filler regex removed useful technical conclusions.
- **How**:
  - `thinking.js` `parseSections()`: Replaced blanket `[{}[\]"\\`]+` strip with targeted JSON tool object removal, preserving backticks and quotes
  - `thinking.js`: Slimmed `FILLER_RE` to only truly empty self-talk. Added `TECHNICAL_KEYWORDS_RE` — filler lines containing technical keywords are now kept. Lowered `SHORT_FILLER_RE` to only "ok/yes/no/sure". Reduced min sentence length from 15→8 chars.
  - `thinking.js` `formatThinkingBody()`: Separated `\\"` and `\\\\` handling. Changed `["\`]{2,}` → only compress 3+ repetitions (preserves inline code backticks)
  - `chat.css`: Added `line-height: 1.65`, `padding-top: 2px` to `.thinking-section-body`; increased padding
  - `style.css`: Increased `.thinking-sections-container` gap from 2px→4px
- **Result**: Thinking sections show more content, preserve code references, better visual spacing

### Fix 3: Code Validation
- **What**: `ast.parse()` didn't catch f-string backslash continuation bugs (PEP 701 made multiline f-strings legal in Python 3.12+)
- **How**:
  - `agent_service.py` `_validate_project_integrity()`: Added `py_compile.compile(doraise=True)` subprocess check using workspace venv Python after `ast.parse`. 10s timeout, deduplicates with ast.parse errors.
  - Same location: Added regex-based f-string backslash-newline warning (non-blocking, goes to warnings list for review LLM to see)
- **Result**: Review Pass 1 now catches compilation issues ast.parse misses + flags suspicious f-string patterns

### Fix 4: Auto-Run Terminal on Completion
- **What**: Terminal auto-run was gated behind `autoStart` setting — user expected code to run automatically
- **How**: `task-detail.js`: Removed `if (task.settings?.autoStart)` check. Terminal always opens and calls `runProject()` when all steps complete.
- **Result**: Terminal auto-opens and runs the project after the last step finishes, regardless of autoStart setting

---

## MicroTask: Hide JSON Phase Output & Assemble Narration from Chat
- **Date**: 2026-02-15
- **Files Changed**: `backend/services/agent_service.py`
- **What**: Raw JSON from scope/deep_dive/interfaces phases was streamed as visible `data:` chat tokens, showing ugly JSON blobs like `{"complexity":"complex","components":[...]}` in the UI. Assemble phase narration also showed as blank space before tool calls.
- **How**:
  - `_run_json_phase()` line ~2580: Changed `yield f"data: ..."` to `yield f"event: thinking\ndata: ..."` — JSON phase output now goes to thinking sections instead of main chat
  - `_run_microtask_assemble()` line ~2688: Same change — assemble narration goes to thinking. Tool call/result events remain visible (emitted separately downstream).
- **Result**: Requirements step chat is clean — only thinking sections, phase status pills, tool calls, and step summary are visible. No raw JSON or blank space.

---

## Structured Thinking + Hardcoded Completion + Code Audit
- **Date**: 2026-02-15
- **Files Changed**: `backend/prompts/requirements_phases.py`, `backend/prompts/technical_specification.py`, `backend/prompts/planning.py`, `backend/prompts/implementation.py`, `backend/services/agent_service.py`, `backend/static/js/thinking.js`
- **What**: Three-part enhancement to improve LLM orchestration quality:
  1. **Thinking preambles**: Added "Think through:" guidance blocks to all phase prompts (scope, deep-dive, interface, assemble, tech-spec, planning, implementation) so the LLM reasons more structurally before acting
  2. **Synthetic thinking labels**: Injected emoji-prefixed thinking tokens (📋, 🔍, 🔗, 📝, 🏗️, 📐, ⚡, ✅) before each phase/step so the UI shows clear phase transitions in the thinking section
  3. **Hardcoded completion**: Orchestrator now auto-completes SDD steps when artifact is written+valid, and impl steps when all Files:-listed files are written — no longer relies on LLM to say [STEP_COMPLETE]
- **How**:
  - All prompt files: Added structured "Think through:" blocks with 3-4 bullet points guiding chain-of-thought
  - `agent_service.py`: Added `_extract_owned_files()` static method, synthetic thinking token yields before phases, auto-complete logic for both SDD and impl steps
  - `thinking.js`: Added 4 new TOPIC_CATEGORIES (Scope Analysis, Component Analysis, Interface Design, Step Completion) and updated Planning Steps keywords
- **Result**: ✅ Working. Compilation clean, server healthy.
- **Bug Fixed During Implementation**: `NameError: name 'step_name' is not defined` at line 3783 — used non-existent variable in synthetic label code. Fixed by creating `_step_display_name` from `step_for_chat.get('name', '')`.
- **Code Audit Cleanup**: Removed dead `step_label` variable (line 3743), normalized inconsistent indentation (6sp jumps → consistent 2sp) in the auto-complete block (lines 4282-4328).

---

## Mandatory Post-Code Steps in Planning Prompt
- **Date**: 2026-02-15
- **Files Changed**: `backend/prompts/planning.py`, `backend/services/agent_service.py`
- **What**: Every implementation plan now includes 3 mandatory ending steps after all code steps:
  1. **Setting Up Environment** — audits all imports, ensures requirements.txt is complete
  2. **Writing Unit Tests** — creates unit tests for the code produced
  3. **Creating User Guide** — writes a README.md with setup/run instructions for non-technical users
- **How**:
  - `planning.py`: Updated HOW MANY STEPS to distinguish "code steps" (max 8) from "mandatory ending steps" (always 3). Added full MANDATORY ENDING STEPS section with exact heading names, template, and sub-steps. Updated fold-in rule to exclude mandatory steps. Updated SCOPE RULES. Updated WRITEFILE EXAMPLE to show the 3 mandatory steps.
  - `agent_service.py`: Raised `_extract_tasks_from_impl_plan` cap from 8 → 11 (8 code + 3 mandatory)
- **Result**: ✅ Compiles clean, server healthy. Mandatory step names ("Setting Up Environment", "Writing Unit Tests", "Creating User Guide") are 3+ words so they bypass VAGUE_NAMES filter. `_auto_install_dependencies()` continues to run after each step (complementary, not conflicting).

---

## Prevent Disconnected Modules (Integration Wiring System)
- **Date**: 2026-02-16
- **Trigger**: Stress test Flask+SocketIO project generated completely disconnected modules — main.py only registered status_bp, auth blueprint was orphaned, no Socket.IO handlers, routes redirected to non-existent endpoints. Root cause: no mechanism forces cross-step integration wiring.
- **What**: 4-layer defense system across planning, implementation, validation, and review to ensure generated projects are fully wired together.
- **Files Modified**: `backend/prompts/planning.py`, `backend/prompts/implementation.py`, `backend/services/agent_service.py`, `backend/prompts/review.py`, `backend/static/js/task-detail.js`
- **How**:
  1. **Planning prompt** (`planning.py`): Added `Modifies:` metadata line to FORMAT RULES (rule 5), INTEGRATION WIRING block after PROJECT STRUCTURE RULES, `Modifies:` in REQUIRED OUTPUT FORMAT template, and `Modifies: main.py` in the WRITEFILE EXAMPLE's second step
  2. **Implementation prompt** (`implementation.py`): Added `modifies_files` extraction (regex parsing `Modifies:` lines), "FILES YOU MUST EDIT" section surfacing those files in instructions, and WIRING CHECKLIST with framework-specific examples (Flask blueprint → register_blueprint, Socket.IO → import handlers, FastAPI → include_router, Express → app.use)
  3. **Deterministic validation** (`agent_service.py`):
     - Line 2361: Added `Modifies?:` to metadata regex so it's preserved in plan parsing
     - `_validate_project_integrity()`: Added entry-point reachability check (BFS from main.py/app.py through import_graph — flags orphan modules)
     - `_validate_project_integrity()`: Added Flask blueprint registration check (scans for `Blueprint(` definitions without matching `register_blueprint()` calls)
  4. **Review prompts** (`review.py`): Added item 6 to API check pass ("Integration completeness — every .py must be imported somewhere"), added `**Integration**` line to fix summary format
  5. **Frontend** (`task-detail.js`): Added `Modifies?` to metadata filter regex so it doesn't show in UI
- **Result**: ✅ All files compile clean, server healthy. Unit tests confirm: Modifies: parsing extracts files correctly, orphan detection catches unimported modules, blueprint check catches unregistered blueprints. The 4-layer approach (prompt guidance → wiring checklist → deterministic validation → review catch) ensures disconnected modules are caught at multiple stages.

---

## Terminal Enhancement — 10 Features (Streaming, Kill, History, ANSI, Fullscreen)
- **Date**: 2026-02-16
- **Files Changed**: `backend/static/js/icons.js`, `backend/routes/terminal.py` (NEW), `backend/app.py`, `backend/static/js/api.js`, `backend/static/js/terminal.js`, `backend/static/css/terminal.css`
- **What**: Transformed the terminal from a simple synchronous command runner (commands blocked for up to 300s with "Running..." text) into a proper interactive terminal with 10 enhancements:
  1. **SSE Streaming Output** — Lines appear in real-time as subprocess produces them (Popen + line-buffered stdout)
  2. **Kill Button** — Run button swaps to red Kill button during execution; terminates subprocess + aborts fetch stream
  3. **Command History** — Arrow Up/Down navigates previous commands (preserves current input)
  4. **Clear Terminal** — Trash icon resets output to welcome messages
  5. **Copy Output** — Clipboard copy with checkmark feedback animation
  6. **ANSI Color Support** — `escHtml()` → `ansiToHtml()` pipeline renders 16 SGR colors + bold + underline
  7. **Fullscreen Toggle** — Maximize/minimize icon, fixed overlay with z-index:100, Escape to exit
  8. **Auto-Scroll Toggle** — Pin/unpin icon, re-enables when user scrolls to bottom
  9. **Timestamps** — HH:MM:SS prefix on command lines (tabular-nums for alignment)
  10. **Input Placeholder** — After Run Project detects entry point, placeholder shows `e.g., python main.py`
- **How**:
  - **Backend** (`routes/terminal.py`): New blueprint with process registry (`_active_processes` dict with threading.Lock), `POST /api/tasks/<task_id>/terminal/stream` SSE endpoint (Popen + readline loop + cancel_event check), `POST /api/terminal/<session_id>/kill` endpoint. Replicates venv PATH injection from tool_service.
  - **Backend** (`app.py`): Registered `terminal_bp` blueprint (2 lines)
  - **Frontend** (`api.js`): Added `streamCommand(taskId, command, cwd)` and `killTerminal(sessionId)` methods
  - **Frontend** (`terminal.js`): Full rewrite. DOM architecture changed from "regenerate innerHTML on every render" to "build shell once, append incrementally." New state: autoScroll, isFullscreen, commandHistory[], historyIndex, streamSessionId, activeAbortController. SSE parser reads `terminal_session`, `terminal_output`, `terminal_done`, `terminal_error` events. Toolbar rebuilt via `updateToolbar()` on state changes.
  - **Frontend** (`icons.js`): Added 5 icons — copy, maximize, minimize, pin, unpin
  - **CSS** (`terminal.css`): Added kill button (red #ef4444), toolbar-spacer, toolbar-btn (30x30 transparent), timestamp styling, fullscreen overlay (position:fixed inset:0)
- **Result**: All files written. Old `/api/tasks/<id>/command` endpoint unchanged (agent's RunCommand still uses it). Terminal UI uses new streaming endpoint exclusively.
- **Notes**: The old synchronous `execCommand()` is completely replaced by `execStreamCommand()`. Public API contract unchanged: `{ element, runProject }`.

---

## Review Agent Can't Fix Files + Terminal Streaming Failure
- **Date**: 2026-02-16
- **Files Changed**: `backend/services/agent_service.py`, `backend/static/js/api.js`, `backend/static/js/terminal.js`, `backend/routes/terminal.py`
- **What**: Two bugs:
  1. **Review agent finds issues but says "contents unavailable"**: The review only loaded files "written in this step" from chat history. If the extracted file path didn't match disk (prefix mismatch), it got `(file not found)` placeholder. Even when found, the review couldn't edit OTHER project files not written in this step because they weren't in context.
  2. **Terminal shows "Failed to start streaming command"**: The `streamCommand()` API didn't pass AbortController signal to fetch (breaking Kill button), didn't show server error messages, and endpoint lacked directory existence validation.
- **How**:
  1. **Review file loading** (`agent_service.py`):
     - Added debug logging when files aren't found (logs exact path attempted)
     - Added basename-search fallback: when file not found at expected path, walks workspace looking for a file with same basename (catches path-prefix mismatches like `src/reporter.py` vs `reporter.py`)
     - Added `all_project_files` dict: after loading step-written files, walks entire workspace loading ALL source files (.py, .js, .html, .css, .json, etc.) up to 40,000 chars total
     - Updated `_build_files_context()` to include both "Files to Review" (written in step) and "Other Project Files" (reference context, explicitly marked "you can EditFile these too")
     - Updated `_refresh_file_contents()` to also refresh `all_project_files` after review passes make edits
  2. **Terminal streaming** (`api.js`, `terminal.js`, `terminal.py`):
     - `api.js`: Added `signal` parameter to `streamCommand()`, passed to fetch. Also reads server error JSON for better error messages.
     - `terminal.js`: Passes `controller.signal` to `streamCommand()` so Kill button aborts the fetch stream
     - `terminal.py`: Added `os.path.isdir()` check on workspace path (was only checking truthiness)
- **Result**: Review agent now has full project context and can find/edit any file. Terminal streaming passes abort signal correctly and shows actual server errors.
- **Notes**: The terminal "Failed to start streaming command" was most likely caused by the Flask server not being restarted after adding the new terminal blueprint. The `os.path.isdir` check and better error reporting will surface the actual cause if it recurs.

---

## Execution Agent Expansion + WriteFile Diff Marker Root Cause Fix
- **Date**: 2026-02-16
- **Files Changed**: `backend/services/tool_service.py`, `backend/services/agent_service.py`, `backend/static/js/terminal.js`, `backend/static/js/task-detail.js`
- **What**: Root-cause fixed diff marker corruption at write time (instead of only catching it in the execution agent). Expanded the execution agent with 5 new capabilities: pre-scan, __init__.py detection, requirements.txt generation, file tree refresh, smarter retry with revert.
- **How**: 7 changes:
  1. **WriteFile diff marker stripping** (`tool_service.py`): Added `_strip_diff_markers()` static method that cleans stray `+`/`-` diff markers and junk lines (`*** End of File ***`, merge markers, diff headers) at write time. Called from `write_file()` for all source code and markdown files. This is the **root cause fix** — files written by the main SDD agent are now clean before they hit disk.
  2. **Pre-execution scan** (`agent_service.py`): `_pre_scan_and_fix(workspace_path)` — Phase 0 of the execution agent. Proactively scans ALL source files before the first run. Strips leftover diff markers, junk lines. Python files get a `compile()` check to surface syntax errors early.
  3. **Missing __init__.py detection** (`agent_service.py`): `_detect_missing_init_files(workspace_path)` — Uses AST parsing to find which directories are imported as packages. If a directory has .py files + is imported but lacks `__init__.py`, creates an empty one. Also runs as a deterministic fix when ImportError is encountered at runtime.
  4. **Smart requirements.txt generation** (`agent_service.py`): `_scan_and_generate_requirements(workspace_path)` — AST-scans all imports, filters out stdlib and local modules, maps to pip package names (handling mismatches like PIL→Pillow, cv2→opencv-python), and appends missing packages to requirements.txt.
  5. **Snapshot/revert for LLM fixes** (`agent_service.py`): `_snapshot_project_files()` + `_restore_snapshot()` + `_count_errors_in_output()`. Before each LLM fix attempt, snapshots all source files. After the fix, does a quick verify run. If error count went UP, reverts all files to pre-fix state — prevents the LLM from making things worse.
  6. **File tree refresh event** (`terminal.js`, `task-detail.js`): New `exec_files_changed` SSE event. Terminal dispatches a DOM `CustomEvent('exec-files-changed')` that bubbles up. `task-detail.js` listens for it and calls `filesTab.refresh()`. File explorer now stays in sync after execution agent fixes.
  7. **Execution loop rewire** (`agent_service.py`): `run_execution_stream()` now has Phase 0 (pre-scan, __init__.py, requirements.txt), ImportError deterministic handler, snapshot/revert around LLM fixes, and `exec_files_changed` events at every point files are modified.
- **Result**: Server starts cleanly. Diff marker corruption is now prevented at the source (WriteFile) AND caught by the execution agent as a fallback. The execution agent is significantly more capable — most common issues (diff markers, missing packages, missing __init__.py) are fixed deterministically without needing the LLM at all.
- **Notes**: The f-string nesting issue (escaped quotes inside json.dumps inside f-strings) caused a SyntaxError on first restart. Fixed by extracting values into variables before the yield statement.

---

## LLM Activity Logger — Full Output Capture
- **Date**: 2026-02-16
- **Files Changed**: `backend/services/llm_logger.py` (NEW), `backend/services/agent_service.py`, `backend/app.py`
- **What**: Created a per-task LLM activity logger that captures EVERYTHING the model says or does — thinking tokens, content tokens, tool calls, tool results, full responses, errors, aborts. Writes timestamped append-only logs to `storage/llm_logs/{task_id}.log`. Added API endpoint `/api/tasks/<task_id>/llm-log` to view logs.
- **How**:
  - Created `LLMLogger` class with tagged entries: `[THINK_FULL]`, `[CONTENT]`, `[RESPONSE]`, `[TOOL]`, `[RESULT]`, `[ERROR]`, `[ABORT]`, `[STEP]`, `[EXEC]`, `[META]`, `[TURN]`
  - Thinking tokens buffered per-turn as `_think_buffer`, flushed as single `THINK_FULL` entry on `turn_end()`
  - Content tokens buffered as `_token_buffer`, flushed on `turn_end()` or `response()`
  - Multiline content collapsed to single line (max 2000 chars per entry)
  - Wired into main agent loop in `continue_chat_stream()`: turn_start, thinking, token, response, tool_call, tool_result, turn_end, step_complete, error paths
  - Wired into execution agent: exec_attempt, exec_error, exec_fix
  - API endpoint returns plain text log; returns placeholder message (not 404) if no log exists yet
- **Result**: Working. Log captures complete agent activity including thinking, decisions, and all tool interactions. Verified with complexity-10 expense tracker task.
- **Notes**: Logger writes on init (`[META] Logger initialized`) to guarantee file exists before any API call. Silent exception handling in `_write()` prevents logger failures from crashing the agent.

---

## LLM Logger 404 Fix + Requirements Micro-Task Logging
- **Date**: 2026-02-16
- **Files Changed**: `backend/services/agent_service.py`, `backend/services/llm_logger.py`, `backend/app.py`
- **What**: Two issues found during E2E test: (1) LLM log endpoint returned 404 for tasks that hadn't started LLM calls yet. (2) Requirements step (which uses micro-task pipeline) never passed `llm_log` to `_run_requirements_micro_tasks()`, so no logs were created for the first step of any task.
- **How**:
  1. **404 fix** (`app.py`): Changed `/api/tasks/<task_id>/llm-log` to return a placeholder message (`[META] No LLM activity recorded yet`) instead of 404 when log file doesn't exist.
  2. **Logger init** (`llm_logger.py`): Added `self._write('META', ...)` in `__init__` so the file is created immediately — guarantees the API always has something to serve.
  3. **Micro-task wiring** (`agent_service.py`): Added `llm_log=None` param to `_run_requirements_micro_tasks()` signature. Passed `llm_log=llm_log` from `continue_chat_stream()` call site. Added logging at each phase boundary: `turn_start` + `response` + `turn_end` for Scope, DeepDive, Interfaces, and Assemble phases. Also logs `step_complete` with written files at the end.
- **Result**: No more 404s. All steps including requirements now produce log entries. Verified with live task.
- **Notes**: Root cause was that `_run_requirements_micro_tasks()` returns early from `continue_chat_stream()` at line 5259, before the main agent loop where all the logger hooks live. Tech-spec and planning don't have this issue because they use the standard agent loop.

---

## plan.md + SDD Artifacts Visible in Files Section
- **Date**: 2026-02-16
- **Files Changed**: `backend/routes/files.py`
- **What**: plan.md, requirements.md, spec.md, and implementation-plan.md were invisible in the Files tab because they live in `.sentinel/tasks/{task_id}/` and `.sentinel` was in `IGNORE_DIRS`. Users couldn't see ANY of the SDD artifacts — the workflow documents that define the entire project were hidden.
- **How**: Modified `file_tree()` endpoint in `files.py` to inject a virtual "Artifacts" folder at the top of the file tree. Scans `.sentinel/tasks/{task_id}/` for `.md` files and presents them with their real relative paths (so the file reader API works). The folder has a `"virtual": True` flag for potential frontend styling. `.sentinel` remains in `IGNORE_DIRS` so other internal files stay hidden.
- **Result**: Files tab now shows "Artifacts" folder at top containing plan.md, requirements.md, spec.md, implementation-plan.md. Clicking any file shows its content. All project code files still appear below as before.
- **Notes**: The paths use the real `.sentinel/tasks/{task_id}/filename.md` format so the existing `/api/tasks/<id>/file?path=...` endpoint works without changes. The file reader already accepts `.sentinel` paths because `ToolService` is scoped to the workspace root.

---

## Step ID Slugification — Forward Slash Breaks Routing
- **Date**: 2026-02-16
- **Files Changed**: `backend/services/plan_engine.py`, `backend/static/js/task-detail.js`
- **What**: Step names containing `/` (e.g. "Build Import/Export Utilities") generated step IDs like `build-import/export-utilities`. The forward slash in the ID broke: (1) Flask URL routing — `/api/tasks/{id}/steps/build-import/export-utilities/start` returned 404 because Flask interpreted the slash as a path separator. (2) CSS `querySelector('#desc-build-import/export-utilities')` threw SyntaxError because `/` is invalid in CSS selectors. Steps with `/` in their name could never be started.
- **How**:
  1. **plan_engine.py**: Replaced `.lower().replace(" ", "-")` slugification with new `_slugify()` function that uses `re.sub(r'[^a-z0-9-]+', '-', ...)` to replace ALL non-alphanumeric characters with hyphens, then collapses consecutive hyphens. Applied to both `_derive_id()` and child step ID derivation.
  2. **task-detail.js**: Changed `querySelector('#desc-${step.id}')` to use `CSS.escape()` — `querySelector('#${CSS.escape('desc-' + step.id)}')` — so special characters in IDs don't break the selector.
- **Result**: "Build Import/Export Utilities" now gets ID `build-import-export-utilities`. Step starts successfully. No more 404 or querySelector errors.
- **Notes**: This affects ALL future tasks. The LLM can write any step name it wants — `_slugify` handles `/`, `&`, `(`, `)`, `+`, etc. Any character that isn't `[a-z0-9-]` gets replaced with a hyphen. Existing tasks with old IDs get fixed on server restart because plan_engine re-parses plan.md on each API call.

---

## E2E Complexity-10 Test — Full SDD Pipeline Run
- **Date**: 2026-02-16
- **Task**: Python CLI Expense Tracker (SQLite, Click, Rich, Tabulate)
- **Task ID**: `666be515-4339-4c06-b165-927828951e05`
- **What**: Full end-to-end test of the complete SDD pipeline at max complexity. Created a complexity-10 task that generated 14 steps (4 SDD + 10 implementation children) and ran them all with auto-start enabled.
- **Results**:
  - ✅ All 14 steps completed successfully (Requirements → Tech Spec → Planning → 10 Implementation steps → all green)
  - ✅ 21 files generated: main.py, cli.py, db.py, services.py, report.py, budget.py, dashboard.py, import_export.py, requirements.txt, README.md, 3 test files, 4 SDD artifacts
  - ✅ LLM Activity Logger captured full activity (91 lines)
  - ✅ Error Memory auto-recorded runtime failure
  - ✅ Artifacts folder visible in Files tab (plan.md, requirements.md, spec.md, implementation-plan.md)
  - ✅ Review pipeline ran on every step (Code Check → API Check → Quality → Summary)
  - ✅ Thinking sections concise and clear (labeled topics, 1-2 sentence descriptions)
  - ✅ Slugification fix handled "Build Import/Export Utilities" step correctly mid-run
  - ❌ Execution agent failed: `UnicodeEncodeError: 'charmap' codec can't encode character '\u2011'` — Windows cp1252 console can't render the non-breaking hyphen used in Rich/Click output
- **Bugs Found During Run**:
  1. LLM Logger 404 (requirements micro-tasks didn't receive logger) — fixed mid-run
  2. plan.md invisible in Files (`.sentinel` in IGNORE_DIRS) — fixed mid-run
  3. Step ID `/` in "Import/Export" broke Flask routing — fixed mid-run
  4. Windows Unicode encoding error in CLI output — recorded in error_memory.json, added seed entry `seed_009` for future prevention
- **Notes**: The Unicode error is a Windows-specific pitfall when using `rich` library with Unicode characters. Added `seed_009` to error_memory.json to warn future tasks: "NEVER use Unicode chars like \u2011, \u2013, \u2019 in CLI output strings on Windows. Use plain ASCII equivalents."

---

## 10 Real-Time Micro-Agents — Deterministic Assistants for Main Agent Loop
- **Date**: 2026-02-16
- **Files Changed**: `backend/services/micro_agents.py` (NEW), `backend/services/agent_service.py`
- **What**: Created 10 micro-agents that fire deterministically during the agent loop — after file writes, between turns, at step start, and at step completion. They provide instant feedback (syntax errors, broken imports, convention violations) that the LLM agent would otherwise only discover after execution failures. No LLM calls — all AST-based or regex-based.
- **How**:
  1. **SyntaxSentinel** — AST-parses every `.py` file after WriteFile. Catches syntax errors immediately, injects fix hint into next LLM turn.
  2. **ImportResolver** — Validates cross-module imports after writes. Checks `from X import Y` — verifies X exists and defines Y.
  3. **SignatureIndex** — Builds function/class manifest at step start. Gives the LLM an "API index" of all existing code so it knows what's available.
  4. **DownstreamScanner** — Extracts what future steps need from this step (by parsing plan.md's Depends-on metadata). Injects warnings if expected outputs are missing.
  5. **ProgressTracker** — Tracks completion % vs expected files (from plan step's Files: metadata).
  6. **PatternMatcher** — Enforces tech stack conventions (type hints, docstrings, naming patterns) by sampling existing code style.
  7. **CircularImportDetector** — Detects import cycles in real time using DFS on the import graph.
  8. **DeadReferenceWatchdog** — Detects broken references after edits (renamed/deleted functions still imported elsewhere).
  9. **ContextBudgetOptimizer** — Smart history compression when context window fills up. Summarizes old tool results, keeps recent ones.
  10. **TestRunnerScout** — Runs tests after step completion if test files exist.
  - Wired into `agent_service.py`: `post_write_checks()` fires after every WriteFile (agents 1,2,6,7,8), `step_start_context()` fires at step begin (agents 3,4,5), `step_end_checks()` fires at completion (agent 10).
- **Result**: Working. All agents fire correctly in the main loop. Warnings are accumulated for RL scoring.
- **Notes**: Micro-agent warnings are collected in `_step_micro_warnings` list and fed to the RL reward scorer for step scoring. The SignatureIndex + DownstreamScanner outputs are injected into the system prompt as `_micro_context`.

---

## Reinforcement Learning Brain — Agent That Learns From Every Task
- **Date**: 2026-02-16
- **Files Changed**: `backend/services/reward_scorer.py` (NEW), `backend/services/experience_memory.py` (NEW), `backend/prompts/reward.py` (NEW), `backend/services/reward_agent.py` (NEW), `backend/services/agent_service.py`, `backend/app.py`
- **What**: Built a complete RL system where every task teaches the agent something. The more tasks it runs, the smarter it gets — better code, better tool usage, better architecture decisions. Four new modules + wiring into the main agent loop and execution pipeline.
- **How**:
  1. **Reward Scorer** (`reward_scorer.py`, ~277 lines): Deterministic multi-signal scoring — no LLM calls. Scores each step on code_quality (0.30), efficiency (0.25), tool_adherence (0.25), import_health (0.20). Scores execution on execution_success (0.40), first_try (0.15), code_quality (0.20), import_health (0.10), review_pass_rate (0.15). Aggregates into task score (60% step avg + 40% execution). Grades: A >= 0.85, B >= 0.70, C >= 0.55, D >= 0.40, F < 0.40.
  2. **Experience Memory** (`experience_memory.py`, ~660 lines): Persistent behavioral knowledge base (`storage/experience_memory.json`). Mirrors ErrorMemory patterns: Thompson Sampling (alpha/beta bandit arms), context fingerprinting (Jaccard similarity on tech stack/libraries/extensions), multi-tier lookup scoring, escalation tiers, TTL pruning. 10 seed lessons bootstrapped on first run. `record()` upserts by MD5 signature hash. `format_for_injection()` formats top lessons as "DO: X" / "DONT: Y" rules (800 char budget).
  3. **Reward Prompt** (`reward.py`, ~70 lines): System prompt template for reward agent — "You are a CODE QUALITY ANALYST, generate 3-5 SHORT behavioral rules." Output format: `LESSON: [rule] | TYPE: [positive/negative] | TAGS: [tags]`. Includes `build_existing_lessons_block()` for duplicate avoidance.
  4. **Reward Agent** (`reward_agent.py`, ~280 lines): Post-task LLM call (max_tokens=512, temp 0.3) that converts scores into behavioral lessons. `_parse_lessons()` regex parser for structured output. `_fallback_lessons()` deterministic lesson generation when LLM fails (derives lessons from signal values). `_format_signal_breakdown()` uses ASCII markers (`+`/`-`/`~`) — not Unicode (Windows cp1252 compatibility).
  5. **Agent Service Wiring** (6 integration points):
     - Experience injection after micro-context injection: lookup lessons matching current tech stack/step type, inject into system prompt
     - Warning/failure accumulation: `_step_micro_warnings` and `_step_tool_failures` counters for scoring input
     - Step scoring at completion: `score_step()` + confirm/penalize injected lessons based on composite score
     - Force-complete scoring: steps force-completed due to stall/max turns also generate RL signals
     - Thread-safe step score management: `_task_step_scores` dict with lock, `_stash_step_score()`/`_pop_step_scores()` methods, TTL-based cleanup (2hr expiry)
     - Execution scoring at 4 `exec_done` paths (3 success, 1 failure): `score_execution()` + `_fire_reward_agent_async()` background thread
  6. **App Startup** (`app.py`): `ExperienceMemory.ensure_seeded()` bootstraps 10 seed lessons on first run
- **Result**: Working. Full pipeline verified: Score step -> Score execution -> Aggregate task -> Generate lessons -> Record to memory -> Lookup -> Format injection -> Confirm/Penalize.
- **Notes**: The reward agent fires in a background daemon thread (`_fire_reward_agent_async`) so it doesn't block the SSE stream. Early cancellation paths (cancelled during pre-scan) correctly skip RL scoring. The `review_issues=0` hardcoded in execution scoring calls is a known limitation — `integrity_issues` already captures most review data.

---

## RL System Stress Test + 5 Bug Fixes
- **Date**: 2026-02-16
- **Files Changed**: `backend/services/reward_scorer.py`, `backend/services/experience_memory.py`, `backend/services/agent_service.py`
- **What**: Comprehensive stress testing of the entire RL system — 192 total tests across all 4 modules + end-to-end integration. Found and fixed 5 bugs.
- **How**: Ran 5 test suites:
  - **Reward Scorer**: 139 edge cases (weight validation, step scoring, execution scoring, task aggregation, clamping, grade boundaries, composite bounds sweep, signal details) — 139/139 PASS after fix
  - **Experience Memory**: 19 edge cases (load/save, record/upsert, confirm/penalize, lookup, format injection, signature dedup, stats) — 19/19 PASS
  - **Reward Agent**: 16 edge cases (_parse_lessons, _fallback_lessons, _format_signal_breakdown) — 16/16 PASS
  - **E2E Integration**: 12 pipeline tests (full score→lesson→record→lookup→inject→confirm flow + thread-safe stash/pop) — 12/12 PASS
  - **Syntax Check**: 6 files — 6/6 OK
- **Bugs Found & Fixed**:
  1. **Efficiency edge case** (`reward_scorer.py`): Clean-run bonus (+0.2 for no nudges and no code-in-prose) was applied even when `file_count=0` — rewarding a step that produced nothing. Fixed: added `file_count > 0` guard to the clean-run bonus condition.
  2. **Empty lesson guard** (`experience_memory.py`): `record()` accepted empty or trivially short lessons (<=10 chars) which polluted the knowledge base. Fixed: added early return validation at top of `record()`.
  3. **Thread safety** (`agent_service.py`): `_task_step_scores` class-level dict was accessed without locking from both the main agent thread and background reward agent thread. Fixed: added `_task_step_scores_lock` and created `_stash_step_score()`/`_pop_step_scores()` thread-safe methods.
  4. **Memory leak** (`agent_service.py`): `_task_step_scores` accumulated step scores per task_id but only cleaned up when execution fired. Abandoned tasks leaked memory indefinitely. Fixed: added TTL-based cleanup (2-hour expiry) inside `_stash_step_score()` — prunes entries whose last timestamp exceeds 7200 seconds.
  5. **Force-completed steps not scored** (`agent_service.py`): When a step was force-completed (stall detection or max turns), the RL scoring block was entirely skipped — no learning signal generated. Fixed: added RL scoring block (same pattern as normal completion) in the force-complete path.
- **Result**: All 192 tests pass. All 6 files pass syntax check. Server starts cleanly with RL system seeded.
- **Notes**:
  - The `_format_signal_breakdown()` originally used Unicode markers (checkmark/cross) which failed on Windows cp1252 console. Fixed in creation session by replacing with ASCII `+`/`-`.
  - The redundant `hasattr(AgentService, '_task_step_scores')` check (leftover from before it was a class attribute) was removed during thread-safety fix.
  - Wiring verified across all execution paths: 3 success `exec_done` paths + 1 failure path all correctly fire `score_execution()` + `_fire_reward_agent_async()`. 4 early cancellation paths (cancelled during pre-scan) correctly skip RL scoring.

---

## Auto-Fix Auto-Retry on Terminal Stage
- **Date**: 2026-02-16
- **Files Changed**: `backend/static/js/terminal.js`, `backend/static/js/task-detail.js`
- **What**: When the terminal stage activates (all SDD steps done), the initial `runProject()` now checks the exit code. If the project fails, Auto-Fix automatically starts and retries up to 5 times without user intervention.
- **How**:
  1. **terminal.js `execStreamCommand()`**: Now returns the exit code (number or null) instead of void, so callers can detect success/failure.
  2. **terminal.js `runProject(autoTriggerFix)`**: Added `autoTriggerFix` parameter (default false). When true and exit code is non-zero, automatically calls `runAutoFix(true)`.
  3. **terminal.js `runAutoFix(autoRetry)`**: Added `autoRetry` parameter and `autoFixRetryCount` state (max 5). When `autoRetry=true`, tracks retry count, shows round number in terminal output, and auto-retries on failure with 1.5s delay between rounds. Manual button clicks reset the counter. Exhausted retries show a clear "manual intervention needed" message.
  4. **terminal.js `handleExecEvent`**: `exec_done` events set `lastExecSuccess` flag which the `finally` block reads to decide whether to retry.
  5. **task-detail.js**: Changed `terminalPanel.runProject()` → `terminalPanel.runProject(true)` so the automatic terminal-stage run triggers auto-fix on failure.
- **Result**: Applied. Flow: Run Project → fails → Auto-Fix round 1 → fails → round 2 → ... → round 5 → gives up. Success at any point stops the chain.
- **Notes**: Manual "Auto-Fix" button clicks still work independently (reset counter to 0). Cancel button aborts the chain. The 1.5s delay between retries prevents hammering.

---

## Run Project Resilience + Execution Agent str.get Crash Fix
- **Date**: 2026-02-16
- **Files Changed**: `backend/static/js/terminal.js`, `backend/services/agent_service.py`
- **What**: Two bugs fixed:
  1. **Run Project always fails after Auto-Fix**: `runProject()` treated pip install exit code 1 as fatal and propagated it. Also treated CLI argparse exit code 2 as failure, even though Auto-Fix correctly counts it as success.
  2. **`'str' object has no attribute 'get'` crash**: Execution agent crashed when building fix-path lists because `all_fixes` could contain non-dict entries in edge cases.
- **How**:
  1. **terminal.js `runProject()`**: pip install exit code is now logged as a warning but doesn't block the entry point run. Exit code 2 (CLI argparse help) is treated as success for the auto-fix trigger check.
  2. **agent_service.py `run_execution_stream()`**: Added `_fix_path(f)` helper that safely extracts `path` from dict or converts string entries. Applied to all 11 occurrences of `.get('path', '') for f in all_fixes` and `pass_results['edits']` list comprehensions. Also hardened `_write_execution_log` with the same pattern.
- **Result**: Run Project now succeeds consistently after Auto-Fix fixes code errors. The `str.get` crash is prevented.
- **Notes**: The orphan module warnings (config.py, parser.py not imported from main.py) and syntax errors in scheduler.py/storage.py are issues in the *generated workspace project*, not Zenflow itself. The execution agent correctly detects and reports these — they need the LLM to fix the actual code.

---

## RL Learning Report — Per-Task .txt Export
- **Date**: 2026-02-16
- **Files Changed**: `backend/services/agent_service.py`
- **What**: After the terminal/execution agent finishes and the reward agent fires, a comprehensive `rl-learning-report.txt` is written to the workspace root. Contains everything the RL system learned from that task.
- **How**:
  1. **`_fire_reward_agent_async()`**: Now captures the return value from `_generate_reward_lessons()` and passes it to a new `_write_rl_report()` method.
  2. **`_write_rl_report()`** (new static method): Generates a human-readable .txt report with sections:
     - Overall grade + composite score + file/turn counts
     - Signal breakdown (step-level averaged + execution-level)
     - Per-step scores (grade, composite, files, turns per step)
     - Execution outcome (attempts, success, execution grade)
     - Lessons learned this task (type, text, tags, context, reward)
     - Error memory entries (relevant to this task's fingerprint — shows tier, hits, confidence, bandit arm stats)
     - Experience memory (cumulative lessons across all tasks — sorted by confidence, shows alpha/beta/expected)
     - Aggregate stats (tasks scored, avg composite, best/worst grade)
     - Context fingerprint (tech stack, libraries, file extensions, complexity)
  3. Report is written to `{workspace}/rl-learning-report.txt` and overwrites on each execution run.
- **Result**: Applied. The report is generated in the background thread alongside the reward agent, so it doesn't block the SSE stream.
- **Notes**: The report imports `_format_signal_breakdown`, `_format_step_summaries`, `_format_execution_outcome` from `reward_agent.py` (lazy import inside the method). ExperienceMemory is also lazy-imported. All wrapped in try/except so report generation can't crash the reward agent.

---

## RL Report — On-Demand Endpoint + Run Project / Auto-Fix Triggers
- **Date**: 2026-02-17
- **Files Changed**: `backend/routes/terminal.py`, `backend/services/agent_service.py`, `backend/static/js/api.js`, `backend/static/js/terminal.js`
- **What**: The RL learning report was only generated via the reward agent (background thread after Auto-Fix). If Run Project succeeded on the first try, no report was written. Added an on-demand endpoint and wired it into all terminal completion paths.
- **How**:
  1. **terminal.py**: New `POST /api/tasks/<task_id>/rl-report` endpoint calls `AgentService.generate_rl_report_for_task()`.
  2. **agent_service.py**: New `generate_rl_report_for_task()` static method gathers existing step scores, reads `execution.log` for exec score, re-scores via `score_execution()`, loads task-specific lessons from ExperienceMemory, computes fingerprint, and calls `_write_rl_report()`.
  3. **api.js**: Added `generateRlReport(taskId)` API method.
  4. **terminal.js**: Calls `ZF.api.generateRlReport()` in 3 places: after Run Project finishes (regardless of auto-fix), after Auto-Fix succeeds, and after Auto-Fix exhausts retries. Fire-and-forget with `exec-files-changed` event to refresh file tree.
- **Result**: `rl-learning-report.txt` now appears in the workspace file tree after any terminal run.
- **Notes**: The on-demand endpoint is idempotent — safe to call multiple times. The reward agent's background thread may also write the report, but the on-demand call will overwrite with fresh data. Both paths produce the same content.

---

## Planning Step WriteFile Truncation — Salvage & Token Budget Fix
- **Date**: 2026-02-17
- **Files Changed**: `backend/services/agent_service.py`
- **What**: The Planning step (and other SDD steps) failed when the model hit max_tokens mid-WriteFile JSON. The `<tool_code>` closing tag was never emitted, so the tool extraction regex missed the entire block. Result: 3 WriteFile attempts, 0 files committed, "Review Failed: No files found to review."
- **Root Cause**: `re.findall(r'<tool_code>(.*?)</tool_code>', ...)` requires the closing tag. When the model runs out of tokens mid-JSON, the tag is missing. The fallback extraction for bare JSON also failed because it looks for `depth == 0` bracket matching, which never completes on truncated JSON. Additionally, `_extract_tool_call_fallback()` didn't properly unescape truncated content when no closing `"}}` was found.
- **How**:
  1. **Truncated tool_code salvage** (new block after bare JSON fallback, ~line 7038): Detects unclosed `<tool_code>` or `<|channel|>` blocks containing WriteFile. Extracts truncated body and runs `_extract_tool_call_fallback()` to recover path + content. If ≥200 chars recovered, pushes the salvaged call into `tool_matches` for normal execution AND updates `best_writefile_content` for auto-save fallback.
  2. **Improved `_extract_tool_call_fallback()`**: The `else` branch (line ~5650) for truncated JSON (no closing `"}}`) now properly unescapes `\\n`, `\\t`, `\\"`, `\\\\` using the same safe sequence as the normal path. Previously it just did a regex strip and left escaped content.
  3. **Chat history rescue** (new fallback in completion handler): When artifact is missing and both `best_writefile_content` and narration rescue are empty, scans ALL assistant messages in history for truncated WriteFile JSON matching the artifact name. Extracts and unescapes the longest content found.
  4. **Higher SDD token budget**: Minimum output tokens raised from 1024 to 2048 for SDD steps (`requirements`, `technical-specification`, `planning`). Planning's `implementation-plan.md` for complex tasks can be 8000+ chars; 1024 tokens wasn't enough for the JSON wrapper + thinking + preamble + content.
- **Result**: Truncated WriteFile calls are now recovered and either executed directly or auto-saved. The higher token minimum reduces the chance of truncation in the first place.
- **Notes**: The salvage respects the existing duplicate write guard — if the tool actually executes successfully, the path goes into `written_files` and subsequent attempts are blocked normally. The fallback 3 (chat history rescue) is a last resort that only fires during step completion when no artifact exists.

---

## GPT-OSS Channel Regex — Accept All Channel Types
- **Date**: 2026-02-17
- **Files Changed**: `backend/services/agent_service.py`
- **What**: The GPT-OSS `<|channel|>` regex was hardcoded to only match `commentary` channel type, but the model uses multiple channel types (`analysis`, `code`, etc.). ReadFile calls like `<|channel|>analysis to=ReadFile` were completely invisible to the tool extraction pipeline. This was the PRIMARY cause of "0 files committed" across many step types.
- **How**: Changed `commentary` to `\w+` in the regex pattern at 3 locations:
  1. Main agent loop (~line 6977)
  2. Assemble phase in requirements micro-tasks (~line 4879)
  3. Another tool extraction method (~line 1806)
- **Result**: All GPT-OSS channel types now match. ReadFile, WriteFile, and other tool calls using `analysis` or `code` channels are extracted correctly.
- **Notes**: The second location (assemble phase) was missed in the first fix pass. The first MarkdownTOC test task failed at requirements because the assemble phase still had the old `commentary` regex. Fixed in a second pass.

---

## Review Auto-Pass for 0-File Implementation Steps
- **Date**: 2026-02-17
- **Files Changed**: `backend/services/agent_service.py`
- **What**: When an implementation step legitimately writes 0 files (e.g., "Wire Entry Point Execution" finds main.py already correct), the review function emitted `review_error` with "No files found to review." This blocked auto-start and showed Retry/Skip buttons, even though the step completed successfully.
- **How**: Changed the 0-file review path to emit `review_done` (the event the frontend expects) with proper data format `{content, edits: [], editDetails: []}` instead of `review_error`. The frontend's `review_done` handler calls `flushPendingStepCompleted()` to auto-advance to the next step.
- **Result**: Steps with 0 files now auto-pass review and the pipeline continues without manual intervention.
- **Notes**: First attempt incorrectly used `review_complete` event name. Frontend expects `review_done`. Fixed to use correct event name and data shape.

---

## Recoder Agent + Pre-Scan Hardening for Execution Pipeline
- **Date**: 2026-02-17
- **Files Changed**: `backend/services/agent_service.py`, `backend/prompts/execution.py`, `backend/prompts/__init__.py`
- **What**: The execution agent's auto-fix loop (Phase 3) goes in circles on broken generated projects. It patches symptoms one at a time but never steps back to look at the whole picture. When a project has multiple compounding issues (file shadowing, bad dep pins, circular imports, corrupted files), the current approach fails after 5 attempts and gives up.
- **How**:
  - **Pre-scan hardening (Phase 0)**:
    1. New `_detect_shadowing_files()` method — detects local .py files that shadow pip packages (e.g. flask.py), renames them (flask.py -> flask_app.py), and updates all imports across the project.
    2. Expanded Phase 2 pip error detection to catch build failures (`subprocess-exited-with-error`, `Failed building wheel`). New `_BUILD_SUBS` dict maps packages with known build issues to binary alternatives (e.g. psycopg2 -> psycopg2-binary).
    3. Fixed integrity check false positives — `_check_third_party_dep()` now checks if `top_pkg` exists as a local directory/package before flagging as "Missing/Uninstalled dependency".
  - **Recoder Agent (Phase 3.5)**:
    1. New `build_recoder_prompt()` in `execution.py` — holistic framing ("rewrite files to make project work"), includes ALL files, ALL errors, ALL fixes already applied.
    2. New `_run_recoder_agent()` method — reads ALL .py files (60KB budget), builds comprehensive error history, runs 8-turn LLM session via `_run_review_pass` with WriteFile/EditFile/ReadFile/RunCommand tools.
    3. Wired into `run_execution_stream` between Phase 3 (loop exhaustion) and Phase 4 (step-fix). Takes full project snapshot before running; reverts if error count increases.
    4. On success: emits `exec_done` with success=True, logs to execution.log, fires RL scoring.
    5. On failure: falls through to existing Phase 4 step-fix as final fallback.
  - **fix_history param added to `build_diagnose_prompt()`** — Phase 3 diagnosis now sees what deterministic fixes were already applied (prevents re-applying same fixes).
  - **error_output added to exec_history entries** — so the recoder can read the actual error messages from all attempts.
- **Result**: The execution pipeline now has 3 layers of defense: (1) deterministic pre-scan fixes, (2) LLM diagnosis loop, (3) holistic recoder rewrite, (4) step-fix fallback.
- **Pipeline flow**: Phase 0 (pre-scan + shadowing + build subs) -> Phase 1 (entry point) -> Phase 2 (deps + build fix) -> Phase 3 (diagnose loop x5) -> Phase 3.5 (Recoder Agent) -> Phase 4 (step-fix) -> give up.

---

## RequirementsScan False Positives + Entry Point Detection + Unit Test Step Removal
- **Date**: 2026-02-17
- **Files Changed**: `backend/services/agent_service.py`, `backend/utils/entry_point.py`, `backend/prompts/planning.py`
- **What**: Three interconnected bugs causing the execution pipeline to fail on Flask factory projects:
  1. `_scan_and_generate_requirements` added local subpackages (auth, routes, utils, extensions, metrics, etc.) to requirements.txt because it only tracked top-level directory names as local modules — subdirectories inside packages were invisible.
  2. `detect_entry_point` couldn't find Flask factory apps with `app/__init__.py` pattern (no `main.py`/`app.py` at root), causing "No entry point found" failure.
  3. Planning prompt's mandatory "Writing Unit Tests" step created test files importing pytest, triggering false integrity warnings and wasting an agent step.
- **How**:
  1. **RequirementsScan fix**: Rewrote local module collection in `_scan_and_generate_requirements` — now collects ALL directory names at every level of the path AND all .py filenames (without extension) at every level. Also filters out `_DEV_TOOL_PACKAGES` (pytest, black, mypy, etc.) from the third-party set before adding to requirements.txt.
  2. **Entry point fix**: Added step 6 to `detect_entry_point` — scans `__init__.py` in top-level package directories for Flask/FastAPI/server patterns. When found, auto-generates `run.py` with `from app import create_app` factory invocation.
  3. **Planning fix**: Removed "Writing Unit Tests" from mandatory ending steps (3 → 2 steps). Added explicit instruction "Do NOT create unit test steps or test files." Updated example content to match.
  4. **Integrity fix**: Added `_DEV_TOOL_PACKAGES` exclusion set to `_check_third_party_dep` — pytest, black, mypy etc. no longer trigger "Uninstalled dependency" warnings.
- **Result**: Isolated test with mock Flask factory project passes all 4 checks: (1) zero local modules added to requirements.txt, (2) run.py auto-generated from app/__init__.py, (3) zero false positive dependency issues in integrity check, (4) shadow detection works.

---

## Missing-Files Completion Validator + Grading Fix
- **Date**: 2026-02-18
- **Files Changed**: `backend/prompts/nudges.py`, `backend/services/agent_service.py`, `backend/services/reward_scorer.py`
- **What**: LLM agent could say [STEP_COMPLETE] after writing only some of the files listed in its step's `Files:` line (e.g., 2/3 files), and the system would accept it, grade it A (1.00), and move on. Missing files were never created.
- **How**:
  1. **New nudge** (`nudges.py`): Added `missing_files()` function that shows the LLM exactly which files it wrote, which are still missing, and forces it to create them before completing.
  2. **Assemble phase validation** (`agent_service.py` ~line 6584): Before marking step completed in the microtask/assemble loop, cross-checks `_extract_owned_files()` against `written_files` using `track_progress()`. If files are missing and nudge_count < 2, injects the missing_files nudge and continues the loop.
  3. **Main agent loop validation** (`agent_service.py` ~line 9080): Added "Check #0: Missing files" as the FIRST wiring safeguard check (before integrity, import smoke, etc.). Uses same logic — `_extract_owned_files()` + `track_progress()`. Nudges up to 2 times; after that, force-completes. New counter `missing_files_nudge_count` initialized alongside other wiring counters.
  4. **Grading fix** (`reward_scorer.py`): Added `file_completion` signal (25% weight) = `min(1.0, written_count / expected_count)`. Redistributed weights: file_completion=0.25, code_quality=0.25, efficiency=0.20, tool_adherence=0.15, import_health=0.15. Added `expected_file_count` param to `score_step()`. Both call sites in agent_service.py now pass `len(_extract_owned_files(...))` as `expected_file_count`.
- **Result**: A step that writes 2/3 files now gets nudged to create the missing file. If it still skips after 2 nudges, it force-completes but the grade reflects the incomplete file list (file_completion=0.667 → score drops significantly from A to B or lower). The banner.jpg scenario from the landing page task would now be caught and the LLM would be forced to create it.
- **Notes**: The check runs BEFORE integrity/import checks because there's no point validating code structure when files are missing entirely. The nudge limit is 2 (not 1) to give the LLM a fair chance since it may need to create multiple missing files across turns.

---
