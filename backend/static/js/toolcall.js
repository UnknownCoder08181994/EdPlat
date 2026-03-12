// ── Tool Call Parser & Renderer ──────────────────────────
window.ZF = window.ZF || {};

(function() {
  const TOOL_SCHEMAS = {
    ListFiles: ['path'],
    ReadFile: ['path'],
    WriteFile: ['path', 'content'],
    EditFile: ['path', 'old_string', 'new_string'],
    Glob: ['pattern'],
    RunCommand: ['command', 'cwd'],
  };

  function sanitizeJson(raw) {
    let s = raw;
    s = s.replace(/"""([\s\S]*?)"""/g, (_, inner) => {
      inner = inner.replace(/\\/g, '\\\\').replace(/"/g, '\\"')
        .replace(/\n/g, '\\n').replace(/\r/g, '\\r').replace(/\t/g, '\\t');
      return `"${inner}"`;
    });
    s = fixControlChars(s);
    s = s.replace(/,\s*([}\]])/g, '$1');
    if (!s.includes('"') && s.includes("'")) s = s.replace(/'/g, '"');
    return s;
  }

  function fixControlChars(s) {
    const result = [];
    let inStr = false, i = 0;
    while (i < s.length) {
      const c = s[i];
      if (inStr) {
        if (c === '\\') { result.push(c); if (i+1 < s.length) result.push(s[i+1]); i += 2; continue; }
        if (c === '"') { inStr = false; result.push(c); }
        else if (c === '\n') result.push('\\n');
        else if (c === '\r') result.push('\\r');
        else if (c === '\t') result.push('\\t');
        else { const code = c.charCodeAt(0); result.push(code < 0x20 ? '\\u'+code.toString(16).padStart(4,'0') : c); }
      } else {
        if (c === '"') inStr = true;
        result.push(c);
      }
      i++;
    }
    return result.join('');
  }

  function extractFallback(raw) {
    const nameMatch = raw.match(/"name"\s*:\s*"(\w+)"/);
    if (!nameMatch) return null;
    const toolName = nameMatch[1];
    if (!(toolName in TOOL_SCHEMAS)) return null;
    const args = {};
    if (toolName === 'WriteFile') {
      const pathMatch = raw.match(/"path"\s*:\s*"([^"]*)"/);
      if (pathMatch) args.path = pathMatch[1];
      const contentStart = raw.match(/"content"\s*:\s*/);
      if (contentStart && contentStart.index !== undefined) {
        let rem = raw.slice(contentStart.index + contentStart[0].length);
        if (rem.startsWith('"""')) { rem = rem.slice(3); const end = rem.indexOf('"""'); args.content = end >= 0 ? rem.slice(0, end) : rem.replace(/[\s"]*}\s*}\s*$/, ''); }
        else if (rem.startsWith('"')) {
          rem = rem.slice(1);
          // Find the true end: last occurrence of "}} (possibly with whitespace)
          // Use lastIndexOf to skip over unescaped quotes inside HTML content
          let endIdx = -1;
          for (let i = rem.length - 1; i >= 0; i--) {
            if (rem[i] === '}') { const tail = rem.slice(i).trim(); if (/^\}\s*\}\s*$/.test(tail)) { endIdx = i; break; } }
          }
          if (endIdx > 0) {
            // Walk back from the closing braces to find the content-ending quote
            let quoteIdx = endIdx - 1;
            while (quoteIdx >= 0 && rem[quoteIdx] !== '"') quoteIdx--;
            let rc = quoteIdx > 0 ? rem.slice(0, quoteIdx) : rem.slice(0, endIdx);
            rc = rc.replace(/\\n/g,'\n').replace(/\\t/g,'\t').replace(/\\r/g,'\r').replace(/\\"/g,'"').replace(/\\\\/g,'\\');
            args.content = rc;
          } else {
            args.content = rem.replace(/[\s"]*}\s*}\s*$/, '');
          }
        }
        else args.content = rem.replace(/\s*}\s*}\s*$/, '');
      }
      if (!('path' in args)) return null;
    } else {
      for (const k of TOOL_SCHEMAS[toolName]) {
        const m = raw.match(new RegExp(`"${k}"\\s*:\\s*"([^"]*)"`));
        if (m) { let v = m[1].replace(/\\n/g,'\n').replace(/\\t/g,'\t').replace(/\\"/g,'"').replace(/\\\\/g,'\\'); args[k] = v; }
      }
      if (!(TOOL_SCHEMAS[toolName][0] in args)) return null;
    }
    return { name: toolName, arguments: args };
  }

  function parseToolCall(rawContent) {
    let jsonStr = rawContent.replace(/^<tool_code>\s*/, '').replace(/\s*<\/tool_code>\s*$/, '').trim();
    jsonStr = jsonStr.replace(/^```json\s*/, '').replace(/```$/, '').trim();
    try { const p = JSON.parse(jsonStr); if (p.name) return p; } catch {}
    try { const p = JSON.parse(sanitizeJson(jsonStr)); if (p.name) return p; } catch {}
    return extractFallback(jsonStr) || extractFallback(rawContent);
  }

  function parsePartialToolCall(partialBlock) {
    const text = partialBlock.trim().replace(/^```json\s*/, '').replace(/^```\s*/, '');
    const nameMatch = text.match(/"name"\s*:\s*"(\w+)"/);
    if (!nameMatch) return null;
    const toolName = nameMatch[1];
    const pathMatch = text.match(/"path"\s*:\s*"([^"]*)"/);
    const path = pathMatch ? pathMatch[1] : null;
    let partialContent = null;
    if (toolName === 'WriteFile') {
      const cs = text.match(/"content"\s*:\s*/);
      if (cs && cs.index !== undefined) {
        let rem = text.slice(cs.index + cs[0].length);
        if (rem.startsWith('"""')) { rem = rem.slice(3); const end = rem.indexOf('"""'); partialContent = end >= 0 ? rem.slice(0, end) : rem; }
        else if (rem.startsWith('"')) { rem = rem.slice(1); partialContent = rem.replace(/\\n/g,'\n').replace(/\\t/g,'\t').replace(/\\r/g,'\r').replace(/\\"/g,'"').replace(/\\\\/g,'\\'); }
      }
    }
    if (toolName === 'EditFile') {
      const osm = text.match(/"old_string"\s*:\s*"([^"]*)"/);
      const nsm = text.match(/"new_string"\s*:\s*"([^"]*)"/);
      if (osm || nsm) {
        const oldStr = osm ? osm[1].replace(/\\n/g,'\n').replace(/\\t/g,'\t').replace(/\\"/g,'"') : '';
        const newStr = nsm ? nsm[1].replace(/\\n/g,'\n').replace(/\\t/g,'\t').replace(/\\"/g,'"') : '';
        partialContent = `--- old ---\n${oldStr}\n--- new ---\n${newStr}`;
      }
    }
    if (toolName === 'RunCommand') { const m = text.match(/"command"\s*:\s*"([^"]*)"/); if (m) partialContent = m[1]; }
    return { toolName, path, partialContent };
  }

  // Render a completed tool call card
  function renderToolCard(tool, args, resultText) {
    const isWrite = tool === 'WriteFile' && args?.path && args?.content;
    const isEdit = tool === 'EditFile' && args?.path;
    const isRead = tool === 'ReadFile' && args?.path;
    const label = isWrite ? `WriteFile \u2192 ${args.path}`
                 : isEdit ? `EditFile \u2192 ${args.path}`
                 : isRead ? `ReadFile \u2192 ${args.path}` : tool;
    const id = 'tc-' + Math.random().toString(36).slice(2, 8);
    let bodyHtml = '';
    if (isWrite) {
      let writeContent = args.content || '';
      // Safety: unescape any remaining literal \n sequences that survived parsing
      if (typeof writeContent === 'string' && writeContent.includes('\\n')) {
        writeContent = writeContent.replace(/\\n/g, '\n').replace(/\\t/g, '\t').replace(/\\r/g, '\r');
      }
      bodyHtml = ZF.codeblock.render(writeContent, ZF.codeblock.langFromFilename(args.path), args.path);
    } else if (isEdit) {
      const lang = ZF.codeblock.langFromFilename(args.path);
      bodyHtml = `<div class="edit-file-diff">` +
        `<div class="edit-file-section edit-file-old">` +
        `<div class="edit-file-label">\u2212 Old</div>` +
        ZF.codeblock.render(args.old_string || '', lang) +
        `</div>` +
        `<div class="edit-file-section edit-file-new">` +
        `<div class="edit-file-label">+ New</div>` +
        ZF.codeblock.render(args.new_string || '', lang) +
        `</div></div>`;
    } else {
      bodyHtml = `<div class="tool-card-json"><div class="tool-card-json-label">ARGS</div><pre>${ZF._escHtml(JSON.stringify(args, null, 2))}</pre></div>`;
    }
    if (resultText != null) {
      const displayResult = resultText || '(empty)';
      bodyHtml += `<div class="tool-card-result"><div class="tool-card-result-label">RESULT</div><pre>${ZF._escHtml(displayResult)}</pre></div>`;
    }
    return `<div class="tool-card" id="${id}">
      <div class="tool-card-header" onclick="this.parentElement.classList.toggle('open')">
        <span style="color:var(--color-text-tertiary);">${ZF.icons.chevronRight(14)}</span>
        <span class="tool-card-label">${ZF._escHtml(label)}</span>
        <span class="tool-card-badge">Tool Call</span>
      </div>
      <div class="tool-card-body" style="display:none;">${bodyHtml}</div>
    </div>`;
  }

  // Inject a tool result into an existing tool card in the DOM
  function injectResultIntoCard(cardEl, resultText) {
    const body = cardEl.querySelector('.tool-card-body');
    if (!body) return;
    // Remove any existing result section (idempotent)
    const existing = body.querySelector('.tool-card-result');
    if (existing) existing.remove();
    // Append result
    const div = document.createElement('div');
    div.className = 'tool-card-result';
    div.innerHTML = `<div class="tool-card-result-label">RESULT</div><pre>${ZF._escHtml(resultText)}</pre>`;
    body.appendChild(div);
    // Auto-expand the card if it was collapsed
    if (body.style.display === 'none') {
      body.style.display = 'block';
      const header = cardEl.querySelector('.tool-card-header');
      const chevron = header?.querySelector('span:first-child');
      if (chevron) chevron.innerHTML = ZF.icons.chevronDown(14);
    }
  }

  // Render streaming tool call card (always expanded)
  function renderStreamingToolCard(toolName, path, partialContent) {
    const label = (toolName === 'WriteFile' || toolName === 'EditFile') && path ? `${toolName} \u2192 ${path}` : toolName;
    let bodyHtml = '';
    if (toolName === 'WriteFile' && partialContent !== null) {
      bodyHtml = ZF.codeblock.render(partialContent, path ? ZF.codeblock.langFromFilename(path) : '', path || undefined);
    } else if (partialContent !== null) {
      bodyHtml = `<div class="tool-card-json"><pre>${ZF._escHtml(partialContent)}</pre></div>`;
    } else {
      bodyHtml = '<div class="tool-card-generating">Generating...</div>';
    }
    return `<div class="tool-card tool-card-streaming">
      <div class="tool-card-header">
        <span style="color:var(--color-text-tertiary);">${ZF.icons.chevronDown(14)}</span>
        <span class="tool-card-label">${ZF._escHtml(label)}</span>
        <span class="thinking-pulse" style="margin-left:4px;"></span>
        <span class="tool-card-badge">Tool Call</span>
      </div>
      <div class="tool-card-body" style="display:block;">${bodyHtml}</div>
    </div>`;
  }

  // Toggle handler for tool cards
  document.addEventListener('click', (e) => {
    const header = e.target.closest('.tool-card-header');
    if (!header) return;
    const card = header.closest('.tool-card');
    if (!card || card.classList.contains('tool-card-streaming')) return;
    const body = card.querySelector('.tool-card-body');
    if (!body) return;
    const isOpen = body.style.display !== 'none';
    body.style.display = isOpen ? 'none' : 'block';
    // Update chevron
    const chevron = header.querySelector('span:first-child');
    if (chevron) chevron.innerHTML = isOpen ? ZF.icons.chevronRight(14) : ZF.icons.chevronDown(14);
  });

  window.ZF.toolcall = { parseToolCall, parsePartialToolCall, renderToolCard, renderStreamingToolCard, injectResultIntoCard };
})();
