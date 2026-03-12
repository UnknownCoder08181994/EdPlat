// ── Files Tab ────────────────────────────────────────────
window.ZF = window.ZF || {};

(function() {
  function getFileIcon(filename) {
    const ext = filename.includes('.') ? filename.split('.').pop().toLowerCase() : '';
    switch(ext) {
      case 'py': return { icon: 'fileCode', color: 'color:rgb(56,189,248);' };
      case 'js': case 'jsx': case 'ts': case 'tsx':
      case 'html': case 'htm': case 'css': case 'scss':
        return { icon: 'fileCode', color: '' };
      case 'json': case 'yaml': case 'yml': case 'toml': case 'ini': case 'cfg':
        return { icon: 'settings', color: '' };
      case 'md': case 'mdx': case 'txt': case 'log':
        return { icon: 'fileText', color: '' };
      case 'png': case 'jpg': case 'jpeg': case 'gif': case 'svg': case 'ico':
        return { icon: 'image', color: '' };
      case 'sh': case 'bash': case 'bat': case 'ps1':
        return { icon: 'hash', color: '' };
      default: return { icon: 'file', color: '' };
    }
  }

  function collectDirs(node, paths) {
    if (node.type === 'directory') {
      if (!node.shallow) paths.add(node.path);
      if (node.children) node.children.forEach(c => collectDirs(c, paths));
    }
  }
  function countFiles(node) {
    if (node.type === 'file') return 1;
    return (node.children || []).reduce((s, c) => s + countFiles(c), 0);
  }
  function collectAllFiles(node, results) {
    if (node.type === 'file') results.push({ name: node.name, path: node.path });
    if (node.children) node.children.forEach(c => collectAllFiles(c, results));
  }

  function createFilesTab(taskId, opts) {
    const onFileOpen = opts?.onFileOpen || (() => {});
    let tree = null;
    let expanded = new Set(['.']);
    let selectedFile = null;
    let searchQuery = '';

    const container = document.createElement('div');
    container.className = 'files-tab';

    async function loadTree() {
      try {
        const result = await ZF.api.getFileTree(taskId);
        tree = result;
        const allPaths = new Set(['.']);
        if (result.children) result.children.forEach(c => collectDirs(c, allPaths));
        expanded = allPaths;
        render();
      } catch(e) { console.error('File tree error:', e); }
    }

    function setSelected(path) {
      selectedFile = path;
      render();
    }

    function renderTreeNode(node, depth) {
      const indent = depth * 18;
      if (node.type === 'directory') {
        const isExp = expanded.has(node.path);
        const count = node.children?.length ?? 0;
        let html = `<div class="tree-node tree-node-dir" style="padding-left:${indent+4}px;" data-path="${ZF._escHtml(node.path)}" data-type="dir">
          <span class="tree-node-chevron">${isExp ? ZF.icons.chevronDown(16) : ZF.icons.chevronRight(16)}</span>
          <span class="tree-node-icon-dir ${isExp?'open':''}">${isExp ? ZF.icons.folderOpen(18) : ZF.icons.folder(18)}</span>
          <span class="tree-node-name">${ZF._escHtml(node.name)}</span>
          ${count > 0 ? `<span class="tree-node-count">${count}</span>` : ''}
        </div>`;
        if (isExp && node.children) {
          node.children.forEach(c => { html += renderTreeNode(c, depth + 1); });
          if (node.children.length === 0 && node.shallow) {
            html += `<div class="tree-node-empty" style="padding-left:${indent+56}px;color:var(--color-text-tertiary);font-style:italic;">Contents hidden</div>`;
          } else if (node.children.length === 0) {
            html += `<div class="tree-node-empty" style="padding-left:${indent+56}px;">Empty</div>`;
          }
        }
        return html;
      }
      // File
      const { icon, color } = getFileIcon(node.name);
      const isSel = selectedFile === node.path;
      return `<div class="tree-node tree-node-file ${isSel?'selected':''}" style="padding-left:${indent+22}px;${color}" data-path="${ZF._escHtml(node.path)}" data-type="file">
        <span style="${color}">${ZF.icons[icon](16)}</span>
        <span class="tree-node-name truncate">${ZF._escHtml(node.name)}</span>
        ${isSel ? '<span class="tree-node-dot"></span>' : ''}
      </div>`;
    }

    function render() {
      const isSearching = searchQuery.trim().length > 0;

      let html = `<div class="files-tab-inner">
        <div class="files-header">
          <div class="files-header-row">
            <span class="files-header-label">Project Structure</span>
          </div>
          <div class="files-search">
            <span class="files-search-icon">${ZF.icons.search(15)}</span>
            <input type="text" placeholder="Search files..." value="${ZF._escHtml(searchQuery)}">
            ${searchQuery ? `<button class="files-search-clear">${ZF.icons.x(14)}</button>` : ''}
          </div>
        </div>`;

      if (isSearching) {
        const allFiles = [];
        if (tree) collectAllFiles(tree, allFiles);
        const q = searchQuery.toLowerCase();
        const results = allFiles.filter(f => f.name.toLowerCase().includes(q) || f.path.toLowerCase().includes(q));
        html += '<div class="files-search-results">';
        if (results.length > 0) {
          results.forEach(f => {
            const { icon, color } = getFileIcon(f.name);
            const isSel = selectedFile === f.path;
            html += `<div class="files-search-result ${isSel?'selected':''}" data-path="${ZF._escHtml(f.path)}" data-type="file">
              <span style="${color}">${ZF.icons[icon](16)}</span>
              <div class="files-search-result-info">
                <span class="files-search-result-name truncate">${ZF._escHtml(f.name)}</span>
                <span class="files-search-result-path truncate">${ZF._escHtml(f.path)}</span>
              </div>
              ${isSel ? '<span class="tree-node-dot"></span>' : ''}
            </div>`;
          });
        } else {
          html += `<div class="files-search-empty">No files matching "${ZF._escHtml(searchQuery)}"</div>`;
        }
        html += '</div>';
      } else {
        html += '<div class="file-tree">';
        if (tree && tree.children && tree.children.length > 0) {
          tree.children.forEach(n => { html += renderTreeNode(n, 0); });
        } else {
          html += `<div class="files-empty">
            ${ZF.icons.folder(40)}
            <span class="files-empty-title">No files in workspace yet</span>
            <span class="files-empty-subtitle">Files will appear here as the agent creates them</span>
          </div>`;
        }
        html += '</div>';
      }

      html += '</div>';
      container.innerHTML = html;

      // Bind events
      container.querySelectorAll('[data-type="dir"]').forEach(el => {
        el.addEventListener('click', () => {
          const p = el.dataset.path;
          if (expanded.has(p)) expanded.delete(p); else expanded.add(p);
          render();
        });
      });
      container.querySelectorAll('[data-type="file"]').forEach(el => {
        el.addEventListener('click', () => {
          const p = el.dataset.path;
          selectedFile = p;
          render();
          onFileOpen(p);
        });
      });
      container.querySelector('.files-search input')?.addEventListener('input', (e) => {
        searchQuery = e.target.value;
        render();
      });
      container.querySelector('.files-search-clear')?.addEventListener('click', () => {
        searchQuery = '';
        render();
      });
    }

    loadTree();
    return { element: container, refresh: loadTree, setSelected };
  }

  window.ZF.files = { createFilesTab, getFileIcon };
})();
