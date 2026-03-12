// ── Code Block Renderer ──────────────────────────────────
window.ZF = window.ZF || {};

(function() {
  const EXT_TO_LANG = {
    '.py': 'python', '.js': 'javascript', '.ts': 'typescript',
    '.tsx': 'typescript', '.jsx': 'javascript', '.json': 'json',
    '.html': 'html', '.htm': 'html', '.xml': 'xml', '.css': 'css',
    '.md': 'markdown', '.yaml': 'yaml', '.yml': 'yaml',
    '.sh': 'bash', '.bash': 'bash', '.bat': 'bash',
    '.sql': 'sql', '.ini': 'ini', '.cfg': 'ini', '.toml': 'ini',
    '.txt': '',
  };

  function langFromFilename(filename) {
    if (!filename || !filename.includes('.')) return '';
    const ext = '.' + filename.split('.').pop().toLowerCase();
    return EXT_TO_LANG[ext] || '';
  }

  function highlight(code, lang) {
    if (!window.hljs) return null;
    try {
      if (lang && hljs.getLanguage(lang)) {
        return hljs.highlight(code, { language: lang }).value;
      }
      return hljs.highlightAuto(code).value;
    } catch { return null; }
  }

  window.ZF.codeblock = {
    langFromFilename,
    highlight,
    render(code, language, filename) {
      const label = filename || language || 'code';
      const highlighted = highlight(code, language || (filename ? langFromFilename(filename) : ''));
      const id = 'cb-' + Math.random().toString(36).slice(2, 8);
      return `<div class="code-block">
        <div class="code-block-header">
          <span>${ZF._escHtml(label)}</span>
          <button class="code-block-copy" data-copy-id="${id}">Copy code</button>
        </div>
        <pre><code id="${id}">${highlighted || ZF._escHtml(code)}</code></pre>
      </div>`;
    },
  };

  // Global click handler for copy buttons
  document.addEventListener('click', (e) => {
    const btn = e.target.closest('.code-block-copy');
    if (!btn) return;
    const id = btn.dataset.copyId;
    const el = document.getElementById(id);
    if (!el) return;
    navigator.clipboard.writeText(el.textContent).then(() => {
      btn.textContent = '\u2713 Copied';
      setTimeout(() => btn.textContent = 'Copy code', 2000);
    });
  });
})();
