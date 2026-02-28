# AWM Institute of Technology (OIT) — Agent Instructions (Part 3 of 4)
# =====================================================================
# **Continuation of:** `agents-2.md` (Sections 7-17)
# **Continued in:** `agents-4.md` (Section 24)
# This file covers Sections 18-23: Chat Systems, Q&A Data Structures,
# Q&A Engine, Adding Q&A Content, Chat API Flow, Bank Merging.

---

## 18. Chat Systems Overview

OIT has **two chat interfaces** that share the same backend API but differ
in context, features, and UI.

### 18.1 Standalone Chat (`/chat`)

**Purpose:** General-purpose chatbot for all AWMIT topics.

| Property | Value |
|----------|-------|
| Template | `chat.html` |
| JS files | `chat-core.js`, `chat-messages.js`, `chat-autocomplete.js` |
| Class | `AgentChat` |
| Agent name | "AWMIT Assistant" |
| API params | `{ message, pendingFollowUp }` |
| Banks used | Global (all categories merged) |

**Features exclusive to standalone chat:**
- **Autocomplete** — Dropdown suggestions as user types (≥2 chars)
- **Next-question chips** — "Suggested" follow-ups after each answer
- **Module references** — Links to source module when answer comes
  from a module-scoped bank
- **Video cards with module links** — "View in Module" button on videos
- **Welcome typewriter** — Animated subtitle typed at 30ms per char
- **Custom input cursor** — Tracks caret position visually
- **Welcome chips** — "Say Hello" and "What Can You Do?" quick-start buttons

### 18.2 Module Viewer Coach (`/modules/<slug>/<section>`)

**Purpose:** Context-aware AI coach for the current video section.

| Property | Value |
|----------|-------|
| Template | `module_viewer.html` |
| JS files | `viewer-core.js`, `viewer-video.js`, `viewer-timeline.js`, `viewer-chat.js` |
| Class | `ModuleCoach` |
| Agent name | "AWMIT Coach" |
| API params | `{ message, pendingFollowUp, moduleSlug }` |
| Banks used | Module-scoped (`MODULE_BANKS[slug]`) |

**Features exclusive to module coach:**
- **Quick chips** — Preset action buttons (e.g., "Video Summary")
  with `data-query` attributes in HTML
- **Section navigator** — "IN THIS TOPIC" panel with breakdown items
  linked to video timestamps
- **Video integration** — Timeline, playback controls, seek-to-section
- **Context-aware placeholder** — "Ask about {module.title}..."
- **Module data injection** — `window.MODULE_DATA` JSON in template
- **Context-aware welcome** — "I'm your AWMIT coach for **{module}** —
  **{section}**." with status dot

**Features NOT in module coach (standalone only):**
- No autocomplete dropdown
- No next-question chips after answers
- No module reference links (already in the module)
- No custom input cursor

### 18.3 Shared Between Both

- Same backend API (`POST /api/chat`, `POST /api/chat/resolve`)
- Same typewriter effect (6ms per character, HTML-aware tokenization)
- Same follow-up question buttons (different CSS class prefixes)
- Same message format (avatar + sender name + body)
- Same `formatMessage()` HTML sanitization
- Same typing indicator ("Thinking" + 3 animated dots)

### 18.4 Key CSS Class Differences

| Element | Standalone | Module Viewer |
|---------|-----------|---------------|
| Message | `.chat-msg` | `.viewer-msg` |
| Agent msg | `.agent-msg` | `.viewer-agent-msg` |
| User msg | `.user-msg` | `.viewer-user-msg` |
| Follow-up btn | `.followup-btn` | `.viewer-followup-btn` |
| Disabled btn | `.followup-btn-disabled` | `.viewer-followup-btn-disabled` |
| Selected btn | `.followup-btn-selected` | `.viewer-followup-btn-selected` |
| Typing msg | `.typing-msg` | `.viewer-typing-msg` |
| Input | `.chat-input` | `.viewer-chat-input` |
| Send btn | `.chat-send-btn` | `.viewer-send-btn` |

---

## 19. Q&A Data Structures

Every Q&A topic file exports up to 5 dicts/lists. Category `__init__.py`
files merge them and build `MODULE_BANKS`.

### 19.1 ANSWERS (required)
```python
ANSWERS: dict[str, str] = {
    'copilot-basics-intro-summary': "Full answer text here...",
    'copilot-basics-intro-example': "Another answer...",
}
```
- Key: Answer ID (format: `{category}-{slug}-{section}-{descriptor}`)
- Value: Plain text answer (can contain `<strong>`, `<br>` tags)

### 19.2 SUGGESTIONS (required)
```python
SUGGESTIONS: list[dict] = [
    {'text': 'What is Copilot?', 'keywords': ['copilot', 'what', 'about']},
]
```
- `text`: Display text in autocomplete dropdown
- `keywords`: Words that trigger this suggestion

### 19.3 QA_ENTRIES (required)
```python
# Direct answer:
{'keywords': ['what', 'copilot', 'overview'], 'answer': 'copilot-basics-intro-summary'}

# Follow-up question:
{
    'keywords': ['install', 'setup', 'get started'],
    'followUp': {
        'question': 'Which OS are you on?',
        'options': [
            {'label': 'Windows', 'keywords': ['windows', 'pc'],
             'answerId': 'copilot-basics-install-windows'},
            {'label': 'Mac', 'keywords': ['mac', 'macos'],
             'answerId': 'copilot-basics-install-mac'},
        ]
    }
}
```

### 19.4 NEXT_QUESTIONS (optional)
```python
NEXT_QUESTIONS: dict[str, list[str]] = {
    'copilot-basics-intro-summary': [
        'Show me a real example',
        'How do I install Copilot?',
        'How do I get GitHub Copilot access?',
    ],
}
```
- Key: Answer ID
- Value: List of 3 suggested follow-up question strings
- Only displayed by standalone chat (not module coach)

### 19.5 VIDEOS (optional)
```python
VIDEOS: dict[str, dict] = {
    'copilot-basics-intro-summary': {
        'src': 'modules/copilot-basics/intro/video.mp4',
        'label': 'Introduction Overview',
        'moduleUrl': '/modules/copilot-basics/intro',
    },
}
```
- Key: Answer ID
- Value: Video metadata dict (`src`, `label`, optional `moduleUrl`)

---

## 20. Q&A Engine (backend/qa/engine.py)

### 20.1 Query Resolution Flow
```
User input → normalize() → select banks (global or module-scoped)
  → if pendingFollowUp: score follow-up options first
  → score all QA_ENTRIES in active bank
  → best score ≥ 5? → return answer or followUp
  → else → return noMatch
```

### 20.2 Keyword Scoring (`_score_keywords`)

| Match Type | Points | Example |
|-----------|--------|---------|
| Exact phrase | +10 | keyword "use case" in "show me a use case" |
| Exact word | +5 | keyword "copilot" equals word "copilot" |
| Prefix/stem | +2 | keyword "install" matches "installing" |

**Minimum threshold:** 5 points (one exact word match minimum).

### 20.3 Bank Selection
```python
if module_slug and module_slug in module_banks:
    # Use MODULE_BANKS[slug] — module-specific answers only
else:
    # Use global merged banks — all categories combined
```

### 20.4 Answer Enrichment (`_build_answer`)

After finding a match, the engine enriches the answer:
- **video** — module-scoped videos first, then global `video_bank`
- **nextQuestions** — module-scoped first, then global `next_questions_bank`
- **moduleRef** — when NOT in module scope, adds `{name, url}` link
  to parent module (from `answer_module_map`)

### 20.5 Key Functions

| Function | Purpose |
|----------|---------|
| `resolve_query(query, pending?, slug?)` | Main entry — answer, followUp, or noMatch |
| `resolve_by_answer_id(answer_id)` | Direct lookup for follow-up clicks |
| `get_autocomplete(query, limit=5, slug?)` | Top N suggestions for autocomplete |
| `normalize(query)` | Lowercase, strip punctuation, collapse spaces |
| `_score_keywords(query, keywords)` | Score query against keyword list |
| `_build_answer(aid, text, slug?)` | Enrich with video, nextQuestions, moduleRef |

---

## 21. Adding Q&A Content

### 21.1 Create a Topic File

File: `backend/qa/<category>/<topic_name>.py`
```python
ANSWERS = {
    'category-slug-section-descriptor': "Answer text...",
}
SUGGESTIONS = [
    {'text': 'Display text', 'keywords': ['keyword1', 'keyword2']},
]
QA_ENTRIES = [
    {'keywords': ['word1', 'word2'], 'answer': 'category-slug-section-descriptor'},
]
NEXT_QUESTIONS = {
    'category-slug-section-descriptor': [
        'Follow-up question 1', 'Follow-up question 2', 'Follow-up question 3',
    ],
}
```

### 21.2 Register in Category __init__.py
```python
from backend.qa.category.topic_name import (
    ANSWERS as _aN, SUGGESTIONS as _sN,
    QA_ENTRIES as _qN, NEXT_QUESTIONS as _nqN,
)
# Merge into existing dicts:
ANSWERS = {**_a1, ..., **_aN}
SUGGESTIONS = _s1 + ... + _sN
QA_ENTRIES = _q1 + ... + _qN
NEXT_QUESTIONS = {**_nq1, ..., **_nqN}
```

### 21.3 Add to MODULE_BANKS
```python
MODULE_BANKS = {
    'module-slug': {
        'answers': {**_aN},
        'suggestions': _sN,
        'qa_entries': _qN,
        'next_questions': {**_nqN},
    },
}
```

### 21.4 Keyword Tips
- Use 5-10 keywords per entry for good coverage
- Include synonyms: `['install', 'setup', 'get started', 'configure']`
- Multi-word phrases get +10 points: `'use case'` matches better than `'use'`
- One exact word match (5 pts) meets the threshold
- Test with `POST /api/chat {"message": "your test query"}`

---

## 22. Chat API Request/Response Flow

### 22.1 Standalone Chat Flow
```
1. User types → AgentChat.handleSend()
2. POST /api/chat { message, pendingFollowUp }
3. Backend: resolve_query(message, pendingFollowUp, module_slug=None)
4. Uses GLOBAL banks (all categories merged)
5. Response:
   - answer → addMessage('agent', text, video, nextQuestions, moduleRef)
   - followUp → addFollowUpMessage(question, options)
   - noMatch → "I'm not sure I understand. Could you try rephrasing?"
```

### 22.2 Module Coach Flow
```
1. User types → ModuleCoach.handleSend()
2. POST /api/chat { message, pendingFollowUp, moduleSlug }
3. Backend: resolve_query(message, pendingFollowUp, module_slug=slug)
4. Uses MODULE_BANKS[slug] (module-specific answers only)
5. Response:
   - answer → addMessage('agent', text, video) — NO nextQuestions/moduleRef
   - followUp → addFollowUpMessage(question, options)
   - noMatch → "I'm not sure about that. Try asking about this section's
     content, or click a chip below for a quick recap."
```

### 22.3 Follow-Up Button Click (Both)
```
1. User clicks follow-up option button
2. POST /api/chat/resolve { answerId }
3. Backend: resolve_by_answer_id(answerId) — direct dict lookup
4. Returns answer or noMatch
```

### 22.4 Autocomplete (Standalone Only)
```
1. User types ≥2 chars → updateAutocomplete()
2. GET /api/suggestions?q={query}&module={slug?}
3. Backend: get_autocomplete(query, limit=5)
4. Returns sorted suggestions (highest score first, threshold > 0)
5. User selects → sets input value + fires handleSend()
```

### 22.5 Welcome Chips (Standalone Only)
```
1. GET /api/chips on page load
2. Returns CHIPS list from backend/qa/chips.py
3. Displayed as quick-start buttons: "Say Hello", "What Can You Do?"
```

---

## 23. Bank Merging (backend/qa/__init__.py)

### 23.1 Global Banks
Built by merging all 6 categories: general, copilot, smartsdk, stratos,
prompting, fullstack.
- `answer_bank` — All ANSWERS merged (raises ValueError on duplicate IDs)
- `suggestion_bank` — All SUGGESTIONS concatenated
- `qa_bank` — All QA_ENTRIES concatenated
- `video_bank` — All VIDEOS merged
- `next_questions_bank` — All NEXT_QUESTIONS merged

### 23.2 Module Banks
Each category exports `MODULE_BANKS` (except general). These are merged
into a single `module_banks` dict keyed by module slug:
```python
module_banks = {
    'copilot-basics': { answers, suggestions, qa_entries, videos, next_questions },
    'building-smartsdk': { answers, suggestions, qa_entries, next_questions },
    'advanced-copilot-patterns': { ... },
    ...
}
```

### 23.3 Answer Module Map
Auto-built from `module_banks`. Maps each answer ID to its parent module:
```python
answer_module_map = {
    'copilot-basics-intro-summary': {'slug': 'copilot-basics', 'name': 'Copilot Basics'},
    ...
}
```
Used by `_build_answer()` to add `moduleRef` links in standalone chat.

### 23.4 Auto-Generated "modules" Answer
`_build_modules_answer()` creates `general-modules` answer listing all
available topics. Updated automatically when new categories are added.

---

**Continued in [`agents-4.md`](agents-4.md) — Section 24: Page-by-Page
Visual Structure.**

*Part 3 of 4. Part 1: `../agents.md` (0-6), Part 2: `agents-2.md` (7-17),
Part 4: `agents-4.md` (24).*
