// ── Terminal Panel (Enhanced) ────────────────────────────
window.ZF = window.ZF || {};

(function() {

  // ── ANSI SGR → HTML converter ───────────────────────────
  const ANSI_COLORS = {
    '30': '#4b5563', '31': '#f87171', '32': '#4ade80', '33': '#facc15',
    '34': '#60a5fa', '35': '#c084fc', '36': '#22d3ee', '37': '#d1d5db',
    '90': '#6b7280', '91': '#fca5a5', '92': '#86efac', '93': '#fde68a',
    '94': '#93c5fd', '95': '#d8b4fe', '96': '#67e8f9', '97': '#f3f4f6',
  };

  function ansiToHtml(str) {
    // Operates on already HTML-escaped text (< > & are safe)
    let out = '';
    let openSpans = 0;
    const parts = str.split(/\x1b\[/);
    out += parts[0];
    for (let i = 1; i < parts.length; i++) {
      const m = parts[i].match(/^([0-9;]*)m([\s\S]*)/);
      if (!m) { out += parts[i]; continue; }
      const codes = m[1].split(';').filter(Boolean);
      const text = m[2];
      // Close all open spans on reset
      if (codes.includes('0') || codes.length === 0) {
        while (openSpans > 0) { out += '</span>'; openSpans--; }
        out += text;
        continue;
      }
      let styles = [];
      for (const c of codes) {
        if (c === '1') styles.push('font-weight:bold');
        else if (c === '4') styles.push('text-decoration:underline');
        else if (ANSI_COLORS[c]) styles.push(`color:${ANSI_COLORS[c]}`);
      }
      if (styles.length) {
        out += `<span style="${styles.join(';')}">`;
        openSpans++;
      }
      out += text;
    }
    while (openSpans > 0) { out += '</span>'; openSpans--; }
    return out;
  }

  function formatLine(raw) {
    return ansiToHtml(ZF._escHtml(raw));
  }

  function formatTimestamp(ts) {
    const d = new Date(ts);
    return d.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
  }

  // ── Terminal Factory ────────────────────────────────────
  function createTerminal(taskId) {
    // State
    let history = [
      { type: 'output', content: 'Sentinel Terminal v2.0.0' },
      { type: 'output', content: 'Type a command and press Enter, or click Run Project.' },
    ];
    let processing = false;
    let autoScroll = true;
    let isFullscreen = false;
    let commandHistory = [];
    let historyIndex = -1;
    let currentInput = '';
    let detectedCommand = null;
    let activeAbortController = null;
    let streamSessionId = null;
    let execRunning = false;
    let execAbortController = null;
    let autoFixRetryCount = 0;
    let rlReportFired = false;
    const MAX_AUTOFIX_RETRIES = 5;

    // DOM refs (set once in render)
    let outputEl = null;
    let inputEl = null;
    let toolbarEl = null;
    let shellBuilt = false;

    const container = document.createElement('div');
    container.className = 'terminal-panel';

    // ── Push a line to history and append to DOM ──────────
    function pushLine(type, content) {
      const line = { type, content, timestamp: Date.now() };
      history.push(line);
      if (shellBuilt) appendLineEl(line);
    }

    function appendLineEl(lineObj) {
      if (!outputEl) return;
      // Remove processing indicator if present
      const proc = outputEl.querySelector('.terminal-processing');
      if (proc) proc.remove();

      const div = document.createElement('div');
      const cls = lineObj.type === 'command' ? 'terminal-line terminal-line-cmd' :
                  lineObj.type === 'error' ? 'terminal-line terminal-line-err' :
                  lineObj.type === 'info' ? 'terminal-line terminal-line-info' : 'terminal-line';
      div.className = cls;

      let html = '';
      if (lineObj.type === 'command' && lineObj.timestamp) {
        html += `<span class="terminal-timestamp">${formatTimestamp(lineObj.timestamp)}</span>`;
      }
      html += formatLine(lineObj.content);
      div.innerHTML = html;
      outputEl.appendChild(div);

      if (autoScroll) {
        outputEl.scrollTop = outputEl.scrollHeight;
      }
    }

    function showProcessingIndicator() {
      if (!outputEl) return;
      // Don't duplicate
      if (outputEl.querySelector('.terminal-processing')) return;
      const div = document.createElement('div');
      div.className = 'terminal-processing animate-pulse';
      div.textContent = 'Running...';
      outputEl.appendChild(div);
      if (autoScroll) outputEl.scrollTop = outputEl.scrollHeight;
    }

    function removeProcessingIndicator() {
      if (!outputEl) return;
      const proc = outputEl.querySelector('.terminal-processing');
      if (proc) proc.remove();
    }

    // ── Toolbar HTML ─────────────────────────────────────
    function buildToolbarHtml() {
      const runKillBtn = processing
        ? `<button class="terminal-kill-btn" data-action="kill">${ZF.icons.stop(14)} Kill</button>`
        : `<button class="terminal-run-btn" data-action="run">${ZF.icons.play(14)} Run Project</button>`;

      const autofixBtn = execRunning
        ? `<button class="terminal-kill-btn" data-action="cancel-autofix">${ZF.icons.stop(14)} Cancel Fix</button>`
        : `<button class="terminal-autofix-btn" data-action="autofix"${processing ? ' disabled' : ''}>${ZF.icons.bug(14)} Auto-Fix</button>`;

      const scrollIcon = autoScroll ? ZF.icons.pin(14) : ZF.icons.unpin(14);
      const scrollTitle = autoScroll ? 'Auto-scroll ON (click to disable)' : 'Auto-scroll OFF (click to enable)';
      const fsIcon = isFullscreen ? ZF.icons.minimize(14) : ZF.icons.maximize(14);
      const fsTitle = isFullscreen ? 'Exit fullscreen' : 'Fullscreen';

      return `
        ${runKillBtn}
        ${autofixBtn}
        <div class="terminal-toolbar-spacer"></div>
        <button class="terminal-toolbar-btn" data-action="autoscroll" title="${scrollTitle}">${scrollIcon}</button>
        <button class="terminal-toolbar-btn" data-action="clear" title="Clear terminal">${ZF.icons.trash(14)}</button>
        <button class="terminal-toolbar-btn" data-action="copy" title="Copy output">${ZF.icons.copy(14)}</button>
        <button class="terminal-toolbar-btn" data-action="fullscreen" title="${fsTitle}">${fsIcon}</button>
      `;
    }

    function updateToolbar() {
      if (toolbarEl) toolbarEl.innerHTML = buildToolbarHtml();
      bindToolbarEvents();
    }

    // ── Processing state ─────────────────────────────────
    function updateProcessingState(isProcessing) {
      processing = isProcessing;
      updateToolbar();
      if (inputEl) inputEl.disabled = isProcessing;
      if (isProcessing) {
        showProcessingIndicator();
      } else {
        removeProcessingIndicator();
      }
    }

    // ── SSE streaming command execution ──────────────────
    // Returns the exit code (number) or null on abort/error
    async function execStreamCommand(cmd) {
      if (!cmd || processing) return null;
      pushLine('command', `> ${cmd}`);
      updateProcessingState(true);

      const controller = new AbortController();
      activeAbortController = controller;
      streamSessionId = null;
      let exitCode = null;

      try {
        const res = await ZF.api.streamCommand(taskId, cmd, undefined, controller.signal);
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          if (controller.signal.aborted) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop(); // keep incomplete line in buffer

          let eventType = null;
          for (const line of lines) {
            if (line.startsWith('event: ')) {
              eventType = line.slice(7).trim();
            } else if (line.startsWith('data: ') && eventType) {
              try {
                const data = JSON.parse(line.slice(6));
                if (eventType === 'terminal_session') {
                  streamSessionId = data.sessionId;
                } else if (eventType === 'terminal_output') {
                  removeProcessingIndicator();
                  pushLine('output', data.line);
                } else if (eventType === 'terminal_done') {
                  exitCode = data.exitCode;
                  pushLine('info', exitCode === 0 ? 'Process exited successfully.' : `Process exited with code ${exitCode}.`);
                } else if (eventType === 'terminal_error') {
                  pushLine('error', data.error || 'Unknown error');
                }
              } catch(_) { /* skip malformed JSON */ }
              eventType = null;
            } else if (line === '') {
              eventType = null;
            }
          }
        }
      } catch(err) {
        if (!controller.signal.aborted) {
          pushLine('error', err.message || 'Stream error');
        }
      } finally {
        activeAbortController = null;
        streamSessionId = null;
        updateProcessingState(false);
        if (inputEl) inputEl.focus();
      }
      return exitCode;
    }

    // ── Kill current process ─────────────────────────────
    async function killCurrentProcess() {
      if (activeAbortController) {
        activeAbortController.abort();
      }
      if (streamSessionId) {
        try {
          await ZF.api.killTerminal(streamSessionId);
        } catch(_) { /* session may already be gone */ }
      }
    }

    // ── Run Project (entry point detection + streaming) ──
    // If autoTriggerFix is true, auto-fix runs on failure (up to MAX_AUTOFIX_RETRIES)
    async function runProject(autoTriggerFix = false) {
      if (processing) return;
      pushLine('info', 'Detecting project entry point...');

      try {
        const ep = await ZF.api.getEntryPoint(taskId);
        if (!ep.entryPoint && !ep.installCmd) {
          if (ep.isFrontend) {
            pushLine('info', 'Frontend-only project detected (HTML/CSS/JS).');
            pushLine('info', 'Open the HTML file directly in your browser to view the project.');
            pushLine('info', 'No server-side entry point to run.');
          } else {
            pushLine('error', 'No entry point found. Create a main.py, app.py, or similar file.');
          }
          // Still generate RL report for completed tasks
          ZF.api.generateRlReport(taskId).then(() => {
            pushLine('info', 'RL learning report saved to rl-learning-report.txt');
            container.dispatchEvent(new CustomEvent('exec-files-changed', { bubbles: true }));
          }).catch(() => {});
          return;
        }

        if (ep.hasVenv) {
          pushLine('info', 'Virtual environment active (.venv)');
        }

        // Install dependencies first
        let depsOk = true;
        if (ep.installCmd) {
          pushLine('info', 'Installing dependencies...');
          const pipCode = await execStreamCommand(ep.installCmd);
          if (pipCode !== 0 && pipCode !== null) {
            depsOk = false;
            pushLine('error', 'WARNING: Dependency install failed — project may not run correctly.');
            pushLine('info', 'Check requirements.txt for invalid version pins (e.g. Flask==2.3.4 does not exist).');
            pushLine('info', 'Attempting to run anyway...');
          }
        }

        // Run entry point
        if (ep.entryPoint) {
          if (ep.importError) {
            pushLine('error', `Warning: Import issue detected: ${ep.importError}`);
            pushLine('info', 'Attempting to run anyway...');
          }

          if (ep.isFrontend && ep.isServer) {
            const port = ep.serverPort || 8080;
            pushLine('info', `Frontend project detected — serving static files`);
            pushLine('info', `Open http://localhost:${port}/${ep.entryPoint} in your browser`);
          } else if (ep.isServer) {
            const port = ep.serverPort || 5000;
            pushLine('info', `Web server detected: ${ep.entryPoint}`);
            pushLine('info', `Starting server at http://localhost:${port}`);
          } else if (ep.needsArgs || ep.readsStdin) {
            pushLine('info', `CLI tool detected: ${ep.entryPoint}`);
            if (ep.description) pushLine('info', ep.description);
            if (ep.sampleFile && !ep.hasArgparse) pushLine('info', `Using sample file: ${ep.sampleFile}`);
          }

          // Update placeholder with detected command
          detectedCommand = ep.command;
          if (inputEl) inputEl.placeholder = `e.g., ${ep.command}`;

          // For servers, fire RL report alongside the stream (server never exits, so
          // code after await would never run). Give 5s for crash/start detection.
          if (ep.isServer) {
            const streamPromise = execStreamCommand(ep.command);
            setTimeout(() => {
              if (!rlReportFired) {
                rlReportFired = true;
                ZF.api.generateRlReport(taskId).then(() => {
                  pushLine('info', 'RL learning report saved to rl-learning-report.txt');
                  container.dispatchEvent(new CustomEvent('exec-files-changed', { bubbles: true }));
                }).catch(() => {});
              }
            }, 5000);
            await streamPromise;
            // If server stream ends (crashed), still generate report
            pushLine('info', `Server running at: http://localhost:${ep.serverPort || 5000}`);
          } else {
            const exitCode = await execStreamCommand(ep.command);

            // Post-run tips
            if (ep.hasArgparse) {
              pushLine('info', `Tip: Run with: python ${ep.entryPoint} --help  for usage info`);
            } else if (ep.needsArgs || ep.readsStdin) {
              pushLine('info', `Tip: Run manually with: python ${ep.entryPoint} <your-file>`);
            }

            // Auto-trigger auto-fix if initial run failed
            // Exit code 2 from CLI tools (argparse --help) counts as success ONLY if deps installed OK
            const runFailed = exitCode !== null && exitCode !== 0 && (exitCode !== 2 || !depsOk);
            if (autoTriggerFix && runFailed) {
              pushLine('info', '');
              pushLine('info', 'Initial run failed — automatically starting Auto-Fix...');
              autoFixRetryCount = 0;
              await runAutoFix(true);
            }

            // Generate RL learning report (fire and forget)
            if (!rlReportFired) {
              rlReportFired = true;
              ZF.api.generateRlReport(taskId).then(() => {
                pushLine('info', 'RL learning report saved to rl-learning-report.txt');
                container.dispatchEvent(new CustomEvent('exec-files-changed', { bubbles: true }));
              }).catch(() => { /* silent — report is optional */ });
            }
          }
        }
      } catch(err) {
        pushLine('error', 'Failed to detect entry point: ' + (err.message || 'Unknown error'));
      }
    }

    // ── Auto-Fix (Execution Agent) ─────────────────────────
    // autoRetry: when true, retries automatically on failure (up to MAX_AUTOFIX_RETRIES)
    async function runAutoFix(autoRetry = false) {
      if (execRunning || processing) return;
      execRunning = true;
      execAbortController = new AbortController();
      let lastExecSuccess = false;
      let fatalError = false;  // Set for errors that retrying won't fix (e.g. no entry point)
      updateToolbar();
      if (inputEl) inputEl.disabled = true;

      if (autoRetry) {
        autoFixRetryCount++;
        pushLine('info', `═══ Auto-Fix Agent Started (round ${autoFixRetryCount}/${MAX_AUTOFIX_RETRIES}) ═══`);
      } else {
        autoFixRetryCount = 0;
        pushLine('info', '═══ Auto-Fix Agent Started ═══');
      }
      pushLine('info', 'Detecting entry point, installing deps, running project...');

      try {
        const res = await ZF.api.startExecution(taskId, execAbortController.signal);
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          if (execAbortController.signal.aborted) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop();

          let eventType = null;
          for (const line of lines) {
            if (line.startsWith('event: ')) {
              eventType = line.slice(7).trim();
            } else if (line.startsWith('data: ') && eventType) {
              try {
                const data = JSON.parse(line.slice(6));
                if (eventType === 'exec_done') lastExecSuccess = !!data.success;
                // Detect fatal errors that retrying won't fix
                if (eventType === 'exec_error' && (data.fatal || (data.error && (
                    data.error.includes('No entry point') ||
                    data.error.includes('No .py or .js files') ||
                    data.error.includes('Frontend-only project')
                )))) {
                  fatalError = true;
                }
                handleExecEvent(eventType, data);
              } catch(_) { /* skip malformed JSON */ }
              eventType = null;
            } else if (line === '') {
              eventType = null;
            }
          }
        }
      } catch(err) {
        if (!execAbortController.signal.aborted) {
          pushLine('error', 'Auto-Fix error: ' + (err.message || 'Unknown error'));
        }
      } finally {
        const wasAborted = execAbortController && execAbortController.signal.aborted;
        execRunning = false;
        execAbortController = null;
        updateToolbar();
        if (inputEl) inputEl.disabled = false;
        if (inputEl) inputEl.focus();

        // Auto-retry if failed and under the retry limit
        // BUT skip retries for fatal errors (no entry point found) — retrying won't help
        if (!wasAborted && !lastExecSuccess && !fatalError && autoFixRetryCount < MAX_AUTOFIX_RETRIES) {
          pushLine('info', '');
          pushLine('info', `Auto-Fix failed — retrying (${autoFixRetryCount}/${MAX_AUTOFIX_RETRIES})...`);
          // Small delay before retry to let the system settle
          await new Promise(r => setTimeout(r, 1500));
          await runAutoFix(true);
        } else if (!wasAborted && !lastExecSuccess && (fatalError || autoFixRetryCount >= MAX_AUTOFIX_RETRIES)) {
          if (fatalError) {
            pushLine('error', '═══ Auto-Fix cannot proceed — no runnable entry point found ═══');
          } else {
            pushLine('error', `═══ Auto-Fix exhausted all ${MAX_AUTOFIX_RETRIES} retries — manual intervention needed ═══`);
          }
          // Generate report even on failure (captures what was learned)
          if (!rlReportFired) {
            rlReportFired = true;
            ZF.api.generateRlReport(taskId).then(() => {
              pushLine('info', 'RL learning report saved to rl-learning-report.txt');
              container.dispatchEvent(new CustomEvent('exec-files-changed', { bubbles: true }));
            }).catch(() => {});
          }
        } else if (!wasAborted && lastExecSuccess) {
          // Auto-Fix succeeded — generate report (supplement reward agent's async report)
          if (!rlReportFired) {
            rlReportFired = true;
            ZF.api.generateRlReport(taskId).then(() => {
              pushLine('info', 'RL learning report saved to rl-learning-report.txt');
              container.dispatchEvent(new CustomEvent('exec-files-changed', { bubbles: true }));
            }).catch(() => {});
          }
        }
      }
    }

    async function cancelAutoFix() {
      if (execAbortController) {
        execAbortController.abort();
      }
      try {
        await ZF.api.cancelExecution(taskId);
      } catch(_) { /* may already be done */ }
      pushLine('info', 'Auto-Fix cancelled by user.');
    }

    function handleExecEvent(type, data) {
      switch (type) {
        case 'exec_status':
          pushLine('info', data.status || '');
          break;
        case 'exec_output':
          pushLine('output', data.line || '');
          break;
        case 'exec_run':
          if (data.status === 'running') {
            pushLine('info', `── Attempt ${data.attempt}: ${data.command} ──`);
          } else if (data.status === 'success') {
            pushLine('info', `✓ Process exited successfully (code ${data.exitCode})`);
          } else if (data.status === 'error') {
            pushLine('error', `✗ Process failed (code ${data.exitCode})`);
          }
          break;
        case 'exec_diagnosis':
          pushLine('info', `Diagnosis: ${data.errorType}${data.file ? ' in ' + data.file : ''}${data.line ? ':' + data.line : ''}`);
          if (data.message) pushLine('info', `  → ${data.message}`);
          break;
        case 'exec_token':
          // LLM streaming tokens — collect for inline display
          break;
        case 'exec_fix':
          pushLine('info', `FIX: ${data.tool} → ${data.path}`);
          if (data.result) pushLine('output', `  ${data.result}`);
          break;
        case 'exec_integrity': {
          const count = data.count || 0;
          if (count > 0) {
            pushLine('info', `Integrity check: ${count} issue(s) found`);
            if (data.issues && data.issues.length) {
              data.issues.forEach(iss => pushLine('output', `  • ${iss}`));
            }
          } else {
            pushLine('info', 'Integrity check: no issues found');
          }
          break;
        }
        case 'exec_validate':
          if (data.valid) {
            pushLine('info', '✓ Output validation: OK');
          } else {
            pushLine('error', `✗ Output validation failed: ${data.reason || 'unknown'}`);
          }
          break;
        case 'exec_files_changed':
          // Dispatch event so task-detail.js can refresh the file tree
          container.dispatchEvent(new CustomEvent('exec-files-changed', { bubbles: true }));
          break;
        case 'exec_done':
          if (data.success) {
            pushLine('info', `═══ ✓ Auto-Fix Complete — project runs successfully after ${data.attempts} attempt(s) ═══`);
          } else {
            pushLine('error', `═══ ✗ Auto-Fix Failed after ${data.attempts} attempt(s) ═══`);
            if (data.output) pushLine('output', data.output.slice(-500));
          }
          break;
        case 'exec_error':
          pushLine('error', 'Auto-Fix error: ' + (data.error || 'Unknown'));
          break;
        // ── Step-Fix Events (reopening implementation step to fix errors) ──
        case 'exec_step_fix_start':
          pushLine('info', '');
          pushLine('info', `─── Reopening Step "${data.stepName}" to fix ${data.errorType} in ${data.errorFile} ───`);
          break;
        case 'exec_step_fix_status':
          pushLine('info', `  [Step Fix] ${data.status || ''}`);
          break;
        case 'exec_step_fix_edit':
          pushLine('info', `  [Step Fix] Edited: ${data.path || 'unknown'}`);
          break;
        case 'exec_step_fix_token':
          // LLM streaming tokens during step fix — skip to reduce noise
          break;
        case 'exec_step_fix_complete':
          pushLine('info', `─── Step Fix Complete: modified ${(data.filesFixed || []).length} file(s) ───`);
          pushLine('info', 'Retrying execution...');
          container.dispatchEvent(new CustomEvent('exec-files-changed', { bubbles: true }));
          break;
        case 'exec_step_fix_failed':
          pushLine('error', `─── Step Fix Failed: ${data.reason || 'unknown'} ───`);
          break;
        case 'exec_step_fix_error':
          pushLine('error', `  [Step Fix] Error: ${data.error || 'unknown'}`);
          break;
        default:
          break;
      }
    }

    // ── Clear terminal ───────────────────────────────────
    function clearTerminal() {
      history = [
        { type: 'output', content: 'Sentinel Terminal v2.0.0' },
        { type: 'output', content: 'Terminal cleared.' },
      ];
      if (outputEl) {
        outputEl.innerHTML = '';
        history.forEach(l => appendLineEl(l));
      }
    }

    // ── Copy output ──────────────────────────────────────
    function copyOutput() {
      const text = history.map(l => l.content).join('\n');
      navigator.clipboard.writeText(text).then(() => {
        // Swap icon to checkmark briefly
        const btn = toolbarEl?.querySelector('[data-action="copy"]');
        if (btn) {
          btn.innerHTML = ZF.icons.check(14);
          setTimeout(() => { btn.innerHTML = ZF.icons.copy(14); }, 1500);
        }
      });
    }

    // ── Auto-scroll toggle ───────────────────────────────
    function toggleAutoScroll() {
      autoScroll = !autoScroll;
      updateToolbar();
      if (autoScroll && outputEl) {
        outputEl.scrollTop = outputEl.scrollHeight;
      }
    }

    // ── Fullscreen toggle ────────────────────────────────
    function toggleFullscreen() {
      isFullscreen = !isFullscreen;
      container.classList.toggle('terminal-fullscreen', isFullscreen);
      updateToolbar();
    }

    // ── Event Bindings ───────────────────────────────────
    function bindToolbarEvents() {
      if (!toolbarEl) return;
      toolbarEl.querySelectorAll('[data-action]').forEach(btn => {
        btn.addEventListener('click', (e) => {
          const action = e.currentTarget.getAttribute('data-action');
          if (action === 'run') runProject();
          else if (action === 'kill') killCurrentProcess();
          else if (action === 'autofix') runAutoFix();
          else if (action === 'cancel-autofix') cancelAutoFix();
          else if (action === 'clear') clearTerminal();
          else if (action === 'copy') copyOutput();
          else if (action === 'autoscroll') toggleAutoScroll();
          else if (action === 'fullscreen') toggleFullscreen();
        });
      });
    }

    function bindInputEvents() {
      if (!inputEl) return;
      inputEl.addEventListener('keydown', async (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          const cmd = inputEl.value.trim();
          if (!cmd) return;
          // Push to command history
          commandHistory.push(cmd);
          historyIndex = -1;
          currentInput = '';
          inputEl.value = '';
          await execStreamCommand(cmd);
        } else if (e.key === 'ArrowUp') {
          e.preventDefault();
          if (commandHistory.length === 0) return;
          if (historyIndex === -1) {
            currentInput = inputEl.value;
            historyIndex = commandHistory.length - 1;
          } else if (historyIndex > 0) {
            historyIndex--;
          }
          inputEl.value = commandHistory[historyIndex] || '';
        } else if (e.key === 'ArrowDown') {
          e.preventDefault();
          if (historyIndex === -1) return;
          if (historyIndex < commandHistory.length - 1) {
            historyIndex++;
            inputEl.value = commandHistory[historyIndex];
          } else {
            historyIndex = -1;
            inputEl.value = currentInput;
          }
        } else if (e.key === 'Escape') {
          if (isFullscreen) {
            toggleFullscreen();
          } else {
            inputEl.value = '';
          }
        }
      });
    }

    function bindScrollEvents() {
      if (!outputEl) return;
      outputEl.addEventListener('scroll', () => {
        // Re-enable auto-scroll when user scrolls to bottom
        const atBottom = outputEl.scrollHeight - outputEl.scrollTop - outputEl.clientHeight < 30;
        if (atBottom && !autoScroll) {
          autoScroll = true;
          updateToolbar();
        }
      });
    }

    // ── Render (builds shell ONCE, then appends incrementally) ─
    function render() {
      if (shellBuilt) return; // Only build the shell once

      // Toolbar
      toolbarEl = document.createElement('div');
      toolbarEl.className = 'terminal-toolbar';
      toolbarEl.innerHTML = buildToolbarHtml();
      container.appendChild(toolbarEl);

      // Output area
      outputEl = document.createElement('div');
      outputEl.className = 'terminal-output';
      container.appendChild(outputEl);

      // Input bar
      const inputBar = document.createElement('div');
      inputBar.className = 'terminal-input-bar';
      inputBar.innerHTML = `
        <span class="terminal-input-icon">${ZF.icons.terminal(16)}</span>
        <input class="terminal-input" type="text" placeholder="Enter command..." autocomplete="off">
      `;
      container.appendChild(inputBar);
      inputEl = inputBar.querySelector('.terminal-input');

      // Render existing history
      history.forEach(l => appendLineEl(l));

      // Bind events once
      bindToolbarEvents();
      bindInputEvents();
      bindScrollEvents();

      shellBuilt = true;
      inputEl.focus();
    }

    render();
    return { element: container, runProject };
  }

  window.ZF.terminal = { createTerminal };
})();
