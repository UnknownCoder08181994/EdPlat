"""Prompt template for the Planning step."""


def build(*, artifacts_path: str, task_details: str, complexity: int = 5, known_pitfalls: str = '', **_kwargs) -> str:
    """Return the full instruction string for the Planning step."""
    def fp(filename):
        if artifacts_path == ".":
            return filename
        return f"{artifacts_path}/{filename}"

    # Complexity just sets the tone — step count comes from the task itself
    complexity_tone = (
        "bare minimum" if complexity <= 2 else
        "keep it lean" if complexity <= 4 else
        "be thorough" if complexity <= 6 else
        "be comprehensive" if complexity <= 8 else
        "go deep — cover everything"
    )

    return f"""
STOP — READ THIS FIRST (NO EXCEPTIONS)
You are in the PLANNING step.

Your job: create an implementation plan that the UI can show as build progress.

HARD RULES (ABSOLUTELY MANDATORY):
- Do NOT write any code. No pseudocode. No code blocks.
- Do NOT create any file except implementation-plan.md.
- Do NOT implement the app or generate deliverables.
- The spec.md and requirements.md have been pre-loaded above. Do NOT use ReadFile to read them again.
- Do NOT add features. The plan must only implement what is in THE USER'S TASK + requirements/spec.

=== THE USER'S TASK (SOURCE OF TRUTH #1) ===
{task_details}
=== END OF TASK ===

SOURCE OF TRUTH #2:
- requirements.md and spec.md are pre-loaded above (already in context).
- If they conflict with THE USER'S TASK, THE USER'S TASK wins.
- If something is unclear, keep the plan generic and note uncertainty in the NOTES lines (do NOT invent scope).

BEFORE WRITING — STUDY BOTH ARTIFACTS (pre-loaded above):
- Read requirements.md: identify EVERY feature and acceptance criterion.
- Read spec.md: identify the architecture, file structure, and technology stack.
- Your plan steps MUST cover every feature from requirements.md using the architecture from spec.md.
- If a requirement has no plan step that implements it, your plan is INCOMPLETE.
- If a plan step doesn't trace back to a requirement, it doesn't belong (except the 3 mandatory ending steps).

============================================================
THINKING GUIDANCE
============================================================
Think through before writing (in your thinking, not your output):
- How many distinct buildable components does this project need?
- What is the dependency order? Which files must exist first?
- What is the entry point and how does a user run the project?
- Can each step be executed independently, building on the previous?

============================================================
THE UI CONSTRAINT (STRICT)
============================================================
CRITICAL: Each `## (double hash)` heading becomes a directly executable Step in the UI.
Use EXACTLY ## for headings — NOT # or ### or ####.
The agent will run EACH heading as its own work unit — writing code and building files.
Each `- [ ]` checkbox describes a concrete task the agent will perform within this step.

IMPORTANT — each checkbox item is guidance for the agent working on this step.
The checkbox descriptions must be 15+ words of self-contained instruction with
no thinking or commentary — just actionable build instructions.
Include no thinking in the file.

IMPORTANT — FLAT STRUCTURE ONLY:
- Each `##` heading IS the work. There is NO grouping or nesting.
- Do NOT create category headings (e.g. "User Management") that just group sub-topics.
- Every heading must describe REAL, buildable work — not an organizational category.

============================================================
HOW MANY STEPS?
============================================================
The user rated this task {complexity}/10 complexity. Approach: {complexity_tone}.

Use as many ## headings as the task ACTUALLY NEEDS for BUILDING CODE — no more, no less.
- A simple script? 1 code step.
- A multi-module app? 3-5 code steps.
- A full-scale project with many components? 5-8 code steps.

Read the requirements and spec. Count the distinct buildable components. That is your CODE step count.
ABSOLUTE MAXIMUM: 8 code headings.

After ALL code steps, you MUST add exactly 3 MANDATORY ENDING STEPS (detailed below).
These always come last and are REQUIRED on every plan.

============================================================
HEADING & LABEL RULES (STRICT)
============================================================
HEADING LABELS (##):
- MUST be 3–6 words. Title Case.
- MUST START with an action verb. Use DIVERSE verbs — NEVER repeat the same verb on two consecutive headings.
- VERB VARIETY IS MANDATORY. Pick from this list and ROTATE through them:
  Create, Design, Wire, Configure, Set Up, Add, Connect, Assemble, Define, Construct, Compose, Establish
- BANNED: Do NOT use "Build" as a heading verb. It is overused and vague. Use a specific alternative.
- BANNED: Do NOT use "Implementing" or "Implement".
- If you catch yourself starting 2+ headings with the same verb, STOP and pick a different verb.
- These headings are shown to the USER watching an agent build their project.
  They should read like a build log — each heading tells the user what is being DONE.
- No punctuation at the end.
- NEVER include complexity/difficulty labels like (Simple), (Medium), (Complex), (Advanced).
- Each heading must be a self-contained unit of work that produces files.
- DO NOT use generic labels like "Core Application", "Quality Assurance", "Setup Files".
- DO NOT create extra Documentation or Testing steps in your CODE steps — fold them in.
  (The 2 mandatory ending steps handle environment and user guide separately.)
- Do NOT create unit test steps or test files. The execution agent handles testing separately.
- GOOD: "Create Project Entry Point", "Design Database Schema", "Wire REST API Routes", "Configure Logging System", "Assemble CLI Commands", "Define Search Engine"
- BAD: "Build API" (banned verb), "Build Models" (banned verb), "Project Entry Point" (no verb), "Implementing Scan" (banned verb), "Setup" (too vague)

SUB-STEP LABELS (- [ ]):
- MUST be 3–5 words. Title Case. No punctuation.
- Describe a CONCRETE deliverable.

============================================================
FORMAT RULES (MANDATORY)
============================================================
1) Use EXACTLY `## (double hash)` for headings. NOT # or ### or ####.
2) The file must start with ## (no title, no intro paragraph).
3) Do NOT write "Category 1:" or any numbering prefix — just the heading text.
4) Every heading includes a `Files:` line listing NEW files created in this step.
5) If this step creates code that must be imported/registered in an EXISTING file,
   add a `Modifies:` line. Examples:
   - New Flask blueprint → Modifies: main.py (to register_blueprint)
   - New route/handler module → Modifies: app.py (to import and mount)
   Omit Modifies if no existing files need changes.
6) Every heading includes a `Depends on:` line: which prior heading(s) this step imports from. First step: `Depends on: none`.
6) If a heading creates the project entry point, add `Entry point: YES — <run command>` (e.g. `Entry point: YES — python main.py`). Otherwise omit this line.
7) Every heading has `- [ ]` sub-steps underneath.
8) Do NOT copy the example below — write your own content specific to THE USER'S TASK.
   DO NOT copy category names, sub-step names, or file names from the example.
9) Do NOT use numbered lists.
10) Do NOT invent build steps for unrequested features.

============================================================
PROJECT STRUCTURE RULES (MANDATORY)
============================================================
You are planning ONE cohesive, runnable project — not isolated files.
- The FIRST implementation heading must set up the project entry point (e.g. main.py, app.py, cli.py).
  This file must be runnable: `python main.py` (or equivalent) should execute the project.
- Each heading builds ON TOP of previous headings. Later steps import from / extend earlier steps.
- The Files: lines across ALL headings must form a complete project — no orphan files, no missing imports.
- The Depends on: line traces the import graph. If step B depends on step A, step A's Files MUST define what step B imports.
- Think: "After all steps run, can someone type one command to use this project?" If not, fix the plan.

INTEGRATION WIRING (CRITICAL — #1 cause of broken multi-file projects):
- If a step creates a module (blueprint, router, handler, service), the plan MUST say where it gets registered.
- Use the Modifies: line. Example: Files: auth.py, Modifies: main.py
- This tells the agent: "After writing auth.py, EditFile main.py to register it."
- If 3+ steps create modules but NONE modify the entry point, the plan is BROKEN.
- Every new .py file must be imported somewhere — an unimported file is dead code.

CONFIG & DATA FILES (CRITICAL — #2 cause of broken projects):
- If your code reads a config file (YAML, JSON, .env, INI, TOML), you MUST create that file in the plan.
- If a step creates config.py that loads config.yml, the Files: line MUST include BOTH: Files: config.py, config.yml
- If your code reads sample data, templates, or schema files, include them in Files: too.
- Think: "When the user runs this project for the first time, what files must already exist on disk?"
  Every file that must exist → must appear in some step's Files: line.
- Default config files should have WORKING default values so the project runs out of the box.
- Common examples:
  - Python reads config.yaml → Files: config.py, config.yaml
  - App loads .env → Files: app.py, .env.example
  - SQLite DB path in config → config must include a valid default path like ./data.db
  - Templates directory → Files: templates/index.html, templates/base.html

FILE LOCATION & IMPORT CONSISTENCY (CRITICAL — #1 cause of broken projects):
- PREFER FLAT file layout (all .py files at project root) unless the task explicitly needs a package.
  GOOD: main.py, storage.py, cli.py, reporting.py (all at root, import as `from storage import func`)
  BAD: main.py at root + random_package/storage.py (creates confusing import paths)
- If you DO use a package directory (e.g. myapp/), then ALL module files must go INSIDE that directory.
  main.py at root does `from myapp import cli` → cli.py MUST be at myapp/cli.py, NOT at root.
- NEVER split modules between root and a package directory. Either ALL at root OR ALL in the package.
- The Files: line must show the EXACT path where each file goes (e.g. `myapp/cli.py` not just `cli.py`).
- If using a package, include `myapp/__init__.py` in the Files: line of the first step.

============================================================
SCOPE RULES (MANDATORY)
============================================================
- Only plan what is necessary to satisfy requirements.md + THE USER'S TASK.
- Do NOT add auth, DB, API, caching, pagination, CI/CD, Docker, or extra platforms unless explicitly required.
- Prefer a single-application design unless requirements force otherwise.
- The 3 mandatory ending steps (environment, tests, user guide) are NOT extra scope — they are always required.

{"" if not known_pitfalls else f"""============================================================
KNOWN PITFALLS FROM PAST TASKS
============================================================
{known_pitfalls}
Avoid these mistakes. They have been seen in similar projects before.
"""}============================================================
MANDATORY ENDING STEPS (ALWAYS — AFTER ALL CODE STEPS)
============================================================
After ALL code-building steps are done, add these 2 steps IN THIS EXACT ORDER.
CRITICAL: These MUST be the LAST 2 steps in the plan. No code steps may appear after these.
Do NOT place "Setting Up Environment" in the middle of code steps — it goes AFTER all code.
Use these EXACT heading names. Do NOT rename, skip, or reorder them.
IMPORTANT: Adapt the descriptions and notes to match YOUR PROJECT'S actual technology.
Do NOT blindly copy — rewrite notes to fit the language, framework, and files you planned above.
Do NOT create a unit testing step — the execution agent handles testing separately.

## Setting Up Environment
[Write a sentence describing what dependencies YOUR project needs.]
Files: [dependency file for your project — e.g. requirements.txt for Python, package.json for JS]
Depends on: [last code step name]
- [ ] Dependency Audit
  - Notes: [Scan all source files for imports/dependencies. List every third-party package in the dependency file. Adapt to your tech — Python uses requirements.txt, JS uses package.json, etc.]
- [ ] Run Verification
  - Notes: [Describe the exact command to install deps and run the project. Must match YOUR entry point from above.]

## Creating User Guide
Write a short README.md a complete beginner can follow to run this project.
Files: README.md
Depends on: Setting Up Environment
- [ ] Setup Instructions
  - Notes: [Keep it short. What does this project do (one sentence), then numbered steps to run it: open PowerShell/Terminal, cd to folder, run the command. Show EXACT commands to copy-paste. No installation essays, no architecture explanations.]
- [ ] Usage Examples
  - Notes: [Show 2-3 example commands with different inputs and what the output looks like when it works.]

============================================================
REQUIRED OUTPUT FORMAT (STRICT)
============================================================
You MUST output a WriteFile tool call with JSON that writes implementation-plan.md.

The Markdown inside `content` MUST follow this exact structure:

## [Short Heading Label]
[One-sentence description of what this step builds.]
Files: [comma-separated NEW files created in this step]
Modifies: [existing files this step must edit to wire in new code — omit if none]
Depends on: [prior heading name(s), or "none" for the first step]
- [ ] [Short Sub-step Label]
  - Notes: [1–3 lines describing what to build, full sentences allowed]
- [ ] [Short Sub-step Label]
  - Notes: [...]

## [Next Short Heading Label]
...

============================================================
WRITEFILE EXAMPLE (STYLE REFERENCE — DO NOT COPY)
============================================================
NOTE: This example demonstrates LENGTH + NOTES usage, not your task's content.
DO NOT copy names, structure, or file paths from this example.

{{
  "name": "WriteFile",
  "arguments": {{
    "path": "{fp('implementation-plan.md')}",
    "content": "## Create Project Entry Point\\nSet up the runnable project shell with main script and dependency file.\\nFiles: main.py, requirements.txt\\nDepends on: none\\nEntry point: YES — python main.py\\n- [ ] Main Script Shell\\n  - Notes: Define the single command to run the project locally.\\n- [ ] Dependency Baseline\\n  - Notes: List only required runtime dependencies; do not add extra tooling unless required.\\n\\n## Design CSV Data Loader\\nCreate the data ingestion path that reads and validates input files for the dashboard.\\nFiles: src/io.py, src/models.py\\nModifies: main.py\\nDepends on: Create Project Entry Point\\n- [ ] Input Source Handling\\n  - Notes: Support only the input sources explicitly requested; treat everything else as out-of-scope.\\n- [ ] Validation And Errors\\n  - Notes: Validate required fields/shape and produce actionable error messages aligned to acceptance criteria.\\n\\n## Setting Up Environment\\nAudit all Python imports and ensure requirements.txt lists every third-party dependency.\\nFiles: requirements.txt\\nDepends on: Design CSV Data Loader\\n- [ ] Dependency Audit\\n  - Notes: Scan all .py files for imports like pandas, flask, requests. Pin versions in requirements.txt.\\n- [ ] Run Verification\\n  - Notes: Verify project runs: pip install -r requirements.txt && python main.py.\\n\\n## Creating User Guide\\nWrite a short README a beginner can follow to run this project.\\nFiles: README.md\\nDepends on: Setting Up Environment\\n- [ ] Setup Instructions\\n  - Notes: One sentence what it does, then numbered steps: open PowerShell, cd to folder, run the command. Exact copy-paste commands only.\\n- [ ] Usage Examples\\n  - Notes: Show 2-3 example commands with different inputs and expected output."
  }}
}}

=== END OF EXAMPLE ===

============================================================
PRE-FLIGHT CHECK (do this in your thinking BEFORE calling WriteFile)
============================================================
1. VERB CHECK: Read all your ## headings. Did you use "Build"? Change it. Did you repeat any verb? Fix it.
2. FILE CHECK: For every code file that reads/loads an external file (YAML, JSON, .env, SQL, CSV),
   is that external file listed in some step's Files: line? If not, add it.
3. IMPORT CHECK: For every .py file in Files:, is it imported somewhere? Check Modifies: lines.
4. RUN CHECK: Imagine typing `python main.py` after all steps complete. Would it work?
   - Are all config files present with working defaults?
   - Are all dependencies listed in requirements.txt?
   - Is every module imported by the entry point?
5. FIRST-RUN CHECK: A user clones this project and runs it. What breaks? Fix those gaps NOW.

============================================================
FINAL INSTRUCTIONS
============================================================
1) Go DIRECTLY to WriteFile. Do NOT narrate your reasoning — your chain-of-thought is captured separately.
2) Write implementation-plan.md content using the exact structure and label-length rules above.
3) SAVE using WriteFile to: {fp('implementation-plan.md')}
4) After the WriteFile call succeeds, say [STEP_COMPLETE].

CRITICAL — WRITE ONCE ONLY:
- Call WriteFile for implementation-plan.md EXACTLY ONCE. ONE time. Not twice.
- After WriteFile succeeds, you are DONE. Say [STEP_COMPLETE] and STOP.
- Do NOT rewrite, revise, or re-save the file. The first save IS the final save.
- Do NOT say "let me improve this" or "let me refine this". Save once, then stop.

CRITICAL — GO STRAIGHT TO WRITEFILE:
- Do NOT narrate your reasoning in the chat — your chain-of-thought is captured separately.
- Put ALL content inside the WriteFile content field.
- The WriteFile `content` field must contain the COMPLETE implementation plan.
- Do NOT write out the plan as text and then call WriteFile with "..." placeholders.
- Use \\n for newlines inside the JSON content string. Do NOT use actual line breaks inside JSON.

REMINDER: You may ONLY create implementation-plan.md. Do NOT create the actual deliverable.
""".lstrip()
