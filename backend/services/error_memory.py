"""Universal Error Memory — cross-task error/resolution database with RL.

Records error patterns and their resolutions, then provides lookup
for future tasks to avoid repeating the same mistakes.

v2 features:
  - Escalation tiers: warnings get stronger as errors repeat
  - Multi-armed bandit: Thompson Sampling ranks fix strategies
  - Context fingerprinting: workspace-aware similarity scoring

Storage: storage/error_memory.json (global, persists across all tasks)
"""

import os
import re
import json
import random
import hashlib
import math
import fnmatch
import threading
from datetime import datetime, timedelta

from config import Config
from utils.logging import _safe_log

# File-level lock for concurrent access to error_memory.json
_db_lock = threading.Lock()

# ── Constants ──────────────────────────────────────────────────
MAX_ENTRIES = 80
PRUNE_TARGET = 70
DECAY_DAYS = 90
MIN_CONFIDENCE = 0.3
MAX_INJECTION_CHARS = 600
MAX_TIER3_CHARS = 400
MAX_BULLET_CHARS = 100
DB_PATH = os.path.join(Config.STORAGE_DIR, 'error_memory.json')

# ── Escalation tiers ──────────────────────────────────────────
TIER1_MAX = 2       # effective_hits 0-2: Note
TIER2_MAX = 5       # effective_hits 3-5: Warning
# effective_hits 6+: Tier 3 Critical
TIER3_ALWAYS_INJECT = True

# ── Multi-armed bandit ────────────────────────────────────────
BANDIT_ALPHA_PRIOR = 1   # optimistic prior for new strategies
BANDIT_BETA_PRIOR = 1

# ── Context fingerprinting ────────────────────────────────────
FINGERPRINT_WEIGHT = 15.0   # scoring: between tag (10) and exact match (100)
COMPLEXITY_BUCKETS = {
    (0, 3): "trivial",
    (3, 5): "simple",
    (5, 7): "medium",
    (7, 9): "complex",
    (9, 11): "massive",
}
EXT_TO_TECH = {
    '.py': 'python', '.js': 'javascript', '.ts': 'typescript',
    '.html': 'html', '.css': 'css', '.jsx': 'react',
    '.tsx': 'react-ts', '.vue': 'vue', '.rs': 'rust',
    '.go': 'go', '.java': 'java', '.rb': 'ruby',
    '.php': 'php', '.cs': 'csharp', '.cpp': 'cpp',
}
SKIP_DIRS = {'node_modules', 'venv', '.venv', '__pycache__', '.git', '.sentinel', 'dist', 'build'}
MAX_LIBRARIES = 20

# ── Seed data — known pitfalls bootstrapped on first run ──────
_now_iso = datetime.utcnow().isoformat()

SEED_ENTRIES = [
    {
        "id": "seed_001",
        "sig": "planning:pip_nodejs_tools",
        "type": "planning",
        "tags": ["planning", "implementation", "execution"],
        "pattern": "vite|sass|webpack|babel|eslint|prettier|tailwindcss",
        "context": "nodejs",
        "mistake": "Put Node.js tools (vite, sass, webpack) in requirements.txt",
        "fix": "Node.js tools go in package.json devDependencies, NOT requirements.txt. requirements.txt is Python-only.",
        "fixes": [{"strategy": "Node.js tools go in package.json devDependencies, NOT requirements.txt. requirements.txt is Python-only.", "alpha": 6, "beta": 1, "last_used": _now_iso}],
        "fingerprint": {"tech_stack": ["javascript", "python"], "libraries": [], "file_exts": [".py", ".js"], "step_type": "planning", "complexity_bucket": "medium"},
        "auto_fix": {
            "type": "line_remove",
            "file_pattern": "requirements.txt",
            "find": r"^(vite|sass|webpack|babel|eslint|prettier|tailwindcss|postcss|autoprefixer)([>=<~!\[].*)?$",
            "on_write": True,
            "description": "Remove Node.js packages from requirements.txt",
        },
        "hits": 5, "confirmed": 5, "failed": 0, "confidence": 1.0,
        "first_seen": _now_iso, "last_seen": _now_iso, "last_confirmed": _now_iso,
        "source": "seed",
    },
    {
        "id": "seed_002",
        "sig": "module_not_found:cv2",
        "type": "module_not_found",
        "tags": ["execution"],
        "pattern": "cv2",
        "context": "python",
        "mistake": "pip install cv2",
        "fix": "The pip package is opencv-python, not cv2. Run: pip install opencv-python",
        "fixes": [{"strategy": "The pip package is opencv-python, not cv2. Run: pip install opencv-python", "alpha": 4, "beta": 1, "last_used": _now_iso}],
        "fingerprint": {"tech_stack": ["python"], "libraries": ["opencv-python"], "file_exts": [".py"], "step_type": "execution", "complexity_bucket": "medium"},
        "hits": 3, "confirmed": 3, "failed": 0, "confidence": 1.0,
        "first_seen": _now_iso, "last_seen": _now_iso, "last_confirmed": _now_iso,
        "source": "seed",
    },
    {
        "id": "seed_003",
        "sig": "module_not_found:PIL",
        "type": "module_not_found",
        "tags": ["execution"],
        "pattern": "PIL",
        "context": "python",
        "mistake": "pip install PIL",
        "fix": "The pip package is Pillow, not PIL. Run: pip install Pillow",
        "fixes": [{"strategy": "The pip package is Pillow, not PIL. Run: pip install Pillow", "alpha": 4, "beta": 1, "last_used": _now_iso}],
        "fingerprint": {"tech_stack": ["python"], "libraries": ["pillow"], "file_exts": [".py"], "step_type": "execution", "complexity_bucket": "medium"},
        "hits": 3, "confirmed": 3, "failed": 0, "confidence": 1.0,
        "first_seen": _now_iso, "last_seen": _now_iso, "last_confirmed": _now_iso,
        "source": "seed",
    },
    {
        "id": "seed_004",
        "sig": "module_not_found:sklearn",
        "type": "module_not_found",
        "tags": ["execution"],
        "pattern": "sklearn",
        "context": "python",
        "mistake": "pip install sklearn",
        "fix": "The pip package is scikit-learn, not sklearn. Run: pip install scikit-learn",
        "fixes": [{"strategy": "The pip package is scikit-learn, not sklearn. Run: pip install scikit-learn", "alpha": 4, "beta": 1, "last_used": _now_iso}],
        "fingerprint": {"tech_stack": ["python"], "libraries": ["scikit-learn"], "file_exts": [".py"], "step_type": "execution", "complexity_bucket": "medium"},
        "hits": 3, "confirmed": 3, "failed": 0, "confidence": 1.0,
        "first_seen": _now_iso, "last_seen": _now_iso, "last_confirmed": _now_iso,
        "source": "seed",
    },
    {
        "id": "seed_005",
        "sig": "planning:flat_vs_package_imports",
        "type": "planning",
        "tags": ["planning", "implementation"],
        "pattern": "import|from.*import|__init__",
        "context": "python",
        "mistake": "Mixed flat and package file layout causing import failures",
        "fix": "Keep all .py files at project root (flat layout) unless the task explicitly requires packages.",
        "fixes": [{"strategy": "Keep all .py files at project root (flat layout) unless the task explicitly requires packages.", "alpha": 5, "beta": 1, "last_used": _now_iso}],
        "fingerprint": {"tech_stack": ["python"], "libraries": [], "file_exts": [".py"], "step_type": "planning", "complexity_bucket": "medium"},
        "hits": 4, "confirmed": 4, "failed": 0, "confidence": 1.0,
        "first_seen": _now_iso, "last_seen": _now_iso, "last_confirmed": _now_iso,
        "source": "seed",
    },
    {
        "id": "seed_006",
        "sig": "implementation:missing_config_file",
        "type": "implementation",
        "tags": ["implementation", "execution"],
        "pattern": "config|yaml|json|env|toml|ini",
        "context": "",
        "mistake": "Code reads a config file that was never created",
        "fix": "If code reads config.yaml/.json/.env, you MUST create that file with working defaults in the same step.",
        "fixes": [{"strategy": "If code reads config.yaml/.json/.env, you MUST create that file with working defaults in the same step.", "alpha": 4, "beta": 1, "last_used": _now_iso}],
        "fingerprint": {"tech_stack": [], "libraries": [], "file_exts": [], "step_type": "implementation", "complexity_bucket": "medium"},
        "hits": 3, "confirmed": 3, "failed": 0, "confidence": 1.0,
        "first_seen": _now_iso, "last_seen": _now_iso, "last_confirmed": _now_iso,
        "source": "seed",
    },
    {
        "id": "seed_007",
        "sig": "implementation:unregistered_blueprint",
        "type": "implementation",
        "tags": ["implementation"],
        "pattern": "blueprint|router|register",
        "context": "flask",
        "mistake": "Created Flask blueprint but never registered it in the entry point",
        "fix": "After creating a new blueprint/router, ALWAYS EditFile the entry point to register_blueprint() or include_router().",
        "fixes": [{"strategy": "After creating a new blueprint/router, ALWAYS EditFile the entry point to register_blueprint() or include_router().", "alpha": 4, "beta": 1, "last_used": _now_iso}],
        "fingerprint": {"tech_stack": ["python"], "libraries": ["flask"], "file_exts": [".py"], "step_type": "implementation", "complexity_bucket": "medium"},
        "hits": 3, "confirmed": 3, "failed": 0, "confidence": 1.0,
        "first_seen": _now_iso, "last_seen": _now_iso, "last_confirmed": _now_iso,
        "source": "seed",
    },
    {
        "id": "seed_008",
        "sig": "execution:windows_unix_commands",
        "type": "execution",
        "tags": ["execution", "implementation"],
        "pattern": "touch|rm -rf|export|source|chmod",
        "context": "windows",
        "mistake": "Used Unix-only commands on Windows",
        "fix": "On Windows: no touch, rm -rf, export, source, chmod. Use WriteFile to create files, set for env vars.",
        "fixes": [{"strategy": "On Windows: no touch, rm -rf, export, source, chmod. Use WriteFile to create files, set for env vars.", "alpha": 3, "beta": 1, "last_used": _now_iso}],
        "fingerprint": {"tech_stack": [], "libraries": [], "file_exts": [], "step_type": "execution", "complexity_bucket": "medium"},
        "hits": 2, "confirmed": 2, "failed": 0, "confidence": 1.0,
        "first_seen": _now_iso, "last_seen": _now_iso, "last_confirmed": _now_iso,
        "source": "seed",
    },
    {
        "id": "seed_009",
        "sig": "planning:windows_unicode_output",
        "type": "planning",
        "tags": ["planning", "implementation"],
        "pattern": "rich|click|tabulate|colorama|unicode|utf-8|encoding",
        "context": "windows",
        "mistake": "Used Unicode characters in strings that go to console output on Windows",
        "fix": "NEVER use Unicode chars like \\u2011, \\u2013, \\u2019 in CLI output strings. Use ASCII equivalents.",
        "fixes": [{"strategy": "NEVER use Unicode chars like \\u2011, \\u2013, \\u2019 in CLI output strings. Use ASCII equivalents.", "alpha": 4, "beta": 1, "last_used": _now_iso}],
        "fingerprint": {"tech_stack": ["python"], "libraries": [], "file_exts": [".py"], "step_type": "planning", "complexity_bucket": "medium"},
        "auto_fix": {
            "type": "regex_replace",
            "file_pattern": "*.py",
            "find": "[\u2018\u2019\u201c\u201d\u2011\u2010\u2013\u2014\u2026\u00a0\u2022]",
            "replace_map": {
                "\u2018": "'", "\u2019": "'",
                "\u201c": '"', "\u201d": '"',
                "\u2011": "-", "\u2010": "-",
                "\u2013": "-", "\u2014": "--",
                "\u2026": "...", "\u00a0": " ", "\u2022": "-",
            },
            "on_write": True,
            "description": "Replace Unicode punctuation with ASCII equivalents",
        },
        "hits": 3, "confirmed": 3, "failed": 0, "confidence": 1.0,
        "first_seen": _now_iso, "last_seen": _now_iso, "last_confirmed": _now_iso,
        "source": "seed",
    },
]


class ErrorMemory:
    """Cross-task error/resolution database with reinforcement learning.

    All methods are static — no instance state. Storage is a single
    JSON file at storage/error_memory.json.

    v2 features: escalation tiers, multi-armed bandit, context fingerprinting.
    """

    # ── Migration ─────────────────────────────────────────────

    # Build a lookup of seed auto_fix configs by ID for migration
    _SEED_AUTO_FIX = {s['id']: s['auto_fix'] for s in SEED_ENTRIES if 'auto_fix' in s}

    @staticmethod
    def migrate_entry(entry):
        """Ensure an entry has all v2 fields with sensible defaults. Idempotent."""
        # Add fixes array if missing
        if 'fixes' not in entry:
            fix_str = entry.get('fix', '')
            if fix_str and fix_str != 'unresolved':
                entry['fixes'] = [{
                    'strategy': fix_str[:200],
                    'alpha': max(entry.get('confirmed', 1), BANDIT_ALPHA_PRIOR),
                    'beta': max(entry.get('failed', 0), BANDIT_BETA_PRIOR),
                    'last_used': entry.get('last_confirmed', '') or entry.get('last_seen', ''),
                }]
            else:
                entry['fixes'] = []

        # Add fingerprint if missing
        if 'fingerprint' not in entry:
            tech = []
            ctx = entry.get('context', '')
            if ctx and ctx != '':
                tech = [ctx.lower()]
            entry['fingerprint'] = {
                "tech_stack": tech,
                "libraries": [],
                "file_exts": [],
                "step_type": entry.get('type', ''),
                "complexity_bucket": "medium",
            }

        # Inject auto_fix from seed definitions if entry is a seed and missing it
        if 'auto_fix' not in entry:
            entry_id = entry.get('id', '')
            if entry_id in ErrorMemory._SEED_AUTO_FIX:
                entry['auto_fix'] = dict(ErrorMemory._SEED_AUTO_FIX[entry_id])

        return entry

    @staticmethod
    def migrate_db(db):
        """Migrate DB from v1 to v2 format. Idempotent."""
        if db.get('version', 1) >= 2:
            for entry in db.get('entries', []):
                ErrorMemory.migrate_entry(entry)
            return db

        _safe_log("[ErrorMemory] Migrating DB from v1 to v2")
        for entry in db.get('entries', []):
            ErrorMemory.migrate_entry(entry)

        db['version'] = 2
        ErrorMemory.save(db)
        _safe_log(f"[ErrorMemory] Migration complete: {len(db.get('entries', []))} entries updated")
        return db

    # ── I/O ────────────────────────────────────────────────────

    @staticmethod
    def load():
        """Load the error memory DB. Auto-migrates v1 → v2.

        Thread-safe: acquires _db_lock before file I/O.
        """
        with _db_lock:
            try:
                if os.path.isfile(DB_PATH):
                    with open(DB_PATH, 'r', encoding='utf-8') as f:
                        raw = f.read()
                    if not raw.strip():
                        _safe_log("[ErrorMemory] DB file is empty, returning default")
                        return {"version": 2, "entries": []}
                    db = json.loads(raw)
                    if not isinstance(db, dict):
                        _safe_log("[ErrorMemory] DB file is not a JSON object, returning default")
                        return {"version": 2, "entries": []}
                    if db.get('version', 1) < 2:
                        db = ErrorMemory.migrate_db(db)
                    return db
            except json.JSONDecodeError as e:
                _safe_log(f"[ErrorMemory] Corrupted JSON, backing up and resetting: {e}")
                # Back up the corrupted file so we don't lose data entirely
                try:
                    backup = DB_PATH + '.corrupt'
                    if not os.path.isfile(backup):
                        os.rename(DB_PATH, backup)
                except Exception:
                    pass
            except Exception as e:
                _safe_log(f"[ErrorMemory] Failed to load DB: {e}")
            return {"version": 2, "entries": []}

    @staticmethod
    def save(db):
        """Save the error memory DB to disk.

        Thread-safe: acquires _db_lock. Writes to a temp file first
        then renames atomically to prevent half-written corruption.
        """
        with _db_lock:
            try:
                os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
                tmp_path = DB_PATH + '.tmp'
                with open(tmp_path, 'w', encoding='utf-8') as f:
                    json.dump(db, f, indent=2)
                # Atomic rename (on Windows this may fail if target exists)
                try:
                    os.replace(tmp_path, DB_PATH)
                except OSError:
                    # Fallback for older Windows: delete + rename
                    if os.path.isfile(DB_PATH):
                        os.remove(DB_PATH)
                    os.rename(tmp_path, DB_PATH)
            except Exception as e:
                _safe_log(f"[ErrorMemory] Failed to save DB: {e}")

    @staticmethod
    def ensure_seeded():
        """Populate with seed entries if DB doesn't exist, or add missing seeds."""
        if not os.path.isfile(DB_PATH):
            now = datetime.utcnow().isoformat()
            entries = []
            for seed in SEED_ENTRIES:
                entry = dict(seed)
                entry["first_seen"] = now
                entry["last_seen"] = now
                entry["last_confirmed"] = now
                entries.append(entry)
            db = {"version": 2, "entries": entries}
            ErrorMemory.save(db)
            _safe_log(f"[ErrorMemory] Seeded {len(entries)} entries (v2)")
            return

        # DB exists — check for missing seed entries and add them
        try:
            db = ErrorMemory.load()
            existing_ids = {e.get('id') for e in db.get('entries', [])}
            now = datetime.utcnow().isoformat()
            added = 0

            for seed in SEED_ENTRIES:
                if seed['id'] not in existing_ids:
                    entry = dict(seed)
                    entry["first_seen"] = now
                    entry["last_seen"] = now
                    entry["last_confirmed"] = now
                    db['entries'].append(entry)
                    added += 1

            # Also migrate existing entries (picks up auto_fix from seeds)
            for entry in db.get('entries', []):
                ErrorMemory.migrate_entry(entry)

            if added > 0:
                ErrorMemory.save(db)
                _safe_log(f"[ErrorMemory] Added {added} missing seed entries")
            else:
                # Still save if migration added auto_fix fields
                ErrorMemory.save(db)
        except Exception as e:
            _safe_log(f"[ErrorMemory] ensure_seeded update failed: {e}")

    # ── Escalation Tiers ──────────────────────────────────────

    @staticmethod
    def compute_tier(entry):
        """Compute escalation tier (1-3) from hits + failed count.

        Failures accelerate escalation: each failure counts as 0.5 extra hit.
        """
        hits = entry.get('hits', 1)
        failed = entry.get('failed', 0)
        effective = hits + (failed * 0.5)
        if effective <= TIER1_MAX:
            return 1
        elif effective <= TIER2_MAX:
            return 2
        else:
            return 3

    # ── Context Fingerprinting ────────────────────────────────

    @staticmethod
    def compute_fingerprint(workspace_path, step_type='', complexity=5):
        """Build a lightweight context fingerprint from the workspace.

        Scans for requirements.txt, package.json, and file extensions.
        Returns: {tech_stack, libraries, file_exts, step_type, complexity_bucket}
        """
        tech_stack = set()
        libraries = set()
        file_exts = set()

        if not workspace_path or not os.path.isdir(workspace_path):
            return {
                "tech_stack": [], "libraries": [], "file_exts": [],
                "step_type": step_type,
                "complexity_bucket": ErrorMemory._complexity_to_bucket(complexity),
            }

        # Scan file extensions (top 2 levels, skip noise dirs)
        try:
            for item in os.listdir(workspace_path):
                full = os.path.join(workspace_path, item)
                if os.path.isfile(full):
                    ext = os.path.splitext(item)[1].lower()
                    if ext:
                        file_exts.add(ext)
                elif os.path.isdir(full) and item not in SKIP_DIRS:
                    try:
                        for sub in os.listdir(full):
                            if os.path.isfile(os.path.join(full, sub)):
                                ext = os.path.splitext(sub)[1].lower()
                                if ext:
                                    file_exts.add(ext)
                    except OSError:
                        pass
        except OSError:
            pass

        # Map extensions to tech stack
        for ext in file_exts:
            if ext in EXT_TO_TECH:
                tech_stack.add(EXT_TO_TECH[ext])

        # Parse requirements.txt for Python libraries
        req_path = os.path.join(workspace_path, 'requirements.txt')
        if os.path.isfile(req_path):
            tech_stack.add('python')
            try:
                with open(req_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            pkg = re.split(r'[>=<!~\[\s]', line)[0].strip().lower()
                            if pkg:
                                libraries.add(pkg)
            except OSError:
                pass

        # Parse package.json for JS libraries
        pkg_path = os.path.join(workspace_path, 'package.json')
        if os.path.isfile(pkg_path):
            tech_stack.add('javascript')
            try:
                with open(pkg_path, 'r', encoding='utf-8') as f:
                    pkg_data = json.load(f)
                for section in ('dependencies', 'devDependencies'):
                    for dep in pkg_data.get(section, {}):
                        libraries.add(dep.lower())
            except (OSError, json.JSONDecodeError):
                pass

        # Cap libraries
        lib_list = sorted(libraries)[:MAX_LIBRARIES]

        return {
            "tech_stack": sorted(tech_stack),
            "libraries": lib_list,
            "file_exts": sorted(file_exts),
            "step_type": step_type,
            "complexity_bucket": ErrorMemory._complexity_to_bucket(complexity),
        }

    @staticmethod
    def _complexity_to_bucket(complexity):
        """Map numeric complexity (1-10) to a string bucket."""
        for (lo, hi), bucket in COMPLEXITY_BUCKETS.items():
            if lo <= complexity < hi:
                return bucket
        return "complex"

    @staticmethod
    def fingerprint_similarity(fp1, fp2):
        """Weighted Jaccard similarity between two fingerprints. Returns 0.0-1.0."""
        if not fp1 or not fp2:
            return 0.0

        score = 0.0
        weights = 0.0

        # Tech stack overlap (weight 2)
        s1 = set(fp1.get('tech_stack', []))
        s2 = set(fp2.get('tech_stack', []))
        if s1 or s2:
            jaccard = len(s1 & s2) / len(s1 | s2) if (s1 | s2) else 0.0
            score += jaccard * 2.0
            weights += 2.0

        # Library overlap (weight 3 — most discriminating)
        l1 = set(fp1.get('libraries', []))
        l2 = set(fp2.get('libraries', []))
        if l1 or l2:
            jaccard = len(l1 & l2) / len(l1 | l2) if (l1 | l2) else 0.0
            score += jaccard * 3.0
            weights += 3.0

        # File extension overlap (weight 1)
        e1 = set(fp1.get('file_exts', []))
        e2 = set(fp2.get('file_exts', []))
        if e1 or e2:
            jaccard = len(e1 & e2) / len(e1 | e2) if (e1 | e2) else 0.0
            score += jaccard * 1.0
            weights += 1.0

        # Step type match (weight 1, binary)
        if fp1.get('step_type') and fp2.get('step_type'):
            score += (1.0 if fp1['step_type'] == fp2['step_type'] else 0.0)
            weights += 1.0

        # Complexity bucket match (weight 0.5, binary)
        if fp1.get('complexity_bucket') and fp2.get('complexity_bucket'):
            score += (0.5 if fp1['complexity_bucket'] == fp2['complexity_bucket'] else 0.0)
            weights += 0.5

        return score / weights if weights > 0 else 0.0

    @staticmethod
    def _merge_fingerprint(entry, new_fp):
        """Merge a new fingerprint into an existing entry (union of sets)."""
        existing_fp = entry.get('fingerprint', {})
        for key in ('tech_stack', 'libraries', 'file_exts'):
            merged = set(existing_fp.get(key, []))
            merged.update(new_fp.get(key, []))
            existing_fp[key] = sorted(merged)[:MAX_LIBRARIES if key == 'libraries' else 50]
        # step_type and complexity_bucket: keep most recent
        if new_fp.get('step_type'):
            existing_fp['step_type'] = new_fp['step_type']
        if new_fp.get('complexity_bucket'):
            existing_fp['complexity_bucket'] = new_fp['complexity_bucket']
        entry['fingerprint'] = existing_fp

    # ── Multi-Armed Bandit ────────────────────────────────────

    @staticmethod
    def sample_best_fix(entry):
        """Use Thompson Sampling to select the best fix from multiple strategies.

        Returns the fix string. Falls back to entry['fix'] if no 'fixes' array.
        """
        fixes = entry.get('fixes', [])
        if not fixes:
            return entry.get('fix', '')

        if len(fixes) == 1:
            return fixes[0]['strategy']

        # Thompson Sampling: draw from Beta(alpha, beta) for each arm
        best_score = -1.0
        best_strategy = fixes[0]['strategy']
        for arm in fixes:
            alpha = arm.get('alpha', BANDIT_ALPHA_PRIOR)
            beta = arm.get('beta', BANDIT_BETA_PRIOR)
            sample = random.betavariate(max(alpha, 0.1), max(beta, 0.1))
            if sample > best_score:
                best_score = sample
                best_strategy = arm['strategy']

        return best_strategy

    @staticmethod
    def rank_fixes(entry, max_fixes=2):
        """Rank fixes by expected reward (mean of Beta distribution).

        Returns list of fix strategy strings, best first.
        Uses the mean (not a sample) so results are stable for prompt display.
        """
        fixes = entry.get('fixes', [])
        if not fixes:
            fix_str = entry.get('fix', '')
            return [fix_str] if fix_str else []

        def expected_reward(arm):
            a = arm.get('alpha', BANDIT_ALPHA_PRIOR)
            b = arm.get('beta', BANDIT_BETA_PRIOR)
            return a / (a + b)

        ranked = sorted(fixes, key=expected_reward, reverse=True)
        return [arm['strategy'] for arm in ranked[:max_fixes]]

    # ── Signature ──────────────────────────────────────────────

    @staticmethod
    def compute_signature(error_class):
        """Compute a stable signature string from a classified error."""
        err_type = error_class.get('type', 'unknown')
        if err_type == 'module_not_found':
            mod = error_class.get('module', 'unknown')
            return f"module_not_found:{mod.split('.')[0]}"
        elif err_type == 'import':
            msg = (error_class.get('message', '') or '')[:40].strip()
            return f"import:{msg}"
        elif err_type == 'syntax':
            msg = (error_class.get('message', '') or '')[:40].strip()
            return f"syntax:{msg}"
        elif err_type == 'runtime':
            etype = error_class.get('errorType', 'Error')
            msg = (error_class.get('message', '') or '')[:40].strip()
            return f"runtime:{etype}:{msg}"
        else:
            msg = (error_class.get('message', '') or '')[:40].strip()
            return f"unknown:{msg}"

    # ── Recording ──────────────────────────────────────────────

    @staticmethod
    def record(error_class, fix_description, success, tags=None, context='',
               fingerprint=None):
        """Record an error-resolution outcome. Upserts by signature.

        Updates bandit arms and merges fingerprints for existing entries.
        """
        try:
            sig = ErrorMemory.compute_signature(error_class)
            db = ErrorMemory.load()
            now = datetime.utcnow().isoformat()

            # Find existing entry by signature
            existing = None
            for entry in db['entries']:
                if entry.get('sig') == sig:
                    existing = entry
                    break

            if existing:
                ErrorMemory.migrate_entry(existing)  # ensure v2 fields
                existing['hits'] = existing.get('hits', 0) + 1
                existing['last_seen'] = now

                # Update bandit arms
                if fix_description and fix_description != 'unresolved':
                    fix_str = fix_description[:200]
                    # Find or create the strategy arm
                    arm = None
                    for f in existing.get('fixes', []):
                        if f['strategy'] == fix_str:
                            arm = f
                            break

                    if arm is None:
                        # New strategy discovered
                        arm = {
                            'strategy': fix_str,
                            'alpha': BANDIT_ALPHA_PRIOR,
                            'beta': BANDIT_BETA_PRIOR,
                            'last_used': now,
                        }
                        existing['fixes'].append(arm)

                    arm['last_used'] = now
                    if success:
                        arm['alpha'] = arm.get('alpha', 1) + 1
                    else:
                        arm['beta'] = arm.get('beta', 1) + 1

                    # Sync legacy fix field to best performer
                    ranked = ErrorMemory.rank_fixes(existing, max_fixes=1)
                    if ranked:
                        existing['fix'] = ranked[0]

                if success:
                    existing['confirmed'] = existing.get('confirmed', 0) + 1
                    existing['last_confirmed'] = now
                else:
                    existing['failed'] = existing.get('failed', 0) + 1

                # Recompute confidence
                conf_total = existing.get('confirmed', 0) + existing.get('failed', 0)
                existing['confidence'] = existing.get('confirmed', 0) / conf_total if conf_total > 0 else 0.0

                # Merge fingerprint if provided
                if fingerprint:
                    ErrorMemory._merge_fingerprint(existing, fingerprint)
            else:
                # Create new entry
                entry_id = hashlib.sha256(sig.encode()).hexdigest()[:8]
                fix_str = (fix_description or '')[:200]
                new_entry = {
                    "id": entry_id,
                    "sig": sig,
                    "type": error_class.get('type', 'unknown'),
                    "tags": tags or ['execution'],
                    "pattern": error_class.get('module', '') or error_class.get('errorType', ''),
                    "context": context,
                    "mistake": (error_class.get('message', '') or '')[:150],
                    "fix": fix_str,
                    "fixes": [{
                        "strategy": fix_str,
                        "alpha": BANDIT_ALPHA_PRIOR + (1 if success else 0),
                        "beta": BANDIT_BETA_PRIOR + (0 if success else 1),
                        "last_used": now,
                    }] if fix_str else [],
                    "fingerprint": fingerprint or {
                        "tech_stack": [], "libraries": [], "file_exts": [],
                        "step_type": "", "complexity_bucket": "medium",
                    },
                    "hits": 1,
                    "confirmed": 1 if success else 0,
                    "failed": 0 if success else 1,
                    "confidence": 1.0 if success else 0.0,
                    "first_seen": now,
                    "last_seen": now,
                    "last_confirmed": now if success else "",
                    "source": "auto",
                }
                db['entries'].append(new_entry)

            # Prune if needed
            if len(db['entries']) > MAX_ENTRIES:
                ErrorMemory._prune(db)

            ErrorMemory.save(db)
        except Exception as e:
            _safe_log(f"[ErrorMemory] Record failed: {e}")

    @staticmethod
    def record_planning_mistake(keyword, mistake, fix, tags=None, fingerprint=None):
        """Record a planning-level mistake (not tied to a runtime error)."""
        try:
            sig = f"planning:{keyword}"
            db = ErrorMemory.load()
            now = datetime.utcnow().isoformat()

            existing = None
            for entry in db['entries']:
                if entry.get('sig') == sig:
                    existing = entry
                    break

            if existing:
                ErrorMemory.migrate_entry(existing)  # ensure v2 fields
                existing['hits'] = existing.get('hits', 0) + 1
                existing['confirmed'] = existing.get('confirmed', 0) + 1
                existing['last_seen'] = now
                existing['last_confirmed'] = now

                # Update bandit arm
                fix_str = fix[:200]
                arm = None
                for f in existing.get('fixes', []):
                    if f['strategy'] == fix_str:
                        arm = f
                        break
                if arm is None:
                    arm = {'strategy': fix_str, 'alpha': BANDIT_ALPHA_PRIOR, 'beta': BANDIT_BETA_PRIOR, 'last_used': now}
                    existing['fixes'].append(arm)
                arm['alpha'] = arm.get('alpha', 1) + 1
                arm['last_used'] = now

                # Sync legacy fix field
                ranked = ErrorMemory.rank_fixes(existing, max_fixes=1)
                if ranked:
                    existing['fix'] = ranked[0]

                conf_total = existing.get('confirmed', 0) + existing.get('failed', 0)
                existing['confidence'] = existing.get('confirmed', 0) / conf_total if conf_total > 0 else 0.0

                if fingerprint:
                    ErrorMemory._merge_fingerprint(existing, fingerprint)
            else:
                entry_id = hashlib.sha256(sig.encode()).hexdigest()[:8]
                fix_str = fix[:200]
                db['entries'].append({
                    "id": entry_id,
                    "sig": sig,
                    "type": "planning",
                    "tags": tags or ['planning', 'implementation'],
                    "pattern": keyword,
                    "context": "",
                    "mistake": mistake[:150],
                    "fix": fix_str,
                    "fixes": [{
                        "strategy": fix_str,
                        "alpha": BANDIT_ALPHA_PRIOR + 1,
                        "beta": BANDIT_BETA_PRIOR,
                        "last_used": now,
                    }],
                    "fingerprint": fingerprint or {
                        "tech_stack": [], "libraries": [], "file_exts": [],
                        "step_type": "planning", "complexity_bucket": "medium",
                    },
                    "hits": 1, "confirmed": 1, "failed": 0, "confidence": 1.0,
                    "first_seen": now, "last_seen": now, "last_confirmed": now,
                    "source": "auto",
                })

            if len(db['entries']) > MAX_ENTRIES:
                ErrorMemory._prune(db)

            ErrorMemory.save(db)
        except Exception as e:
            _safe_log(f"[ErrorMemory] Record planning mistake failed: {e}")

    # ── Lookup ─────────────────────────────────────────────────

    @staticmethod
    def lookup(*, step_type='', task_details='', error_class=None,
               max_entries=5, fingerprint=None):
        """Query for relevant entries with fingerprint + tier scoring.

        Returns list of matching entries sorted by relevance, with _tier attached.
        """
        try:
            db = ErrorMemory.load()
            entries = db.get('entries', [])
            if not entries:
                return []

            scored = []

            for entry in entries:
                # Skip low-confidence entries
                if entry.get('confidence', 0) < MIN_CONFIDENCE:
                    continue

                ErrorMemory.migrate_entry(entry)  # ensure v2 fields
                score = 0.0

                # Tier 1: Exact error match (highest relevance)
                if error_class:
                    query_sig = ErrorMemory.compute_signature(error_class)
                    if entry.get('sig') == query_sig:
                        score += 100.0

                # Tier 2: Tag match
                if step_type and step_type in entry.get('tags', []):
                    score += 10.0

                # Fingerprint similarity scoring (between tag and keyword)
                if fingerprint and entry.get('fingerprint'):
                    fp_sim = ErrorMemory.fingerprint_similarity(fingerprint, entry['fingerprint'])
                    score += fp_sim * FINGERPRINT_WEIGHT  # 0-15 points

                # Tier 3: Keyword match against task details
                if task_details and entry.get('pattern'):
                    try:
                        pattern_parts = entry['pattern'].split('|')
                        text_lower = task_details.lower()
                        for part in pattern_parts:
                            part = part.strip().lower()
                            if part and part in text_lower:
                                score += 5.0
                                break
                    except Exception:
                        pass

                # Boost by confidence and hits
                if score > 0:
                    score *= entry.get('confidence', 0.5)
                    score *= (1 + math.log(entry.get('hits', 1) + 1))
                    # Attach tier for downstream formatting (transient, not persisted)
                    entry['_tier'] = ErrorMemory.compute_tier(entry)
                    scored.append((score, entry))

            # Sort by score descending
            scored.sort(key=lambda x: x[0], reverse=True)
            return [entry for _, entry in scored[:max_entries]]

        except Exception as e:
            _safe_log(f"[ErrorMemory] Lookup failed: {e}")
            return []

    # ── Formatting ─────────────────────────────────────────────

    @staticmethod
    def format_for_prompt(entries, header='## Known Pitfalls', compact_mode=False):
        """Format matched entries into a tier-aware prompt block.

        Tier 1 (Note): soft suggestion
        Tier 2 (Warning): MUST-DO language
        Tier 3 (Critical): strongest framing, injected even in compact_mode

        Returns formatted markdown string.
        """
        if not entries:
            return ''

        # Separate Tier 3 entries (they get special treatment)
        tier3 = [e for e in entries if e.get('_tier', 1) >= 3][:2]  # cap at 2
        other = [e for e in entries if e.get('_tier', 1) < 3]

        lines = []
        char_count = 0

        # Tier 3 entries: always injected, even in compact_mode
        if tier3:
            t3_header = "## CRITICAL REQUIREMENTS (REPEATED FAILURES)\n"
            lines.append(t3_header)
            char_count += len(t3_header)

            for entry in tier3:
                fix = ErrorMemory.sample_best_fix(entry)
                failed = entry.get('failed', 0)
                # Allow longer for Tier 3
                if len(fix) > MAX_BULLET_CHARS + 40:
                    fix = fix[:MAX_BULLET_CHARS + 37] + '...'
                bullet = f"- **YOU MUST**: {fix} (Failed {failed} times — this is a known trap.)\n"
                if char_count + len(bullet) > MAX_TIER3_CHARS:
                    break
                lines.append(bullet)
                char_count += len(bullet)
            lines.append("\n")

        # Skip non-critical entries in compact mode
        if compact_mode:
            return ''.join(lines) if lines else ''

        # Non-Tier-3 entries
        if other:
            lines.append(f"{header}\n")
            char_count_other = len(header) + 1

            for entry in other:
                tier = entry.get('_tier', 1)
                fix = ErrorMemory.sample_best_fix(entry)

                # Truncate fix text
                if len(fix) > MAX_BULLET_CHARS:
                    m = re.search(r'\.(?:\s|$)', fix[15:])
                    if m and (15 + m.start() + 1) < MAX_BULLET_CHARS:
                        fix = fix[:15 + m.start() + 1]
                    else:
                        fix = fix[:MAX_BULLET_CHARS - 3] + '...'

                if tier == 1:
                    bullet = f"- Note: {fix}\n"
                else:  # tier == 2
                    bullet = f"- WARNING — MUST DO: {fix}\n"

                if char_count_other + len(bullet) > MAX_INJECTION_CHARS:
                    break
                lines.append(bullet)
                char_count_other += len(bullet)

        return ''.join(lines)

    # ── Corrective Fixes ────────────────────────────────────────

    @staticmethod
    def get_corrective_fixes(file_ext=None, filename=None, on_write=False):
        """Return auto_fix entries matching a file extension/name.

        Args:
            file_ext: e.g. '.py' -- matched against auto_fix.file_pattern
            filename: e.g. 'requirements.txt' -- matched against auto_fix.file_pattern
            on_write: if True, only return entries with on_write=True

        Returns: list of (entry, auto_fix_config) tuples
        """
        try:
            db = ErrorMemory.load()
            results = []

            for entry in db.get('entries', []):
                af = entry.get('auto_fix')
                if not af:
                    continue

                # Filter by on_write flag
                if on_write and not af.get('on_write', False):
                    continue

                pattern = af.get('file_pattern', '')
                if not pattern:
                    continue

                # Check if the file matches the pattern
                matched = False
                if filename and fnmatch.fnmatch(filename, pattern):
                    matched = True
                elif file_ext and fnmatch.fnmatch('*' + file_ext, pattern):
                    matched = True
                elif not filename and not file_ext:
                    # No filter specified -- return all
                    matched = True

                if matched:
                    results.append((entry, af))

            return results
        except Exception as e:
            _safe_log(f"[ErrorMemory] get_corrective_fixes failed: {e}")
            return []

    @staticmethod
    def record_auto_fix(entry_id, success=True):
        """Record an auto-fix application result back to bandit arms.

        Increments hits/confirmed (or failed) and updates the top bandit arm.
        """
        try:
            db = ErrorMemory.load()
            entry = None
            for e in db.get('entries', []):
                if e.get('id') == entry_id:
                    entry = e
                    break

            if not entry:
                return

            now = datetime.utcnow().isoformat()
            entry['hits'] = entry.get('hits', 0) + 1
            entry['last_seen'] = now

            if success:
                entry['confirmed'] = entry.get('confirmed', 0) + 1
                entry['last_confirmed'] = now
                # Boost the top bandit arm
                fixes = entry.get('fixes', [])
                if fixes:
                    ranked = sorted(fixes, key=lambda a: a.get('alpha', 1) / (a.get('alpha', 1) + a.get('beta', 1)), reverse=True)
                    ranked[0]['alpha'] = ranked[0].get('alpha', 1) + 1
                    ranked[0]['last_used'] = now
            else:
                entry['failed'] = entry.get('failed', 0) + 1

            # Recompute confidence
            conf_total = entry.get('confirmed', 0) + entry.get('failed', 0)
            entry['confidence'] = entry.get('confirmed', 0) / conf_total if conf_total > 0 else 0.0

            # Sync legacy fix field
            ranked = ErrorMemory.rank_fixes(entry, max_fixes=1)
            if ranked:
                entry['fix'] = ranked[0]

            ErrorMemory.save(db)
        except Exception as e:
            _safe_log(f"[ErrorMemory] record_auto_fix failed: {e}")

    # ── Pruning ────────────────────────────────────────────────

    @staticmethod
    def _prune(db):
        """Remove low-value entries when DB exceeds MAX_ENTRIES.

        High-tier entries get survival bonus to resist pruning.
        """
        entries = db.get('entries', [])
        if len(entries) <= MAX_ENTRIES:
            return

        now = datetime.utcnow()
        tier_bonus_map = {1: 1.0, 2: 1.5, 3: 3.0}

        def value(entry):
            # Seed entries get infinite value (never pruned)
            if entry.get('source') == 'seed':
                return float('inf')

            confidence = entry.get('confidence', 0)
            hits = entry.get('hits', 1)

            # Recency factor: 1.0 for today, 0.0 at DECAY_DAYS
            last_confirmed = entry.get('last_confirmed', '')
            if last_confirmed:
                try:
                    last_dt = datetime.fromisoformat(last_confirmed)
                    days_ago = (now - last_dt).days
                    recency = max(0.0, 1.0 - days_ago / DECAY_DAYS)
                except Exception:
                    recency = 0.3
            else:
                recency = 0.1

            # Tier bonus: Tier 3 entries get 3x survival bonus
            tier = ErrorMemory.compute_tier(entry)
            bonus = tier_bonus_map.get(tier, 1.0)

            return confidence * math.log(hits + 1) * (recency + 0.1) * bonus

        # Sort by value ascending (lowest value first for removal)
        entries.sort(key=value)

        # Remove until we're at PRUNE_TARGET
        while len(entries) > PRUNE_TARGET:
            entry = entries[0]
            if entry.get('source') == 'seed':
                break  # Don't prune seed entries
            entries.pop(0)

        db['entries'] = entries


# ── Auto-seed on import ───────────────────────────────────────
ErrorMemory.ensure_seeded()
