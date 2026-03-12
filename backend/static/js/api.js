// ── API Client ───────────────────────────────────────────
window.ZF = window.ZF || {};

window.ZF.api = {
  async getProjects() {
    const res = await fetch('/api/projects');
    if (!res.ok) throw new Error('Failed to fetch projects');
    return res.json();
  },

  async createProject(name, path) {
    const res = await fetch('/api/projects', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, path }),
    });
    if (!res.ok) throw new Error('Failed to create project');
    return res.json();
  },

  async getTasks(projectId) {
    const url = projectId ? `/api/tasks?projectId=${projectId}` : '/api/tasks';
    const res = await fetch(url);
    if (!res.ok) throw new Error('Failed to fetch tasks');
    return res.json();
  },

  async getTask(taskId) {
    const res = await fetch(`/api/tasks/${taskId}`);
    if (!res.ok) throw new Error('Failed to fetch task');
    return res.json();
  },

  async createTask(data) {
    const res = await fetch('/api/tasks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!res.ok) {
      const errorData = await res.json().catch(() => ({}));
      throw new Error(errorData.error || 'Failed to create task');
    }
    return res.json();
  },

  async getChats(taskId) {
    const res = await fetch(`/api/tasks/${taskId}/chats`);
    if (!res.ok) return [];
    return res.json();
  },

  async createChat(taskId) {
    const res = await fetch(`/api/tasks/${taskId}/chats`, { method: 'POST' });
    if (!res.ok) throw new Error('Failed to create chat');
    return res.json();
  },

  getChatStreamUrl(taskId, chatId, message) {
    return `/api/chats/${chatId}/stream?taskId=${taskId}&message=${encodeURIComponent(message)}`;
  },

  async getFiles(taskId, path = '.') {
    const res = await fetch(`/api/tasks/${taskId}/files?path=${encodeURIComponent(path)}`);
    if (!res.ok) throw new Error('Failed to fetch files');
    return res.json();
  },

  async getFileTree(taskId) {
    const res = await fetch(`/api/tasks/${taskId}/file-tree`);
    if (!res.ok) throw new Error('Failed to fetch file tree');
    return res.json();
  },

  async readFile(taskId, path) {
    const res = await fetch(`/api/tasks/${taskId}/file?path=${encodeURIComponent(path)}`);
    if (!res.ok) throw new Error('Failed to read file');
    return res.json();
  },

  async writeFile(taskId, path, content) {
    const res = await fetch(`/api/tasks/${taskId}/file`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path, content }),
    });
    if (!res.ok) throw new Error('Failed to write file');
  },

  async startStep(taskId, stepId) {
    const res = await fetch(`/api/tasks/${taskId}/steps/${stepId}/start`, { method: 'POST' });
    if (!res.ok) {
      const errorData = await res.json().catch(() => ({}));
      throw new Error(errorData.error || 'Failed to start step');
    }
    return res.json();
  },

  async updateStep(taskId, stepId, data) {
    const res = await fetch(`/api/tasks/${taskId}/steps/${stepId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!res.ok) throw new Error('Failed to update step');
    return res.json();
  },

  async updateTask(taskId, data) {
    const res = await fetch(`/api/tasks/${taskId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!res.ok) throw new Error('Failed to update task');
    return res.json();
  },

  async pauseTask(taskId) {
    await fetch(`/api/tasks/${taskId}/pause`, { method: 'POST' });
  },

  async cancelChat(chatId) {
    await fetch(`/api/chats/${chatId}/cancel`, { method: 'POST' });
  },

  getReviewStreamUrl(taskId, chatId, prompt) {
    return `/api/chats/${chatId}/review?taskId=${taskId}&prompt=${encodeURIComponent(prompt)}`;
  },

  async cancelReview(chatId) {
    await fetch(`/api/chats/${chatId}/cancel-review`, { method: 'POST' });
  },

  async applyReviewEdits(chatId, taskId, editedPaths, editDetails) {
    const res = await fetch(`/api/chats/${chatId}/apply-review-edits`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ taskId, editedPaths, editDetails: editDetails || [] }),
    });
    return res.json();
  },

  async cancelAllTaskChats(taskId) {
    const res = await fetch(`/api/tasks/${taskId}/cancel-all`, { method: 'POST' });
    const ct = res.headers.get('content-type') || '';
    if (!ct.includes('application/json')) {
      const text = await res.text();
      throw new Error(`Expected JSON but got ${ct}: ${text.slice(0, 300)}`);
    }
    return res.json();
  },

  async cancelGpu() {
    await fetch('/api/gpu/cancel', { method: 'POST' });
  },

  async deleteTask(taskId) {
    await fetch(`/api/tasks/${taskId}`, { method: 'DELETE' });
  },

  async deleteProject(projectId) {
    await fetch(`/api/projects/${projectId}`, { method: 'DELETE' });
  },

  async getLlmStatus() {
    const res = await fetch('/api/llm/status');
    if (!res.ok) return { connected: false, error: 'Failed to fetch LLM status' };
    return res.json();
  },

  async batchDeleteTasks(taskIds) {
    const res = await fetch('/api/tasks/batch-delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ taskIds }),
    });
    if (!res.ok) throw new Error('Failed to batch delete tasks');
    return res.json();
  },

  async runCommand(taskId, command, cwd) {
    const res = await fetch(`/api/tasks/${taskId}/command`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command, cwd }),
    });
    if (!res.ok) throw new Error('Failed to run command');
    return res.json();
  },

  async getEntryPoint(taskId) {
    const res = await fetch(`/api/tasks/${taskId}/entry-point`);
    if (!res.ok) throw new Error('Failed to detect entry point');
    return res.json();
  },

  async streamCommand(taskId, command, cwd, signal) {
    const res = await fetch(`/api/tasks/${taskId}/terminal/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command, cwd }),
      signal,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || 'Failed to start streaming command');
    }
    return res;
  },

  async killTerminal(sessionId) {
    const res = await fetch(`/api/terminal/${sessionId}/kill`, { method: 'POST' });
    if (!res.ok) throw new Error('Failed to kill terminal process');
    return res.json();
  },

  async reformatTask(details, complexity) {
    const res = await fetch('/api/reformat-task', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ details, complexity }),
    });
    if (!res.ok) {
      const errorData = await res.json().catch(() => ({}));
      throw new Error(errorData.error || 'Failed to reformat task');
    }
    return res.json();
  },

  async startExecution(taskId, signal) {
    const res = await fetch(`/api/tasks/${taskId}/execute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || 'Failed to start execution agent');
    }
    return res;
  },

  async cancelExecution(taskId) {
    const res = await fetch(`/api/tasks/${taskId}/execute/cancel`, { method: 'POST' });
    if (!res.ok) throw new Error('Failed to cancel execution');
    return res.json();
  },

  async generateRlReport(taskId) {
    const res = await fetch(`/api/tasks/${taskId}/rl-report`, { method: 'POST' });
    if (!res.ok) throw new Error('Failed to generate RL report');
    return res.json();
  },
};
