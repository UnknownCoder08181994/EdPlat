# LLM QA Guardrails — Part 2: Content Generation Rules

> Continuation of
> [`LLM_QA_GUARDRAILS.md`](LLM_QA_GUARDRAILS.md) (validation spec).
> This file covers **how to generate** new QA content that will pass all
> existing tests and match the established voice.

---

## 1. Tone and Voice Guidelines

All answer text must follow these voice rules:

1. **Second-person instructional** — address the reader as "you."
2. **Active voice preferred** — "Click the Request tile" not
   "The Request tile should be clicked."
3. **Confident and direct** — no hedging ("might," "perhaps," "you could
   try"). State facts or steps plainly.
4. **Professional-casual** — not stiff enterprise docs, not chatbot slang.
   Contractions are fine ("you'll," "it's," "don't").
5. **Technical terms unquoted** — use product names (GitHub Copilot,
   SmartSDK, Stratos) naturally, never in scare quotes.
6. **HTML emphasis** — wrap UI element names, button labels, and key terms
   in `<strong>` tags. No other HTML tags except `<br>` for line breaks.
7. **No emoji** in answer text.
8. **No first-person plural** — avoid "we" or "our." The agent speaks as
   "I" only in `general-*` greetings; all other answers are impersonal
   instructional.

### Greetings (general-* only)

General-prefixed answers may use first person ("I'm the AWMIT Agent")
and can be short (one sentence). They are the only category exempt from
the 2-sentence minimum.

---

## 2. Answer Length Targets

| Answer type | Character range | Word range | Notes |
|-------------|-----------------|------------|-------|
| `general-*` greeting/utility | 40–120 chars | 8–20 words | Single sentence OK |
| Topic overview / summary | 200–500 chars | 35–90 words | 2–4 sentences |
| Process walkthrough | 500–1 100 chars | 80–180 words | Steps + quick-ref section |
| Example / demo description | 150–400 chars | 25–70 words | Concrete code or UI steps |

Hard limits enforced by tests:

- Minimum raw length: `>= 20` characters.
- Minimum word count: `>= 3` words.
- Non-`general-*` answers: at least 2 meaningful sentences.
- Type-token ratio of content words `>= 0.30` (10+ content words).

---

## 3. Content Scoping by Category

Each category prefix owns a bounded topic domain. Generated content must
stay within scope.

| Prefix | Domain scope |
|--------|-------------|
| `general` | Greetings, help prompts, thanks acknowledgement. No technical teaching. |
| `copilot` | DevPod virtual labs: provisioning, environment setup, lab exercises, collaboration, shortcuts, advanced patterns. |
| `smartsdk` | SmartSDK framework: architecture, components, hooks, utilities, API integration. |
| `stratos` | Stratos platform: environment setup, deployment, CI/CD workflows, orchestration. |
| `prompting` | Prompt engineering: technique comparison, best practices, structured prompting. |
| `fullstack` | Full-stack AI integration: capstone patterns, end-to-end architecture. |
| `downloads` | Downloadable assets and resource links. |

**Scope violations to avoid:**

1. A `copilot-*` answer must not teach SmartSDK architecture.
2. A `stratos-*` answer must not explain prompt engineering techniques.
3. Cross-references are fine ("For deployment, see the Stratos module")
   but the answer itself must stay on-topic for its prefix.

---

## 4. Keyword Selection Strategy

### 4.1 Keyword composition per entry

Target **8–15 keywords** per QA entry, drawn from four buckets:

1. **Anchor terms** (2–4) — the unique topic identifiers.
   Example for a Copilot shortcuts answer: `shortcuts`, `keybindings`,
   `copilot`.
2. **Action verbs** (2–4) — what the user wants to do.
   Example: `configure`, `set up`, `customize`, `change`.
3. **Synonyms / paraphrases** (2–4) — natural alternate phrasing.
   Example: `hotkeys`, `keyboard`, `key combo`.
4. **Meta-intent words** (1–3) — generic query starters.
   Example: `how`, `what`, `summary`, `overview`, `video`, `recap`.

### 4.2 Keyword formatting rules

1. All keywords lowercase.
2. Multi-word phrases allowed and encouraged for exact-phrase scoring
   (`+10`). Example: `github copilot`, `inline chat`.
3. No punctuation inside keywords.
4. No duplicate keywords within one entry.
5. Stemmed uniqueness ratio `>= 0.60` for entries with 3+ keywords
   (avoid `install`, `installing`, `installation` all in one list —
   pick two).

### 4.3 Cross-entry collision avoidance

1. Jaccard overlap between two keyword lists in the same category must
   stay `< 0.60`.
2. Before adding a new entry, score its keywords against every existing
   entry in the same category. If two entries would tie or come within
   `20%` margin, differentiate their keyword lists.

---

## 5. When to Use Follow-Ups vs Direct Answers

### Direct answer (most common)

Use a direct `answer` entry when:

1. The user's intent maps to exactly one answer.
2. No disambiguation is needed.
3. The topic has a single canonical explanation.

### Follow-up (`followUp`)

Use a follow-up when:

1. A keyword set is genuinely ambiguous between 2–4 sub-topics.
   Example: "copilot setup" could mean onboarding OR installation.
2. The user needs to choose a path before the system can help.
3. Each follow-up option resolves to a different `answerId`.

**Follow-up rules:**

1. `followUp.question` — a short clarifying question (`>= 5` chars).
2. `followUp.options` — 2–4 options, each with `label`, `keywords`,
   and `answerId`.
3. In module banks, all option `answerId` values must belong to the
   same module.
4. Option keywords should be distinct enough to avoid re-triggering the
   same follow-up.
5. Follow-ups are currently unused in production data. When adding the
   first ones, start with high-ambiguity entry points (category-level
   queries like "tell me about copilot").

---

## 6. Content Examples

### 6.1 Good answer text

**Process walkthrough (copilot onboarding):**

```
To request GitHub Copilot access, start in myTechHub. From the
Technology Support homepage, click the <strong>Request</strong> tile.
In the search bar, type <strong>GitHub</strong> or enter Seal ID
<strong>106135</strong>. Select <strong>GitHub Enterprise Cloud</strong>
from the results.<br><br><strong>Quick Reference:</strong><br>
1. Open myTechHub > Request<br>
2. Search "GitHub" or Seal ID 106135<br>
3. Select GitHub Enterprise Cloud<br>
4. Submit the request form
```

**Conceptual overview (SmartSDK):**

```
SmartSDK is the core development framework for building AI-powered
features within the AWM ecosystem. It provides a collection of
pre-built components, hooks, and utilities that abstract away the
complexity of integrating machine learning models, data pipelines,
and intelligent interfaces into your applications.
```

### 6.2 Good keyword list

```python
['request', 'access', 'get', 'copilot', 'github copilot',
 'onboarding', 'onboard', 'set up', 'setup', 'start',
 'enable', 'activate', 'steps', 'checklist']
```

Why this works: 3 anchor terms (`copilot`, `github copilot`,
`onboarding`), 4 action verbs (`request`, `get`, `activate`, `start`),
3 synonyms (`set up`, `setup`, `onboard`), 2 meta terms (`steps`,
`checklist`). Stemmed uniqueness > 0.60.

### 6.3 Good suggestion text

```python
{'text': 'How do I get GitHub Copilot?',
 'keywords': ['get', 'copilot', 'github copilot', 'request', 'access']}
```

Patterns that work:
- Direct question: "How do I install Copilot in VS Code?"
- Topic label: "SmartSDK component architecture"
- Action phrase: "Prompting best practices"

### 6.4 Good next-question set

```python
'copilot-basics-onboarding-overview': [
    'How do I navigate the myTechHub portal?',
    'What Seal ID do I search for?',
    'Which resource instance should I choose?',
]
```

Why this works: 3 questions (always exactly 3), each targets a different
`answerId`, phrasing varies (How/What/Which), all end with `?`,
no near-duplicate wording, each resolves above threshold.

---

## 7. Existing Content Catalog

### 7.1 Global answer IDs (39 total)

**general (3):**
`general-hello`, `general-thanks`, `general-help`

**copilot (5 active — DevPod virtual lab content):**
`copilot-basics-onboarding-overview`, `-mytechhub`, `-sealid`,
`-instance`, `-summary`

*Inactive (kept for future use):*
`copilot-basics-intro-summary`, `-example`,
`copilot-basics-install-summary`, `-example`,
`copilot-basics-suggestion-summary`, `-example`,
`copilot-basics-chat-summary`, `-example`,
`copilot-basics-shortcuts-summary`, `-example`,
`copilot-basics-wrapup-summary`, `-example`,
`copilot-advanced-intro-summary`, `-example`

**smartsdk (5):**
`smartsdk-fundamentals-intro-summary`, `-example`,
`smartsdk-building-intro-summary`, `-example`,
`smartsdk-fundamentals`

**stratos (6):**
`stratos-setup-intro-summary`, `-example`,
`stratos-workflows-intro-summary`, `-example`,
`stratos-setup`, `stratos-workflows`

**prompting (2):**
`prompting-engineering-intro-summary`, `-example`

**fullstack (3):**
`fullstack-integration-intro-summary`, `-example`,
`fullstack-ai-integration`

### 7.2 Module slugs and their answer ownership

| Slug | Category | Answers owned |
|------|----------|---------------|
| `copilot-basics` | copilot | 5 active answer IDs |
| `smartsdk-fundamentals` | smartsdk | 2 |
| `building-smartsdk` | smartsdk | 2 |
| `stratos-setup` | stratos | 2 |
| `stratos-workflows` | stratos | 2 |
| `prompt-engineering` | prompting | 2 |
| `fullstack-ai-integration` | fullstack | 2 |

### 7.3 Naming convention for new IDs

Pattern: `{prefix}-{topic}-{subtopic}-{aspect}`

- `{prefix}` — one of the 7 allowed prefixes.
- `{topic}` — module or subject area (e.g., `basics`, `fundamentals`).
- `{subtopic}` — section within the topic (e.g., `onboarding`, `install`).
- `{aspect}` — `summary`, `example`, `overview`, or a specific facet.

Examples:
- `copilot-basics-onboarding-overview` (4 segments)
- `smartsdk-building-intro-summary` (4 segments)
- `general-hello` (2 segments — OK for general)

---

## 8. Video Association Rules

### 8.1 When to add video metadata

Add a `video_bank` entry only when:

1. A recorded video file exists under `frontend/static/videos/`.
2. The video directly demonstrates or explains the answer content.
3. The answer ID belongs to a module (not `general-*`).

### 8.2 Video metadata structure

```python
'answer-id-here': {
    'src': 'modules/{slug}/{section}/{filename}.mp4',
    'label': 'Human-readable video title (>= 5 chars)',
    'moduleUrl': '/modules/{slug}/{section}',
}
```

Required fields:
- `src` — relative path under `frontend/static/videos/`. File must
  exist. Minimum 5 characters.
- `label` — descriptive title. Minimum 5 characters.

Optional field:
- `moduleUrl` — deep link to the module viewer section.

### 8.3 Current video inventory

Only one video association exists today:

| Answer ID | Video src |
|-----------|-----------|
| `copilot-basics-onboarding-overview` | `modules/copilot-basics/onboarding/github-onboarding.mp4` (DevPod walkthrough) |

When adding videos for other modules, follow the same directory pattern:
`modules/{slug}/{section}/{descriptive-name}.mp4`.

---

## 9. Cross-Category Referencing Guidance

### 9.1 Allowed cross-references

Answers may reference other categories in two ways:

1. **Textual mention** — "For deployment options, explore the Stratos
   module." This is purely informational; the answer itself stays
   on-topic.
2. **Next-question bridging** — one of the 3 next-questions can point
   to a different category's answer. This enables learning-path flow.

### 9.2 Cross-reference rules

1. An answer's `answerId` prefix must match its own category. Never
   create a `copilot-*` ID that lives in the `stratos` bank.
2. Next-question cross-references must still resolve globally
   (score >= 5).
3. A next-question should not cross into `general-*` (those are
   utility, not learning content).
4. Maximum 1 cross-category next-question per answer's 3-question set.
   The other 2 should stay within the same topic for depth.
5. Module-scoped `qa_entries` and suggestions must only reference their
   own module's answers. Cross-references happen at the next-question
   level only.

### 9.3 Recommended learning flow

The intended cross-module path (for next-question bridging):

```
copilot-basics → smartsdk-fundamentals → building-smartsdk
    → stratos-setup → stratos-workflows
    → prompt-engineering → fullstack-ai-integration
```

When generating next-questions, prefer forward links along this path.
Backward links are acceptable but less common.

---

## Maintenance Rule

Update this document whenever:

1. New category prefixes or module slugs are added.
2. Tone, voice, or length conventions change.
3. Video files are added to `frontend/static/videos/`.
4. Follow-up entries are introduced in production data.
5. The content catalog (Section 7) grows — add new answer IDs here.
