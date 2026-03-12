// ── App Module (Router + Sidebar + ActiveTaskManager + Init) ──────
window.ZF = window.ZF || {};

// ── Active Task Manager ──────────────────────────────────
(function() {
  let _activeTaskId = null;
  let _cleanupAbort = null;
  let _beforeUnloadRegistered = false;

  function ensureBeforeUnload() {
    if (_beforeUnloadRegistered) return;
    _beforeUnloadRegistered = true;
    window.addEventListener('beforeunload', () => {
      if (_activeTaskId) {
        navigator.sendBeacon(`/api/tasks/${_activeTaskId}/pause`);
      }
    });
  }

  window.ZF.activeTask = {
    async set(newTaskId) {
      const oldTaskId = _activeTaskId;
      if (oldTaskId === newTaskId) return;
      _activeTaskId = newTaskId;
      if (newTaskId) ensureBeforeUnload();
      if (_cleanupAbort) { _cleanupAbort.abort(); }

      if (oldTaskId) {
        const ac = new AbortController();
        _cleanupAbort = ac;
        console.log(`[ActiveTask] Deactivating ${oldTaskId}`);
        try {
          const result = await ZF.api.cancelAllTaskChats(oldTaskId);
          console.log(`[ActiveTask] Cancelled ${result.count} streams`);
          if (ac.signal.aborted) return;
          try { await ZF.api.pauseTask(oldTaskId); } catch(e) {}
        } catch(e) {
          console.error('[ActiveTask] Cancel error:', e);
        } finally {
          if (_cleanupAbort === ac) _cleanupAbort = null;
        }
      }
      if (newTaskId) console.log(`[ActiveTask] Now: ${newTaskId}`);
    },
    get() { return _activeTaskId; },
  };
})();

// ── Router ───────────────────────────────────────────────
(function() {
  function getRoute() {
    const path = window.location.pathname;
    const match = path.match(/^\/task\/(.+)/);
    if (match) return { page: 'task', taskId: match[1] };
    return { page: 'home' };
  }

  function navigate(path) {
    if (window.location.pathname === path) return;
    history.pushState(null, '', path);
    renderPage();
  }

  async function renderPage() {
    const route = getRoute();
    const main = document.getElementById('main');
    if (!main) return;

    if (route.page === 'task') {
      ZF.activeTask.set(route.taskId);
      main.innerHTML = '<div class="loading-state">Loading...</div>';
      ZF.taskDetail.render(main, route.taskId);
    } else {
      ZF.taskDetail.clearRenderGuard();
      main.innerHTML = '';
      ZF.home.render(main);
    }
  }

  window.addEventListener('popstate', renderPage);

  window.ZF.router = { navigate, getRoute, renderPage };
})();

// ── Home Page ────────────────────────────────────────────
(function() {
  window.ZF.home = {
    render(container) {
      const html = `
        <div class="home-page">
          <span class="home-subtitle">What do you have in mind?</span>
          <div class="home-workflow-selector">
            <button class="workflow-chip active">${ZF.icons.workflow(14)} <span>Full SDD workflow</span></button>
          </div>
          <h1 class="home-title">Full Spec-Driven Development</h1>
          <p class="home-description">For bigger features and improvements. The agent asks questions, generates PRD and tech spec documents, plans implementation, and auto-reviews code while generated.</p>
          <button class="home-start-btn" id="home-start-btn">
            <span>Start</span> ${ZF.icons.chevronRight(20)}
          </button>
          <div class="home-steps">
            <div class="home-step">
              <div class="home-step-circle">1</div>
              <div class="home-step-line"></div>
              <span class="home-step-label">Gather requirements and create PRD</span>
            </div>
            <div class="home-step">
              <div class="home-step-circle">2</div>
              <div class="home-step-line"></div>
              <span class="home-step-label">Prepare the technical specification</span>
            </div>
            <div class="home-step">
              <div class="home-step-circle">3</div>
              <div class="home-step-line"></div>
              <span class="home-step-label">Break down the work into steps</span>
            </div>
            <div class="home-step">
              <div class="home-step-circle">4</div>
              <span class="home-step-label">Implement with AI code review</span>
            </div>
          </div>
        </div>
      `;
      container.innerHTML = html;
      document.getElementById('home-start-btn')?.addEventListener('click', () => {
        ZF.newTaskModal.open();
      });
    }
  };
})();

// ── Sidebar ──────────────────────────────────────────────
(function() {
  let _projects = [];
  let _tasks = [];
  let _projectsOpen = false;
  let _openMenuId = null;
  let _selectMode = false;
  let _selectedIds = new Set();
  let _confirmDelete = null;

  async function fetchData() {
    try {
      const [projects, tasks] = await Promise.all([
        ZF.api.getProjects(),
        ZF.api.getTasks(),
      ]);
      _projects = projects;
      _tasks = tasks;
    } catch(e) { console.error('Sidebar fetch error:', e); }
  }

  function renderSidebar() {
    const el = document.getElementById('sidebar');
    if (!el) return;
    const route = ZF.router.getRoute();
    const activeTaskId = route.page === 'task' ? route.taskId : null;

    let html = '';

    // Projects header
    html += `<div class="sidebar-header">
      <button class="sidebar-projects-toggle" style="display:flex;align-items:center;justify-content:space-between;width:100%;padding:8px 0;font-size:14px;font-weight:500;color:var(--color-text-primary);">
        <span style="display:flex;align-items:center;gap:8px;">${ZF.icons.folder(16)} All projects</span>
        <span style="transition:transform 200ms;${_projectsOpen ? 'transform:rotate(180deg)' : ''}">${ZF.icons.chevronDown(16)}</span>
      </button>`;

    if (_projectsOpen) {
      html += '<div style="margin-top:8px;">';
      if (_projects.length === 0) {
        html += '<div style="font-size:12px;padding:4px 8px;color:var(--color-text-tertiary);">No projects</div>';
      }
      _projects.forEach(p => {
        html += `<div class="task-item" style="padding:6px 8px;flex-direction:row;align-items:center;gap:8px;font-size:13px;color:var(--color-text-secondary);">
          ${ZF.icons.folder(12)} <span class="truncate" style="flex:1;">${esc(p.name)}</span>
        </div>`;
      });
      html += '</div>';
    }
    html += '</div>';

    // Separator
    html += '<div class="sidebar-separator"></div>';

    // Action buttons
    html += '<div class="sidebar-actions">';
    if (_selectMode) {
      html += `<button class="btn-cancel-select" data-action="cancel-select">${ZF.icons.x(15)} Cancel</button>`;
      const count = _selectedIds.size;
      const cls = count > 0 ? 'enabled' : 'disabled';
      html += `<button class="btn-delete-selected ${cls}" data-action="delete-selected">${ZF.icons.trash(15)} Delete (${count})</button>`;
    } else {
      html += `<button class="btn-filled" data-action="new-task">${ZF.icons.plus(15)} New task</button>`;
      html += `<button class="btn-ghost-border" data-action="manage">Manage</button>`;
    }
    html += '</div>';

    // Task list
    html += '<div class="sidebar-task-list">';
    html += `<div class="sidebar-task-list-header">
      <span class="sidebar-task-list-label">Recent Tasks</span>`;
    if (_selectMode && _tasks.length > 0) {
      const allSelected = _selectedIds.size === _tasks.length;
      html += `<button data-action="select-all" style="font-size:11px;font-weight:500;color:var(--color-accent);">${allSelected ? 'Deselect all' : 'Select all'}</button>`;
    }
    html += '</div>';

    _tasks.forEach(task => {
      if (_selectMode) {
        const sel = _selectedIds.has(task.id);
        html += `<div class="task-item-select ${sel ? 'selected' : ''}" data-task-id="${task.id}" data-action="toggle-select">
          <div style="margin-top:2px;flex-shrink:0;">${sel ? ZF.icons.checkSquare(18) : ZF.icons.square(18)}</div>
          <div style="flex:1;min-width:0;display:flex;flex-direction:column;gap:6px;">
            <span class="task-item-title truncate">${esc(task.title)}</span>
            <div class="task-item-meta">
              <span class="task-item-project">${ZF.icons.folder(11)} <span class="truncate">${esc(task.projectName)}</span></span>
              ${ZF.statusPill(task.status)}
            </div>
          </div>
        </div>`;
      } else {
        const isActive = activeTaskId === task.id;
        html += `<div class="task-item ${isActive ? 'active' : ''}" data-task-id="${task.id}" data-action="nav-task">
          <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;">
            <span class="task-item-title truncate">${esc(task.title)}</span>
            <button class="task-item-menu-btn" data-action="task-menu" data-task-id="${task.id}">${ZF.icons.more(14)}</button>
          </div>
          <div class="task-item-meta">
            <span class="task-item-project">${ZF.icons.folder(11)} <span class="truncate">${esc(task.projectName)}</span></span>
            <div style="display:flex;align-items:center;gap:6px;">
              ${task.status === 'Paused' ? `<button class="task-resume-btn" data-action="resume-task" data-task-id="${task.id}">${ZF.icons.play(12)}</button>` : ''}
              ${ZF.statusPill(task.status)}
            </div>
          </div>
        </div>`;
      }
    });
    html += '</div>';

    // Footer
    html += `<div class="sidebar-footer">
      <div class="sidebar-separator"></div>
      <div class="sidebar-footer-links">
        <button class="sidebar-footer-link">${ZF.icons.settings(16)} Settings</button>
        <button class="sidebar-footer-link">${ZF.icons.feedback(16)} Feedback</button>
      </div>
      <div class="sidebar-separator" style="margin:4px 16px;"></div>
      <div class="sidebar-user">
        <div class="sidebar-avatar">SA</div>
        <div>
          <div class="sidebar-user-name">Shane Anderson</div>
          <div class="sidebar-user-plan">Pro Plan</div>
        </div>
      </div>
    </div>`;

    el.innerHTML = html;
    // Bind event listener only once (on first render)
    if (!el._sidebarBound) {
      el._sidebarBound = true;
      bindSidebarEvents(el);
    }
  }

  // Show a custom delete confirmation modal.  Returns a Promise<boolean>.
  function showDeleteModal(count) {
    return new Promise(resolve => {
      const overlay = document.createElement('div');
      overlay.className = 'modal-overlay';
      overlay.innerHTML = `
        <div class="modal-confirm">
          <h3>Delete ${count === 1 ? 'task' : count + ' tasks'}?</h3>
          <p class="text-muted">This will permanently remove the ${count === 1 ? 'task' : 'selected tasks'} and all associated files. This cannot be undone.</p>
          <div class="modal-actions">
            <button class="btn-ghost-border" data-modal="cancel">Cancel</button>
            <button class="btn-filled" style="background:#dc2626;border-color:#dc2626;" data-modal="confirm">Delete</button>
          </div>
        </div>`;
      document.body.appendChild(overlay);
      overlay.addEventListener('click', (e) => {
        const btn = e.target.closest('[data-modal]');
        if (!btn) return;
        overlay.remove();
        resolve(btn.dataset.modal === 'confirm');
      });
      // Close on backdrop click
      overlay.addEventListener('click', (e) => {
        if (e.target === overlay) { overlay.remove(); resolve(false); }
      });
    });
  }

  function bindSidebarEvents(el) {
    el.addEventListener('click', async (e) => {
      const btn = e.target.closest('[data-action]');
      if (!btn) {
        // Projects toggle
        if (e.target.closest('.sidebar-projects-toggle')) {
          _projectsOpen = !_projectsOpen;
          renderSidebar();
        }
        return;
      }
      const action = btn.dataset.action;
      const taskId = btn.dataset.taskId;

      switch(action) {
        case 'new-task':
          ZF.newTaskModal.open();
          break;
        case 'manage':
          _selectMode = true;
          _selectedIds = new Set();
          renderSidebar();
          break;
        case 'cancel-select':
          _selectMode = false;
          _selectedIds = new Set();
          renderSidebar();
          break;
        case 'select-all':
          if (_selectedIds.size === _tasks.length) {
            _selectedIds = new Set();
          } else {
            _selectedIds = new Set(_tasks.map(t => t.id));
          }
          renderSidebar();
          break;
        case 'toggle-select':
          if (_selectedIds.has(taskId)) _selectedIds.delete(taskId);
          else _selectedIds.add(taskId);
          renderSidebar();
          break;
        case 'delete-selected':
          if (_selectedIds.size === 0) return;
          showDeleteModal(_selectedIds.size).then(confirmed => {
            if (!confirmed) return;
            const ids = Array.from(_selectedIds);
            _tasks = _tasks.filter(t => !ids.includes(t.id));
            _selectMode = false;
            _selectedIds = new Set();
            renderSidebar();
            ZF.api.batchDeleteTasks(ids).catch(e => console.error(e));
            const route = ZF.router.getRoute();
            if (route.page === 'task' && ids.includes(route.taskId)) {
              ZF.router.navigate('/');
            }
          });
          break;
        case 'nav-task':
          e.preventDefault();
          ZF.router.navigate(`/task/${taskId}`);
          break;
        case 'resume-task':
          e.stopPropagation();
          ZF.api.updateTask(taskId, { status: 'In Progress' }).catch(() => {});
          const t = _tasks.find(t => t.id === taskId);
          if (t) t.status = 'In Progress';
          renderSidebar();
          ZF.router.navigate(`/task/${taskId}`);
          break;
        case 'task-menu':
          e.stopPropagation();
          showDeleteModal(1).then(confirmed => {
            if (!confirmed) return;
            _tasks = _tasks.filter(t => t.id !== taskId);
            renderSidebar();
            ZF.api.deleteTask(taskId).catch(e => console.error(e));
            const route = ZF.router.getRoute();
            if (route.page === 'task' && route.taskId === taskId) {
              ZF.router.navigate('/');
            }
          });
          break;
      }
    });
  }

  // Escape HTML
  function esc(s) {
    const d = document.createElement('div');
    d.textContent = s || '';
    return d.innerHTML;
  }
  window.ZF._esc = esc;

  // Status pill helper
  window.ZF.statusPill = function(status) {
    const statusMap = {
      'action required': 'action_required', 'in review': 'in_review',
      'to do': 'todo', 'in progress': 'in_progress',
      'done': 'done', 'paused': 'paused', 'cancelled': 'cancelled',
    };
    const labels = {
      action_required: 'Action required', in_review: 'In Review',
      todo: 'To Do', in_progress: 'In Progress',
      done: 'Done', paused: 'Paused', cancelled: 'Cancelled',
      completed: 'Completed', failed: 'Failed',
    };
    const lower = (status || '').toLowerCase().replace(' ', '_');
    let key = 'todo';
    if (lower.includes('cancel')) key = 'cancelled';
    else if (lower.includes('pause')) key = 'paused';
    else if (lower.includes('fail')) key = 'failed';
    else if (lower.includes('action')) key = 'action_required';
    else if (lower.includes('review')) key = 'in_review';
    else if (lower.includes('progress')) key = 'in_progress';
    else if (lower.includes('complete') || lower.includes('done') || lower.includes('success')) key = 'completed';
    return `<span class="status-pill status-${key}">${labels[key] || status}</span>`;
  };

  window.ZF.sidebar = {
    async init() {
      await fetchData();
      renderSidebar();
    },
    refresh() {
      fetchData().then(renderSidebar);
    },
    render: renderSidebar,
  };
})();

// ── LLM Status Banner ────────────────────────────────────
(function() {
  let _bannerEl = null;
  let _pollTimer = null;

  function createBanner() {
    if (_bannerEl) return _bannerEl;
    _bannerEl = document.createElement('div');
    _bannerEl.className = 'llm-status-banner';
    _bannerEl.innerHTML = `
      <span class="llm-banner-icon">${ZF.icons.warning ? ZF.icons.warning(18) : '⚠'}</span>
      <span class="llm-banner-text">LM Studio is not reachable. Steps cannot start until the connection is restored.</span>
      <button class="llm-banner-retry">Retry Connection</button>
      <button class="llm-banner-dismiss">&times;</button>
    `;
    _bannerEl.querySelector('.llm-banner-retry').addEventListener('click', () => retry());
    _bannerEl.querySelector('.llm-banner-dismiss').addEventListener('click', () => dismiss());
    document.body.prepend(_bannerEl);
    // Disable step start buttons
    document.querySelectorAll('[data-start-step]').forEach(btn => btn.disabled = true);
    return _bannerEl;
  }

  function show(errorMsg) {
    const banner = createBanner();
    if (errorMsg) {
      banner.querySelector('.llm-banner-text').textContent =
        `LM Studio is not reachable: ${errorMsg}. Steps cannot start until the connection is restored.`;
    }
    banner.style.display = 'flex';
    document.querySelectorAll('[data-start-step]').forEach(btn => btn.disabled = true);
  }

  function dismiss() {
    if (_bannerEl) _bannerEl.style.display = 'none';
    document.querySelectorAll('[data-start-step]').forEach(btn => btn.disabled = false);
  }

  async function retry() {
    const retryBtn = _bannerEl?.querySelector('.llm-banner-retry');
    if (retryBtn) { retryBtn.textContent = 'Checking...'; retryBtn.disabled = true; }
    try {
      const status = await ZF.api.getLlmStatus();
      if (status.connected) {
        dismiss();
      } else {
        show(status.error || 'Connection failed');
      }
    } catch (e) {
      show('Network error');
    } finally {
      if (retryBtn) { retryBtn.textContent = 'Retry Connection'; retryBtn.disabled = false; }
    }
  }

  async function checkOnLoad() {
    try {
      const status = await ZF.api.getLlmStatus();
      if (!status.connected) {
        show(status.error || 'Not connected');
      }
    } catch (e) {
      // Don't show banner on network errors during initial load — server might still be starting
    }
  }

  window.ZF.llmBanner = { show, dismiss, retry, check: checkOnLoad };
})();

// ── Init ─────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  await ZF.sidebar.init();
  ZF.router.renderPage();
  // Check LLM connectivity on page load
  ZF.llmBanner.check();
});
