# AWM Institute of Technology (OIT) — Agent Instructions (Part 1 of 4)
# =====================================================================
# This file is the single source of truth for any AI agent,
# LLM, GitHub Copilot model, or Claude instance working on
# this codebase. Read it completely before making changes.
#
# **Continued in:** `agentsmd/agents-2.md` → `agents-3.md` → `agents-4.md`

---

## 0. Agent File Rules (READ FIRST)

**Every file in this project must be 400 lines or fewer.** This includes
`agents.md` files themselves. No exceptions. No cheating with long lines.

When editing `agents.md` or any `agentsmd/*.md` file:
- If adding content would push a file past 400 lines, move sections to
  the next file or create a new `agentsmd/agents-N.md` continuation file.
- Always update the "Continued in" reference at the bottom of the file
  and the header of the continuation file so the chain is unbroken.
- Keep lines at a normal readable width — never pack content into
  massive single lines to stay under the limit.
- Check `agentsmd/ui-changelog.md` before making CSS changes to avoid
  redoing previous work.

**Agent file chain:**
1. `agents.md` (this file) — Sections 0-6
2. `agentsmd/agents-2.md` — Sections 7-17
3. `agentsmd/agents-3.md` — Sections 18-23 (Chat Systems, Q&A Deep Dive)
4. `agentsmd/agents-4.md` — Section 24 (Page-by-Page Visual Structure)
5. `agentsmd/ui-changelog.md` — CSS change log

---

## 1. Project Overview

OIT is an interactive developer education platform built with **Flask** (backend)
and **vanilla JavaScript** (frontend). It teaches GitHub Copilot, SmartSDK, and
Stratos through video-based modules with an AI Coach sidebar.

Key characteristics:
- **No build step.** No webpack, no bundler, no npm. Raw HTML/CSS/JS served by Flask.
- **No frameworks.** No React, Vue, Angular. Vanilla JS with class-based architecture.
- **No database.** All data is in Python dicts. Q&A is deterministic keyword matching.
- **Dark theme only.** Neon-accented cyberpunk aesthetic. No light mode.
- **Self-contained.** Only dependency is Flask (`requirements.txt`: `flask>=3.0.0`).
- **No authentication.** Public educational platform, no user accounts.

---

## 2. Folder Structure

```
OIT/
├── app.py                              Flask entry point (79 lines)
├── run.bat                             Windows launcher (python app.py)
├── requirements.txt                    flask>=3.0.0
├── agents.md                           THIS FILE — agent instructions (Part 1)
├── agentsmd/
│   ├── agents-2.md                     Agent instructions (Part 2)
│   └── ui-changelog.md                 CSS change log — check before styling
│
├── backend/
│   ├── __init__.py                     Empty package init
│   ├── modules/
│   │   ├── __init__.py                 Module loader (get_module, get_all_modules)
│   │   ├── copilot_basics/             Beginner module (ENABLED)
│   │   │   ├── __init__.py
│   │   │   └── registry.py             Module metadata + sections + breakdowns
│   │   ├── building_smartsdk/          Intermediate module (infrastructure ready)
│   │   │   ├── __init__.py
│   │   │   └── registry.py
│   │   └── advanced_copilot_patterns/  Advanced module (infrastructure ready)
│   │       ├── __init__.py
│   │       └── registry.py
│   │
│   └── qa/
│       ├── __init__.py                 Merges all banks into unified + per-module
│       ├── _types.py                   Data format documentation
│       ├── engine.py                   Keyword matching algorithm (146 lines)
│       ├── chips.py                    Welcome screen suggestion chips
│       ├── general/                    Greetings, help responses
│       ├── copilot/                    Copilot module Q&A (8 topic files)
│       ├── smartsdk/                   SmartSDK module Q&A
│       ├── stratos/                    Stratos module Q&A
│       ├── prompting/                  Prompt engineering Q&A
│       ├── fullstack/                  Full-stack integration Q&A
│       └── downloads/                  Download paths + placeholders
│
├── frontend/
│   ├── templates/                      Jinja2 HTML templates (6 files)
│   │   ├── base.html                   Home page (cinematic + fullpage scroll)
│   │   ├── chat.html                   Standalone chat page
│   │   ├── modules.html                Module catalog
│   │   ├── module_detail.html          Module overview + topics
│   │   ├── module_viewer.html          Video player + AI Coach
│   │
│   └── static/
│       ├── css/                        ~53 source files, split by feature
│       │   ├── main.css                @import manifest (development only)
│       │   ├── main.built.css          Concatenated CSS (what templates load)
│       │   ├── build_css.ps1           PowerShell build script
│       │   ├── cinematic.css           @import master for intro animations
│       │   ├── variables.css           CSS custom properties (:root)
│       │   ├── reset.css               Box-sizing, margin reset
│       │   ├── layout.css              Container, utilities
│       │   ├── typography.css          Headings, gradients
│       │   ├── nav.css                 Navigation bar
│       │   ├── hamburger.css           Mobile hamburger menu
│       │   ├── standalone.css          Standalone page overrides
│       │   ├── responsive.css          ALL breakpoints (MUST be last import)
│       │   ├── animations.css          Shared keyframe animations
│       │   ├── terminal.css            Terminal component styles
│       │   ├── fullpage/               Fullpage scroll system (3 files)
│       │   ├── hero/                   Hero section (5 files)
│       │   ├── humanoid/               Humanoid/Vision section (12 files)
│       │   ├── faq/                    FAQ + Programs section (5 files)
│       │   ├── modules/                Module catalog (6 files)
│       │   ├── module-detail/          Module detail page (3 files)
│       │   ├── module-viewer/          Module viewer (4 files)
│       │   ├── chat/                   Chat interface (3 files)
│       │   └── cinematic/              Cinematic intro (4 files)
│       │
│       ├── js/                         26 files, split by feature
│       │   ├── home/                   Home page scripts (11 files)
│       │   ├── chat/                   Chat page scripts (3 files)
│       │   ├── modules/                Module catalog + detail (3 files)
│       │   ├── module-viewer/          Module viewer scripts (4 files)
│       │   └── faq/                    FAQ effects (5 files)
│       │
│       └── videos/
│           ├── galaxy.mp4              Hero background (UI)
│           ├── humanoid.mp4            Page 2 background (UI)
│           ├── bluefield.mp4           Lab environment background (UI)
│           ├── globe.mp4               FAQ/Programs background (UI)
│           ├── face.mp4                Card 1 preview (UI)
│           ├── eye.mp4                 Card 2 preview (UI)
│           ├── brain.mp4               Card 3 preview (UI)
│           └── modules/                MODULE CONTENT VIDEOS
│               └── <module-slug>/      e.g. copilot-basics/
│                   └── <section-id>/   e.g. onboarding/
│                       └── video.mp4   e.g. github-onboarding.mp4
│
└── venv/                               Python virtual environment (DO NOT TOUCH)
```

---

## 3. Critical Rules

### 3.1 File Size Limit
**Every file must be 400 lines or fewer.** No exceptions. Never bypass this by
making lines longer/horizontal. If a file approaches 400, split to a continuation
file using JS prototype-attachment (section 7.3) or CSS @import (section 6.2).

### 3.2 No New Dependencies
Do not add npm, webpack, bundlers, CSS preprocessors, or JS frameworks.
The only Python dependency is Flask. Keep it that way.

### 3.3 No Build Step (except CSS concat)
Everything is served raw. JS uses `<script>` tags in order.
There is no transpilation, minification, or bundling.

**Exception — CSS:** Individual CSS files are the source of truth. Templates
load `main.built.css` — an auto-generated concatenation of all source files.
**NEVER manually edit `main.built.css`.** Only edit the source files (e.g.,
`chat/input.css`), then rebuild:
```powershell
powershell -File frontend/static/css/build_css.ps1
```
The build script reads each source file and concatenates them into
`main.built.css`. Any manual edits to `main.built.css` will be overwritten.

### 3.4 Dark Theme Only
The entire UI is dark (#000000 base). Never add light mode, white backgrounds,
or high-contrast light elements unless they are accent glows or text.

### 3.5 Video References
**UI videos** (backgrounds, card previews) live flat in `videos/`:
```html
{{ url_for('static', filename='videos/galaxy.mp4') }}
```
**Module videos** (walkthroughs, tutorials) live in `videos/modules/<slug>/<section>/`:
```html
{{ url_for('static', filename='videos/modules/copilot-basics/onboarding/github-onboarding.mp4') }}
```
In registry.py, the `video` field is relative to `videos/`:
```python
'video': 'modules/copilot-basics/onboarding/github-onboarding.mp4'
```

### 3.6 Video Playback Rules
- **No autoplay** on offscreen videos. Only the active section's video plays.
- `preload="auto"` only for the hero galaxy video (loads first).
- `preload="metadata"` for humanoid, bluefield, globe (next sections).
- `preload="none"` for card preview videos (loaded on reveal).
- **Pause all videos** when leaving a section (handled in `fullpage-core.js`).
- Card previews play only after `HumanoidCardReveal` summons them.
- Videos get `Cache-Control: public, max-age=31536000, immutable` via `app.py`.

### 3.7 Import Paths
All Python imports use the `backend.` prefix:
```python
from backend.qa.engine import resolve_query
from backend.modules import get_module
```
Never use bare `qa.` or `modules.` imports.

---

## 4. Flask Application (app.py)

### 4.1 Configuration
```python
app = Flask(
    __name__,
    static_folder='frontend/static',
    template_folder='frontend/templates',
)
```

### 4.2 Routes

| Method | Path | Handler | Template |
|--------|------|---------|----------|
| GET | `/` | `index()` | base.html |
| GET | `/modules` | `modules()` | modules.html |
| GET | `/modules/<slug>` | `module_detail(slug)` | module_detail.html |
| GET | `/modules/<slug>/<section_id>` | `module_viewer(slug, section_id)` | module_viewer.html |
| GET | `/chat` | `chat()` | chat.html |
| POST | `/api/chat` | `api_chat()` | JSON response |
| POST | `/api/chat/resolve` | `api_chat_resolve()` | JSON response |
| GET | `/api/suggestions` | `api_suggestions()` | JSON response |
| GET | `/api/chips` | `api_chips()` | JSON response |

### 4.3 API Response Formats

**POST /api/chat** — Accepts `{ message, pendingFollowUp?, moduleSlug? }`
Returns one of:
```json
{ "type": "answer", "answerId": "copilot-basics-intro-summary", "text": "..." }
{ "type": "followUp", "question": "...", "options": [...] }
{ "type": "noMatch" }
```

**POST /api/chat/resolve** — Accepts `{ answerId }`
Returns `{ "type": "answer", "answerId": "...", "text": "..." }` or `{ "type": "noMatch" }`

**GET /api/suggestions?q=...&module=...** — Returns `[{ text, keywords }, ...]`

**GET /api/chips** — Returns `[{ label, icon }, ...]`

---

## 5. Module System (backend/modules/)

### 5.1 Adding a New Module

1. Create `backend/modules/your_module_name/` (use snake_case for folder)
2. Add empty `__init__.py`
3. Create `registry.py` exporting a `MODULE` dict
4. Register in `backend/modules/__init__.py`

### 5.2 Module Dict Structure
```python
MODULE = {
    'title': 'Module Title',
    'subtitle': 'Short tagline.',
    'category': 'copilot',              # copilot, smartsdk, stratos
    'accent': 'purple',                 # purple, pink, cyan
    'difficulty': 'beginner',           # beginner, intermediate, advanced
    'duration': '45 min',
    'ai_native': True,
    'author': { 'name': 'Full Name', 'role': 'Job Title', 'initials': 'FN' },
    'description': 'Long paragraph...',
    'learning_objectives': ['Objective one', 'Objective two'],
    'sections': [
        {
            'id': 'intro',              # URL-safe slug (kebab-case)
            'title': 'Introduction',
            'video': None,              # None until real video is added; path in videos/
            'start': 0,
            'description': 'What this covers.',
            'breakdown': [              # OPTIONAL sub-topic timestamps
                {'label': 'Sub-topic name', 'time': 0},
            ],
        },
    ],
}
```

### 5.3 Sections vs Breakdowns
- **Sections** are independent topics with their own video file and URL
- **Breakdowns** are sub-topics WITHIN a section's video, marked by timestamps
- A section without `breakdown` shows no topic navigator in the viewer

---

## 6. CSS Architecture

### 6.1 Design Tokens (variables.css)
All colors, fonts, spacing, and radii are defined as CSS custom properties.
Always use variables — never hard-code colors.

Key variables:
```css
--bg-primary: #000000;          --bg-card: #0a0a18;
--text-primary: #e8eaff;        --text-secondary: #8b90b8;
--accent-cyan: #22d3ee;         --neon-purple: #a78bfa;
--font-body: 'Inter', sans-serif;
--font-mono: 'JetBrains Mono', monospace;
```

### 6.2 @import Strategy + Build
`main.css` is a pure import manifest — ZERO style rules. Import order matters:
1. Foundation (variables, reset, layout, typography, nav)
2. Fullpage system
3. Page sections (hero, humanoid, faq)
4. Standalone pages (modules, chat, module-detail, module-viewer)
5. `responsive.css` — ALWAYS LAST

**CRITICAL: Templates load `main.built.css`, NOT `main.css`.**

### 6.3 Adding New Styles
1. Find or create the appropriate file in `css/<feature>/`
2. If new file, add `@import` to `main.css`
3. Keep under 400 lines; use existing CSS variables
4. **Rebuild:** `powershell -File frontend/static/css/build_css.ps1`

### 6.4 Class Naming Convention
- Prefix with feature area: `.hero-*`, `.chat-*`, `.viewer-*`, `.faq-*`
- kebab-case: `.course-card-title`, `.viewer-chat-input`
- State classes: `.active`, `.open`, `.scrolled`, `.revealed`, `.summoned`

### 6.5 CSS Build System
`build_css.ps1` reads each source file listed in its `$files` array and
concatenates them into `main.built.css` (~170KB, one HTTP request).
**Rebuild after ANY CSS change.** Never manually edit `main.built.css`.

### 6.6 CSS Changelog
Before making CSS changes, check `agentsmd/ui-changelog.md` for current values
and change history. Update it after every styling change to prevent redundant work.

### 6.7 Resolution-Independent Scaling — vw Units Only
**All sizing properties must use `vw` (viewport width) units** so the UI looks
proportionally identical on any screen resolution (1080p, 1440p, 4K, etc.).
Every element maintains the same percentage of viewport width at any size.

**Use `vw` for:** font-size, padding, margin, gap, width, height, max-width,
border-radius, box-shadow spread/blur, backdrop-filter blur, transforms
(translateX/Y for layout shifts), and any spacing/sizing property.

**Keep as `px`:** Only these exceptions stay in fixed pixels:
- `1px` borders (hairline decorative borders — must stay exactly 1 pixel)
- Thin decorative lines (`1.5px` connectors, dividers)
- Micro hover animations (`translateY(-1px)`)
- Media query breakpoints (`@media (max-width: 1024px)`)

**Conversion formula:** The reference viewport is 2560px wide.
```
vw_value = px_value / 2560 × 100
rem_value → first convert to px (1rem = 16px), then to vw
```
Examples: `16px → 0.625vw`, `24px → 0.938vw`, `1rem → 0.625vw`

**CSS variables** in `variables.css` (`--space-*`, `--radius-*`) are already
in `vw`. Always use them. Never introduce new `rem`, `em`, or fixed `px`
values for layout-affecting properties.

**When creating a new page or component:** Start with `vw` from the beginning.
If porting an existing design from a mockup with `px` values, convert all
measurements using the formula above before committing.

---

**Continued in [`agentsmd/agents-2.md`](agentsmd/agents-2.md) — Sections 7-17,
[`agents-3.md`](agentsmd/agents-3.md) — Sections 18-23,
[`agents-4.md`](agentsmd/agents-4.md) — Section 24 (Page Visual Structure).**
