// ── Thinking Parser & Renderer ───────────────────────────
window.ZF = window.ZF || {};

(function() {
  function stripHeading(text) { return text.replace(/^#{1,4}\s+/, '').trim(); }

  // ── High-Level Topic Classification ──────────────────────
  // Classify a chunk of thinking text into a high-level topic category.
  // Uses keyword matching against the content to find the best-fit category.
  const TOPIC_CATEGORIES = [
    { label: 'Scope Analysis',              keys: /\b(scope|complexity|component count|deliverable|what is being built|task analysis|functional pieces|simple or medium|simple or complex)\b/i },
    { label: 'Component Analysis',          keys: /\b(component detail|deep.?dive|behavior|inputs? and outputs?|edge cases?|per component|for each component|component requirements)\b/i },
    { label: 'Interface Design',            keys: /\b(interface between|communication|between components|data passing|direction|bidirectional|coupling|dependency graph|component pair)\b/i },
    { label: 'Step Completion',             keys: /\b(step complete|artifact saved|validated|completing step|all files saved|wrapping up|auto.?complete)\b/i },
    { label: 'Understanding the Task',       keys: /\b(task|user wants|user asked|prompt|request|goal|objective|what they want|what is being asked|understand|interpret)\b/i },
    { label: 'Analyzing Requirements',       keys: /\b(requirement|feature|need|must have|should have|acceptance criteria|constraint|scope|in scope|out of scope|non-goal|PRD)\b/i },
    { label: 'Architecture & Design',        keys: /\b(architect|design|structure|pattern|module|component|layer|separation|MVC|API|interface|abstraction|system design)\b/i },
    { label: 'Technology Decisions',         keys: /\b(technology|framework|library|stack|python|javascript|database|SQL|sqlite|react|flask|dependencies|package|tool|tooling|version)\b/i },
    { label: 'File Structure',              keys: /\b(file|directory|folder|path|\.py|\.js|\.md|\.json|\.css|\.html|filename|naming|project structure)\b/i },
    { label: 'Implementation Approach',      keys: /\b(implement|code|function|class|method|algorithm|logic|write the|build|create the|develop|construct)\b/i },
    { label: 'Data & Storage',              keys: /\b(data|database|storage|schema|table|column|record|field|store|persist|cache|memory|state)\b/i },
    { label: 'Error Handling',              keys: /\b(error|exception|handling|retry|fallback|validation|edge case|failure|catch|try|robust)\b/i },
    { label: 'Testing Strategy',            keys: /\b(test|testing|unit test|integration|coverage|assert|verify|validate|QA|spec)\b/i },
    { label: 'Planning Steps',              keys: /\b(plan|step|phase|breakdown|task list|checklist|order|sequence|first.*then|workflow|pipeline|stages|dependency order|entry point|buildable|heading)\b/i },
    { label: 'Evaluating Trade-offs',       keys: /\b(trade.?off|pros? and cons?|alternatively|versus|compared|option|choice|decide|decision|consider|weigh)\b/i },
    { label: 'Complexity Assessment',        keys: /\b(complex|simple|trivial|straightforward|difficult|easy|minimal|overhead|scope|effort)\b/i },
    { label: 'Output Formatting',           keys: /\b(format|markdown|JSON|escape|string|content|output|template|render|display|WriteFile|write file|save)\b/i },
    { label: 'Security & Validation',       keys: /\b(security|auth|permission|validate|sanitize|input|injection|safe|protect|credential)\b/i },
    { label: 'Performance',                 keys: /\b(performance|speed|optimize|efficient|fast|slow|latency|throughput|scalable|memory usage)\b/i },
  ];

  function classifyTopic(text) {
    let bestLabel = null;
    let bestScore = 0;
    for (const cat of TOPIC_CATEGORIES) {
      const matches = text.match(cat.keys);
      const score = matches ? matches.length : 0;
      if (score > bestScore) {
        bestScore = score;
        bestLabel = cat.label;
      }
    }
    return bestLabel || 'Reasoning';
  }

  // ── Topic-aware text splitting ──────────────────────────
  // Split continuous text into chunks, then classify and merge by topic.

  // Patterns that signal a shift in reasoning (used for initial chunking)
  const BREAK_RE = /^(?:Now[,\s]|Next[,\s]|So[,\s]|However[,\s]|But[,\s]|Also[,\s]|Additionally[,\s]|Furthermore[,\s]|Let me|Let's|I (?:need to|should|will|can|think|believe)|First[,\s]|Second(?:ly)?[,\s]|Third(?:ly)?[,\s]|Finally[,\s]|In (?:summary|conclusion|terms of|addition)|To (?:summarize|start|begin|do this)|The (?:key|main|first|next|last|final|most important)|Moving (?:on|forward)|Looking at|Considering|Thinking about|Regarding|For (?:the|this|each)|On the other hand|Another (?:thing|approach|option|consideration|important)|Wait[,\s]|Actually[,\s]|Hmm[,\s]|Alright[,\s]|Okay[,\s]|OK[,\s]|Given (?:that|this)|Based on|This (?:means|suggests|indicates|implies|requires)|We (?:need|should|can|could|must)|One (?:approach|option|thing|way)|There (?:are|is|should)|What (?:about|if)|How (?:about|should|can|do)|Overall[,\s]|In this case)/i;

  // Split text into raw chunks (before classification)
  function splitIntoRawChunks(text) {
    // Try \n\n splitting first
    const doubleNewlineParts = text.split(/\n\n+/);
    if (doubleNewlineParts.length > 1) {
      return doubleNewlineParts.map(p => p.trim()).filter(p => p);
    }

    // Split on single newlines at topic transitions
    const lines = text.split('\n');
    if (lines.length <= 1) {
      return splitSentences(text);
    }

    const chunks = [];
    let current = '';
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      if (current && trimmed.length > 20 && BREAK_RE.test(trimmed)) {
        if (current.trim()) chunks.push(current.trim());
        current = trimmed;
      } else {
        current += (current ? '\n' : '') + trimmed;
      }
    }
    if (current.trim()) chunks.push(current.trim());

    if (chunks.length === 1 && chunks[0].length > 300) {
      return splitSentences(chunks[0]);
    }
    return chunks;
  }

  // Split a long string by sentences at topic transitions
  function splitSentences(text) {
    const sentences = text.match(/[^.!?]+[.!?]+(?:\s|$)|[^.!?]+$/g);
    if (!sentences || sentences.length <= 1) return [text];

    const chunks = [];
    let current = '';
    for (const sent of sentences) {
      const trimmed = sent.trim();
      if (!trimmed) continue;
      if (current.length > 120 && BREAK_RE.test(trimmed)) {
        if (current.trim()) chunks.push(current.trim());
        current = trimmed;
      } else {
        current += (current ? ' ' : '') + trimmed;
      }
    }
    if (current.trim()) chunks.push(current.trim());
    return chunks;
  }

  // Classify raw chunks and merge ALL chunks with the same topic (not just consecutive)
  // This groups all "Analyzing Requirements" content together, all "File Structure" together, etc.
  function classifyAndMerge(rawChunks) {
    if (rawChunks.length === 0) return [];

    const classified = rawChunks.map(chunk => ({
      topic: classifyTopic(chunk),
      content: chunk
    }));

    // Group all chunks by topic, preserving first-seen order
    const topicOrder = [];
    const topicMap = new Map();
    for (const item of classified) {
      if (topicMap.has(item.topic)) {
        topicMap.get(item.topic).push(item.content);
      } else {
        topicOrder.push(item.topic);
        topicMap.set(item.topic, [item.content]);
      }
    }

    return topicOrder.map(topic => ({
      topic,
      content: topicMap.get(topic).join('\n\n')
    }));
  }

  function parseSections(text, isStreaming) {
    if (!text || !text.trim()) return [];
    // Strip GPT-OSS format tags and delimited blocks from reasoning content
    text = text.replace(/<\|[a-z_]+\|>[^<]*(?=<\|)/gi, '')
               .replace(/<\|[a-z_]+\|>/gi, '')
               .replace(/<\/?tool_code>/gi, '')
               .replace(/commentary\s+to=\w+[^a-z]*/gi, '')
               .replace(/json>\s*\{[^}]*\}?\s*/gi, '')
               .replace(/\{[^}]*"name"\s*:\s*"[^"]*"[^}]*\}/g, '')
               .replace(/"[a-z_]+"\s*:\s*"[^"]*"/g, '')
               .replace(/[{}[\]]+/g, '')
               .replace(/[\u2026]{2,}/g, '')
               .replace(/\.{2,}/g, '.')
               .replace(/\?{2,}/g, '?')
               .replace(/[?.]{3,}/g, '')
               .replace(/[?.!\u2026\u2011\u2013\u2014-]{4,}/g, '')
               .replace(/[\u00e2][\u0080-\u009f][\u0080-\u00bf]/g, '')
               .replace(/[ \t]{2,}/g, ' ')
               .replace(/\n{3,}/g, '\n\n').trim();
    if (!text) return [];

    // 1. Split into raw chunks
    const rawChunks = splitIntoRawChunks(text);

    // 2. Filter out noise
    const filtered = rawChunks.filter(p => {
      const t = p.trim();
      if (!t) return false;
      if (t.length <= 5) return false;
      const alphaCount = (t.match(/[a-zA-Z]/g) || []).length;
      if (t.length > 5 && alphaCount / t.length < 0.3) return false;
      return true;
    });

    if (filtered.length === 0) return [];

    // 3. Classify and merge by topic
    const topicGroups = classifyAndMerge(filtered);

    // 4. Build sections
    const sections = topicGroups.map((group, idx) => ({
      id: `t-${idx}`,
      title: group.topic,
      content: group.content,
      isStreaming: isStreaming && idx === topicGroups.length - 1
    }));

    if (sections.length === 1 && sections[0].content.length < 20) return [];
    return sections;
  }

  function groupTitle(sections) {
    if (sections.length === 0) return 'Thinking';
    const first = sections[0].title;
    return first === 'Thinking...' ? 'Reasoning' : first;
  }

  // Format thinking duration for display
  function formatDuration(seconds) {
    if (!seconds || seconds < 1) return null;
    if (seconds < 60) return `${Math.round(seconds)} seconds`;
    const mins = Math.floor(seconds / 60);
    const secs = Math.round(seconds % 60);
    if (secs === 0) return `${mins} minute${mins > 1 ? 's' : ''}`;
    return `${mins}m ${secs}s`;
  }

  // ── Summarize raw thinking into a short prose paragraph ──
  // The LLM's chain-of-thought is verbose stream-of-consciousness.
  // We distill it into a 3-4 sentence high-level summary so users
  // can quickly see what the AI concluded without reading the wall of text.

  // Technical keywords — lines containing these are valuable even if they match filler patterns
  const TECHNICAL_KEYWORDS_RE = /\b(?:function|class|module|file|import|api|route|endpoint|database|model|server|config|parse|component|handler|schema|validate|error|test|format|render|query|template|argument|parameter|variable|method|interface|array|object|dictionary|list|string|integer|boolean|async|request|response|middleware|token|auth|cache|package|dependency|framework|library|algorithm|data|index|column|table|record|stream|buffer|queue|path|url|json|yaml|csv|xml|html|css|react|flask|django|express|git|docker|pip|npm|venv)\b/i;
  // Filler — only truly empty self-talk (stripped down from aggressive version)
  const FILLER_RE = /^(?:Need to |Now (?:we|I|let)|So (?:we|I|let)|OK(?:ay)?,? |Alright,? |Hmm,? |Also (?:mention|note)|Not specified|This is feature|Use ["'])/i;
  // Short throwaway lines (< 20 chars) — only truly empty words
  const SHORT_FILLER_RE = /^(?:ok|okay|yes|no|right|sure|got it|do it)/i;
  // Meta — internal notes about formatting, tool calls, escaping, prompt-following
  const META_RE = /\b(?:use \\n|avoid double|escape if|no triple|single quote|double quotes|content string|markdown content|WriteFile|write file|compose content|craft content|call plan|call WriteFile|produce features|create the (?:markdown|PRD|content)|produce the|ensure no placeholder|need to (?:call|produce|create|ensure)|should create the|craft final|use \\n for|newlines (?:inside|in) content|No UI or stdout|no placeholders|system message|developer (?:says|wants|instruction)|highest priority|instruction (?:conflict|priority|hierarchy)|there's a conflict|must be at least \d+ sentences|reasoning (?:must|should) be|go straight to tool|analysis (?:must|first)|resolve.*conflict|prompt (?:says|asks|wants|requires))\b/i;
  // Label lines like "Non-goals: ...", "Constraints: ..."
  const LABEL_RE = /^(?:Constraints|Non-goals|Non goals|Assumptions|Requirements|Features|Inputs|Outputs|Dependencies|Notes|Summary|Overview|Platform|Language|Goals|Trade-offs|Tradeoffs|Approach|Decision|Conclusion|Result|Reason|Problem|Solution|Context|Scope|Priority|Status|Risk|Impact|Edge)[&\w\s,]*:/i;

  function formatThinkingBody(text) {
    if (!text || !text.trim()) return text;
    let t = text;

    // ── Hard sanitize: strip JSON/tool junk that leaks into thinking ──
    t = t.replace(/\{[^}]*"name"\s*:\s*"[^"]*"[^}]*\}/g, '');  // JSON tool call objects
    t = t.replace(/"[a-z_]+"\s*:\s*"[^"]*"/g, '');              // JSON key-value pairs
    t = t.replace(/[{}[\]]/g, '');                                // stray braces/brackets
    t = t.replace(/\\n/g, '\n');                                  // literal \n to newline
    t = t.replace(/\\"/g, '"');                                   // escaped quotes
    t = t.replace(/\\\\/g, '');                                   // remaining backslash escapes
    t = t.replace(/"{3,}/g, '"');                                 // 3+ quotes → single
    t = t.replace(/`{3,}/g, '`');                                 // 3+ backticks → single
    t = t.replace(/\s*,\s*,+/g, ',');                             // doubled commas
    t = t.replace(/[?.!]{2,}/g, match => match[0]);               // repeated punctuation → single
    t = t.replace(/^\s*[,;:)\]}>]+/gm, '');                      // lines starting with stray punctuation
    t = t.replace(/\n{3,}/g, '\n\n');                             // excessive blank lines
    t = t.trim();
    if (!t) return 'Considered options and continued reasoning.';

    // ── Tokenise into sentences ──
    // Break inline numbered lists so each item is its own line
    if (/\b1\.\s+\S/.test(t) && /\b2\.\s+\S/.test(t)) {
      t = t.replace(/ (\d{1,2})\. (?=\S)/g, (m, num, off) => {
        const n = parseInt(num);
        if (n < 1 || n > 20 || off === 0 || t[off - 1] === '\n') return m;
        return '\n' + num + '. ';
      });
    }
    // Break at sentence boundaries
    t = t.split('\n').map(line =>
      line.replace(/([a-zA-Z)\]][.!?])\s+([A-Z])/g, '$1\n$2')
    ).join('\n');

    const lines = t.split('\n').map(l => l.trim()).filter(Boolean);

    // ── Collect structured data ──
    const labels = {};        // key → value  e.g. "Non-goals" → "no UI, no auth..."
    const listNames = [];     // condensed item names from numbered lists
    let currentList = [];
    const listGroups = [];
    const substantive = [];   // non-filler, non-meta sentences

    for (const s of lines) {
      // Label line
      const lm = s.match(/^([^:]+):\s+(.*)/);
      if (LABEL_RE.test(s) && lm) {
        // Normalize key for dedup (lowercase, collapse whitespace/punctuation)
        const rawKey = lm[1].trim();
        const normKey = rawKey.toLowerCase().replace(/[^a-z]/g, '');
        // Keep the first occurrence of each label type (skip duplicates)
        if (!labels[normKey]) labels[normKey] = { display: rawKey, value: lm[2].trim() };
        continue;
      }
      // Numbered list item
      if (/^\d+\.\s/.test(s)) { currentList.push(s); continue; }
      // End of a numbered run
      if (currentList.length > 0) { listGroups.push([...currentList]); currentList = []; }
      // Regular sentence — keep if substantive
      // Filler lines are kept if they contain technical keywords
      if (FILLER_RE.test(s) && !TECHNICAL_KEYWORDS_RE.test(s)) continue;
      if (META_RE.test(s)) continue;
      if (s.length < 20 && SHORT_FILLER_RE.test(s)) continue;
      if (s.length > 8) substantive.push(s);
    }
    if (currentList.length > 0) listGroups.push(currentList);

    // Keep longest numbered list (model often drafts twice)
    const bestList = listGroups.length > 0
      ? listGroups.reduce((a, b) => b.length >= a.length ? b : a, [])
      : [];

    // Condense each list item to just its name
    for (const item of bestList) {
      const content = item.replace(/^\d+\.\s*/, '');
      const nm = content.match(/^([^:.(]+?)(?:\s*[:.(]|\s+(?:that|which|with|accepting|inserting|performing|using)\b)/);
      listNames.push(nm ? nm[1].trim() : (content.length > 50 ? content.substring(0, 47) + '...' : content));
    }

    // ── Build a prose paragraph (3-4 sentences max) ──
    const sentences = [];

    // Sentence 1: What items/features were identified
    if (listNames.length > 0) {
      const shown = listNames.length <= 4
        ? listNames.join(', ')
        : listNames.slice(0, 3).join(', ') + `, and ${listNames.length - 3} more`;
      sentences.push(`Identified ${listNames.length} key items: ${shown}.`);
    }

    // Helper: truncate at word boundary
    function truncAt(str, max) {
      if (str.length <= max) return str;
      const cut = str.lastIndexOf(' ', max);
      return (cut > max * 0.5 ? str.substring(0, cut) : str.substring(0, max)) + '...';
    }

    // Sentence 2-3: Label-based info (Non-goals, Constraints, etc.)
    const labelKeys = Object.keys(labels);
    for (const key of labelKeys) {
      if (sentences.length >= 3) break;
      const { display, value } = labels[key];
      sentences.push(`${display}: ${truncAt(value, 70)}.`.replace(/\.{2,}/g, '.').replace(/\.\s*\./g, '.'));
    }

    // Fill remaining slots from substantive sentences (pick the most info-dense)
    if (sentences.length < 3) {
      // Prefer longer substantive sentences (more info-dense)
      const sorted = [...substantive].sort((a, b) => b.length - a.length);
      for (const s of sorted) {
        if (sentences.length >= 3) break;
        // Clean up: truncate and ensure ends with period
        const trimmed = truncAt(s.replace(/[,;:]$/, ''), 100);
        const clean = trimmed + (trimmed.match(/[.!?]$/) ? '' : '.');
        // Skip if it substantially overlaps with what we already have
        const existing = sentences.join(' ').toLowerCase();
        const words = clean.toLowerCase().split(/\s+/);
        const overlap = words.filter(w => w.length > 4 && existing.includes(w)).length;
        if (overlap > words.length * 0.4) continue;
        sentences.push(clean);
      }
    }

    // Fallback: if nothing extracted, take first 2 non-filler lines
    if (sentences.length === 0) {
      const fallback = lines.filter(l => {
        if (FILLER_RE.test(l) || META_RE.test(l)) return false;
        if (l.length < 25 && SHORT_FILLER_RE.test(l)) return false;
        return l.length > 15;
      });
      if (fallback.length === 0) return 'Considered options and continued reasoning.';
      return fallback.slice(0, 2).map(l => truncAt(l, 100)).join('. ').replace(/\.{2,}/g, '.') + '.';
    }

    // Final cleanup: strip stray punctuation/symbols from the assembled output
    let result = sentences.slice(0, 3).join(' ');
    result = result.replace(/[{}[\]"\\`]+/g, '');         // any remaining junk chars
    result = result.replace(/\s*,\s*,+/g, ',');            // doubled commas
    result = result.replace(/[?.!]{2,}/g, m => m[0]);      // repeated punctuation
    result = result.replace(/\s{2,}/g, ' ').trim();        // collapse spaces
    return result || 'Considered options and continued reasoning.';
  }

  // Render a thinking group (collapsible)
  // When streaming (!isComplete), the group is ALWAYS expanded and the last section
  // is ALWAYS open so the user sees live thinking content at all times.
  function renderThinkingGroup(sections, isComplete, durationSec) {
    if (sections.length === 0) return '';
    const title = groupTitle(sections);
    const groupId = 'tg-' + Math.random().toString(36).slice(2, 8);
    const collapsed = isComplete;
    let sectionsHtml = '';
    sections.forEach((s, i) => {
      const isLast = i === sections.length - 1;
      const bodyContent = s.content.replace(/^#{1,4}\s+[^\n]*\n?/, '').trimStart();
      const sectionId = groupId + '-s' + i;
      // During streaming: last section is always expanded (shows live content)
      // When complete: all sections start collapsed
      const sectionExpanded = isLast && !isComplete;
      sectionsHtml += `<div class="thinking-section">
        <div class="thinking-section-header" data-toggle="${sectionId}">
          <span style="margin-top:2px;flex-shrink:0;color:var(--color-text-tertiary);">${sectionExpanded ? ZF.icons.chevronDown(14) : ZF.icons.chevronRight(14)}</span>
          <span class="thinking-section-title">${ZF._escHtml(s.title)}</span>
          ${s.isStreaming ? '<span class="thinking-pulse" style="margin-top:4px;margin-left:4px;flex-shrink:0;"></span>' : ''}
        </div>
        <div class="thinking-section-body" id="${sectionId}" style="display:${sectionExpanded ? 'block' : 'none'};">
          ${bodyContent.trim() ? ZF.markdown.render(formatThinkingBody(bodyContent)) : ''}
        </div>
      </div>`;
    });

    const durationStr = isComplete ? formatDuration(durationSec) : null;
    // During streaming: show the current topic category as the label
    // When complete: show "Thought for X seconds"
    const streamingLabel = !isComplete && sections.length > 0
      ? ZF._escHtml(sections[sections.length - 1].title)
      : null;
    const headerLabel = durationStr ? `Thought for ${durationStr}` : (streamingLabel || ZF._escHtml(title));
    const countBadge = collapsed ? `<span class="thinking-group-count">${sections.length} ${sections.length === 1 ? 'topic' : 'topics'}</span>` : '';
    // During streaming show topic count inline
    const streamingCount = !isComplete && sections.length > 1
      ? `<span class="thinking-group-count">${sections.length} ${sections.length === 1 ? 'topic' : 'topics'}</span>`
      : '';
    const activePulse = !isComplete ? '<span class="thinking-pulse" style="margin-left:6px;"></span>' : '';

    return `<div class="thinking-group" id="${groupId}">
      <div class="thinking-group-header" data-toggle="${groupId}-body">
        <span style="color:var(--color-text-tertiary);">${collapsed ? ZF.icons.chevronRight(14) : ZF.icons.chevronDown(14)}</span>
        <span class="thinking-group-label">${headerLabel}</span>
        ${activePulse}
        ${collapsed ? countBadge : streamingCount}
      </div>
      <div class="thinking-sections-container" id="${groupId}-body" style="margin-left:4px;padding-left:12px;border-left:1px solid var(--color-thinking-border);display:${collapsed ? 'none' : 'flex'};">
        ${sectionsHtml}
      </div>
    </div>`;
  }

  // Toggle handler
  document.addEventListener('click', (e) => {
    const header = e.target.closest('[data-toggle]');
    if (!header) return;
    // Only handle thinking toggles
    if (!header.classList.contains('thinking-group-header') && !header.classList.contains('thinking-section-header')) return;
    const targetId = header.dataset.toggle;
    const target = document.getElementById(targetId);
    if (!target) return;
    const isHidden = target.style.display === 'none';
    target.style.display = isHidden ? (target.classList.contains('thinking-sections-container') ? 'flex' : 'block') : 'none';
    // Update chevron
    const chevron = header.querySelector('span:first-child');
    if (chevron) chevron.innerHTML = isHidden ? ZF.icons.chevronDown(14) : ZF.icons.chevronRight(14);
  });

  // Clean filler/noise from raw text (same logic as parseSections pre-filter)
  function cleanFiller(text) {
    if (!text) return '';
    return text.replace(/<\|[a-z_]+\|>[^<]*(?=<\|)/gi, '')
               .replace(/<\|[a-z_]+\|>/gi, '')
               .replace(/<\/?tool_code>/gi, '')
               .replace(/commentary\s+to=\w+[^a-z]*/gi, '')
               .replace(/json>\s*\{[^}]*\}?\s*/gi, '')
               .replace(/[\u2026]{2,}/g, '')
               .replace(/\.{2,}/g, '.')
               .replace(/\?{2,}/g, '?')
               .replace(/[?.]{3,}/g, '')
               .replace(/[?.!\u2026\u2011\u2013\u2014-]{4,}/g, '')
               .replace(/[\u00e2][\u0080-\u009f][\u0080-\u00bf]/g, '')
               .replace(/\s{2,}/g, ' ').trim();
  }

  // Generate a title from arbitrary text (wrapper for fallback)
  function generateTitleFromText(text) {
    if (!text) return 'Thinking...';
    return classifyTopic(text);
  }

  window.ZF.thinking = { parseSections, renderThinkingGroup, groupTitle, cleanFiller, generateTitleFromText, formatThinkingBody };
})();
