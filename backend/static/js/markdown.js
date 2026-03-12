// ── Markdown Renderer ────────────────────────────────────
window.ZF = window.ZF || {};

(function() {
  // Close incomplete markdown fences during streaming
  function closeIncomplete(text) {
    const fenceRegex = /^(`{3,})/gm;
    let count = 0, lastOpen = '';
    let m;
    while ((m = fenceRegex.exec(text)) !== null) {
      if (count % 2 === 0) lastOpen = m[1];
      count++;
    }
    if (count % 2 !== 0) text += '\n' + lastOpen;
    return text;
  }

  // Configure marked
  if (window.marked) {
    marked.setOptions({
      breaks: false,
      gfm: true,
      headerIds: false,
      mangle: false,
    });
  }

  window.ZF.markdown = {
    render(content) {
      if (!content || !content.trim()) return '';
      const sanitized = closeIncomplete(content);
      try {
        let html = marked.parse(sanitized);
        // Post-process: add classes
        html = html.replace(/<pre><code/g, '<pre class="code-raw"><code');
        // Wrap code blocks with our styled container
        html = html.replace(/<pre class="code-raw"><code class="language-(\w+)">([\s\S]*?)<\/code><\/pre>/g, (match, lang, code) => {
          return ZF.codeblock.render(decodeHtml(code), lang);
        });
        // Plain code blocks (no language)
        html = html.replace(/<pre class="code-raw"><code>([\s\S]*?)<\/code><\/pre>/g, (match, code) => {
          return ZF.codeblock.render(decodeHtml(code), '');
        });
        return `<div class="markdown-body">${html}</div>`;
      } catch(e) {
        console.error('Markdown render error:', e);
        return `<div class="markdown-body"><p>${escHtml(content)}</p></div>`;
      }
    },
  };

  function decodeHtml(html) {
    const txt = document.createElement('textarea');
    txt.innerHTML = html;
    return txt.value;
  }

  function escHtml(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }
  window.ZF._escHtml = escHtml;
})();
