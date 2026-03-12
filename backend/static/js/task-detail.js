// ── Task Detail Page ─────────────────────────────────────
window.ZF = window.ZF || {};

(function() {
  // Strip internal metadata lines (Files:, Depends on:, Entry point:) from step
  // descriptions before displaying to the user. These are plan internals.
  // Also auto-wrap bare file references in backticks so they render as styled badges.
  function _cleanStepDesc(desc) {
    if (!desc) return '';
    let cleaned = desc.split('\n')
      .filter(line => !/^\s*(Files?|Modifies?|Depends on|Entry point)\s*:/i.test(line))
      .filter(line => !/^\s*\d+\.\s*(Simple|Medium|Complex)\s*(tasks)?/i.test(line))
      .filter(line => !/^\s*\d+\.\s*Assess\s+(the\s+)?task\s+complexity/i.test(line))
      .filter(line => !/^\s*\d+\.\s*Break down the work into categories/i.test(line))
      .filter(line => !/^\s*\d+\.\s*Choose\s+technology\s+that\s+matches/i.test(line))
      .filter(line => !/^\s*\d+\.\s*Write\s+a\s+spec\s+sized\s+to\s+match/i.test(line))
      .join('\n')
      .trim();
    // Wrap bare filenames (e.g. index.html, app.js) in backticks if not already wrapped
    // Matches word/path chars followed by a known extension, not already inside backticks
    cleaned = cleaned.replace(
      /(?<!`)(\b[\w\-./]+\.(?:py|md|txt|json|yaml|yml|toml|ini|cfg|html|css|js|ts|tsx|jsx|csv|xlsx|svg|png|jpg|sh|bat|ps1|env|lock|cfg|xml|sql|rb|go|rs|java|c|cpp|h|hpp)\b)(?!`)/gi,
      '`$1`'
    );
    return cleaned;
  }

  let _currentRenderTaskId = null;

  window.ZF.taskDetail = {
    clearRenderGuard() { _currentRenderTaskId = null; },
    async render(container, taskId) {
      // Prevent duplicate renders for the same task
      if (_currentRenderTaskId === taskId) return;
      _currentRenderTaskId = taskId;
      let task = null;
      let activeTab = 'steps';
      let rightView = 'step-chat'; // 'step-chat' | 'file-view' | 'terminal'
      let activeStepId = null;
      let activeFilePath = null;
      let openStepIds = new Set();
      let openFiles = new Map(); // path -> { name, element }
      let mountedPanels = {}; // stepId -> { element, destroy, isStreaming }
      let filesTab = null;
      let terminalPanel = null;
      let startingStep = false;

      // Load task
      try {
        task = await ZF.api.getTask(taskId);
      } catch(e) {
        container.innerHTML = '<div class="loading-state">Task not found</div>';
        return;
      }

      let steps = task.steps || [];

      // Auto-select steps on page load: restore all steps that have chat history
      const allStepsInit = [];
      steps.forEach(s => { allStepsInit.push(s); (s.children || []).forEach(c => allStepsInit.push(c)); });
      if (steps.length > 0) {
        // Open all steps that have a chatId (they've been worked on and have history)
        const stepsWithChat = allStepsInit.filter(s => s.chatId);
        stepsWithChat.forEach(s => openStepIds.add(s.id));

        const inProgress = allStepsInit.find(s => s.status === 'in_progress');
        const pending = allStepsInit.find(s => s.status === 'pending');

        if (inProgress) {
          openStepIds.add(inProgress.id);
          activeStepId = inProgress.id;
        } else if (pending && task.settings?.autoStart && task.status !== 'Paused') {
          // Auto-start first pending step
          try {
            const result = await ZF.api.startStep(taskId, pending.id);
            pending.chatId = result.chatId;
            pending.status = 'in_progress';
            task.status = 'In Progress';
            openStepIds.add(pending.id);
            activeStepId = pending.id;
            ZF.sidebar.refresh();
          } catch(e) {
            console.error('Auto-start failed:', e);
            openStepIds.add(pending.id);
            activeStepId = pending.id;
          }
        } else if (stepsWithChat.length > 0) {
          // All steps done or no pending — show last step that was worked on
          activeStepId = stepsWithChat[stepsWithChat.length - 1].id;
        } else if (pending) {
          openStepIds.add(pending.id);
          activeStepId = pending.id;
        } else if (steps.length > 0) {
          openStepIds.add(steps[0].id);
          activeStepId = steps[0].id;
        }
      }

      // Check if any panel is currently streaming
      function isAnyPanelStreaming() {
        return Object.values(mountedPanels).some(p => p.isStreaming && p.isStreaming());
      }

      function ensureFilesTab() {
        if (!filesTab) {
          filesTab = ZF.files.createFilesTab(taskId, { onFileOpen: openFileTab });
        }
        return filesTab;
      }

      async function openFileTab(filePath) {
        const name = filePath.split('/').pop();
        if (!openFiles.has(filePath)) {
          const panel = createFilePanel(filePath, name);
          openFiles.set(filePath, { name, element: panel });
        }
        activeFilePath = filePath;
        rightView = 'file-view';
        smartRender();
      }

      function createFilePanel(filePath, name) {
        const wrapper = document.createElement('div');
        wrapper.className = 'step-panel';
        wrapper.style.cssText = 'display:flex;flex-direction:column;flex:1;min-height:0;';
        wrapper.innerHTML = '<div style="flex:1;display:flex;align-items:center;justify-content:center;color:var(--color-text-tertiary);">Loading...</div>';

        // Load file content
        ZF.api.readFile(taskId, filePath).then(result => {
          const content = result.content || '';
          let rendered;
          if (filePath.endsWith('.md')) {
            rendered = `<div style="padding:16px;overflow-y:auto;flex:1;min-height:0;">${ZF.markdown.render(content)}</div>`;
          } else if (ZF.codeblock.langFromFilename(filePath)) {
            rendered = `<div style="overflow-y:auto;flex:1;min-height:0;">${ZF.codeblock.render(content, ZF.codeblock.langFromFilename(filePath), filePath)}</div>`;
          } else {
            rendered = `<pre style="padding:16px;font-size:14px;font-family:var(--font-mono);color:var(--color-text-secondary);white-space:pre-wrap;margin:0;overflow-y:auto;flex:1;min-height:0;">${ZF._escHtml(content)}</pre>`;
          }
          wrapper.innerHTML = rendered;
        }).catch(() => {
          wrapper.innerHTML = '<div style="padding:16px;color:var(--color-text-tertiary);">Error reading file</div>';
        });

        return wrapper;
      }

      // Partial render: update middle panel and tab bar without destroying right panel
      function partialRender() {
        const existing = container.querySelector('.task-detail');
        if (!existing) { fullRender(); return; }

        // Update middle panel
        const middle = existing.querySelector('.task-middle-panel');
        if (middle) {
          middle.innerHTML = renderMiddle();
          // Re-attach files tab if active
          if (activeTab === 'files' && filesTab) {
            const tc = middle.querySelector('#tab-content');
            if (tc) { tc.innerHTML = ''; tc.appendChild(filesTab.element); }
          }
          bindMiddleEvents(middle);
        }

        // Update tab bar without destroying panels
        const right = existing.querySelector('.task-right-panel');
        if (right) {
          const tabBar = right.querySelector('.step-tab-bar');
          if (tabBar) {
            tabBar.outerHTML = renderStepTabBar();
            bindTabBarEvents(right);
          }

          // Mount any new panels that don't exist yet
          const panelsArea = right.querySelector('div[style*="flex:1"]');
          if (panelsArea) {
            openStepIds.forEach(stepId => {
              const step = steps.find(s => s.id === stepId) || steps.flatMap(s => s.children || []).find(c => c.id === stepId);
              if (!step) return;
              if (!mountedPanels[stepId]) {
                mountedPanels[stepId] = createStepPanel(step);
                mountedPanels[stepId].element.style.flex = '1';
                mountedPanels[stepId].element.style.minHeight = '0';
                panelsArea.appendChild(mountedPanels[stepId].element);
              }
            });
            // Mount any new file panels
            openFiles.forEach((file, path) => {
              if (!file.element.parentElement) {
                file.element.style.flex = '1';
                file.element.style.minHeight = '0';
                panelsArea.appendChild(file.element);
              }
            });
          }
        }

        // Show/hide step panels based on active state
        Object.keys(mountedPanels).forEach(stepId => {
          const panel = mountedPanels[stepId];
          if (panel && panel.element) {
            panel.element.style.display = (rightView === 'step-chat' && activeStepId === stepId) ? 'flex' : 'none';
          }
        });
        // Show/hide file panels
        openFiles.forEach((file, path) => {
          file.element.style.display = (rightView === 'file-view' && activeFilePath === path) ? 'flex' : 'none';
        });
      }

      // Smart render: use partialRender if streaming, fullRender otherwise
      function smartRender() {
        if (isAnyPanelStreaming()) {
          partialRender();
        } else {
          fullRender();
        }
      }

      function fullRender() {
        container.innerHTML = '';
        const div = document.createElement('div');
        div.className = 'task-detail';

        // ── Middle Panel ──
        const middle = document.createElement('div');
        middle.className = 'task-middle-panel';
        middle.innerHTML = renderMiddle();
        // Re-attach files tab if active
        if (activeTab === 'files' && filesTab) {
          const tc = middle.querySelector('#tab-content');
          if (tc) { tc.innerHTML = ''; tc.appendChild(filesTab.element); }
        }
        div.appendChild(middle);
        bindMiddleEvents(middle);

        // ── Right Panel ──
        const right = document.createElement('div');
        right.className = 'task-right-panel';
        right.innerHTML = renderStepTabBar();

        // Step panels
        const panelsArea = document.createElement('div');
        panelsArea.style.cssText = 'flex:1;display:flex;flex-direction:column;min-height:0;overflow:hidden;';

        // Mount step chat panels
        openStepIds.forEach(stepId => {
          const step = steps.find(s => s.id === stepId) || steps.flatMap(s => s.children || []).find(c => c.id === stepId);
          if (!step) return;
          if (!mountedPanels[stepId]) {
            mountedPanels[stepId] = createStepPanel(step);
          }
          const panel = mountedPanels[stepId];
          panel.element.style.display = (rightView === 'step-chat' && activeStepId === stepId) ? 'flex' : 'none';
          panel.element.style.flex = '1';
          panel.element.style.minHeight = '0';
          panelsArea.appendChild(panel.element);
        });

        // Mount file panels
        openFiles.forEach((file, path) => {
          file.element.style.display = (rightView === 'file-view' && activeFilePath === path) ? 'flex' : 'none';
          file.element.style.flex = '1';
          file.element.style.minHeight = '0';
          panelsArea.appendChild(file.element);
        });

        // Empty state
        const hasNoTabs = openStepIds.size === 0 && openFiles.size === 0;
        if (hasNoTabs || (rightView === 'step-chat' && !activeStepId) || (rightView === 'file-view' && !activeFilePath)) {
          if (hasNoTabs) {
            const empty = document.createElement('div');
            empty.className = 'empty-state';
            empty.innerHTML = '<p>No tab selected</p><p>Select a step from the left panel to view its content</p>';
            panelsArea.appendChild(empty);
          }
        }

        // Terminal
        if (rightView === 'terminal') {
          if (!terminalPanel) {
            terminalPanel = ZF.terminal.createTerminal(taskId);
            // Listen for exec agent file changes to refresh file tree
            terminalPanel.element.addEventListener('exec-files-changed', () => {
              if (filesTab) filesTab.refresh();
            });
          }
          terminalPanel.element.style.display = 'flex';
          terminalPanel.element.style.flex = '1';
          panelsArea.appendChild(terminalPanel.element);
        }

        right.appendChild(panelsArea);
        div.appendChild(right);
        bindTabBarEvents(right);

        container.appendChild(div);
      }

      function createStepPanel(step) {
        const wrapper = document.createElement('div');
        wrapper.className = 'step-panel';
        wrapper.style.cssText = 'display:flex;flex-direction:column;flex:1;min-height:0;';

        let panelIsStreaming = () => false;

        if (!step.chatId) {
          // Start prompt
          wrapper.innerHTML = `<div style="flex:1;display:flex;flex-direction:column;min-height:0;background:var(--color-bg-panel);">
            ${step.description ? `<div style="border-bottom:1px solid var(--color-border);">
              <button class="step-desc-toggle" data-toggle-desc="${step.id}">
                ${ZF.icons.fileText(14)} <span>Step description</span> ${ZF.icons.chevronDown(12)}
              </button>
              <div class="step-desc-content" id="desc-${step.id}" style="display:none;">${ZF.markdown.render(step.description)}</div>
            </div>` : ''}
            <div class="step-start-prompt">
              <div class="step-start-icon">${ZF.icons.play(24)}</div>
              <div>
                <div class="step-start-title">${ZF._escHtml(step.name)}</div>
                <p class="step-start-subtitle">Start this step to begin a conversation with the AI agent.</p>
              </div>
              <div class="step-start-actions">
                <div class="step-agent-selector">${ZF.icons.settings(14)} Sentinel Default ${ZF.icons.chevronDown(12)}</div>
                <button class="btn btn-md btn-primary" data-start-step="${step.id}" style="box-shadow:0 0 10px rgba(249,115,22,0.2);">
                  ${ZF.icons.play(14)} Start ${ZF._escHtml(step.name)}
                </button>
              </div>
            </div>
          </div>`;

          // Wire up description toggle for pre-start state
          const preToggle = wrapper.querySelector(`[data-toggle-desc="${step.id}"]`);
          if (preToggle) {
            preToggle.addEventListener('click', () => {
              const content = wrapper.querySelector(`#${CSS.escape('desc-' + step.id)}`);
              const chevron = preToggle.querySelector('svg:last-child');
              if (content.style.display === 'none') {
                content.style.display = '';
                if (chevron) chevron.style.transform = 'rotate(180deg)';
              } else {
                content.style.display = 'none';
                if (chevron) chevron.style.transform = '';
              }
            });
          }

          wrapper.querySelector(`[data-start-step="${step.id}"]`)?.addEventListener('click', async () => {
            if (startingStep) return;
            startingStep = true;
            try {
              const result = await ZF.api.startStep(taskId, step.id);
              step.chatId = result.chatId;
              step.status = 'in_progress';
              task.status = 'In Progress';
              mountedPanels[step.id] = createStepPanel(step);
              fullRender();
              ZF.sidebar.refresh();
            } catch(e) { console.error('Start step failed:', e); }
            startingStep = false;
          });
        } else {
          // Chat panel — step description is rendered INSIDE the chat scroll area as a card
          const chatPanel = ZF.chat.createChatPanel({
            taskId, task, chatId: step.chatId,
            stepDescription: _cleanStepDesc(step.description || ''),
            paused: task.status === 'Paused',
            onResume: async () => {
              try { task = await ZF.api.updateTask(taskId, { status: 'In Progress' }); ZF.sidebar.refresh(); } catch {}
            },
            onStepCompleted: async (completedStepId) => {
              if (startingStep) return;
              const s = steps.find(s => s.id === completedStepId) || steps.flatMap(s => s.children || []).find(c => c.id === completedStepId);
              if (s) s.status = 'completed';

              // Re-fetch task to pick up updated filesCount
              try {
                const refreshed = await ZF.api.getTask(taskId);
                task = refreshed;
                steps = task.steps || steps;
              } catch {}

              const allStepsFlat = [];
              steps.forEach(s => { allStepsFlat.push(s); (s.children || []).forEach(c => allStepsFlat.push(c)); });
              const nextPending = allStepsFlat.find(s => s.status === 'pending');
              if (nextPending && task.settings?.autoStart) {
                startingStep = true;
                try {
                  const result = await ZF.api.startStep(taskId, nextPending.id);
                  nextPending.chatId = result.chatId;
                  nextPending.status = 'in_progress';
                  openStepIds.add(nextPending.id);
                  activeStepId = nextPending.id;
                  rightView = 'step-chat';
                  smartRender();
                } catch(e) { console.error('Auto-start next step failed:', e); }
                setTimeout(() => { startingStep = false; }, 2000);
              } else if (nextPending) {
                openStepIds.add(nextPending.id);
                activeStepId = nextPending.id;
                rightView = 'step-chat';
                smartRender();
              } else {
                // All steps complete — mark task done
                try { task = await ZF.api.updateTask(taskId, { status: 'Completed' }); } catch(e) { console.error('Failed to mark task completed:', e); }

                // Always switch to terminal and auto-run when all steps are done
                rightView = 'terminal';
                if (!terminalPanel) terminalPanel = ZF.terminal.createTerminal(taskId);
                smartRender();
                // Small delay so terminal mounts in DOM before running
                setTimeout(() => terminalPanel.runProject(true), 500);
              }
              ZF.sidebar.refresh();
            },
            onFileWritten: (path) => {
              if (filesTab) filesTab.refresh();
              // Update file count badge dynamically
              ZF.api.getTask(taskId).then(t => {
                task = t;
                const badge = document.querySelector('[data-tab="files"] .tab-count');
                if (badge) badge.textContent = t.filesCount || '';
                else if (t.filesCount) {
                  const btn = document.querySelector('[data-tab="files"]');
                  if (btn && !btn.querySelector('.tab-count')) {
                    btn.insertAdjacentHTML('beforeend', `<span class="tab-count">${t.filesCount}</span>`);
                  }
                }
              }).catch(() => {});
            },
          });
          panelIsStreaming = chatPanel.isStreaming || (() => false);
          wrapper.appendChild(chatPanel.element);
        }

        return { element: wrapper, destroy: () => {}, isStreaming: panelIsStreaming };
      }

      function renderStepsContent() {
        const autoStart = !!task.settings?.autoStart;
        // Flatten all steps (root + children) to find in-progress / next eligible
        const allFlat = [];
        steps.forEach(s => { allFlat.push(s); (s.children || []).forEach(c => allFlat.push(c)); });
        const nextEligible = (() => {
          if (allFlat.some(s => s.status === 'in_progress')) return null;
          for (const s of allFlat) {
            // Skip parent steps that have children (they auto-complete)
            if (s.children && s.children.length > 0) continue;
            if (s.status === 'pending') return s.id;
          }
          return null;
        })();
        const isPaused = task.status === 'Paused';

        function renderStepIcon(status) {
          if (status === 'completed') return '<div class="step-circle-done"></div>';
          if (status === 'in_progress') return '<div class="step-circle-active"></div>';
          if (status === 'failed') return `<span style="color:#ef4444;">${ZF.icons.x(16)}</span>`;
          if (status === 'skipped') return `<span style="color:var(--color-text-tertiary);">${ZF.icons.minus ? ZF.icons.minus(16) : '—'}</span>`;
          return '<div class="step-circle"></div>';
        }

        function renderStepItem(step, isChild) {
          const iconHtml = renderStepIcon(step.status);
          let labelHtml = '';
          if (step.status === 'in_progress') {
            labelHtml = isPaused ? '<div class="step-item-label paused">Paused</div>' : '<div class="step-item-label action">In progress</div>';
          } else if (step.status === 'failed') {
            labelHtml = '<div class="step-item-label" style="color:#ef4444;font-size:11px;">Blocked</div>';
          } else if (step.status === 'skipped') {
            labelHtml = '<div class="step-item-label" style="color:var(--color-text-tertiary);font-size:11px;">Skipped</div>';
          }
          const nameClass = step.status === 'skipped' ? 'step-item-name completed' : 'step-item-name';
          const isActive = activeStepId === step.id;
          let actionBtn = '';
          if (step.id === nextEligible) actionBtn = `<button class="step-start-btn" data-start-step="${step.id}">Start</button>`;
          const indent = isChild ? 'padding-left:28px;' : '';
          return `<div class="step-item ${isActive ? 'active' : ''}" data-step-id="${step.id}" data-action="step-click" style="${indent}">
            <div class="step-item-icon">${iconHtml}</div>
            <div style="flex:1;min-width:0;">
              <div class="${nameClass}">${ZF._escHtml(step.name)}</div>
              ${labelHtml}
            </div>
            ${actionBtn}
          </div>`;
        }

        let stepsHtml = '';
        steps.forEach(step => {
          stepsHtml += renderStepItem(step, false);
          if (step.children && step.children.length > 0) {
            step.children.forEach(child => {
              stepsHtml += renderStepItem(child, true);
            });
          }
        });

        return `<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;">
          <button style="font-size:13px;color:var(--color-accent);display:flex;align-items:center;gap:6px;" data-action="edit-plan">
            Edit steps in plan.md ${ZF.icons.chevronRight(12)}
          </button>
          <div style="display:flex;align-items:center;gap:8px;">
            <span style="font-size:13px;color:var(--color-text-secondary);">Auto-start steps</span>
            <button class="toggle ${autoStart?'active':''}" data-action="toggle-autostart">
              <div class="toggle-thumb"></div>
            </button>
          </div>
        </div>
        ${stepsHtml}`;
      }

      function renderMiddle() {
        const stalledBanner = task.hasStalled ? `
          <div class="stalled-banner" id="stalled-banner">
            <span class="stalled-banner-text">This task was interrupted by a server restart. A step may be stuck in progress.</span>
            <button class="stalled-restart" data-action="restart-stalled">Restart Step</button>
            <button class="stalled-dismiss" data-action="dismiss-stalled">Dismiss</button>
          </div>` : '';
        return `<div class="task-middle-header">
          <div>
            <h2>Task Workflow</h2>
            <h1>${ZF._escHtml(task.title)}</h1>
            ${stalledBanner}
            ${task.details ? `<div class="task-details-text line-clamp-2">${ZF._escHtml(task.details)}</div>` : ''}
            <div class="task-status-row">
              <span>Status:</span>
              <div style="position:relative;" id="status-pill-wrapper">${ZF.statusPill(task.status)}</div>
            </div>
          </div>
          <div class="tab-bar">
            <button class="tab-btn ${activeTab==='steps'?'active':''}" data-tab="steps">Steps<span class="tab-count">${steps.length}</span></button>
            <button class="tab-btn ${activeTab==='files'?'active':''}" data-tab="files">Files${task.filesCount ? `<span class="tab-count">${task.filesCount}</span>` : ''}</button>
          </div>
        </div>
        <div class="tab-content ${activeTab === 'files' ? '' : 'tab-content-padded'}" id="tab-content">
          ${activeTab === 'steps' ? renderStepsContent() : ''}
        </div>`;
      }

      function renderStepTabBar() {
        let tabsHtml = '';
        const allSteps = [];
        steps.forEach(s => { allSteps.push(s); (s.children || []).forEach(c => allSteps.push(c)); });
        const openSteps = allSteps.filter(s => openStepIds.has(s.id));
        let tabIdx = 0;
        openSteps.forEach(step => {
          const isActive = rightView === 'step-chat' && activeStepId === step.id;
          tabsHtml += `${tabIdx > 0 ? '<div class="step-tab-divider"></div>' : ''}
            <div class="step-tab ${isActive?'active':''}" data-step-tab="${step.id}">
              <div class="step-tab-label">${ZF.icons.chat(18)} ${ZF._escHtml(step.name)}</div>
              <button class="step-tab-close" data-close-tab="${step.id}">${ZF.icons.x(13)}</button>
            </div>`;
          tabIdx++;
        });

        // File tabs
        openFiles.forEach((file, path) => {
          const isActive = rightView === 'file-view' && activeFilePath === path;
          const { icon, color } = ZF.files.getFileIcon(file.name);
          tabsHtml += `${tabIdx > 0 ? '<div class="step-tab-divider"></div>' : ''}
            <div class="step-tab ${isActive?'active':''}" data-file-tab="${ZF._escHtml(path)}">
              <div class="step-tab-label"><span style="${color}">${ZF.icons[icon](18)}</span> ${ZF._escHtml(file.name)}</div>
              <button class="step-tab-close" data-close-file-tab="${ZF._escHtml(path)}">${ZF.icons.x(13)}</button>
            </div>`;
          tabIdx++;
        });

        return `<div class="step-tab-bar">
          <div class="step-tab-bar-left">${tabsHtml}</div>
          <div class="step-tab-bar-right">
            <button class="btn btn-sm btn-ghost ${rightView==='terminal'?'active':''}" data-action="show-terminal" style="${rightView==='terminal'?'background:var(--color-bg-secondary);color:var(--color-text-primary);':'color:var(--color-text-secondary);'}">
              ${ZF.icons.terminal(15)} Terminal
            </button>
          </div>
        </div>`;
      }

      function bindMiddleEvents(el) {
        el.addEventListener('click', async (e) => {
          const tab = e.target.closest('[data-tab]');
          if (tab) {
            activeTab = tab.dataset.tab;
            if (activeTab === 'files') ensureFilesTab();
            const content = el.querySelector('#tab-content');
            if (content) {
              if (activeTab === 'files' && filesTab) {
                content.className = 'tab-content';
                content.innerHTML = '';
                content.appendChild(filesTab.element);
              } else {
                content.className = 'tab-content tab-content-padded';
                content.innerHTML = renderStepsContent();
              }
            }
            // Update tab buttons
            el.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === activeTab));
            return;
          }
          const stepClick = e.target.closest('[data-action="step-click"]');
          if (stepClick) {
            const stepId = stepClick.dataset.stepId;
            openStepIds.add(stepId);
            activeStepId = stepId;
            rightView = 'step-chat';
            smartRender();
            return;
          }
          const startBtn = e.target.closest('[data-start-step]');
          if (startBtn) {
            e.stopPropagation();
            const stepId = startBtn.dataset.startStep;
            if (startingStep) return;
            startingStep = true;
            try {
              const result = await ZF.api.startStep(taskId, stepId);
              const step = steps.find(s => s.id === stepId) || steps.flatMap(s => s.children || []).find(c => c.id === stepId);
              if (step) { step.chatId = result.chatId; step.status = 'in_progress'; }
              task.status = 'In Progress';
              openStepIds.add(stepId);
              activeStepId = stepId;
              rightView = 'step-chat';
              smartRender();
            } catch(e) { console.error('Start step failed:', e); }
            startingStep = false;
            return;
          }
          // ── Stalled banner handlers ──
          const dismissStalled = e.target.closest('[data-action="dismiss-stalled"]');
          if (dismissStalled) {
            task.hasStalled = false;
            ZF.api.updateTask(taskId, { hasStalled: false }).catch(() => {});
            document.getElementById('stalled-banner')?.remove();
            return;
          }
          const restartStalled = e.target.closest('[data-action="restart-stalled"]');
          if (restartStalled) {
            // Find the in_progress step and reset it to pending
            const allSteps = [];
            steps.forEach(s => { allSteps.push(s); (s.children || []).forEach(c => allSteps.push(c)); });
            const stalled = allSteps.find(s => s.status === 'in_progress');
            if (stalled) {
              try {
                await ZF.api.updateStep(taskId, stalled.id, { status: 'pending' });
                stalled.status = 'pending';
                stalled.chatId = null;
              } catch (err) { console.error('Failed to reset stalled step:', err); }
            }
            task.hasStalled = false;
            ZF.api.updateTask(taskId, { hasStalled: false }).catch(() => {});
            smartRender();
            return;
          }
          const editPlan = e.target.closest('[data-action="edit-plan"]');
          if (editPlan) {
            activeTab = 'files';
            ensureFilesTab();
            const content = el.querySelector('#tab-content');
            if (content && filesTab) {
              content.className = 'tab-content';
              content.innerHTML = '';
              content.appendChild(filesTab.element);
            }
            el.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === activeTab));
            return;
          }
          const toggleAS = e.target.closest('[data-action="toggle-autostart"]');
          if (toggleAS) {
            const newVal = !task.settings?.autoStart;
            try {
              task = await ZF.api.updateTask(taskId, { settings: { ...task.settings, autoStart: newVal } });
              partialRender();
            } catch {}
            return;
          }
        });
      }

      function bindTabBarEvents(el) {
        el.addEventListener('click', (e) => {
          const stepTab = e.target.closest('[data-step-tab]');
          if (stepTab && !e.target.closest('[data-close-tab]')) {
            activeStepId = stepTab.dataset.stepTab;
            rightView = 'step-chat';
            smartRender();
            return;
          }
          const closeTab = e.target.closest('[data-close-tab]');
          if (closeTab) {
            const stepId = closeTab.dataset.closeTab;
            openStepIds.delete(stepId);
            if (activeStepId === stepId) {
              const remaining = [...openStepIds];
              activeStepId = remaining.length > 0 ? remaining[remaining.length - 1] : null;
            }
            smartRender();
            return;
          }
          // File tab click
          const fileTab = e.target.closest('[data-file-tab]');
          if (fileTab && !e.target.closest('[data-close-file-tab]')) {
            activeFilePath = fileTab.dataset.fileTab;
            rightView = 'file-view';
            if (filesTab) filesTab.setSelected(activeFilePath);
            smartRender();
            return;
          }
          // File tab close
          const closeFileTab = e.target.closest('[data-close-file-tab]');
          if (closeFileTab) {
            const path = closeFileTab.dataset.closeFileTab;
            openFiles.delete(path);
            if (activeFilePath === path) {
              const remaining = [...openFiles.keys()];
              if (remaining.length > 0) {
                activeFilePath = remaining[remaining.length - 1];
                rightView = 'file-view';
              } else if (openStepIds.size > 0) {
                activeFilePath = null;
                activeStepId = [...openStepIds].pop();
                rightView = 'step-chat';
              } else {
                activeFilePath = null;
                rightView = 'step-chat';
              }
            }
            if (filesTab) filesTab.setSelected(activeFilePath);
            smartRender();
            return;
          }
          const termBtn = e.target.closest('[data-action="show-terminal"]');
          if (termBtn) {
            rightView = 'terminal';
            smartRender();
            return;
          }
        });

        // Detect tab overflow and toggle fade hint
        const tabLeft = el.querySelector('.step-tab-bar-left');
        if (tabLeft) {
          const check = () => tabLeft.classList.toggle('has-overflow', tabLeft.scrollWidth > tabLeft.clientWidth + 4);
          check();
          tabLeft.addEventListener('scroll', check);
        }
      }

      fullRender();
    }
  };
})();
