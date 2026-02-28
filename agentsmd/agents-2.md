# AWM Institute of Technology (OIT) — Agent Instructions (Part 2 of 4)
# =====================================================================
# **Continuation of:** `../agents.md` (Sections 0-6)
# **Continued in:** `agents-3.md` → `agents-4.md`
# This file covers Sections 7-17: JS Architecture, Q&A System,
# Templates, Home Page, Naming, Common Tasks, Architecture Decisions,
# Testing, File Limits, Environment, Active Modules.

---

## 7. JavaScript Architecture

### 7.1 No Modules, No Bundler
All JS files are loaded via `<script>` tags in HTML templates. Order matters.

### 7.2 Script Load Order

**base.html** (home page):
```
js/home/hero-bg.js, fullpage-core.js, fullpage-input.js, nav.js,
splash-intro.js, hero-animation.js, terminal.js, section-fx.js,
humanoid-ripple.js, humanoid-ripple-ext.js, neon-grid-lines.js, card-tilt.js
js/faq/faq-bg-fx.js, faq-constellation.js, faq-shatter.js,
faq-panels.js, faq-globe.js
```

**chat.html**: `chat-core.js, chat-messages.js, chat-messages-video.js, chat-autocomplete.js`

**module_viewer.html**: `viewer-core.js, viewer-video.js, viewer-timeline.js, viewer-chat.js, viewer-chat-video.js, card-fx.js`

**modules.html**: `modules.js, card-fx.js`
**module_detail.html**: `module-detail.js, card-fx.js`

### 7.3 Prototype Attachment Pattern
When a class exceeds 400 lines, split across files. Core defines the class;
extension files attach methods to the prototype:
```javascript
// Extension file (loaded after core):
MyClass.prototype.addMessage = function(sender, text) { /* ... */ };
```

### 7.4 Event System
- `cinematic-done` — Splash + hero animation complete
- `lock-scroll` / `unlock-scroll` — Controls fullpage scroll lock
- `section-revealed` — `{ detail: { index } }` when section becomes active

### 7.5 API Call Pattern
```javascript
const res = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, pendingFollowUp, moduleSlug }),
});
const data = await res.json();
// Handle data.type: 'answer' | 'followUp' | 'noMatch'
```

---

## 8. Q&A System (backend/qa/)

### 8.1 How It Works
Deterministic keyword matching — no LLMs, no ML models. Users type a question,
the engine scores it against keyword lists, returns the best pre-written answer.

### 8.2 Adding Q&A Content
1. Create topic file in `backend/qa/<category>/` with `ANSWERS`, `SUGGESTIONS`, `QA_ENTRIES`
2. Register in category `__init__.py` — merge into unified dicts + `MODULE_BANKS`

### 8.3 Answer ID Convention
Format: `{category}-{module-slug}-{section-id}-{descriptor}`
Examples: `general-hello`, `copilot-basics-intro-summary`

### 8.4 Keyword Scoring
- Exact phrase: **+10 pts** | Word match: **+5 pts** | Prefix match: **+2 pts**
- Minimum threshold: **5 points**

### 8.5 Module-Scoped Q&A
When `moduleSlug` is provided, the engine uses `MODULE_BANKS[slug]` instead of
global banks, giving module-specific answers in the AI Coach.

### 8.6 Q&A Topic Files
`copilot/`: basics_intro, basics_install, basics_first_suggestion,
basics_shortcuts, basics_inline_chat, basics_wrap_up, basics_onboarding,
advanced_intro | `smartsdk/`: fundamentals_intro, building_intro |
`stratos/`: setup_intro, workflows_intro | `prompting/`: engineering_intro |
`fullstack/`: integration_intro | `general/`: greetings, help |
`downloads/`: paths

---

## 9. Template System

### 9.1 Template Variables

**base.html**: No variables (static home page)

**modules.html**: No variables (JS handles filtering)

**module_detail.html**:
- `module` — Full module dict from registry
- `slug` — URL slug string

**module_viewer.html**:
- `module` — Full module dict
- `slug` — URL slug
- `section_id` — Current section ID
- `section` — Current section dict
- `window.MODULE_DATA` — JSON object injected for JS access

**chat.html**: No variables


### 9.2 Static File References
Always use Flask's `url_for`:
```html
<link rel="stylesheet" href="{{ url_for('static', filename='css/main.built.css') }}">
<script src="{{ url_for('static', filename='js/home/nav.js') }}"></script>
<source src="{{ url_for('static', filename='videos/galaxy.mp4') }}" type="video/mp4">
```
**Note:** Templates load `main.built.css` (concatenated), NOT `main.css` (imports).

### 9.3 Conditional Topics (module_detail.html)
The Topics section only renders if ANY section has breakdowns:
```jinja2
{% set has_any_breakdown = module.sections | selectattr('breakdown', 'defined')
                          | selectattr('breakdown') | list | length > 0 %}
{% if has_any_breakdown %}
    <!-- Topics accordion -->
{% endif %}
```

---

## 10. Home Page Architecture

### 10.1 Cinematic Intro Sequence
1. **Phase 1** — Black screen, lens flare streaks animate in
2. **Phase 2** — "AWM Institute of Technology" glitch-reveals, then fades
3. **Phase 3** — Galaxy video explodes in, background stabilizes
4. **Phase 4** — "The Future of / AWM" text reveals, terminal types ">>> Starts Here."
5. `cinematic-done` event fires, fullpage scroll unlocks

### 10.2 Fullpage Scroll System
Three sections, snap-scrolled:
- **Section 0** (Hero) — Galaxy bg, headline, terminal
- **Section 1** (Humanoid/Vision) — Video plays, then wave reveals 3 cards
- **Section 2** (FAQ) — Globe video, FAQ accordion

Section transitions use `section-revealed` custom events. The `FullpageScroll`
class manages scroll locking, dot navigation, and section visibility.

### 10.3 Page 2 Card Reveal
At `triggerTime = 3.55` seconds into the humanoid video, `HumanoidCardReveal`
fires a wave animation that sweeps left-to-right replacing the video with a
lab environment, then cards materialize with mesh burst effects.

### 10.4 Skip Cinematic
If `sessionStorage.getItem('hero-destroyed')` is set OR the URL has `?skip`,
the cinematic is skipped and the hero shows its final state immediately.
The `?skip` param is used by nav links from sub-pages (e.g., `/chat` -> `/?skip`).

### 10.5 Page Prefetch
All templates include `<link rel="prefetch">` tags for other pages. This tells
the browser to pre-download those pages in idle time so navigation feels instant.

**When adding a new page:**
- Add `<link rel="prefetch" href="/your-new-page">` to existing templates
- Add `<link rel="prefetch">` tags for other pages in your new template

**Nav links must be plain `<a href>` tags.** Do NOT intercept clicks with
JavaScript, add fade overlays, or use `e.preventDefault()` on navigation links.

---

## 11. Naming Conventions Summary

| Context | Convention | Example |
|---------|-----------|---------|
| Module slugs | kebab-case | `copilot-basics` |
| Module folders | snake_case | `copilot_basics/` |
| Section IDs | kebab-case | `first-suggestion` |
| Answer IDs | kebab-dash | `copilot-basics-intro-summary` |
| CSS classes | kebab-case with prefix | `.viewer-chat-input` |
| CSS files | kebab-case | `card-hover.css` |
| CSS folders | kebab-case | `module-viewer/` |
| JS classes | PascalCase | `ModuleCoach` |
| JS files | kebab-case | `viewer-core.js` |
| JS folders | kebab-case | `module-viewer/` |
| Python files | snake_case | `basics_intro.py` |
| Python folders | snake_case | `copilot_basics/` |
| UI video files | lowercase | `galaxy.mp4` |
| Module video path | `modules/<slug>/<section>/` | `modules/copilot-basics/onboarding/` |
| Original videos | snake_case + `_original` | `galaxy_original.mp4` |

---

## 12. Common Tasks

### 12.1 Adding a New Module
1. Create `backend/modules/new_module/registry.py` with MODULE dict
2. Register in `backend/modules/__init__.py`
3. Create video folders: `frontend/static/videos/modules/<slug>/<section-id>/`
4. Place walkthrough videos in section folders; reference as
   `'video': 'modules/<slug>/<section-id>/filename.mp4'` in registry
5. Create Q&A topic files in `backend/qa/<category>/`
6. Register Q&A in category `__init__.py` + add to MODULE_BANKS
7. Add a course card to `frontend/templates/modules.html`
8. Add filter option if new category

### 12.2 Adding a New Page
1. Create route in `app.py`
2. Create template in `frontend/templates/`
3. Create CSS in `frontend/static/css/<page-name>/` (add @imports to main.css)
4. **Rebuild `main.built.css`** — `powershell -File frontend/static/css/build_css.ps1`
5. Create JS in `frontend/static/js/<page-name>/`
6. Add nav link to all templates that have navigation
7. Add `<link rel="prefetch">` tags to existing templates for the new page
8. Add `<link rel="prefetch">` tags in the new template for existing pages

### 12.3 Adding CSS Styles
1. Find the correct feature file in `css/<feature>/`
2. If none fits, create a new file and add `@import` to `main.css`
3. Use CSS variables from `variables.css`
4. Keep under 400 lines
5. Add responsive overrides to `responsive.css` if needed
6. **Rebuild `main.built.css`**

### 12.4 Adding JS Functionality
1. If extending an existing class, add methods via prototype in a new or
   existing extension file
2. If creating new functionality, create a new class in the appropriate
   `js/<feature>/` folder
3. Add `<script>` tag to the relevant template (order matters!)
4. Keep under 400 lines

---

## 13. Architecture Decisions (Do Not Change)

These are intentional choices. Do not "improve" them:

1. **Deterministic Q&A over LLM** — The chat is keyword-matched on purpose.
   Fast, predictable, no API keys or model hosting needed.

2. **Vanilla JS over frameworks** — Cinematic animations, fullpage scroll,
   and card effects require precise DOM control. Frameworks add overhead.

3. **@import CSS with concat build** — Source files use `@import` for clean
   organization, but `main.built.css` (concatenated) is what templates load.
   No preprocessor — just a PowerShell script that cats files together.

4. **Prototype attachment over ES modules** — Browser ES modules require
   `type="module"` and have CORS restrictions with `file://`. The prototype
   pattern works with any `<script>` tag.

5. **Per-section videos** — Each module section has its own video file.
   Independent section loading, no seeking in large files.

6. **SessionStorage for cinematic skip** — Lightweight, no cookies, no server
   state. Flag set when user navigates away.

7. **Plain `<a href>` nav links with prefetch** — Never intercept with
   `e.preventDefault()`, add fade overlays, or delay with `setTimeout`.
   Use `<link rel="prefetch">` for instant clicks.

---

## 14. Testing Checklist

After any change, verify:

- [ ] If CSS was changed: `powershell -File frontend/static/css/build_css.ps1`
- [ ] `python app.py` starts without import errors
- [ ] `GET /` loads, cinematic plays, hero renders
- [ ] `GET /modules` shows all module cards
- [ ] `GET /modules/copilot-basics` shows detail page with topics
- [ ] `GET /modules/copilot-basics/onboarding` shows viewer with video + AI Coach
- [ ] `GET /chat` loads, typing "hello" returns a response
- [ ] `POST /api/chat` with `{"message": "hello"}` returns answer
- [ ] Browser console shows zero JS errors (ignore Chrome extension warnings)
- [ ] All videos play (galaxy, humanoid, bluefield, face, eye, brain, globe)
- [ ] Page 2 card reveal triggers at ~3.55s into humanoid video
- [ ] Globe video plays on page 3 transition

---

## 15. File Limits Quick Reference

| Area | Max Lines |
|------|-----------|
| Python files | 400 |
| JavaScript files | 400 |
| CSS source files | 400 |
| HTML templates | No hard limit |
| `main.built.css` | **EXEMPT** — auto-generated, will be thousands of lines |
| `agentsmd/*.md` | 400 |

`main.built.css` is **fully exempt** from all agent checks:
- **Not subject to the 400-line rule** (will be thousands of lines)
- **Never manually edited** — only regenerated by `build_css.ps1`
- **Skip it in debugging** — don't read/scan it for bugs
- **Skip it in unit tests / linting** — it's a build artifact, not source
- **Never diff it** — changes come from source CSS files, not this file

If ANY other file exceeds 400 lines, split it immediately into a
continuation file. Do NOT bypass the limit by stretching content into
longer horizontal lines.
Use the split patterns described in Part 1 of these instructions.

---

## 16. Environment

- **Python**: 3.12+ (uses `dict | None` union syntax)
- **Flask**: 3.0+
- **OS**: Windows (paths use backslashes internally, forward slashes in URLs)
- **Browser**: Modern Chrome/Edge/Firefox (uses `requestAnimationFrame`,
  `IntersectionObserver`, CSS custom properties, `clip-path`)
- **Fonts**: Inter (body), JetBrains Mono (code) — loaded from Google Fonts
- **No Node.js, no npm, no package.json**

---

## 17. Currently Active Modules

| Module | Slug | Difficulty | Status |
|--------|------|-----------|--------|
| Copilot Basics | `copilot-basics` | Beginner | **ENABLED** |
| Building SmartSDK | `building-smartsdk` | Intermediate | Infrastructure ready |
| Advanced Copilot Patterns | `advanced-copilot-patterns` | Advanced | Infrastructure ready |

**Author (copilot-basics):** Shane Anderson — AI/ML Data Operations Lead

---

**Continued in [`agents-3.md`](agents-3.md) — Sections 18-23: Chat Systems,
Q&A Data Structures, Q&A Engine, Adding Q&A Content, Chat API Flow.**

*Part 2 of 4. Part 1: `../agents.md` (0-6), Part 3: `agents-3.md` (18-23),
Part 4: `agents-4.md` (24).*
