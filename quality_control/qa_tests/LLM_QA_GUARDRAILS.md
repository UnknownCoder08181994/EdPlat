# LLM QA Guardrails (Aligned with Current `qa_tests`)

## Purpose

This document defines what qualifies as an acceptable question, answer target,
suggestion, and next-question for the current OIT deterministic QA system.

This is explicitly aligned to:

1. `quality_control/qa_tests/test_01_structure.py`
2. `quality_control/qa_tests/test_02_duplicates.py`
3. `quality_control/qa_tests/test_03_answer_quality.py`
4. `quality_control/qa_tests/test_04_suggestions.py`
5. `quality_control/qa_tests/test_05_engine.py`
6. `quality_control/qa_tests/test_06_module_banks.py`
7. `quality_control/qa_tests/test_07_deep_analysis.py`
8. `quality_control/qa_tests/test_08_api_payload_guardrails.py`
9. `quality_control/qa_tests/test_09_engine_scope_regression.py`
10. `quality_control/qa_tests/test_10_topic_bank_reachability.py`

If a generated QA asset violates rules here, it should be treated as test-risk.

---

## Runtime Facts (Do Not Assume Otherwise)

1. Runtime matching is deterministic keyword scoring (`backend/qa/engine.py`).
2. Query normalization behavior:
   - Lowercase conversion
   - Punctuation stripping
   - Whitespace collapse
   - Number preservation
3. Scoring model:
   - Exact phrase: `+10`
   - Exact word: `+5`
   - Prefix/stem-style partial: `+2`
4. Minimum threshold is `>= 5`; below that returns `noMatch`.
5. The system is not a generative runtime answerer; it routes to existing
   `answerId` content.

---

## Current Coverage Snapshot

Current global category prefixes in use:

1. `general`
2. `copilot`
3. `smartsdk`
4. `stratos`
5. `prompting`
6. `fullstack`
7. `downloads` (allowed prefix in tests)

Current module-scoped banks in use:

1. `copilot-basics`
2. `smartsdk-fundamentals`
3. `building-smartsdk`
4. `stratos-setup`
5. `stratos-workflows`
6. `prompt-engineering`
7. `fullstack-ai-integration`

---

## Data Contract Guardrails

### 1. Answer IDs and answer text

1. `answerId` must be lowercase kebab-dash format.
2. `answerId` must not contain spaces.
3. `answerId` must not contain malformed dash patterns (`__`, leading `-`,
   trailing `-`).
4. Prefix must be one of:
   - `general`, `copilot`, `smartsdk`, `stratos`, `prompting`,
     `fullstack`, `downloads`
5. IDs must be unique globally across category merges.
6. IDs must be unique within each module bank.
7. Answer value must be a non-empty string.
8. Minimum raw length should be at least `20` characters.
9. Minimum semantic length should be at least `3` words.
10. Allowed HTML tags in answers are only:
    - `<strong>`, `</strong>`, `<br>`
11. `<strong>` tags must be balanced.
12. No placeholder language:
    - `this is a placeholder`, `coming soon`, `to be determined`,
      `lorem ipsum`, `todo`, `tbd`, `insert answer here`,
      `work in progress`
13. No double spaces inside lines.
14. Non-`general-*` answers should contain at least 2 meaningful sentences.
15. Do not repeat the same sentence verbatim within one answer.
16. Vocabulary richness target:
    - Type-token ratio of content words should be `>= 0.30`
      when an answer has at least 10 content words.

### 2. QA entries

1. `keywords` must exist and be a non-empty list of strings.
2. All keywords must be lowercase.
3. Each entry must contain exactly one of:
   - `answer` OR `followUp`
4. If `answer` is present, it must exist in `answer_bank`.
5. No duplicate `answer` targets in global `qa_bank`.
6. No duplicate `answer` targets within each module's `qa_entries`.
7. For non-general entries, at least one specific trigger keyword should be
   represented in the answer text (directly or via stemming), excluding generic
   intent terms.
8. Within the same category/module, keyword overlap should stay under a Jaccard
   ratio of `0.60`.
9. Within a single entry with 3+ keywords, stemmed keyword uniqueness ratio
   should be at least `0.60`.

### 3. Follow-up entry structure

1. `followUp.question` must be a string with minimum useful length (`>= 5`).
2. `followUp.options` must have at least 2 options.
3. Every option requires:
   - `label` (non-empty)
   - `keywords` (list)
   - `answerId` (existing answer)
4. In module banks, follow-up option `answerId` values must remain inside the
   module's own `answers` set.

### 4. Suggestions

1. Each suggestion requires:
   - `text` string (`>= 3` chars)
   - non-empty `keywords` list
2. Suggestion keywords should be lowercase.
3. Suggestion text must be globally unique.
4. Suggestion text used as a query should resolve (not `noMatch`).
5. Full suggestion text should appear in autocomplete results.
6. In module scope, module suggestion text must resolve with `module_slug`.
7. Similarity controls:
   - SequenceMatcher ratio between two suggestion texts should be `<= 0.80`.
   - Stemmed fingerprint Jaccard similarity should be `<= 0.60`.
8. Score margin control (global bank):
   - For suggestion text, winner margin over runner-up should be at least
     `20%` when both score above zero.

### 5. Next-question lists

1. Keys in `next_questions` must be valid existing `answerId` values.
2. Values must be lists of strings.
3. Each question string should have practical length (`>= 5` chars).
4. Question style rule:
   - Must end with `?` OR begin with a recognized question/action stem
     (`what`, `how`, `why`, `where`, `when`, `which`, `can`, `do`, `is`,
     `are`, `will`, `should`, `tell`, `show`, `explain`, `summarize`,
     `give`, `introduce`, `walk`, `list`, `recap`, `outline`, `guide`,
     `explore`, `dive`, `tips`, `describe`).
5. No duplicate next-question text within one answer's list.
6. Every next-question query should resolve globally (not `noMatch`).
7. A next-question should not resolve back to the same source answer ID.
8. Next-questions under one source answer should diversify outcomes
   (avoid duplicate resolved target IDs).
9. Similarity controls:
   - Global near-duplicate text ratio should be `<= 0.80` (SequenceMatcher).
   - Pairwise stemmed fingerprint Jaccard inside one source answer should be
     `<= 0.60`.
10. Score margin control:
    - Winner margin over runner-up should be at least `10%` when both score
      above zero.
    - Exemption: if top two candidates share the same category prefix,
      thin margin is acceptable.

### 6. Video metadata

1. `video_bank` keys must exist in `answer_bank`.
2. Each video item must contain:
   - `src` string (`>= 5` chars)
   - `label` string (`>= 5` chars)
3. `src` must point to an existing file under:
   - `frontend/static/videos/<src>`

### 7. API payload robustness (diagnostic guardrails)

1. `POST /api/chat` should not return `500` on non-object JSON payloads.
2. `POST /api/chat` should not return `500` when `message` is `null`.
3. `POST /api/chat/resolve` should not return `500` on non-object JSON payloads.
4. For malformed JSON shape, acceptable outcomes are controlled failure
   responses (`400`/`422`) or deterministic `noMatch`, but not unhandled errors.

---

## Module Bank Guardrails

1. Required keys per module bank:
   - `answers`, `suggestions`, `qa_entries`
2. Required types:
   - `answers`: dict
   - `qa_entries`: list
   - `suggestions`: list
3. Banks should be non-empty for all three required keys.
4. All answer IDs within a module bank should share one category prefix.
5. Module `qa_entries` can only reference answers inside their own module bank.
6. Module follow-up options can only reference answers inside their own module
   bank.
7. Scoped resolution check:
   - Querying with `module_slug` should return module-owned answers.
8. Global inclusion:
   - Every module answer must also exist in global `answer_bank`.
9. `answer_module_map` requirements:
   - Every module answer appears in `answer_module_map`.
   - Each mapped `slug` must match the owning module.
   - `general-*` answers must not appear in `answer_module_map`.
10. Module `next_questions` keys must belong to that module's own answers.

---

## Similarity and Collision Guardrails (Advanced)

These thresholds are part of current deep-analysis tests and must be treated as
hard limits for generated QA content:

1. Same-category answer TF-IDF cosine similarity must be `<= 0.85`.
2. Same-module answer TF-IDF cosine similarity must be `<= 0.85`.
3. Same-category answer bigram Jaccard overlap must be `<= 0.50`.
4. Same-category answer pairs should not share more than 3 filtered verbatim
   4-word phrases (excluding same section-prefix pairs and domain-term grams).
5. For module suggestions and module next-questions, avoid tied top scores for
   the same query (ambiguous winner risk).

---

## Acceptable Question Generation Rules

A generated question is acceptable only if:

1. It has a single dominant intent.
2. It has a known expected outcome:
   - `expected_type: answer` with one expected `answerId`, OR
   - explicit collision metadata with accepted IDs, OR
   - `expected_type: noMatch` for negative tests.
3. It contains anchor terms that already exist in QA keywords, unless the case
   is intentionally negative.
4. It does not require real-time external facts or unsupported policy/legal
   claims.
5. It does not mix unrelated module intents in one prompt unless the case is
   explicitly cross-module behavior testing.

Recommended coverage per intent:

1. Canonical direct phrasing
2. Natural paraphrase
3. Keyword-fragment user shorthand
4. Mildly noisy punctuation/filler variant
5. Negative/no-match probe

---

## Alignment Matrix by Test File

### `test_01_structure.py`

1. Answer ID format and lowercase.
2. Answer non-empty string and minimum length.
3. Allowed HTML tags and shape checks.
4. QA entry field presence, follow-up structure, lowercase keywords.
5. Suggestion schema checks.
6. Next-question schema and style checks.
7. Video metadata schema and file existence checks.

### `test_02_duplicates.py`

1. No duplicate answer IDs across source banks.
2. No duplicate QA answer targets (global/module).
3. No high keyword overlap in same category/module (`> 60%` forbidden).
4. No tied top scores for module suggestion/next-question text.
5. No duplicate suggestion text and no duplicate next-question text per answer.

### `test_03_answer_quality.py`

1. No placeholder/stub answer phrases.
2. Minimum answer substance checks.
3. Prefix validity checks.
4. Keyword-to-answer topical alignment checks.
5. Nonsense and empty-query `noMatch` behavior checks.
6. Basic formatting consistency checks.

### `test_04_suggestions.py`

1. Suggestion and next-question text must resolve.
2. Next-question must not loop to source answer.
3. Next-question outcomes should be diverse.
4. Module suggestions must resolve in module scope.
5. Module next-questions should resolve globally.

### `test_05_engine.py`

1. Normalization behavior checks.
2. Score primitive behavior checks.
3. Threshold behavior checks.
4. `resolve_by_answer_id` behavior checks.
5. Autocomplete behavior checks.
6. Winner-selection sanity checks for specific Copilot prompt.

### `test_06_module_banks.py`

1. Module bank required key/type/non-empty checks.
2. Module isolation checks for answers and follow-ups.
3. Scoped query ownership checks.
4. `answer_module_map` completeness and correctness checks.
5. Module next-question key ownership checks.
6. Global bank inclusion checks.

### `test_07_deep_analysis.py`

1. Near-duplicate detection on suggestions/next-questions.
2. TF-IDF cosine similarity checks on answers.
3. Stemmed keyword coverage checks.
4. N-gram overlap and shared-phrase checks.
5. Stemmed fingerprint diversity checks.
6. Score margin robustness checks.
7. Readability and vocabulary richness checks.

### `test_08_api_payload_guardrails.py`

1. API payload shape robustness checks for `/api/chat` and `/api/chat/resolve`.
2. Module-filtered suggestions and chips response shape checks.
3. Module-scope and unknown-module fallback behavior checks.

### `test_09_engine_scope_regression.py`

1. Determinism checks for repeated queries.
2. Scope fallback and pending-follow-up priority checks.
3. Threshold, normalization, and autocomplete regression checks.

### `test_10_topic_bank_reachability.py`

1. Answer-to-entry reachability checks (global + module banks).
2. First-keyword reachability smoke checks.
3. Prefix-set contract and sample query resolution checks.

---

## Suggested Test-Case Metadata Schema

Use this format for LLM-generated QA test prompts:

```yaml
- id: copilot_onboarding_sealid_01
  scope: module
  module_slug: copilot-basics
  query: "What is the Seal ID for GitHub Copilot?"
  expected_type: answer
  expected_answer_id: copilot-basics-onboarding-sealid
  collision_expected: false
  acceptable_answer_ids: []
  notes: "Canonical anchor query"
```

Negative example:

```yaml
- id: nonsense_01
  scope: global
  query: "purple elephant moon"
  expected_type: noMatch
  collision_expected: false
  acceptable_answer_ids: []
  notes: "Intentional gibberish"
```

---

## Acceptance Checklist Before Committing Generated QA Cases

1. Every positive case has a valid expected `answerId`.
2. Every expected `answerId` exists in current banks.
3. Scope is declared (`global` or `module`).
4. Module slug is present for module-scoped cases.
5. Query has anchor terms (unless explicitly negative).
6. No accidental multi-intent composition.
7. No unsupported domains requiring external live knowledge.
8. Collision/tie expectations are explicitly labeled.
9. Proposed prompts do not violate similarity and score-margin thresholds.

---

## Maintenance Rule

Update this document whenever any of the following change:

1. `backend/qa/engine.py` scoring/normalization logic
2. `backend/qa/__init__.py` bank composition or module map behavior
3. QA content IDs/prefixes/categories/modules
4. Any assertions inside `quality_control/qa_tests/test_*.py`

---

> **Continued in
> [`LLM_QA_GUARDRAILS_2.md`](LLM_QA_GUARDRAILS_2.md)** —
> LLM content-generation rules: tone, length targets, keyword strategy,
> follow-up guidance, examples, content catalog, video rules, and
> cross-category referencing.
