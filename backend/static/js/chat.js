// ── Chat Engine ──────────────────────────────────────────
window.ZF = window.ZF || {};

(function() {
  // Module-level dedup guards (survive DOM rebuilds)
  const _kickoffFired = new Set();
  const _activeStreams = new Map();

  // Build step kickoff message.
  // NOTE: These are DISPLAY-ONLY messages shown in the chat UI. The actual detailed
  // instructions are in the system prompt built by agent_service.py on the backend.
  // Keep these SHORT — they should just tell the LLM to begin the step, not duplicate instructions.
  function buildKickoff(task, chatId) {
    const steps = task.steps || [];
    // Search top-level steps and children
    let step = null;
    for (const s of steps) {
      if (s.chatId === chatId) { step = s; break; }
      for (const c of (s.children || [])) {
        if (c.chatId === chatId) { step = c; break; }
      }
      if (step) break;
    }
    if (!step) return task.details || '';
    const id = step.id;
    if (id === 'requirements') return `Begin the REQUIREMENTS step.\n\nTask: ${task.details}`;
    if (id === 'technical-specification') return `Begin the TECHNICAL SPECIFICATION step.\n\nTask: ${task.details}`;
    if (id === 'planning') return `Begin the PLANNING step.\n\nTask: ${task.details}`;
    return `Begin working on step: "${step.name}".`;
  }

  // Strip GPT-OSS format tags and noise from visible text content
  function cleanGptOssTags(text) {
    if (!text) return text;
    return text
      .replace(/<\|[a-z_]+\|>[^<]*(?=<\|)/gi, '')   // tag+content between tags
      .replace(/<\|[a-z_]+\|>/gi, '')                  // remaining bare tags
      .replace(/<\/?tool_code>/gi, '')                  // stray <tool_code> / </tool_code> tags (any case)
      .replace(/commentary\s+to=\w+/gi, '')            // leftover "commentary to=ToolName"
      .replace(/json>/gi, '')                           // leftover "json>" from <|constrain|>json<|message|>
      .replace(/[\u00e2][\u0080-\u009f][\u0080-\u00bf]/g, '')  // mojibake triplets
      .replace(/^\s*\n/gm, '')                          // blank lines left by stripping
      .trim();
  }

  // Parse message content into segments (text + tool calls)
  function parseSegments(content, isStreaming) {
    let text = content.replace(/\[STEP_COMPLETE\]/g, '**Step Completed**').trim();
    let partialTool = null;
    let thinkingContent = null;

    // Extract <think>...</think> blocks (DeepSeek R1 reasoning)
    const thinkMatch = text.match(/<think>([\s\S]*?)<\/think>/);
    if (thinkMatch) {
      thinkingContent = thinkMatch[1].trim();
      text = text.replace(/<think>[\s\S]*?<\/think>\s*/g, '').trim();
    } else if (isStreaming && text.includes('<think>') && !text.includes('</think>')) {
      // Still streaming thinking — extract what we have so far
      const thinkStart = text.indexOf('<think>');
      thinkingContent = text.slice(thinkStart + '<think>'.length).trim();
      text = text.slice(0, thinkStart).trim();
    }

    // Normalize GPT-OSS <|channel|>...<|message|> format into <tool_code>...</tool_code>
    // During streaming, only convert COMPLETE blocks (followed by another <|channel|>),
    // leaving the last (potentially partial) block for the partial tool handler below.
    if (isStreaming) {
      // Only normalize blocks that are followed by another <|channel|> (i.e., completed)
      text = text.replace(/<\|channel\|>commentary\s+to=(\w+)\s*<\|constrain\|>json<\|message\|>([\s\S]*?)(?=<\|channel\|>)/g,
        (match, toolName, body) => {
          const trimmed = body.trim();
          if (trimmed.includes('"name"')) return '<tool_code>' + trimmed + '</tool_code>';
          return '<tool_code>{"name":"' + toolName + '","arguments":' + trimmed + '}</tool_code>';
        });
    } else {
      // Non-streaming: convert all blocks including the last one
      text = text.replace(/<\|channel\|>commentary\s+to=(\w+)\s*<\|constrain\|>json<\|message\|>([\s\S]*?)(?=<\|channel\|>|$)/g,
        (match, toolName, body) => {
          const trimmed = body.trim();
          if (trimmed.includes('"name"')) return '<tool_code>' + trimmed + '</tool_code>';
          return '<tool_code>{"name":"' + toolName + '","arguments":' + trimmed + '}</tool_code>';
        });
      // Clean up any remaining <|channel|>, <|constrain|>, <|message|> tags not caught by normalization
      text = text.replace(/<\|channel\|>[\s\S]*$/g, '');
    }

    if (isStreaming) {
      const lastOpen = text.lastIndexOf('<tool_code>');
      if (lastOpen !== -1 && text.indexOf('</tool_code>', lastOpen) === -1) {
        const partial = text.slice(lastOpen + '<tool_code>'.length);
        partialTool = ZF.toolcall.parsePartialToolCall(partial);
        text = text.slice(0, lastOpen);
      }
      // Also handle partial GPT-OSS format mid-stream
      // If there's a <|channel|> that wasn't normalized to <tool_code> (still incomplete),
      // extract partial tool info from it
      const channelIdx = text.lastIndexOf('<|channel|>');
      if (channelIdx !== -1 && text.indexOf('</tool_code>', channelIdx) === -1) {
        const channelTail = text.slice(channelIdx);
        // Try to extract tool name and partial content from GPT-OSS format
        const toolHint = channelTail.match(/to=(\w+)/);
        const msgStart = channelTail.indexOf('<|message|>');
        if (toolHint && msgStart !== -1) {
          const partial = channelTail.slice(msgStart + '<|message|>'.length);
          partialTool = ZF.toolcall.parsePartialToolCall(partial);
          if (!partialTool) {
            partialTool = { toolName: toolHint[1], path: null, partialContent: null };
          }
        } else if (toolHint) {
          // We have the tool name but no content yet
          partialTool = { toolName: toolHint[1], path: null, partialContent: null };
        }
        text = text.slice(0, channelIdx);
      }
    }

    // Rescue orphaned tool calls: json>{"name":"ToolName"...} left after partial tag stripping
    // Use greedy match with }}\s*$ to find the true end of a nested JSON object
    text = text.replace(/json>\s*(\{"name"\s*:\s*"(?:WriteFile|EditFile|ReadFile|ListFiles|RunCommand)"[\s\S]*\}\s*\})\s*/g,
      (match, body) => '<tool_code>' + body.trim() + '</tool_code>');

    // Rescue bare JSON tool calls (no json> prefix, no <tool_code> wrapper)
    // GPT-OSS sometimes outputs raw {"name":"WriteFile",...} without any wrapper
    if (!text.includes('<tool_code>') && /^\s*\{"name"\s*:\s*"(?:WriteFile|EditFile|ReadFile|ListFiles|RunCommand)"/.test(text)) {
      const jsonMatch = text.match(/(\{"name"\s*:\s*"(?:WriteFile|EditFile|ReadFile|ListFiles|RunCommand)"[\s\S]*\}\s*\})/);
      if (jsonMatch) {
        text = text.replace(jsonMatch[0], '<tool_code>' + jsonMatch[1].trim() + '</tool_code>');
      }
    }

    // Split on <tool_code>...</tool_code> blocks — tags inside blocks are preserved for parsing
    // cleanGptOssTags() handles any stray tags left in text segments
    const parts = text.split(/(<tool_code>[\s\S]*?<\/tool_code>)/g);
    const segments = [];
    let pendingText = '';

    parts.forEach(part => {
      if (part.startsWith('<tool_code>')) {
        const tc = ZF.toolcall.parseToolCall(part);
        if (tc) {
          if (pendingText.trim()) { segments.push({ type: 'text', content: cleanGptOssTags(pendingText.trim()) }); pendingText = ''; }
          segments.push({ type: 'tool', name: tc.name, args: tc.arguments });
        } else pendingText += part;
      } else if (part.trim()) {
        pendingText += (pendingText ? '\n\n' : '') + part;
      }
    });
    if (pendingText.trim()) {
      const cleaned = cleanGptOssTags(pendingText.trim());
      if (cleaned) segments.push({ type: 'text', content: cleaned });
    }

    return { segments, partialTool, thinkingContent };
  }

  // Build the artifact preview HTML (collapsible markdown section)
  function _buildArtifactPreview(name, renderedMd) {
    return `
      <div class="committed-artifact-preview">
        <div class="committed-artifact-toggle" onclick="(function(el){
          var card = el.closest('.committed-artifact-preview');
          var body = card.querySelector('.committed-artifact-body');
          var chevron = card.querySelector('.committed-artifact-chevron');
          card.classList.toggle('collapsed');
          body.style.display = card.classList.contains('collapsed') ? 'none' : '';
          chevron.style.transform = card.classList.contains('collapsed') ? '' : 'rotate(180deg)';
        })(this)">
          ${ZF.icons.fileText(14)}
          <span>${ZF._escHtml(name || 'Document')}</span>
          <svg class="committed-artifact-chevron" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="transform:rotate(180deg);"><polyline points="6 9 12 15 18 9"/></svg>
        </div>
        <div class="committed-artifact-body">
          <div class="markdown-body">${renderedMd}</div>
        </div>
      </div>`;
  }

  // Render a committed changes block (Sentinel-style file change summary)
  function renderCommittedChanges(s) {
    const totalFiles = s.totalFiles || s.files.length;
    const totalAdded = s.totalAdded || 0;
    const totalRemoved = s.totalRemoved || 0;

    let filesHtml = '';
    s.files.forEach(f => {
      let badge;
      if (f.isEdited) {
        badge = '<span class="committed-badge-edited">Edited</span>';
      } else if (f.isNew) {
        badge = '<span class="committed-badge-new">New</span>';
      } else {
        badge = `<span class="committed-badge-delta"><span class="committed-add">+${f.added}</span> <span class="committed-remove">&minus;${f.removed}</span></span>`;
      }
      const icon = f.isEdited ? ZF.icons.edit(14) : (f.isNew ? ZF.icons.file(14) : ZF.icons.edit(14));
      filesHtml += `<div class="committed-file">
        <span class="committed-file-icon">${icon}</span>
        <span class="committed-file-name">${ZF._escHtml(f.name)}</span>
        <span class="committed-file-path">${ZF._escHtml(f.path)}</span>
        <span class="committed-file-badge">${badge}</span>
      </div>`;
    });

    // Artifact preview for SDD steps (requirements.md, spec.md, implementation-plan.md)
    const SDD_ARTIFACTS = {'requirements.md': true, 'spec.md': true, 'implementation-plan.md': true};
    let artifactHtml = '';
    const artifactContent = s.artifactContent || null;
    // Detect SDD artifact from files list if artifactName not provided
    const artifactName = s.artifactName || (s.files || []).find(f => SDD_ARTIFACTS[f.name])?.name || null;

    if (artifactContent) {
      // Content available inline — render immediately
      artifactHtml = _buildArtifactPreview(artifactName, ZF.markdown.render(artifactContent));
    } else if (artifactName) {
      // SDD artifact but no content — render placeholder with lazy-load marker
      const sddFile = (s.files || []).find(f => f.name === artifactName);
      const artifactPath = sddFile ? (sddFile.path + sddFile.name) : artifactName;
      artifactHtml = `<div class="committed-artifact-preview" data-artifact-path="${ZF._escHtml(artifactPath)}" data-artifact-name="${ZF._escHtml(artifactName)}"></div>`;
    }

    return `<div class="committed-changes">
      <div class="committed-header">
        <span class="committed-header-label">${ZF.icons.commit(14)} Committed changes</span>
        <span class="committed-header-stats">
          <span class="committed-stat-files">${totalFiles} file${totalFiles !== 1 ? 's' : ''}</span>
          <span class="committed-add">+${totalAdded}</span>
          <span class="committed-remove">&minus;${totalRemoved}</span>
        </span>
      </div>
      <div class="committed-files">${filesHtml}</div>
      ${artifactHtml}
    </div>`;
  }

  // Render a single message. toolResult is an optional paired tool_result message.
  function renderMessage(msg, isLast, isStreaming, toolResult) {
    // Error message — render as a red error banner
    if (msg.is_error) {
      const icon = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`;
      return `<div class="msg-error">
        <div class="msg-error-icon">${icon}</div>
        <div class="msg-error-body">
          <div class="msg-error-title">Error</div>
          <div class="msg-error-text">${ZF._escHtml(msg.content)}</div>
        </div>
      </div>`;
    }
    // Warning message — render as amber warning banner
    if (msg.is_warning) {
      const icon = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`;
      return `<div class="msg-warning">
        <div class="msg-warning-icon">${icon}</div>
        <div class="msg-warning-body">
          <div class="msg-warning-title">Quality Warning</div>
          <div class="msg-warning-text">${ZF._escHtml(msg.content)}</div>
        </div>
      </div>`;
    }
    // Tool result — skip if it will be merged into a tool card (handled by renderMessages)
    if (msg.role === 'user' && msg.is_tool_result) {
      const text = msg.content.replace('Tool Result: ', '');
      return `<div class="msg-tool-result">
        <div class="msg-tool-result-label">Tool Result</div>
        <div class="msg-tool-result-content">${ZF._escHtml(text)}</div>
      </div>`;
    }
    // Summary — render as committed changes block if structured data available
    if (msg.role === 'assistant' && msg.is_summary) {
      const s = msg.structured;
      if (s && s.files && s.files.length > 0) {
        return renderCommittedChanges(s);
      }
      return `<div class="msg-summary">${ZF.markdown.render(msg.content)}</div>`;
    }
    // User
    if (msg.role === 'user') {
      return `<div class="msg-user"><div class="msg-user-bubble">${ZF._escHtml(msg.content)}</div></div>`;
    }
    // Assistant
    const isStreamingNow = isLast && isStreaming;
    const { segments, partialTool, thinkingContent } = parseSegments(msg.content, isStreamingNow);
    const resultText = toolResult ? toolResult.content.replace('Tool Result: ', '') : null;

    let html = '<div class="msg-assistant"><div class="msg-assistant-content">';

    // ── Combine ALL thinking into one visual group ──
    // Parse each source independently (preserves topic granularity), then merge
    // section arrays so they render as a single collapsible thinking group.
    let lastToolIdx = -1;
    segments.forEach((seg, i) => { if (seg.type === 'tool') lastToolIdx = i; });

    // When streaming with a partial tool detected, all text is pre-action narration
    const treatAllTextAsThinking = isStreamingNow && !!(partialTool && partialTool.toolName);

    const allSections = [];
    const isStillThinking = isStreamingNow && !(msg.content || '').includes('</think>');

    // Source 1: <think> tags + SSE thinkingContent
    const primaryThinking = (thinkingContent || '') + (msg.thinkingContent || '');
    if (primaryThinking.trim()) {
      const sections = ZF.thinking.parseSections(primaryThinking, isStillThinking);
      allSections.push(...sections);
    }

    // Source 2: text segments before tool calls (or ALL text when partialTool detected)
    if (treatAllTextAsThinking) {
      // Model is narrating document content before a WriteFile — show as simple indicator
      const hasNarration = segments.some(s => s.type === 'text' && s.content.trim());
      if (hasNarration) {
        allSections.push({ id: 't-narration', title: 'Composing document', content: 'Drafting content for file...', isStreaming: true });
      }
    } else {
      segments.forEach((seg, i) => {
        if (seg.type === 'text' && lastToolIdx >= 0 && i < lastToolIdx && seg.content.trim()) {
          const sections = ZF.thinking.parseSections(seg.content, false);
          if (sections.length > 0) {
            allSections.push(...sections);
          } else {
            const cleaned = ZF.thinking.cleanFiller(seg.content);
            if (cleaned) {
              allSections.push({ id: 't-seg-' + i, title: ZF.thinking.generateTitleFromText(cleaned), content: cleaned, isStreaming: false });
            }
          }
        }
      });
    }

    // Deduplicate: merge sections with the same topic title
    const deduped = [];
    const topicMap = new Map();
    for (const sec of allSections) {
      if (topicMap.has(sec.title)) {
        const existing = topicMap.get(sec.title);
        existing.content += '\n\n' + sec.content;
      } else {
        const merged = { ...sec };
        deduped.push(merged);
        topicMap.set(sec.title, merged);
      }
    }

    // Render all sections as one group
    if (deduped.length > 0) {
      const isThinkComplete = !isStreamingNow || !isStillThinking;
      html += ZF.thinking.renderThinkingGroup(deduped, isThinkComplete, msg.thinkingDuration || null);
    }

    if (isStreamingNow) {
      let toolIdx = 0;
      segments.forEach((seg, i) => {
        if (seg.type === 'text') {
          const isBeforeTool = (lastToolIdx >= 0 && i < lastToolIdx) || treatAllTextAsThinking;
          if (!isBeforeTool) {
            // Response — visible, with pulse dot if still generating
            const isLastSeg = i === segments.length - 1;
            const showPulse = isLastSeg && !partialTool;
            html += `<div style="padding:0 4px;">${ZF.markdown.render(seg.content)}${showPulse ? '<span class="thinking-pulse" style="margin-left:4px;"></span>' : ''}</div>`;
          }
          // isBeforeTool text already merged into thinking above — skip
        } else if (seg.type === 'tool') {
          html += ZF.toolcall.renderToolCard(seg.name, seg.args, toolIdx === 0 ? resultText : null);
          toolIdx++;
        }
      });
      if (partialTool && partialTool.toolName) {
        html += ZF.toolcall.renderStreamingToolCard(partialTool.toolName, partialTool.path, partialTool.partialContent);
      }
    } else if (segments.length > 0) {
      // Non-streaming: text before tools already merged into thinking above
      let toolIndex = 0;
      segments.forEach((seg, i) => {
        if (seg.type === 'text') {
          const isBeforeTool = lastToolIdx >= 0 && i < lastToolIdx;
          if (!isBeforeTool) {
            html += ZF.markdown.render(seg.content);
          }
        } else if (seg.type === 'tool') {
          html += ZF.toolcall.renderToolCard(seg.name, seg.args, toolIndex === 0 ? resultText : null);
          toolIndex++;
        }
      });
    }

    html += '</div></div>';
    return html;
  }

  // Build streaming content HTML (inner content only, no wrapper)
  function buildStreamingContentHtml(msg) {
    const { segments, partialTool, thinkingContent } = parseSegments(msg.content || '', true);
    let html = '';

    // KEY: When a partial tool is detected, the model is building a tool call.
    // All preceding text is pre-action narration — fold it into thinking instead
    // of showing a wall of text.
    const treatAllTextAsThinking = !!(partialTool && partialTool.toolName);

    // ── Collect ALL thinking into one merged group ──
    const allSections = [];

    // Source 1: <think> tags + SSE thinkingContent
    const allThinking = (thinkingContent || '') + (msg.thinkingContent || '');
    if (allThinking) {
      const hasResponseContent = (msg.content || '').trim().length > 0;
      const thinkSections = ZF.thinking.parseSections(allThinking, !hasResponseContent);
      allSections.push(...thinkSections);
    }

    // Source 2: text segments before tool calls (or ALL text when partialTool detected)
    let lastToolIdx = -1;
    segments.forEach((seg, i) => { if (seg.type === 'tool') lastToolIdx = i; });

    if (treatAllTextAsThinking) {
      // Model is narrating document content before a WriteFile — don't parse it as
      // thinking (it would get mangled). Just show a clean "Composing..." indicator.
      const hasNarration = segments.some(s => s.type === 'text' && s.content.trim());
      if (hasNarration) {
        allSections.push({ id: 't-narration', title: 'Composing document', content: 'Drafting content for file...', isStreaming: true });
      }
    } else {
      segments.forEach((seg, i) => {
        if (seg.type === 'text') {
          const isBeforeTool = lastToolIdx >= 0 && i < lastToolIdx;
          if (isBeforeTool && seg.content.trim()) {
            const sections = ZF.thinking.parseSections(seg.content, false);
            if (sections.length > 0) {
              allSections.push(...sections);
            } else {
              const cleaned = ZF.thinking.cleanFiller(seg.content);
              if (cleaned) {
                allSections.push({ id: 't-seg-' + i, title: ZF.thinking.generateTitleFromText(cleaned), content: cleaned, isStreaming: false });
              }
            }
          }
        }
      });
    }

    // Deduplicate by topic title
    const deduped = [];
    const topicMap = new Map();
    for (const sec of allSections) {
      if (topicMap.has(sec.title)) {
        topicMap.get(sec.title).content += '\n\n' + sec.content;
      } else {
        const merged = { ...sec };
        deduped.push(merged);
        topicMap.set(sec.title, merged);
      }
    }

    // Render merged thinking group
    if (deduped.length > 0) {
      html += ZF.thinking.renderThinkingGroup(deduped, false, msg.thinkingDuration || null);
    }

    // Render non-thinking content: visible text + tool cards
    segments.forEach((seg, i) => {
      if (seg.type === 'text') {
        const isBeforeTool = (lastToolIdx >= 0 && i < lastToolIdx) || treatAllTextAsThinking;
        if (!isBeforeTool) {
          const isLastSeg = i === segments.length - 1;
          const showPulse = isLastSeg && !partialTool;
          html += `<div style="padding:0 4px;">${ZF.markdown.render(seg.content)}${showPulse ? '<span class="thinking-pulse" style="margin-left:4px;"></span>' : ''}</div>`;
        }
      } else if (seg.type === 'tool') {
        html += ZF.toolcall.renderToolCard(seg.name, seg.args);
      }
    });
    if (partialTool && partialTool.toolName) {
      html += ZF.toolcall.renderStreamingToolCard(partialTool.toolName, partialTool.path, partialTool.partialContent);
    }
    return html;
  }

  // Render all messages (full DOM replacement - used for non-streaming paths)
  function renderMessages(container, messages, generating, stepDesc, reviewBarHtml) {
    let html = '';
    // Step description card — rendered as the first element in the chat scroll area
    if (stepDesc) {
      html += `<div class="step-desc-card">
        <div class="step-desc-card-header">
          ${ZF.icons.fileText(14)} <span>Step description</span>
          <svg class="step-desc-card-chevron" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
        </div>
        <div class="step-desc-card-body">${ZF.markdown.render(stepDesc)}</div>
      </div>`;
    }
    if (messages.length === 0 && !stepDesc) {
      html = `<div class="chat-empty">${ZF.icons.chat(48)}<p>Start a conversation...</p></div>`;
    } else {
      // Build a map: assistant message index → next tool_result message
      const toolResultMap = new Map();
      for (let i = 0; i < messages.length; i++) {
        if (messages[i].role === 'assistant' && !messages[i].is_summary) {
          if (i + 1 < messages.length && messages[i + 1].role === 'user' && messages[i + 1].is_tool_result) {
            toolResultMap.set(i, messages[i + 1]);
          }
        }
      }
      messages.forEach((msg, i) => {
        // Skip internal micro-task phase messages (scope prompts, JSON responses, assemble prompts)
        if (msg.is_micro_phase) return;
        // Skip assistant responses that follow a micro-phase prompt (legacy: scope JSON before backend tagged them)
        if (msg.role === 'assistant' && i > 0 && messages[i - 1].is_micro_phase) return;
        // Skip tool_result messages that are merged into the preceding tool card
        if (msg.role === 'user' && msg.is_tool_result) {
          if (i > 0 && messages[i - 1].role === 'assistant' && !messages[i - 1].is_summary) {
            return; // Merged into tool card above
          }
        }
        const toolResult = toolResultMap.get(i) || null;
        html += renderMessage(msg, i === messages.length - 1, generating, toolResult);
      });
      if (generating && !messages.some(m => m.role === 'assistant')) {
        html += '<div class="generating-indicator animate-pulse">Generating...</div>';
      }
    }
    // Review bar — appended after all messages inside the scroll area
    if (reviewBarHtml) html += reviewBarHtml;
    container.innerHTML = html;

    // Wire up step description card toggle
    const descHeader = container.querySelector('.step-desc-card-header');
    if (descHeader) {
      descHeader.addEventListener('click', () => {
        const card = descHeader.closest('.step-desc-card');
        const body = card.querySelector('.step-desc-card-body');
        const chevron = card.querySelector('.step-desc-card-chevron');
        card.classList.toggle('collapsed');
        if (card.classList.contains('collapsed')) {
          body.style.display = 'none';
          if (chevron) chevron.style.transform = '';
        } else {
          body.style.display = '';
          if (chevron) chevron.style.transform = 'rotate(180deg)';
        }
      });
    }

    container.scrollTop = container.scrollHeight;
  }

  // Helper: create a DOM element from HTML and optionally animate it
  function appendNewMessage(container, html, animate) {
    const tempDiv = document.createElement('div');
    tempDiv.innerHTML = html;
    const el = tempDiv.firstElementChild;
    if (el) {
      if (animate) {
        el.classList.add('msg-new');
        el.addEventListener('animationend', () => el.classList.remove('msg-new'), { once: true });
      }
      container.appendChild(el);
      container.scrollTop = container.scrollHeight;
    }
    return el;
  }

  // Create a chat panel instance
  function createChatPanel(options) {
    const { taskId, task, chatId, onResume, onStepCompleted, onFileWritten, stepDescription } = options;
    let paused = !!options.paused;
    let messages = [];
    let generating = false;
    let abortController = null;
    let autoStartFired = false;
    let sendingRef = false;
    let stoppedByUser = false;
    let retryCount = 0;
    const MAX_RETRIES = 3;

    // Review state: 'idle' | 'reviewing' | 'done' | 'error'
    let reviewState = 'idle';
    let reviewPrompt = '';
    let reviewContent = '';   // Markdown result when done
    let reviewStatus = '';    // Live status text during review (e.g. "Evaluating the Previous Work")
    let reviewErrorMsg = '';  // Error message when reviewState === 'error'
    let pendingStepCompletedId = null; // stepId waiting for review to finish before advancing

    // Streaming DOM references for incremental updates
    let streamingMsgEl = null;
    let streamingContentEl = null;
    let rafPending = false;
    let thinkingStartTime = null; // track when thinking began for duration display
    let thinkingThrottleTimer = null; // throttle thinking UI updates
    let stuckDetectorTimeout = null; // fires after 60s of continuous generating
    let heartbeatReconnects = 0; // track heartbeat reconnects to prevent infinite loops

    const wrapper = document.createElement('div');
    wrapper.className = 'chat-panel';
    wrapper.innerHTML = `
      <div class="chat-messages chat-scrollbar" id="chat-msgs-${chatId || 'main'}"></div>
      <div class="chat-composer-wrapper">
        <div class="chat-composer-fade"></div>
        <div id="chat-bottom-${chatId || 'main'}"></div>
      </div>
    `;

    function getMsgContainer() { return wrapper.querySelector('.chat-messages'); }
    function getBottomContainer() { return wrapper.querySelector(`#chat-bottom-${chatId || 'main'}`); }

    function rerender() {
      // Clear streaming refs on full rerender
      streamingMsgEl = null;
      streamingContentEl = null;
      _streamToolCount = 0;
      _streamHasPartial = false;
      _streamContentLen = 0;
      const mc = getMsgContainer();
      if (mc) {
        renderMessages(mc, messages, generating, stepDescription, buildReviewBar());
        wireReviewBar(mc);
        // Lazy-load artifact previews for SDD steps missing inline content (old tasks)
        mc.querySelectorAll('.committed-artifact-preview[data-artifact-path]').forEach(el => {
          const artPath = el.dataset.artifactPath;
          const artName = el.dataset.artifactName;
          if (!artPath || !taskId) return;
          fetch(`/api/tasks/${taskId}/file?path=${encodeURIComponent(artPath)}`)
            .then(r => r.json())
            .then(data => {
              if (data.content) {
                el.outerHTML = _buildArtifactPreview(artName, ZF.markdown.render(data.content));
              } else {
                el.remove();
              }
            })
            .catch(() => el.remove());
        });
      }
    }

    // Centralized streaming state reset — called from all exit paths
    function resetStreamingState() {
      generating = false;
      sendingRef = false;
      abortController = null;
      streamingMsgEl = null;
      streamingContentEl = null;
      rafPending = false;
      const cid = chatId || 'main';
      _activeStreams.delete(cid);
      if (stuckDetectorTimeout) { clearTimeout(stuckDetectorTimeout); stuckDetectorTimeout = null; }
      // Remove stuck-reset button if present
      const mc = getMsgContainer();
      mc?.querySelector('.stuck-reset-btn')?.remove();
      rerender();
      renderComposer();
    }

    // Track streaming state to enable incremental updates
    let _streamToolCount = 0;     // number of tool cards rendered so far
    let _streamHasPartial = false; // whether a partial tool card is showing
    let _streamContentLen = 0;    // length of msg.content at last full rebuild

    // Incremental update: only update the streaming assistant message
    function updateStreamingContent() {
      if (rafPending) return;
      rafPending = true;
      requestAnimationFrame(() => {
        rafPending = false;
        const mc = getMsgContainer();
        if (!mc) return;

        const lastMsg = messages[messages.length - 1];
        if (!lastMsg || lastMsg.role !== 'assistant') return;

        // If no streaming element exists yet, create and append one
        if (!streamingMsgEl || !mc.contains(streamingMsgEl)) {
          // Remove empty state or generating indicator if present
          const empty = mc.querySelector('.chat-empty');
          if (empty) empty.remove();
          const genInd = mc.querySelector('.generating-indicator');
          if (genInd) genInd.remove();

          const tempDiv = document.createElement('div');
          tempDiv.innerHTML = '<div class="msg-assistant msg-streaming-active"><div class="msg-assistant-content"></div></div>';
          streamingMsgEl = tempDiv.firstElementChild;
          streamingContentEl = streamingMsgEl.querySelector('.msg-assistant-content');
          mc.appendChild(streamingMsgEl);
          _streamToolCount = 0;
          _streamHasPartial = false;
          _streamContentLen = 0;
        }

        if (!streamingContentEl) return;

        const hasContent = (lastMsg.content || '').trim().length > 0;
        const hasThinking = (lastMsg.thinkingContent || '').length > 0;

        // During thinking-only phase: rebuild thinking group when section count changes,
        // otherwise do a fast update of just the last section's content
        if (hasThinking && !hasContent) {
          const raw = lastMsg.thinkingContent || '';
          const allThinking = raw;
          const newSections = ZF.thinking.parseSections(allThinking, true);
          const currentSectionCount = streamingContentEl.querySelectorAll('.thinking-section').length;

          if (newSections.length !== currentSectionCount || currentSectionCount === 0) {
            // Section count changed (new topic detected) → full rebuild of thinking group
            streamingContentEl.innerHTML = buildStreamingContentHtml(lastMsg);
            mc.scrollTop = mc.scrollHeight;
            return;
          }

          // Same section count — fast-update last section body only
          const bodies = streamingContentEl.querySelectorAll('.thinking-section-body');
          const lastBody = bodies.length > 0 ? bodies[bodies.length - 1] : null;
          if (lastBody && newSections.length > 0) {
            const lastSection = newSections[newSections.length - 1];
            const bodyContent = lastSection.content.replace(/^#{1,4}\s+[^\n]*\n?/, '').trimStart();
            if (bodyContent.trim()) {
              lastBody.innerHTML = ZF.markdown.render(ZF.thinking.formatThinkingBody(bodyContent));
            }
            // Make sure it's visible
            lastBody.style.display = 'block';
            mc.scrollTop = mc.scrollHeight;
            return;
          }
        }

        // Parse current state to detect structural changes
        const { segments, partialTool } = parseSegments(lastMsg.content || '', true);
        const toolCount = segments.filter(s => s.type === 'tool').length;
        const hasPartial = !!(partialTool && partialTool.toolName);

        // Structural change: new tool card appeared, or partial tool state changed
        // → full rebuild required
        const structureChanged = toolCount !== _streamToolCount || hasPartial !== _streamHasPartial;

        if (structureChanged) {
          // Full rebuild
          streamingContentEl.innerHTML = buildStreamingContentHtml(lastMsg);
          _streamToolCount = toolCount;
          _streamHasPartial = hasPartial;
          _streamContentLen = (lastMsg.content || '').length;
          mc.scrollTop = mc.scrollHeight;
          return;
        }

        // No structural change — try incremental update of trailing text
        // Find the last text div (the one after all tool cards)
        const textDivs = streamingContentEl.querySelectorAll(':scope > div[style*="padding"]');
        const lastTextDiv = textDivs.length > 0 ? textDivs[textDivs.length - 1] : null;

        if (lastTextDiv && segments.length > 0) {
          const lastSeg = segments[segments.length - 1];
          if (lastSeg.type === 'text') {
            // Update just this text div's content
            const cleaned = cleanGptOssTags(lastSeg.content);
            if (cleaned) {
              lastTextDiv.innerHTML = ZF.markdown.render(cleaned) +
                (!hasPartial ? '<span class="thinking-pulse" style="margin-left:4px;"></span>' : '');
            }
            _streamContentLen = (lastMsg.content || '').length;
            mc.scrollTop = mc.scrollHeight;
            return;
          }
        }

        // Fallback: full rebuild if incremental didn't apply
        if ((lastMsg.content || '').length !== _streamContentLen) {
          streamingContentEl.innerHTML = buildStreamingContentHtml(lastMsg);
          _streamToolCount = toolCount;
          _streamHasPartial = hasPartial;
          _streamContentLen = (lastMsg.content || '').length;
        }

        mc.scrollTop = mc.scrollHeight;
      });
    }

    // ── Review Card: 3 states (idle / reviewing / done) ──
    let reviewAbortController = null;
    let reviewEdits = [];      // Paths edited by the review agent
    let reviewEditDetails = []; // Full edit details: [{path, added, removed}]
    let reviewPasses = [];     // Multi-pass tracker: [{name, status, issues, edits}]

    function buildPassTrackerHTML(passes) {
      const passConfig = [
        { key: 'deterministic', label: 'Code Check' },
        { key: 'api_check', label: 'API Check' },
        { key: 'quality', label: 'Quality' },
        { key: 'fix_summary', label: 'Summary' },
      ];
      return passConfig.map((cfg, i) => {
        const p = passes.find(pp => pp.name === cfg.key);
        let stateClass = 'review-pass-pending';
        let icon = '\u25CB';  // empty circle
        let suffix = '';
        if (p && p.status === 'done') {
          stateClass = 'review-pass-done';
          icon = '\u2713';  // checkmark
          const issueCount = (p.issues || []).length;
          const editCount = (p.edits || []).length;
          if (issueCount > 0) suffix = ` (${issueCount})`;
          else if (editCount > 0) suffix = ` (${editCount} fixes)`;
        } else if (p && p.status === 'active') {
          stateClass = 'review-pass-active';
          icon = '\u25CF';  // filled circle
        }
        const arrow = i < passConfig.length - 1
          ? ' <span class="review-pass-arrow">\u2192</span> ' : '';
        return `<span class="review-pass-item ${stateClass}">${icon} ${cfg.label}${suffix}</span>${arrow}`;
      }).join('');
    }

    function startReview(prompt) {
      reviewState = 'reviewing';
      reviewPrompt = prompt || 'Please review my changes';
      reviewContent = '';
      reviewStatus = 'Starting review...';
      reviewEdits = [];
      reviewEditDetails = [];
      reviewPasses = [];
      rerender();
      renderComposer();

      // Start real SSE stream to the review backend
      const ac = new AbortController();
      reviewAbortController = ac;
      const url = ZF.api.getReviewStreamUrl(taskId, chatId || 'main', reviewPrompt);
      console.log('[Review] Starting stream:', url);

      (async () => {
        try {
          const response = await fetch(url, { signal: ac.signal });
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          if (!response.body) throw new Error('No response body');

          const reader = response.body.getReader();
          const decoder = new TextDecoder();
          let buffer = '';

          while (true) {
            const { done, value } = await reader.read();
            if (done || ac.signal.aborted) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';

            let eventType = 'message';
            for (const line of lines) {
              if (line === '') { eventType = 'message'; continue; }
              if (line.startsWith('event: ')) { eventType = line.slice(7).trim(); continue; }
              if (!line.startsWith('data: ')) continue;

              try {
                const data = JSON.parse(line.slice(6));

                if (eventType === 'review_status') {
                  reviewStatus = data.status || '';
                  const statusEl = wrapper.querySelector('.review-card-status-text');
                  if (statusEl) statusEl.textContent = reviewStatus;
                } else if (eventType === 'review_code_check') {
                  // Code check results embedded in review stream
                  const count = (data.issues || []).length;
                  if (count > 0) {
                    reviewStatus = `Code check: ${count} issue${count !== 1 ? 's' : ''} found \u2014 reviewing...`;
                  } else {
                    reviewStatus = 'Code check passed \u2714 \u2014 reviewing...';
                  }
                  const statusEl = wrapper.querySelector('.review-card-status-text');
                  if (statusEl) statusEl.textContent = reviewStatus;
                } else if (eventType === 'review_pass') {
                  // Multi-pass tracker update
                  const passName = data.pass;
                  const passStatus = data.status;
                  if (passStatus === 'starting') {
                    reviewPasses.push({ name: passName, status: 'active', issues: [], edits: [] });
                  } else if (passStatus === 'done') {
                    const p = reviewPasses.find(pp => pp.name === passName);
                    if (p) {
                      p.status = 'done';
                      p.issues = data.issues || [];
                      p.edits = data.edits || [];
                    }
                  }
                  // Update pass tracker in DOM
                  const tracker = wrapper.querySelector('.review-pass-tracker');
                  if (tracker) tracker.innerHTML = buildPassTrackerHTML(reviewPasses);
                  // Clear live content between LLM passes (each pass streams fresh)
                  if (passStatus === 'starting' && passName !== 'deterministic') {
                    reviewContent = '';
                    const liveEl = wrapper.querySelector('.review-card-live');
                    if (liveEl) liveEl.innerHTML = '';
                  }
                } else if (eventType === 'review_token') {
                  reviewContent += data.token || '';
                  // Live-stream the review content into the card (strip tool_code blocks)
                  const liveEl = wrapper.querySelector('.review-card-live');
                  if (liveEl) {
                    const cleaned = cleanReviewContent(reviewContent);
                    liveEl.innerHTML = ZF.markdown.render(cleaned);
                    // Auto-scroll the review card body
                    const body = liveEl.closest('.review-card-body');
                    if (body) body.scrollTop = body.scrollHeight;
                  }
                } else if (eventType === 'review_edit') {
                  reviewEdits.push(data.path);
                  reviewStatus = `Edited ${data.path}`;
                  const statusEl = wrapper.querySelector('.review-card-status-text');
                  if (statusEl) statusEl.textContent = reviewStatus;
                } else if (eventType === 'review_done') {
                  reviewContent = data.content || reviewContent;
                  if (data.edits && data.edits.length > 0) {
                    reviewEdits = data.edits;
                  }
                  if (data.editDetails && data.editDetails.length > 0) {
                    reviewEditDetails = data.editDetails;
                  }
                  reviewState = 'done';
                  reviewAbortController = null;
                  // Always auto-apply review edits to committed changes
                  if (reviewEdits.length > 0 && chatId && taskId) {
                    ZF.api.applyReviewEdits(chatId, taskId, reviewEdits, reviewEditDetails).then(result => {
                      if (result.structured) {
                        const mc = getMsgContainer();
                        const committedEl = mc?.querySelector('.committed-changes');
                        if (committedEl) {
                          const newHtml = renderCommittedChanges(result.structured);
                          const temp = document.createElement('div');
                          temp.innerHTML = newHtml;
                          committedEl.replaceWith(temp.firstElementChild);
                        }
                      }
                      // Mark apply button as done
                      const mc2 = getMsgContainer();
                      const applyBtn = mc2?.querySelector('.review-card-apply-btn');
                      if (applyBtn) {
                        applyBtn.innerHTML = `${ZF.icons.check(12)} Applied`;
                        applyBtn.classList.add('review-card-apply-btn-done');
                        applyBtn.disabled = true;
                      }
                    }).catch(err => console.error('[Review] Auto-apply error:', err));
                    updateCommittedBadges(reviewEdits);
                  }
                  rerender();
                  renderComposer();
                  // Advance to next step if pending (auto-start mode)
                  flushPendingStepCompleted();
                  return;
                } else if (eventType === 'review_error') {
                  console.error('[Review] Error:', data.error);
                  reviewState = 'error';
                  reviewAbortController = null;
                  reviewErrorMsg = data.error || 'Unknown error';
                  rerender();
                  renderComposer();
                  // Do NOT auto-advance — let user decide via retry/skip buttons
                  return;
                }
              } catch {}
            }
          }

          // Stream ended naturally without review_done — treat content as final
          if (reviewState === 'reviewing') {
            reviewState = 'done';
            reviewAbortController = null;
            rerender();
            renderComposer();
            if (reviewEdits.length > 0) {
              updateCommittedBadges(reviewEdits);
            }
            flushPendingStepCompleted();
          }
        } catch (err) {
          if (err.name === 'AbortError') return;
          console.error('[Review] Stream error:', err);
          reviewState = 'idle';
          reviewAbortController = null;
          rerender();
          renderComposer();
          flushPendingStepCompleted();
        }
      })();
    }

    // When review finishes (or fails), advance to next step (auto-start mode)
    function flushPendingStepCompleted() {
      const stepId = pendingStepCompletedId;
      if (!stepId) return;
      pendingStepCompletedId = null;
      // Edits are already auto-applied in the review_done handler — just advance
      onStepCompleted?.(stepId);
    }

    function cancelReview() {
      // Cancel the SSE stream
      if (reviewAbortController) {
        reviewAbortController.abort();
        reviewAbortController = null;
      }
      // Also cancel on the server side
      ZF.api.cancelReview(chatId || 'main').catch(() => {});
      reviewState = 'idle';
      reviewPrompt = '';
      reviewContent = '';
      reviewStatus = '';
      reviewEdits = [];
      reviewPasses = [];
      rerender();
      renderComposer();
    }

    // Update committed changes badges: change "New" to "Edited" for files the review agent modified
    function updateCommittedBadges(editedPaths) {
      const mc = getMsgContainer();
      if (!mc) return;
      const committedFiles = mc.querySelectorAll('.committed-file');
      committedFiles.forEach(fileEl => {
        const nameEl = fileEl.querySelector('.committed-file-name');
        const pathEl = fileEl.querySelector('.committed-file-path');
        if (!nameEl) return;
        const fileName = nameEl.textContent.trim();
        const filePath = pathEl ? pathEl.textContent.trim() : '';
        // Check if this file was edited by the review agent
        const wasEdited = editedPaths.some(ep => {
          const epName = ep.split('/').pop().split('\\').pop();
          return epName === fileName || ep === fileName || ep.endsWith('/' + fileName);
        });
        if (wasEdited) {
          const badgeEl = fileEl.querySelector('.committed-file-badge');
          if (badgeEl) {
            // Replace "New" badge with "Edited" badge, or add "Edited" badge
            const newBadge = badgeEl.querySelector('.committed-badge-new');
            if (newBadge) {
              newBadge.className = 'committed-badge-edited';
              newBadge.textContent = 'Edited';
            } else {
              // Add an "Edited" tag before the delta
              const editedSpan = document.createElement('span');
              editedSpan.className = 'committed-badge-edited';
              editedSpan.textContent = 'Edited';
              badgeEl.insertBefore(editedSpan, badgeEl.firstChild);
            }
            // Update the file icon to edit icon
            const iconEl = fileEl.querySelector('.committed-file-icon');
            if (iconEl) iconEl.innerHTML = ZF.icons.edit(14);
          }
        }
      });
    }

    function cleanReviewContent(text) {
      return text
        .replace(/<tool_code>[\s\S]*?<\/tool_code>/g, '')
        .replace(/<tool_code>[\s\S]*/g, '')
        .replace(/<\|channel\|>[\s\S]*?<\|message\|>[\s\S]*?(?=<\|channel\|>|$)/g, '')
        .replace(/<\|channel\|>[\s\S]*$/g, '')
        .replace(/\{"name":\s*"EditFile"[^}]*"arguments"\s*:\s*\{[^}]*\}\s*\}/g, '');
    }

    function buildReviewBar() {
      if (generating) return '';
      const hasWork = messages.some(m => m.role === 'assistant' && !m.is_tool_result);
      if (!hasWork) return '';

      const rid = `review-card-${chatId || 'main'}`;

      // ── State: idle → show trigger button ──
      if (reviewState === 'idle') {
        return `<div class="review-bar" id="${rid}">
          <div class="review-bar-default">
            <button class="review-bar-trigger">
              <span class="review-bar-icon">${ZF.icons.sparkles(14)}</span>
              <span>Review with Another Agent</span>
            </button>
            <button class="review-bar-edit-btn">
              ${ZF.icons.edit(14)}
            </button>
          </div>
          <div class="review-bar-expanded" style="display:none;">
            <input type="text" class="review-bar-input" value="Please review my changes" />
            <button class="review-bar-submit">Review</button>
            <button class="review-bar-cancel">Cancel</button>
          </div>
        </div>`;
      }

      // ── State: reviewing → in-progress card ──
      if (reviewState === 'reviewing') {
        return `<div class="review-card review-card-active" id="${rid}">
          <div class="review-card-header" data-review-toggle>
            <svg class="review-card-chevron" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
            <span class="review-card-header-icon">${ZF.icons.sparkles(14)}</span>
            <span class="review-card-header-text">Review by Sentinel in progress...</span>
          </div>
          <div class="review-card-body">
            <div class="review-card-prompt">${ZF._escHtml(reviewPrompt)}</div>
            <div class="review-pass-tracker">${buildPassTrackerHTML(reviewPasses)}</div>
            <div class="review-card-live">${reviewContent ? ZF.markdown.render(cleanReviewContent(reviewContent)) : ''}</div>
            <div class="review-card-progress">
              <span class="review-card-spinner"></span>
              <span class="review-card-status-text">${ZF._escHtml(reviewStatus)}</span>
              <button class="review-card-cancel-btn">
                ${ZF.icons.stop(12)} Cancel review
              </button>
            </div>
          </div>
        </div>`;
      }

      // ── State: error → review failed, show retry/skip ──
      if (reviewState === 'error') {
        return `<div class="review-card review-card-error" id="${rid}">
          <div class="review-card-header">
            <span class="review-card-header-icon" style="color:#ef4444;">&#9888;</span>
            <span class="review-card-header-text" style="color:#ef4444;">Review Failed</span>
          </div>
          <div class="review-card-body">
            <div class="review-card-error-msg">${ZF._escHtml(reviewErrorMsg)}</div>
            <div class="review-card-error-actions">
              <button class="review-card-retry-btn">
                Retry Review
              </button>
              <button class="review-card-skip-btn">
                Skip & Continue
              </button>
            </div>
          </div>
        </div>`;
      }

      // ── State: done → completed review card ──
      if (reviewState === 'done') {
        const editCountText = reviewEdits.length > 0
          ? ` · ${reviewEdits.length} file${reviewEdits.length !== 1 ? 's' : ''} edited`
          : '';
        return `<div class="review-card review-card-done" id="${rid}">
          <div class="review-card-header" data-review-toggle>
            <svg class="review-card-chevron" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
            <span class="review-card-header-icon">${ZF.icons.sparkles(14)}</span>
            <div class="review-card-header-col">
              <span class="review-card-header-text">Reviewed by Sentinel${editCountText}</span>
              <span class="review-card-header-sub">Feedback is only visible to you, copy to chat what you want agent to address</span>
            </div>
          </div>
          <div class="review-card-body">
            <div class="review-card-prompt">${ZF._escHtml(reviewPrompt)}</div>
            <div class="review-card-result">${ZF.markdown.render(cleanReviewContent(reviewContent))}</div>
            <div class="review-card-actions">
              ${reviewEdits.length > 0 ? `<button class="review-card-apply-btn review-card-apply-btn-done" disabled>
                ${ZF.icons.check(12)} Applied
              </button>` : ''}
              <button class="review-card-copy-btn">
                ${ZF.icons.chevronRight(12)} Copy to chat input
              </button>
            </div>
          </div>
        </div>`;
      }

      return '';
    }

    function wireReviewBar(container) {
      const rid = `review-card-${chatId || 'main'}`;
      const card = container.querySelector(`#${rid}`);
      if (!card) return;

      // ── Idle state wiring ──
      if (reviewState === 'idle') {
        const defaultView = card.querySelector('.review-bar-default');
        const expandedView = card.querySelector('.review-bar-expanded');
        const trigger = card.querySelector('.review-bar-trigger');
        const editBtn = card.querySelector('.review-bar-edit-btn');
        const input = card.querySelector('.review-bar-input');
        const submitBtn = card.querySelector('.review-bar-submit');
        const cancelBtn = card.querySelector('.review-bar-cancel');

        trigger?.addEventListener('click', () => startReview('Please review my changes'));

        editBtn?.addEventListener('click', () => {
          defaultView.style.display = 'none';
          expandedView.style.display = 'flex';
          input.focus();
          input.select();
        });

        submitBtn?.addEventListener('click', () => {
          const prompt = input.value.trim();
          if (prompt) startReview(prompt);
        });

        cancelBtn?.addEventListener('click', () => {
          expandedView.style.display = 'none';
          defaultView.style.display = 'flex';
          input.value = 'Please review my changes';
        });

        input?.addEventListener('keydown', (e) => {
          if (e.key === 'Enter') { e.preventDefault(); submitBtn?.click(); }
          else if (e.key === 'Escape') { cancelBtn?.click(); }
        });
      }

      // ── Error state wiring ──
      if (reviewState === 'error') {
        card.querySelector('.review-card-retry-btn')?.addEventListener('click', () => {
          reviewState = 'idle';
          reviewErrorMsg = '';
          startReview(reviewPrompt || 'Please review my changes');
        });
        card.querySelector('.review-card-skip-btn')?.addEventListener('click', () => {
          reviewState = 'idle';
          reviewErrorMsg = '';
          rerender();
          renderComposer();
          flushPendingStepCompleted();
        });
      }

      // ── Reviewing state wiring ──
      if (reviewState === 'reviewing') {
        card.querySelector('.review-card-cancel-btn')?.addEventListener('click', cancelReview);
        card.querySelector('[data-review-toggle]')?.addEventListener('click', () => {
          const body = card.querySelector('.review-card-body');
          const chevron = card.querySelector('.review-card-chevron');
          if (body.style.display === 'none') {
            body.style.display = '';
            chevron.style.transform = '';
          } else {
            body.style.display = 'none';
            chevron.style.transform = 'rotate(-90deg)';
          }
        });
      }

      // ── Done state wiring ──
      if (reviewState === 'done') {
        card.querySelector('[data-review-toggle]')?.addEventListener('click', () => {
          const body = card.querySelector('.review-card-body');
          const chevron = card.querySelector('.review-card-chevron');
          if (body.style.display === 'none') {
            body.style.display = '';
            chevron.style.transform = '';
          } else {
            body.style.display = 'none';
            chevron.style.transform = 'rotate(-90deg)';
          }
        });

        card.querySelector('.review-card-apply-btn')?.addEventListener('click', async (e) => {
          const btn = e.currentTarget;
          if (btn.disabled) return;
          btn.disabled = true;
          btn.innerHTML = `${ZF.icons.check(12)} Applying...`;
          try {
            const result = await ZF.api.applyReviewEdits(chatId, taskId, reviewEdits, reviewEditDetails);
            if (result.structured) {
              // Update the committed changes block in the DOM
              const mc = getMsgContainer();
              const committedEl = mc?.querySelector('.committed-changes');
              if (committedEl) {
                const newHtml = renderCommittedChanges(result.structured);
                const temp = document.createElement('div');
                temp.innerHTML = newHtml;
                committedEl.replaceWith(temp.firstElementChild);
              }
            }
            btn.innerHTML = `${ZF.icons.check(12)} Applied`;
            btn.classList.add('review-card-apply-btn-done');
          } catch (err) {
            console.error('[Review] Apply error:', err);
            btn.innerHTML = `${ZF.icons.check(12)} Apply Changes`;
            btn.disabled = false;
          }
        });

        card.querySelector('.review-card-copy-btn')?.addEventListener('click', () => {
          const bc = getBottomContainer();
          if (!bc) return;
          const ta = bc.querySelector('textarea');
          if (ta) {
            ta.value = reviewContent;
            ta.style.height = 'auto';
            ta.style.height = ta.scrollHeight + 'px';
            ta.focus();
          }
        });
      }
    }

    function renderComposer() {
      const bc = getBottomContainer();
      if (!bc) return;
      // Hide the fade gradient when paused (no composer visible = no need for fade)
      const fade = bc.parentElement?.querySelector('.chat-composer-fade');
      if (fade) fade.style.display = (paused && !generating) ? 'none' : '';
      if (paused && !generating) {
        bc.innerHTML = `<div class="chat-paused">
          <span>This task is paused.</span>
          <button class="btn-resume" id="resume-btn-${chatId || 'main'}">${ZF.icons.play(16)} Resume Generation</button>
        </div>`;
        bc.querySelector('.btn-resume')?.addEventListener('click', () => {
          paused = false;
          onResume?.();
          setTimeout(() => handleSend('Continue working on this step from where you left off.'), 300);
        });
      } else {
        bc.innerHTML = `<div class="chat-composer">
          <div class="chat-composer-inner">
            <textarea rows="1" placeholder="Continue working on this task... Type @ to search files." ${generating ? 'disabled' : ''}></textarea>
            <div class="chat-composer-footer">
              <div class="chat-composer-footer-left">
                <button class="btn btn-icon-sm btn-ghost">${ZF.icons.plus(14)}</button>
                <div class="chat-composer-divider"></div>
                <div class="chat-composer-agent">Sentinel Default ${ZF.icons.chevronDown(10)}</div>
              </div>
              <div class="chat-composer-footer-right">
                ${stoppedByUser && !generating ? `<button class="btn-continue" id="continue-btn">${ZF.icons.play ? ZF.icons.play(14) : '▶'} Continue</button>` : ''}
                ${generating ? `<button class="btn-stop" id="stop-btn">${ZF.icons.stop(12)}</button>` : ''}
                <button class="btn-send" id="send-btn" ${generating ? 'disabled' : ''}>${ZF.icons.chevronRight(14)}</button>
              </div>
            </div>
          </div>
        </div>`;

        const ta = bc.querySelector('textarea');
        const sendBtn = bc.querySelector('#send-btn');
        const stopBtn = bc.querySelector('#stop-btn');

        if (ta) {
          ta.addEventListener('input', () => { ta.style.height = 'auto'; ta.style.height = ta.scrollHeight + 'px'; });
          ta.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              if (ta.value.trim()) { handleSend(ta.value); ta.value = ''; ta.style.height = 'auto'; }
            }
          });
        }
        sendBtn?.addEventListener('click', () => {
          if (ta && ta.value.trim()) { handleSend(ta.value); ta.value = ''; ta.style.height = 'auto'; }
        });
        stopBtn?.addEventListener('click', handleStop);
        const continueBtn = bc.querySelector('#continue-btn');
        continueBtn?.addEventListener('click', () => {
          stoppedByUser = false;
          handleSend('Continue working on this step from where you left off.');
        });
      }
    }

    function handleStop() {
      if (abortController) { abortController.abort(); abortController = null; }
      if (messages.length > 0) {
        const lastChat = messages[0]; // get first msg to find chat
      }
      // Cancel server-side
      const cid = chatId || (messages[0] && messages[0]._chatId);
      if (cid) ZF.api.cancelChat(cid).catch(() => {});
      generating = false;
      sendingRef = false;
      stoppedByUser = true;
      streamingMsgEl = null;
      streamingContentEl = null;
      rafPending = false;
      thinkingStartTime = null;
      rerender();
      renderComposer();
    }

    async function handleSend(text, isKickoff) {
      if (sendingRef) return;
      sendingRef = true;
      stoppedByUser = false;

      const userMsg = { id: Date.now().toString(), role: 'user', content: text, timestamp: new Date().toISOString(), ...(isKickoff ? { is_kickoff: true } : {}) };
      messages.push(userMsg);
      generating = true;
      // Start stuck-state detector — show reset button after 60s of continuous generating
      if (stuckDetectorTimeout) clearTimeout(stuckDetectorTimeout);
      stuckDetectorTimeout = setTimeout(() => {
        if (generating) {
          const mc2 = getMsgContainer();
          if (mc2 && !mc2.querySelector('.stuck-reset-btn')) {
            const btn = document.createElement('button');
            btn.className = 'stuck-reset-btn';
            btn.textContent = 'Reset (stream appears stuck)';
            btn.addEventListener('click', () => { resetStreamingState(); });
            mc2.appendChild(btn);
          }
        }
      }, 60000);

      // Append user message to DOM directly instead of full rerender
      const mc = getMsgContainer();
      if (mc) {
        const empty = mc.querySelector('.chat-empty');
        if (empty) empty.remove();
        appendNewMessage(mc, renderMessage(userMsg, false, false), true);
      }
      renderComposer();

      // Abort previous stream
      const activeChatId = chatId || 'main';
      const prev = _activeStreams.get(activeChatId);
      if (prev) { prev.abort(); _activeStreams.delete(activeChatId); }

      const ac = new AbortController();
      abortController = ac;
      _activeStreams.set(activeChatId, ac);

      const url = ZF.api.getChatStreamUrl(taskId, activeChatId, text);
      console.log('[Chat] Starting stream:', url);

      try {
        const response = await fetch(url, { signal: ac.signal });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        if (!response.body) throw new Error('No response body');

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let lastStreamData = Date.now();

        // Heartbeat checker: if no data received for 45s, attempt reconnection
        // (server sends heartbeats every 10s — 45s allows for slow LLM startup after review passes)
        // Max 2 reconnects to prevent infinite loops when LLM is truly stuck
        const heartbeatChecker = setInterval(() => {
          if (!generating) { clearInterval(heartbeatChecker); return; }
          if (Date.now() - lastStreamData > 45000) {
            clearInterval(heartbeatChecker);
            heartbeatReconnects++;
            if (heartbeatReconnects > 2) {
              console.error('[Chat] Max heartbeat reconnects reached — stopping');
              resetStreamingState();
              rerender();
              renderComposer();
              return;
            }
            console.warn(`[Chat] Heartbeat gap detected (>45s), reconnect attempt ${heartbeatReconnects}/2`);
            ac.abort();
            // Auto-reconnect: reload messages from server then re-initiate stream
            setTimeout(async () => {
              resetStreamingState();
              try {
                const list = await ZF.api.getChats(taskId);
                const fresh = list.find(c => c.id === activeChatId);
                if (fresh) { messages = fresh.messages || []; rerender(); }
              } catch (e) { console.error('[Chat] Reconnect reload error:', e); }
              // Re-initiate stream in continue mode (empty message)
              handleSend('');
            }, 500);
          }
        }, 5000);

        while (true) {
          const { done, value } = await reader.read();
          if (done || ac.signal.aborted) { clearInterval(heartbeatChecker); break; }

          buffer += decoder.decode(value, { stream: true });
          lastStreamData = Date.now(); // Track any data received as heartbeat
          heartbeatReconnects = 0; // Reset reconnect counter on successful data
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';

          let eventType = 'message';
          for (const line of lines) {
            if (line === '') { eventType = 'message'; continue; }
            if (line.startsWith('event: ')) { eventType = line.slice(7).trim(); continue; }
            if (!line.startsWith('data: ')) continue;

            try {
              const data = JSON.parse(line.slice(6));

              if (eventType === 'thinking' && data.token) {
                // Accumulate thinking tokens on the current assistant message
                const last = messages[messages.length - 1];
                if (last && last.role === 'assistant') {
                  last.thinkingContent = (last.thinkingContent || '') + data.token;
                } else {
                  thinkingStartTime = Date.now();
                  messages.push({ id: 'temp-' + Date.now(), role: 'assistant', content: '', thinkingContent: data.token, timestamp: new Date().toISOString() });
                }
                // Fast thinking updates — user wants to see thoughts streaming rapidly
                if (!thinkingThrottleTimer) {
                  thinkingThrottleTimer = setTimeout(() => { thinkingThrottleTimer = null; updateStreamingContent(); }, 50);
                }
              } else if (eventType === 'message' && data.token) {
                // Flush any pending thinking update before rendering content
                if (thinkingThrottleTimer) { clearTimeout(thinkingThrottleTimer); thinkingThrottleTimer = null; }
                const last = messages[messages.length - 1];
                if (last && last.role === 'assistant') {
                  last.content += data.token;
                } else {
                  thinkingStartTime = Date.now();
                  messages.push({ id: 'temp-' + Date.now(), role: 'assistant', content: data.token, timestamp: new Date().toISOString() });
                }
                updateStreamingContent();
              } else if (eventType === 'tool_call') {
                // Stamp thinking duration on the current assistant message
                if (thinkingStartTime) {
                  const last = messages[messages.length - 1];
                  if (last && last.role === 'assistant') {
                    last.thinkingDuration = (Date.now() - thinkingStartTime) / 1000;
                  }
                  thinkingStartTime = null;
                }
                // Mark the matching tool card as "executing" using backend index
                const mc2 = getMsgContainer();
                if (mc2) {
                  const toolCards = mc2.querySelectorAll('.tool-card');
                  const idx = data.index;
                  const card = (idx != null && toolCards[idx]) ? toolCards[idx] : toolCards[toolCards.length - 1];
                  if (card) {
                    card.setAttribute('data-tool-index', idx != null ? idx : toolCards.length - 1);
                    card.classList.add('tool-card-executing');
                  }
                }
              } else if (eventType === 'tool_result') {
                const resultText = data.result ?? data.output ?? '(no result)';
                // Still push to messages array for persistence/reload
                messages.push({ id: 'tr-' + Date.now(), role: 'user', content: `Tool Result: ${resultText}`, timestamp: new Date().toISOString(), is_tool_result: true });
                // Inject result into the matching tool card by index
                const mc = getMsgContainer();
                if (mc) {
                  let targetCard = null;
                  if (data.index != null) {
                    targetCard = mc.querySelector(`.tool-card[data-tool-index="${data.index}"]`);
                  }
                  if (!targetCard) {
                    const executing = mc.querySelector('.tool-card-executing');
                    if (executing) targetCard = executing;
                  }
                  if (!targetCard) {
                    const toolCards = mc.querySelectorAll('.tool-card');
                    targetCard = toolCards[toolCards.length - 1];
                  }
                  if (targetCard) {
                    targetCard.classList.remove('tool-card-executing');
                    ZF.toolcall.injectResultIntoCard(targetCard, resultText);
                  }
                }
                // Finalize streaming message references
                streamingMsgEl = null;
                streamingContentEl = null;
              } else if (eventType === 'file_written') {
                onFileWritten?.(data.path);
              } else if (eventType === 'step_summary') {
                streamingMsgEl = null;
                streamingContentEl = null;
                messages.push({ id: 'sum-' + Date.now(), role: 'assistant', content: data.content, timestamp: new Date().toISOString(), is_summary: true, structured: data.structured || null });
                const mc = getMsgContainer();
                if (mc) {
                  appendNewMessage(mc, renderMessage(messages[messages.length - 1], false, false), true);
                }
              } else if (eventType === 'warning') {
                // Quality warning — render as amber warning banner
                messages.push({
                  id: 'warn-' + Date.now(),
                  role: 'assistant',
                  content: data.message || 'Step completed with quality warnings',
                  timestamp: new Date().toISOString(),
                  is_warning: true
                });
                rerender();
              } else if (eventType === 'micro_phase') {
                // Micro-task phase status indicator
                const phaseLabels = {
                  'scope': 'Analyzing scope…',
                  'deep_dive': 'Detailing components…',
                  'interfaces': 'Mapping interfaces…',
                  'assemble': 'Writing requirements…',
                };
                const mc = getMsgContainer();
                if (data.status === 'in_progress') {
                  let pill = mc?.querySelector('.micro-phase-status');
                  if (!pill) {
                    pill = document.createElement('div');
                    pill.className = 'micro-phase-status';
                    mc?.appendChild(pill);
                  }
                  pill.textContent = phaseLabels[data.phase] || data.phase;
                } else if (data.status === 'done') {
                  const pill = mc?.querySelector('.micro-phase-status');
                  if (pill) pill.remove();
                }
              } else if (eventType === 'auto_install') {
                // Post-implementation dependency auto-install feedback
                const mc = getMsgContainer();
                if (mc && data.status === 'success' && data.packages?.length) {
                  const pill = document.createElement('div');
                  pill.className = 'auto-install-status';
                  pill.textContent = `Installed: ${data.packages.join(', ')}`;
                  mc.appendChild(pill);
                  // Auto-remove after 8 seconds
                  setTimeout(() => pill.remove(), 8000);
                } else if (mc && data.status === 'error' && data.errors?.length) {
                  const pill = document.createElement('div');
                  pill.className = 'auto-install-status auto-install-error auto-install-persistent';
                  pill.innerHTML = `<span class="auto-install-error-text">Install error: ${ZF._escHtml(data.errors[0])}</span>`
                    + `<button class="auto-install-retry-btn">Retry</button>`
                    + `<button class="auto-install-dismiss-btn">&times;</button>`;
                  mc.appendChild(pill);
                  pill.querySelector('.auto-install-dismiss-btn')?.addEventListener('click', () => pill.remove());
                  pill.querySelector('.auto-install-retry-btn')?.addEventListener('click', async () => {
                    pill.querySelector('.auto-install-retry-btn').textContent = 'Retrying...';
                    pill.querySelector('.auto-install-retry-btn').disabled = true;
                    try {
                      await fetch(`/api/tasks/${taskId}/retry-install`, { method: 'POST' });
                      pill.remove();
                    } catch (e) {
                      pill.querySelector('.auto-install-retry-btn').textContent = 'Retry';
                      pill.querySelector('.auto-install-retry-btn').disabled = false;
                    }
                  });
                }
              } else if (eventType === 'error') {
                // Display error from backend in chat
                const errMsg = data.error || 'An unexpected error occurred.';
                messages.push({
                  id: 'error-' + Date.now(),
                  role: 'system',
                  content: errMsg,
                  isWarning: true,
                });
                const mc = getMsgContainer();
                if (mc) {
                  renderMessages(mc, messages, generating, stepDescription, buildReviewBar());
                  wireReviewBar(mc);
                }
              } else if (eventType === 'step_completed') {
                paused = false; // Step finished — no longer paused
                if (data.stepId) {
                  // Always run review on step completion (code check is now part of review)
                  if (task?.settings?.autoStart) {
                    // Auto-start: review then advance to next step
                    pendingStepCompletedId = data.stepId;
                  }
                  startReview('Please review my changes');
                  // If not auto-start, still notify step completed (no pending advance)
                  if (!task?.settings?.autoStart) {
                    onStepCompleted?.(data.stepId);
                  }
                }
              } else if (eventType === 'done') {
                paused = false; // Generation finished — no longer paused
                // Stamp thinking duration if not already stamped by tool_call
                if (thinkingStartTime) {
                  const last = messages[messages.length - 1];
                  if (last && last.role === 'assistant' && !last.thinkingDuration) {
                    last.thinkingDuration = (Date.now() - thinkingStartTime) / 1000;
                  }
                  thinkingStartTime = null;
                }
                // Handle stalled agent warning
                if (data.stalled) {
                  messages.push({
                    id: 'stalled-' + Date.now(),
                    role: 'system',
                    content: 'The agent exhausted its maximum turns without completing. The step may be too complex — try breaking it into smaller sub-steps or restarting.',
                    isWarning: true,
                  });
                }
                resetStreamingState();
                // Also reload final state from server to pick up any messages we missed
                setTimeout(async () => {
                  try {
                    const list = await ZF.api.getChats(taskId);
                    const fresh = list.find(c => c.id === activeChatId);
                    if (fresh) {
                      const freshMessages = fresh.messages || [];
                      if (freshMessages.length !== messages.length) {
                        messages = freshMessages;
                        rerender();
                      }
                    }
                  } catch (e) { console.error('[Chat] Message reload error:', e); }
                }, 500);
                return;
              } else if (eventType === 'error') {
                console.error('[Chat] Server error:', data.error);
                // Push an error message so it renders in the chat
                messages.push({
                  id: 'err-' + Date.now(),
                  role: 'assistant',
                  content: data.error || 'An unknown error occurred',
                  timestamp: new Date().toISOString(),
                  is_error: true
                });
                resetStreamingState();
                return;
              }
            } catch (parseErr) { console.error('[Chat] SSE parse error:', parseErr); }
          }
        }

        // Stream ended naturally
        if (!ac.signal.aborted) {
          resetStreamingState();
        }
      } catch(err) {
        if (err.name === 'AbortError') { _activeStreams.delete(activeChatId); return; }
        console.error('[Chat] Stream error:', err.message);
        resetStreamingState();

        if (isKickoff && retryCount < MAX_RETRIES) {
          retryCount++;
          const delay = retryCount * 10000;
          console.log(`[Chat] Retry ${retryCount}/${MAX_RETRIES} in ${delay/1000}s`);
          setTimeout(async () => {
            try { const list = await ZF.api.getChats(taskId); const f = list.find(c => c.id === activeChatId); if (f) messages = f.messages || []; } catch {}
            if (chatId) _kickoffFired.delete(chatId);
            autoStartFired = false;
            handleSend(text, true);
          }, delay);
        }
      }
    }

    // Load chats and try auto-start
    async function init() {
      try {
        const list = await ZF.api.getChats(taskId);
        let chat = null;
        if (chatId) {
          chat = list.find(c => c.id === chatId);
          if (!chat) {
            // Retry up to 5 times
            for (let i = 0; i < 5 && !chat; i++) {
              await new Promise(r => setTimeout(r, 500));
              const retry = await ZF.api.getChats(taskId);
              chat = retry.find(c => c.id === chatId);
            }
          }
        } else if (list.length > 0) {
          chat = list[0];
        } else {
          chat = await ZF.api.createChat(taskId);
        }

        if (chat) {
          messages = chat.messages || [];
          // Restore review state from persisted data
          if (chat.review && chat.review.content) {
            reviewState = 'done';
            reviewContent = chat.review.content;
            reviewEdits = chat.review.edits || [];
            reviewEditDetails = chat.review.editDetails || [];
          }
          rerender();
          // Try auto-start
          if (!paused && chatId && !_kickoffFired.has(chatId) && !autoStartFired && messages.length === 0 && task?.details) {
            autoStartFired = true;
            _kickoffFired.add(chatId);
            handleSend(buildKickoff(task, chatId), true);
          }
        }
      } catch(e) { console.error('[Chat] Init error:', e); }
      renderComposer();
    }

    // Cleanup
    function destroy() {
      if (abortController) { abortController.abort(); abortController = null; }
    }

    init();
    return { element: wrapper, destroy, handleSend, isStreaming: () => generating };
  }

  window.ZF.chat = { createChatPanel, _kickoffFired, _activeStreams };
})();
