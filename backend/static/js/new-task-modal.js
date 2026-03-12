// ── New Task Modal ───────────────────────────────────────
window.ZF = window.ZF || {};

(function() {
  const WORKFLOWS = [
    { id: 'full_sdd', label: 'Full SDD workflow', icon: 'workflow', desc: 'Comprehensive workflow with requirements, spec, and planning phases.' },
  ];

  const COMPLEXITY_LABELS = {
    1: 'Beginner', 2: 'Beginner', 3: 'Basic', 4: 'Basic',
    5: 'Intermediate', 6: 'Intermediate', 7: 'Advanced', 8: 'Advanced',
    9: 'Expert', 10: 'Expert',
  };

  let isOpen = false;
  let selectedWorkflow = WORKFLOWS[0];
  let projects = [];
  let selectedProjectId = '';
  let taskDetails = '';
  let autoStart = true;
  let isLoading = false;
  let isReformatting = false;
  let complexity = 5;
  let rendered = false; // track if DOM is built

  /** Build the full modal DOM once, then show/hide */
  function render() {
    const modal = document.getElementById('new-task-modal');
    if (!modal) return;

    if (!isOpen) { modal.innerHTML = ''; rendered = false; return; }

    if (!rendered) {
      buildModal(modal);
      rendered = true;
    }

    // Patch only the parts that change
    patchWorkflowButtons();
    patchProjectDropdown();
    patchWorkflowTitle();
    patchAutoStartToggle();
    patchActionButtons();
  }

  function buildModal(modal) {
    let workflowHtml = '';
    WORKFLOWS.forEach(w => {
      workflowHtml += `<div class="group" style="position:relative;">
        <button data-workflow="${w.id}" style="width:100%;display:flex;align-items:center;gap:12px;padding:10px 12px;border-radius:var(--radius-lg);font-size:14px;font-weight:500;text-align:left;transition:all 150ms;color:var(--color-text-secondary);border:1px solid transparent;">
          <span style="color:var(--color-text-tertiary);">${ZF.icons[w.icon](16)}</span>
          ${ZF._escHtml(w.label)}
        </button>
      </div>`;
    });

    let projectOptions = '';
    projects.forEach(p => {
      projectOptions += `<button data-select-project="${p.id}" style="width:100%;text-align:left;padding:8px 12px;font-size:14px;color:var(--color-text-primary);display:flex;align-items:center;gap:8px;transition:background 150ms;"
        onmouseover="this.style.background='var(--color-bg-secondary)'" onmouseout="this.style.background=''">${ZF.icons.folder(14)} ${ZF._escHtml(p.name)}</button>`;
    });

    // Build complexity picker dots
    let complexityDotsHtml = '';
    for (let i = 1; i <= 10; i++) {
      complexityDotsHtml += `<button data-complexity="${i}" class="complexity-dot${i === complexity ? ' active' : ''}" title="${i} - ${COMPLEXITY_LABELS[i]}">${i}</button>`;
    }

    modal.innerHTML = `<div class="modal-overlay">
      <div style="width:100%;max-width:896px;height:600px;background:var(--color-bg-panel);border-radius:var(--radius-xl);border:1px solid var(--color-border);box-shadow:var(--shadow-modal);display:flex;overflow:hidden;">
        <div style="width:33.33%;background:var(--color-bg-secondary);padding:24px;border-right:1px solid var(--color-border);display:flex;flex-direction:column;">
          <div style="margin-bottom:24px;">
            <h2 style="font-size:14px;font-weight:600;color:var(--color-text-primary);margin-bottom:4px;">Task type</h2>
            <p style="font-size:12px;color:var(--color-text-tertiary);line-height:1.5;">It defines the workflow used by AI for task implementation</p>
          </div>
          <div style="display:flex;flex-direction:column;gap:8px;flex:1;">${workflowHtml}</div>
        </div>
        <div style="flex:1;padding:24px;display:flex;flex-direction:column;">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:24px;">
            <div style="display:flex;align-items:center;gap:8px;">
              <span style="font-size:14px;color:var(--color-text-tertiary);">New task /</span>
              <span id="modal-workflow-title" style="font-size:14px;font-weight:500;color:var(--color-text-primary);"></span>
            </div>
            <button data-action="close-modal" style="color:var(--color-text-tertiary);transition:color 150ms;" onmouseover="this.style.color='var(--color-text-primary)'" onmouseout="this.style.color='var(--color-text-tertiary)'">${ZF.icons.x(20)}</button>
          </div>
          <div style="flex:1;display:flex;flex-direction:column;gap:16px;overflow-y:auto;">
            <div style="position:relative;">
              <label style="display:block;font-size:14px;font-weight:500;color:var(--color-text-primary);margin-bottom:6px;">Project *</label>
              <button id="project-dropdown-btn" style="width:100%;display:flex;align-items:center;justify-content:space-between;padding:8px 12px;background:var(--color-bg-input);border:1px solid var(--color-border);border-radius:var(--radius-lg);font-size:14px;color:var(--color-text-primary);transition:border-color 150ms;">
                <span id="project-dropdown-label" style="display:flex;align-items:center;gap:8px;"></span>
                ${ZF.icons.chevronDown(14)}
              </button>
              <div id="project-dropdown" style="display:none;position:absolute;top:100%;left:0;right:0;margin-top:4px;background:var(--color-bg-panel);border:1px solid var(--color-border);border-radius:var(--radius-lg);box-shadow:var(--shadow-modal);z-index:10;max-height:192px;overflow-y:auto;">
                ${projects.length > 0 ? projectOptions : '<div style="padding:8px 12px;font-size:14px;color:var(--color-text-tertiary);">No projects found</div>'}
              </div>
            </div>
            <div style="flex:1;display:flex;flex-direction:column;">
              <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;">
                <label style="font-size:14px;font-weight:500;color:var(--color-text-primary);">Task details</label>
                <button id="reformat-btn" class="reformat-btn" data-action="reformat" title="Reformat task description using AI">
                  <span class="reformat-icon">${ZF.icons.sparkles(14)}</span>
                  <span>Reformat</span>
                </button>
              </div>
              <div style="position:relative;flex:1;display:flex;flex-direction:column;">
                <textarea id="task-details-input" placeholder="Describe your task details." style="flex:1;min-height:140px;background:var(--color-bg-input);border:1px solid var(--color-border);border-radius:var(--radius-lg);padding:12px;font-size:14px;color:var(--color-text-primary);resize:none;outline:none;transition:border-color 150ms;" onfocus="this.style.borderColor='var(--color-accent)'" onblur="this.style.borderColor='var(--color-border)'">${ZF._escHtml(taskDetails)}</textarea>
                <div id="reformat-thinking-overlay" style="display:none;position:absolute;inset:0;background:var(--color-bg-input);border:1px solid var(--color-accent);border-radius:var(--radius-lg);padding:12px;pointer-events:none;">
                  <div style="display:flex;align-items:center;gap:8px;color:var(--color-text-tertiary);font-size:14px;">
                    <span class="thinking-pulse" style="flex-shrink:0;"></span>
                    <span id="reformat-thinking-label">Thinking...</span>
                  </div>
                </div>
              </div>
            </div>
            <div>
              <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">
                <label style="font-size:14px;font-weight:500;color:var(--color-text-primary);">Complexity</label>
                <span id="complexity-label" class="complexity-label">${complexity} - ${COMPLEXITY_LABELS[complexity]}</span>
              </div>
              <div class="complexity-picker">
                ${complexityDotsHtml}
              </div>
            </div>
            <div style="display:flex;align-items:center;gap:12px;margin-top:8px;">
              <button class="toggle${autoStart?' active':''}" id="modal-autostart-toggle" data-action="toggle-autostart-modal"><div class="toggle-thumb"></div></button>
              <span style="font-size:14px;color:var(--color-text-primary);">Auto-start next steps on success</span>
            </div>
          </div>
          <div style="margin-top:24px;padding-top:24px;border-top:1px solid var(--color-border);display:flex;align-items:center;justify-content:flex-end;gap:12px;">
            <button class="btn btn-md btn-ghost" data-action="close-modal">Cancel</button>
            <button class="btn btn-md btn-secondary" id="modal-btn-create" data-action="create">Create</button>
            <button class="btn btn-md btn-primary" id="modal-btn-create-run" data-action="create-run">Create & Run</button>
          </div>
        </div>
      </div>
    </div>`;

    // Bind events once
    modal.querySelectorAll('[data-action="close-modal"]').forEach(b => b.addEventListener('click', close));

    modal.querySelectorAll('[data-workflow]').forEach(b => {
      b.addEventListener('click', () => {
        selectedWorkflow = WORKFLOWS.find(w => w.id === b.dataset.workflow) || WORKFLOWS[0];
        patchWorkflowButtons();
        patchWorkflowTitle();
      });
    });

    const ddBtn = modal.querySelector('#project-dropdown-btn');
    const dd = modal.querySelector('#project-dropdown');
    ddBtn?.addEventListener('click', () => {
      dd.style.display = dd.style.display === 'none' ? 'block' : 'none';
    });

    modal.querySelectorAll('[data-select-project]').forEach(b => {
      b.addEventListener('click', () => {
        selectedProjectId = b.dataset.selectProject;
        dd.style.display = 'none';
        patchProjectDropdown();
        patchActionButtons();
      });
    });

    modal.querySelector('#task-details-input')?.addEventListener('input', (e) => { taskDetails = e.target.value; });

    modal.querySelector('[data-action="toggle-autostart-modal"]')?.addEventListener('click', () => {
      autoStart = !autoStart;
      patchAutoStartToggle();
    });

    // Complexity picker
    modal.querySelectorAll('[data-complexity]').forEach(b => {
      b.addEventListener('click', () => {
        complexity = parseInt(b.dataset.complexity);
        patchComplexityPicker();
      });
    });

    // Reformat button
    modal.querySelector('[data-action="reformat"]')?.addEventListener('click', handleReformat);

    modal.querySelector('[data-action="create"]')?.addEventListener('click', () => submit(false));
    modal.querySelector('[data-action="create-run"]')?.addEventListener('click', () => submit(true));

    // Close on overlay click
    modal.querySelector('.modal-overlay')?.addEventListener('click', (e) => {
      if (e.target === e.currentTarget) close();
    });
  }

  /** Handle reformat button click — streams tokens for typewriter effect */
  async function handleReformat() {
    const textarea = document.getElementById('task-details-input');
    const btn = document.getElementById('reformat-btn');
    if (!textarea || !btn) return;

    const text = textarea.value.trim();
    if (!text) return;

    if (isReformatting) return;
    isReformatting = true;

    // Show loading state
    btn.classList.add('loading');
    btn.innerHTML = `<span class="reformat-spinner"></span><span>Reformatting...</span>`;

    // Clear textarea for streaming typewriter
    textarea.value = '';
    taskDetails = '';

    // Show thinking overlay
    const overlay = document.getElementById('reformat-thinking-overlay');
    if (overlay) overlay.style.display = '';
    let contentStarted = false;

    try {
      const resp = await fetch('/api/reformat-task-stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ details: text, complexity }),
      });

      if (!resp.ok) {
        throw new Error('Stream request failed');
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const raw = line.slice(6).trim();
          if (!raw) continue;
          try {
            const evt = JSON.parse(raw);
            if (evt.error) throw new Error(evt.error);
            if (evt.done) break;
            if (evt.thinking) continue; // model is reasoning — overlay already visible
            if (evt.token) {
              // First content token — hide thinking overlay
              if (!contentStarted) {
                contentStarted = true;
                if (overlay) overlay.style.display = 'none';
              }
              taskDetails += evt.token;
              textarea.value = taskDetails;
              // Auto-scroll textarea to bottom as text streams in
              textarea.scrollTop = textarea.scrollHeight;
            }
          } catch (parseErr) {
            if (parseErr.message && !parseErr.message.includes('JSON')) throw parseErr;
          }
        }
      }

      // Ensure overlay is hidden at the end
      if (overlay) overlay.style.display = 'none';

      // Success
      btn.classList.remove('loading');
      btn.classList.add('success');
      btn.innerHTML = `<span class="reformat-icon">${ZF.icons.check(14)}</span><span>Done</span>`;
      setTimeout(() => {
        btn.classList.remove('success');
        btn.innerHTML = `<span class="reformat-icon">${ZF.icons.sparkles(14)}</span><span>Reformat</span>`;
      }, 1500);

    } catch (e) {
      console.error('Reformat failed:', e);
      if (overlay) overlay.style.display = 'none';
      // Restore original text on failure
      if (!taskDetails.trim()) {
        taskDetails = text;
        textarea.value = text;
      }
      btn.classList.remove('loading');
      btn.classList.add('error');
      btn.innerHTML = `<span class="reformat-icon">${ZF.icons.x(14)}</span><span>Failed</span>`;
      setTimeout(() => {
        btn.classList.remove('error');
        btn.innerHTML = `<span class="reformat-icon">${ZF.icons.sparkles(14)}</span><span>Reformat</span>`;
      }, 2000);
    }

    isReformatting = false;
  }

  /** Update complexity picker visual state */
  function patchComplexityPicker() {
    const modal = document.getElementById('new-task-modal');
    if (!modal) return;
    modal.querySelectorAll('[data-complexity]').forEach(btn => {
      const val = parseInt(btn.dataset.complexity);
      if (val === complexity) {
        btn.classList.add('active');
      } else {
        btn.classList.remove('active');
      }
    });
    const label = modal.querySelector('#complexity-label');
    if (label) label.textContent = `${complexity} - ${COMPLEXITY_LABELS[complexity]}`;
  }

  /** Update only workflow button styles */
  function patchWorkflowButtons() {
    const modal = document.getElementById('new-task-modal');
    if (!modal) return;
    modal.querySelectorAll('[data-workflow]').forEach(btn => {
      const sel = btn.dataset.workflow === selectedWorkflow.id;
      btn.style.background = sel ? 'var(--color-bg-panel)' : '';
      btn.style.color = sel ? 'var(--color-text-primary)' : 'var(--color-text-secondary)';
      btn.style.boxShadow = sel ? 'var(--shadow-sm)' : '';
      btn.style.borderColor = sel ? 'var(--color-border)' : 'transparent';
      const icon = btn.querySelector('span');
      if (icon) icon.style.color = sel ? 'var(--color-accent)' : 'var(--color-text-tertiary)';
    });
  }

  /** Update only the workflow title text */
  function patchWorkflowTitle() {
    const el = document.getElementById('modal-workflow-title');
    if (el) el.textContent = selectedWorkflow.label;
  }

  /** Update only the project dropdown label */
  function patchProjectDropdown() {
    const el = document.getElementById('project-dropdown-label');
    if (!el) return;
    const selProject = projects.find(p => p.id === selectedProjectId);
    el.innerHTML = ZF.icons.folder(14) + ' ' + (selProject ? ZF._escHtml(selProject.name) : 'Select a project');
  }

  /** Update only the autostart toggle */
  function patchAutoStartToggle() {
    const el = document.getElementById('modal-autostart-toggle');
    if (!el) return;
    if (autoStart) el.classList.add('active');
    else el.classList.remove('active');
  }

  /** Update only the create button disabled states */
  function patchActionButtons() {
    const btnCreate = document.getElementById('modal-btn-create');
    const btnRun = document.getElementById('modal-btn-create-run');
    if (btnCreate) btnCreate.disabled = !selectedProjectId;
    if (btnRun) btnRun.disabled = !selectedProjectId;
  }

  async function submit(run) {
    if (!selectedProjectId || !taskDetails.trim() || isLoading) return;
    isLoading = true;
    try {
      const task = await ZF.api.createTask({
        projectId: selectedProjectId,
        workflowType: selectedWorkflow.label,
        details: taskDetails,
        settings: { autoStart: run || autoStart, isolatedCopy: true, complexity },
      });
      close();
      await ZF.activeTask.set(task.id);
      ZF.router.navigate(`/task/${task.id}`);
      ZF.sidebar.refresh();
    } catch(e) { console.error('Create task failed:', e); }
    isLoading = false;
  }

  function open() {
    isOpen = true;
    selectedProjectId = '';
    taskDetails = '';
    autoStart = true;
    complexity = 5;
    ZF.api.getProjects().then(p => {
      projects = p;
      // Auto-select if there's only one project
      if (p.length === 1) selectedProjectId = p[0].id;
      render();
    }).catch(console.error);
    // Don't render yet — wait for projects to load to avoid "No projects found" flash
  }

  function close() {
    isOpen = false;
    render();
  }

  window.ZF.newTaskModal = { open, close };
})();
