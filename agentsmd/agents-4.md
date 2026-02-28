# AWM Institute of Technology (OIT) — Agent Instructions (Part 4)
# =====================================================================
# **Continuation of:** `agents-3.md` (Sections 18-23)
# This file covers Section 24: Page-by-Page Visual Structure.
# Every page's layout, components, and visual elements are documented here
# so agents know what each page looks like and what belongs on it.

---

## 24. Page-by-Page Visual Structure

### 24.1 Shared Elements (All Pages)

**Navigation bar** (`.main-nav`) — fixed top on every page:
- Logo: "AWM" + "Institute of Technology"
- Links: Home, Chat, Modules, Contact
- `.nav-glow-line` decorative separator below
- `.nav-hamburger` for mobile menu

**Background system** (`.section-bg`) — on every standalone page:
- `.section-grid-overlay` — subtle grid pattern
- `.section-orb` (2-3) — floating glowing orbs
- `.section-scanlines` — CRT scanline overlay

**Dark theme** — `#000000` base, neon cyan/purple/pink accents.
All pages share this aesthetic. No light mode.

---

### 24.2 Home Page (`/` — `base.html`)

Full-viewport scroll experience with 3 snap sections.

**Section 0 — Hero (`#hero`):**
- Video: `galaxy.mp4` (muted, loop, preload="auto") — fullscreen bg
- Canvas: `hero-canvas` via `hero-bg.js` — particle network (60-250
  flowing particles with connections, mouse repulsion, neural-net look)
- CSS effects: `.hero-grid-overlay`, 3 `.hero-orb` glowing spheres,
  `.hero-scanlines`, `.hero-bottom-fade`
- Content (centered): "The Future of / AWM" headline
- Terminal window mockup: types `>>> Starts Here.`
- SVG: scroll-indicator down arrow at bottom
- Cinematic intro plays first (lens flare → glitch title → galaxy explode)

**Section 1 — Humanoid / Vision (`#humanoid`):**
- Video: `humanoid.mp4` (muted, preload="metadata") — section bg
- Video: `bluefield.mp4` (muted, loop, preload="metadata") — lab env bg
- Card videos: `face.mp4`, `eye.mp4`, `brain.mp4` (preload="none")
  — one per card, play after wave reveal
- Canvas: wave-canvas via `humanoid-ripple.js` — tile-based wave
  sweep animation that transitions humanoid → bluefield at 3.55s
- Canvas: `h2-neon-lines-canvas` via `neon-grid-lines.js` — racing
  tracer lines along grid (cyan/blue, 10 concurrent, 70px grid)
- SVGs: 3 card frames with gradient borders (cyan, purple, mixed)
- CSS effects: `.humanoid-overlay`, `.h2-lab-vignette`, `.hcard-glow`,
  `.hcard-tracer`, `.hcard-halo` (featured card), mesh burst particles
- 3 cards (`.hcard`) materialize with mesh burst effects
- Center card (`.hcard-featured`) has halo effect

**Section 2 — FAQ (`#faq`):**
- Video: `globe.mp4` (muted, loop, preload="metadata") — bg
- Canvas: `faq-fx-canvas` via `faq-bg-fx.js` — 120 glowing nebula
  particles (cyan/blue/purple, sinusoidal drift, pre-rendered sprites)
- Canvas: `faq-constellation` via `faq-constellation.js` — 65 nodes
  with pulsing glows + connection lines + mouse repulsion
- Canvas: `faq-globe` via `faq-globe.js` — 3D wireframe rotating
  sphere (18×24 grid), floating text + data points, mouse-interactive
- CSS effects: `.faq-vignette`
- 7 `.faq-entry` accordion items, terminal-styled:
  - Numbered index + `>>` prompt prefix + chevron SVGs
  - Expandable answers with "AWMIT AGENT" label + typing cursor
  - Accent colors vary per entry (cyan, purple, pink)

**Navigation:** `.fp-dots` right-side dot indicators for section position.
**Scroll:** `FullpageScroll` class manages snapping, locking, transitions.

---

### 24.3 Modules Catalog (`/modules` — `modules.html`)

Single-page scrollable layout. Shows all available modules as cards.

**Hero Banner** (`.catalogue-hero`):
- Badge: glow dot + "Virtual Learning" label
- Large "Modules" title
- Descriptive subtitle paragraph

**Filter Row** (`.catalogue-filters-row`):
- Horizontal `.filter-pill` buttons: All, Copilot, SmartSDK, etc.
- Active pill is highlighted; clicking filters the card grid

**Toolbar** (`.catalogue-toolbar`):
- Left: module count display (e.g., "3 modules")
- Center: `.toolbar-search-input` with search icon
- Right: `.toolbar-dropdown-btn` topic selector with dropdown menu

**Card Grid** (`.catalogue-grid`):
- Responsive grid of `.course-card` article elements
- Each card shows:
  - Category label ("MODULE")
  - Title (e.g., "Copilot Basics")
  - Difficulty bars + colored badge (Beginner/Intermediate/Advanced)
  - Short description paragraph
  - Author section: initials avatar + name + role
  - Footer: duration, section count, "Start" button
- Cards have hover glow effects via `card-fx.js`
- Data attributes: `data-category`, `data-difficulty` for JS filtering

**Empty State** (`.catalogue-empty`):
- Shown when no modules match current filter/search

**Videos:** None. **Canvases:** None. **SVGs:** search icon, dropdown
chevron, empty-state icon. **CSS effects:** standard bg system only.

**JS:** `modules.js` handles filtering + search, `card-fx.js` handles hover.

---

### 24.4 Module Detail (`/modules/<slug>` — `module_detail.html`)

Two-column layout: main content (left ~70%) + sticky sidebar (right ~30%).

**Breadcrumb** (`.detail-breadcrumb`):
- "Modules / {Module Title}" trail at top

**Hero** (`.detail-hero`):
- Category label
- Module title (large h1)
- Subtitle tagline
- Meta pills row: difficulty badge, duration, topic count, category
- Author: initials avatar + name + role
- "Start Module" primary CTA button

**Main Column** (`.detail-main`):

1. **What You'll Learn** (`.detail-section-card`):
   - Grid of `.detail-learn-item` — check icon + objective text
   - Pulled from `module.learning_objectives` list

2. **About This Module** (`.detail-section-card`):
   - `module.description` paragraph

3. **Topics / Chapters** (`.detail-chapters-list`):
   - One `.detail-chapter-card` per section:
     - Chapter number + title (always visible)
     - Description text
     - Divider line
     - "View Topic Details" toggle + "Start Topic" link
     - Expandable `.detail-chapter-breakdown` (hidden default):
       - Lists breakdown items with play icon + label + "Start Here" link
       - "Start Here" links include `?t={seconds}` timestamp param
   - Only renders if any section has `breakdown` data (Jinja2 conditional)

**Sidebar** (`.detail-sidebar`):
- `.detail-sidebar-card` — sticky card with:
  - Duration stat
  - Topics count
  - Difficulty (color-coded badge)
  - Category
  - "Start Module" secondary CTA button

**Videos:** None. **Canvases:** None. **SVGs:** play icons, checkmark
icons (objectives), chevron toggles (accordion). **CSS effects:** standard
bg system only + color-coded difficulty badges.

**JS:** `module-detail.js` handles chapter accordion expand/collapse.

---

### 24.5 Module Viewer (`/modules/<slug>/<section>` — `module_viewer.html`)

Split layout: left sidebar (AI Coach) + right main (video player).

**Left Sidebar** (`.viewer-sidebar`):

1. **Section Navigator** (`.viewer-sections`):
   - "IN THIS TOPIC" header + collapse toggle
   - `.viewer-sections-list` — button per breakdown item:
     - Section number badge + title + timecode
     - First item `.active` by default
     - Click seeks video to that timestamp

2. **Chat Messages** (`.viewer-chat-messages`):
   - Scrollable area, messages injected by JS
   - Welcome message shows on load (robot icon + status dot + coach intro)
   - Agent messages: "AWMIT Coach" + typewriter reveal
   - User messages: "You" + instant display
   - Follow-up buttons appear after multi-turn answers

3. **Input Area** (`.viewer-chat-input-area`):
   - `.viewer-chips` — preset query buttons (e.g., "Video Summary")
   - `.viewer-chat-glow-line` — decorative separator
   - `.viewer-input-wrapper` — input + send button
   - Placeholder: "Ask about {module.title}..."

**Right Main** (`.viewer-main`):

1. **Header** (`.viewer-header`):
   - Back link: "Back to Overview" → module detail page
   - Module title (h1) + subtitle

2. **Video Player** (`.viewer-video-container`):
   - Video: dynamic per section (from `section.video` in registry)
     e.g., `modules/copilot-basics/onboarding/github-onboarding.mp4`
   - `.viewer-video-overlay` — shown when paused (play button centered)
   - Custom controls: play/pause, mute, fullscreen SVG icon buttons

3. **Timeline** (`.viewer-timeline`):
   - Current time display (left)
   - `.viewer-timeline-bar` — progress track with:
     - Section segments (colored by breakdown)
     - Playhead indicator
     - Labels for breakdown points
   - Total duration display (right)
   - Clickable to seek

**Data:** `window.MODULE_DATA` JSON injected in template (slug, title,
category, sections array, currentSectionId, currentVideo).

**JS:** `viewer-core.js` (init + events), `viewer-video.js` (playback),
`viewer-timeline.js` (timeline), `viewer-chat.js` (chat methods).

---

### 24.6 Standalone Chat (`/chat` — `chat.html`)

Full-page centered chat interface.

**Background:**
- Standard: grid overlay, orbs, scanlines
- Extra: `.chat-grid-breathe` (animated breathing grid)
- Extra: `.chat-vignette` (darkened edge vignette)
- Extra: `.chat-ambient-glow` (decorative glow element)

**Chat Area** (`.chat-main` — centered column):

1. **Messages** (`.chat-messages`):
   - **Welcome screen** (`.chat-welcome`) — shown before first message:
     - Pulsing icon with 2 concentric ring animations
     - Chat bubble SVG icon
     - `.agent-status` — green dot + "ONLINE"
     - Title: "AWMIT Assistant"
     - Subtitle: typewriter effect (30ms/char) typing
       "Ask about modules, learning paths, tools, or anything..."
   - Messages appear as user/agent chat bubbles
   - Agent answers may include: video cards, module ref links,
     next-question chips ("Suggested" label + chip buttons)

2. **Input Area** (`.chat-input-area`):
   - `.chat-glow-line` — decorative horizontal separator
   - `.chat-autocomplete` — dropdown (appears when typing ≥2 chars)
   - `.chat-input-wrapper`:
     - Input field: "Ask a question..." placeholder
     - `.chat-input-cursor` — visual caret tracker
     - `.chat-send-btn` — send arrow button
   - `.chat-disclaimer` — small text: "Responses are deterministic
     and based on AWMIT platform knowledge."

**Videos:** None. **Canvases:** None. **SVGs:** chat bubble (welcome),
send arrow (input). **CSS effects:** standard bg + `.chat-grid-breathe`,
`.chat-vignette`, `.chat-ambient-glow`, `.welcome-pulse-ring` (×2),
`.agent-status-dot`, `.chat-glow-line`.

**JS:** `chat-core.js` (init + send), `chat-messages.js` (rendering),
`chat-autocomplete.js` (suggestions dropdown).

---

## 25. Video & Canvas Asset Inventory

### 25.1 UI Videos (`videos/` root — backgrounds & card previews)

| File | Used On | Purpose | Preload |
|------|---------|---------|---------|
| `galaxy.mp4` | Home hero | Fullscreen galaxy background | auto |
| `humanoid.mp4` | Home section 1 | Humanoid section background | metadata |
| `bluefield.mp4` | Home section 1 | Lab environment (after wave reveal) | metadata |
| `globe.mp4` | Home section 2 | FAQ section globe background | metadata |
| `face.mp4` | Home section 1 | Card 1 preview ("Adaptive Coaching") | none |
| `eye.mp4` | Home section 1 | Card 2 preview ("Visual Walkthroughs") | none |
| `brain.mp4` | Home section 1 | Card 3 preview ("Real-World Application") | none |

All UI videos: muted, playsinline.

### 25.2 Module Content Videos (`videos/modules/<slug>/<section>/`)

| File | Module | Section |
|------|--------|---------|
| `copilot-basics/onboarding/github-onboarding.mp4` | Copilot Basics | Onboarding |

Module videos are referenced in `registry.py` as:
`'video': 'modules/copilot-basics/onboarding/github-onboarding.mp4'`

### 25.3 Canvas Effects (JS-Rendered)

| Canvas | JS File | Page | Effect |
|--------|---------|------|--------|
| `#hero-canvas` | `hero-bg.js` | Home hero | Particle network (60-250 particles) |
| `.wave-canvas` | `humanoid-ripple.js` | Home sec 1 | Tile-based wave transition |
| `.h2-neon-lines-canvas` | `neon-grid-lines.js` | Home sec 1 | Racing tracer lines on grid |
| `#faq-fx-canvas` | `faq-bg-fx.js` | Home sec 2 | 120 glowing nebula particles |
| `#faq-constellation` | `faq-constellation.js` | Home sec 2 | 65 connected pulsing nodes |
| `#faq-globe` | `faq-globe.js` | Home sec 2 | 3D wireframe rotating sphere |

All canvas effects are **home page only**. Other pages use CSS effects only.

### 25.4 No Image Files

The project uses **zero image files** (no PNG, JPG, SVG files, GIF, WebP).
All icons are inline SVGs in templates. All graphics are CSS effects or
canvas-rendered. All backgrounds are MP4 videos or CSS gradients.

---

*This is Part 4 of the OIT agent instructions. Part 1: `../agents.md`
(Sections 0-6), Part 2: `agents-2.md` (Sections 7-17), Part 3:
`agents-3.md` (Sections 18-23).*
