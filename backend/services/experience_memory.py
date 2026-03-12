"""Experience Memory -- behavioral RL knowledge base.

Stores lessons learned from every task: positive patterns ("ALWAYS do X"),
anti-patterns ("NEVER do Y"), and behavioral rules. Uses the same RL
primitives as ErrorMemory:

  - Thompson Sampling: alpha/beta counts per lesson for confidence ranking
  - Context Fingerprinting: match lessons to relevant tech stacks
  - Escalation Tiers: high-confidence lessons injected more aggressively
  - Pruning: low-value lessons removed when cap is reached

Unlike ErrorMemory (which only learns from errors), ExperienceMemory
learns from EVERYTHING -- good outcomes reinforce patterns, bad outcomes
create anti-patterns.

Storage: storage/experience_memory.json (global, persists across all tasks)
"""

import os
import re
import json
import math
import hashlib
import threading
from datetime import datetime

from config import Config
from utils.logging import _safe_log


# ── Constants ──────────────────────────────────────────────────────
MAX_ENTRIES = 120
PRUNE_TARGET = 100
MAX_INJECTION_CHARS = 800
DB_PATH = os.path.join(Config.STORAGE_DIR, 'experience_memory.json')

# Thompson Sampling priors
ALPHA_PRIOR = 1
BETA_PRIOR = 1

# File-level lock for concurrent access
_db_lock = threading.Lock()

# ── Seed Lessons ───────────────────────────────────────────────────
_now_iso = datetime.utcnow().isoformat()

SEED_LESSONS = [
    {
        "id": "seed_exp_001",
        "sig": "always_use_writefile",
        "type": "positive",
        "tags": ["implementation", "tool_usage"],
        "lesson": "ALWAYS use WriteFile to save code -- never write code blocks in your response.",
        "context": "Code in responses does NOT save to disk.",
        "alpha": 5, "beta": 1, "confidence": 0.83,
        "fingerprint": {"tech_stack": [], "libraries": [], "file_exts": [".py"], "step_type": "implementation", "complexity_bucket": "medium"},
        "hits": 5, "confirmed": 5, "failed": 0,
        "first_seen": _now_iso, "last_seen": _now_iso, "last_confirmed": _now_iso,
        "source": "seed",
    },
    {
        "id": "seed_exp_002",
        "sig": "read_before_write",
        "type": "positive",
        "tags": ["implementation", "planning"],
        "lesson": "Read existing files with ReadFile BEFORE writing new files that import from them.",
        "context": "Prevents import mismatches and API incompatibilities.",
        "alpha": 4, "beta": 1, "confidence": 0.80,
        "fingerprint": {"tech_stack": [], "libraries": [], "file_exts": [".py"], "step_type": "implementation", "complexity_bucket": "medium"},
        "hits": 4, "confirmed": 4, "failed": 0,
        "first_seen": _now_iso, "last_seen": _now_iso, "last_confirmed": _now_iso,
        "source": "seed",
    },
    {
        "id": "seed_exp_003",
        "sig": "create_all_files",
        "type": "positive",
        "tags": ["implementation", "completion"],
        "lesson": "Create ALL files listed in your step description before saying STEP_COMPLETE.",
        "context": "Missing files cause downstream failures.",
        "alpha": 5, "beta": 1, "confidence": 0.83,
        "fingerprint": {"tech_stack": [], "libraries": [], "file_exts": [], "step_type": "implementation", "complexity_bucket": "medium"},
        "hits": 5, "confirmed": 5, "failed": 0,
        "first_seen": _now_iso, "last_seen": _now_iso, "last_confirmed": _now_iso,
        "source": "seed",
    },
    {
        "id": "seed_exp_004",
        "sig": "config_with_code",
        "type": "positive",
        "tags": ["implementation"],
        "lesson": "Create config/data files in the SAME step as code that reads them.",
        "context": "Missing config files cause runtime FileNotFoundError.",
        "alpha": 4, "beta": 1, "confidence": 0.80,
        "fingerprint": {"tech_stack": [], "libraries": [], "file_exts": [], "step_type": "implementation", "complexity_bucket": "medium"},
        "hits": 4, "confirmed": 4, "failed": 0,
        "first_seen": _now_iso, "last_seen": _now_iso, "last_confirmed": _now_iso,
        "source": "seed",
    },
    {
        "id": "seed_exp_005",
        "sig": "register_blueprints",
        "type": "positive",
        "tags": ["implementation", "flask"],
        "lesson": "Register all Flask blueprints/routers in the entry point file.",
        "context": "Unregistered blueprints cause 404 errors.",
        "alpha": 4, "beta": 1, "confidence": 0.80,
        "fingerprint": {"tech_stack": ["python"], "libraries": ["flask"], "file_exts": [".py"], "step_type": "implementation", "complexity_bucket": "medium"},
        "hits": 4, "confirmed": 4, "failed": 0,
        "first_seen": _now_iso, "last_seen": _now_iso, "last_confirmed": _now_iso,
        "source": "seed",
    },
    {
        "id": "seed_exp_006",
        "sig": "flat_layout",
        "type": "positive",
        "tags": ["planning", "implementation", "python"],
        "lesson": "Keep Python files at project root (flat layout) unless packages are explicitly required.",
        "context": "Nested packages cause import resolution failures.",
        "alpha": 4, "beta": 1, "confidence": 0.80,
        "fingerprint": {"tech_stack": ["python"], "libraries": [], "file_exts": [".py"], "step_type": "planning", "complexity_bucket": "medium"},
        "hits": 4, "confirmed": 4, "failed": 0,
        "first_seen": _now_iso, "last_seen": _now_iso, "last_confirmed": _now_iso,
        "source": "seed",
    },
    {
        "id": "seed_exp_007",
        "sig": "no_placeholders",
        "type": "negative",
        "tags": ["implementation", "code_quality"],
        "lesson": "Do NOT use placeholder code like 'pass' or '...' in function bodies.",
        "context": "Placeholder functions cause runtime errors when called.",
        "alpha": 5, "beta": 1, "confidence": 0.83,
        "fingerprint": {"tech_stack": [], "libraries": [], "file_exts": [".py"], "step_type": "implementation", "complexity_bucket": "medium"},
        "hits": 5, "confirmed": 5, "failed": 0,
        "first_seen": _now_iso, "last_seen": _now_iso, "last_confirmed": _now_iso,
        "source": "seed",
    },
    {
        "id": "seed_exp_008",
        "sig": "different_approach_on_failure",
        "type": "positive",
        "tags": ["implementation", "tool_usage"],
        "lesson": "When a tool fails, try a DIFFERENT approach -- do not retry the same call.",
        "context": "Repeating failed tool calls wastes turns.",
        "alpha": 4, "beta": 1, "confidence": 0.80,
        "fingerprint": {"tech_stack": [], "libraries": [], "file_exts": [], "step_type": "implementation", "complexity_bucket": "medium"},
        "hits": 4, "confirmed": 4, "failed": 0,
        "first_seen": _now_iso, "last_seen": _now_iso, "last_confirmed": _now_iso,
        "source": "seed",
    },
    {
        "id": "seed_exp_009",
        "sig": "match_conventions",
        "type": "positive",
        "tags": ["implementation", "code_quality"],
        "lesson": "Match the codebase conventions -- if existing files use type hints, use type hints.",
        "context": "Inconsistent style creates maintenance burden.",
        "alpha": 3, "beta": 1, "confidence": 0.75,
        "fingerprint": {"tech_stack": [], "libraries": [], "file_exts": [".py"], "step_type": "implementation", "complexity_bucket": "medium"},
        "hits": 3, "confirmed": 3, "failed": 0,
        "first_seen": _now_iso, "last_seen": _now_iso, "last_confirmed": _now_iso,
        "source": "seed",
    },
    {
        "id": "seed_exp_010",
        "sig": "verify_imports",
        "type": "positive",
        "tags": ["implementation", "python"],
        "lesson": "Check that every 'from X import Y' references a name that actually exists in X.",
        "context": "Wrong imports cause ImportError at runtime.",
        "alpha": 4, "beta": 1, "confidence": 0.80,
        "fingerprint": {"tech_stack": ["python"], "libraries": [], "file_exts": [".py"], "step_type": "implementation", "complexity_bucket": "medium"},
        "hits": 4, "confirmed": 4, "failed": 0,
        "first_seen": _now_iso, "last_seen": _now_iso, "last_confirmed": _now_iso,
        "source": "seed",
    },
]


class ExperienceMemory:
    """Cross-task behavioral knowledge base with reinforcement learning.

    All methods are static -- no instance state. Storage is a single
    JSON file at storage/experience_memory.json.
    """

    # ── I/O ────────────────────────────────────────────────────────

    @staticmethod
    def load():
        """Load the experience memory DB. Thread-safe."""
        with _db_lock:
            try:
                if os.path.isfile(DB_PATH):
                    with open(DB_PATH, 'r', encoding='utf-8') as f:
                        raw = f.read()
                    if not raw.strip():
                        return {"version": 1, "entries": [], "stats": {}}
                    db = json.loads(raw)
                    if isinstance(db, dict):
                        return db
                    return {"version": 1, "entries": [], "stats": {}}
                return {"version": 1, "entries": [], "stats": {}}
            except json.JSONDecodeError as e:
                _safe_log(f"[Experience] Corrupted JSON: {e}")
                try:
                    backup = DB_PATH + '.corrupt'
                    if not os.path.isfile(backup):
                        os.rename(DB_PATH, backup)
                except Exception:
                    pass
                return {"version": 1, "entries": [], "stats": {}}
            except Exception as e:
                _safe_log(f"[Experience] Failed to load: {e}")
                return {"version": 1, "entries": [], "stats": {}}

    @staticmethod
    def save(db):
        """Save experience memory to disk. Thread-safe, atomic write."""
        with _db_lock:
            try:
                os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
                tmp_path = DB_PATH + '.tmp'
                with open(tmp_path, 'w', encoding='utf-8') as f:
                    json.dump(db, f, indent=2)
                try:
                    os.replace(tmp_path, DB_PATH)
                except OSError:
                    if os.path.isfile(DB_PATH):
                        os.remove(DB_PATH)
                    os.rename(tmp_path, DB_PATH)
            except Exception as e:
                _safe_log(f"[Experience] Failed to save: {e}")

    @staticmethod
    def ensure_seeded():
        """Populate with seed lessons if DB doesn't exist, or add missing seeds."""
        if not os.path.isfile(DB_PATH):
            now = datetime.utcnow().isoformat()
            entries = []
            for seed in SEED_LESSONS:
                entry = dict(seed)
                entry["first_seen"] = now
                entry["last_seen"] = now
                entry["last_confirmed"] = now
                entries.append(entry)
            db = {
                "version": 1,
                "entries": entries,
                "stats": {
                    "tasks_scored": 0,
                    "avg_composite": 0.0,
                    "grade_distribution": {},
                    "total_lessons_generated": 0,
                    "total_lessons_confirmed": 0,
                },
            }
            ExperienceMemory.save(db)
            _safe_log(f"[Experience] Seeded {len(entries)} foundational lessons")
            return

        # DB exists -- add missing seed entries
        try:
            db = ExperienceMemory.load()
            existing_ids = {e.get('id') for e in db.get('entries', [])}
            now = datetime.utcnow().isoformat()
            added = 0
            for seed in SEED_LESSONS:
                if seed['id'] not in existing_ids:
                    entry = dict(seed)
                    entry["first_seen"] = now
                    entry["last_seen"] = now
                    entry["last_confirmed"] = now
                    db.setdefault('entries', []).append(entry)
                    added += 1
            if added > 0:
                ExperienceMemory.save(db)
                _safe_log(f"[Experience] Added {added} missing seed lessons")
        except Exception as e:
            _safe_log(f"[Experience] ensure_seeded failed: {e}")

    # ── Signature / Dedup ──────────────────────────────────────────

    @staticmethod
    def _compute_sig(lesson_text):
        """Compute a dedup signature from normalized lesson text."""
        # Normalize: lowercase, strip punctuation, collapse whitespace
        normalized = re.sub(r'[^a-z0-9\s]', '', lesson_text.lower())
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        return hashlib.md5(normalized.encode()).hexdigest()[:12]

    # ── Record / Update ────────────────────────────────────────────

    @staticmethod
    def record(lesson, lesson_type, tags, context='', fingerprint=None,
               source_task='', source_grade='', reward_score=0.5):
        """Record a new lesson or update an existing one.

        Args:
            lesson: The behavioral rule text
            lesson_type: "positive" or "negative"
            tags: List of tag strings
            context: When this lesson applies
            fingerprint: Context fingerprint dict
            source_task: Task ID that generated this
            source_grade: Grade of the source task
            reward_score: Composite reward score (0.0-1.0)
        """
        # Validate lesson text
        if not lesson or len(lesson.strip()) <= 10:
            return  # Skip empty or trivially short lessons

        sig = ExperienceMemory._compute_sig(lesson)
        db = ExperienceMemory.load()
        entries = db.setdefault('entries', [])
        now = datetime.utcnow().isoformat()

        # Check for existing entry with same signature
        existing = None
        for entry in entries:
            if entry.get('sig') == sig:
                existing = entry
                break

        if existing:
            # Update existing entry
            existing['hits'] = existing.get('hits', 0) + 1
            existing['last_seen'] = now
            if reward_score >= 0.6:
                existing['alpha'] = existing.get('alpha', ALPHA_PRIOR) + 1
                existing['confirmed'] = existing.get('confirmed', 0) + 1
                existing['last_confirmed'] = now
            elif reward_score < 0.4:
                existing['beta'] = existing.get('beta', BETA_PRIOR) + 1
                existing['failed'] = existing.get('failed', 0) + 1
            # Update confidence
            alpha = existing.get('alpha', ALPHA_PRIOR)
            beta = existing.get('beta', BETA_PRIOR)
            existing['confidence'] = round(alpha / (alpha + beta), 3)
            # Merge fingerprint
            if fingerprint:
                ExperienceMemory._merge_fingerprint(existing, fingerprint)
            # Merge tags
            existing_tags = set(existing.get('tags', []))
            existing_tags.update(tags)
            existing['tags'] = sorted(existing_tags)
        else:
            # Create new entry
            entry_id = f"exp_{sig}"
            alpha = max(int(reward_score * 3), ALPHA_PRIOR)
            beta = max(int((1 - reward_score) * 3), BETA_PRIOR)
            new_entry = {
                "id": entry_id,
                "sig": sig,
                "type": lesson_type,
                "tags": sorted(set(tags)),
                "lesson": lesson[:200],  # Cap lesson length
                "context": context[:200],
                "source_task": source_task,
                "source_grade": source_grade,
                "alpha": alpha,
                "beta": beta,
                "confidence": round(alpha / (alpha + beta), 3),
                "fingerprint": fingerprint or {},
                "hits": 1,
                "confirmed": 1 if reward_score >= 0.6 else 0,
                "failed": 1 if reward_score < 0.4 else 0,
                "first_seen": now,
                "last_seen": now,
                "last_confirmed": now if reward_score >= 0.6 else '',
                "source": "learned",
            }
            entries.append(new_entry)
            # Track lesson generation count
            stats = db.setdefault('stats', {})
            stats['total_lessons_generated'] = stats.get('total_lessons_generated', 0) + 1

        # Prune if over cap
        if len(entries) > MAX_ENTRIES:
            ExperienceMemory._prune(db)

        ExperienceMemory.save(db)

    @staticmethod
    def confirm(lesson_id):
        """Positive reinforcement: lesson was injected and step scored well."""
        db = ExperienceMemory.load()
        now = datetime.utcnow().isoformat()
        for entry in db.get('entries', []):
            if entry.get('id') == lesson_id:
                entry['alpha'] = entry.get('alpha', ALPHA_PRIOR) + 1
                entry['confirmed'] = entry.get('confirmed', 0) + 1
                entry['last_confirmed'] = now
                entry['last_seen'] = now  # Keep recency up to date for pruning
                entry['hits'] = entry.get('hits', 0) + 1
                alpha = entry.get('alpha', ALPHA_PRIOR)
                beta = entry.get('beta', BETA_PRIOR)
                entry['confidence'] = round(alpha / (alpha + beta), 3)
                ExperienceMemory.save(db)
                return
        # Lesson not found -- ignore silently

    @staticmethod
    def penalize(lesson_id):
        """Negative reinforcement: lesson was injected but step scored poorly."""
        db = ExperienceMemory.load()
        now = datetime.utcnow().isoformat()
        for entry in db.get('entries', []):
            if entry.get('id') == lesson_id:
                entry['beta'] = entry.get('beta', BETA_PRIOR) + 1
                entry['failed'] = entry.get('failed', 0) + 1
                entry['last_seen'] = now
                alpha = entry.get('alpha', ALPHA_PRIOR)
                beta = entry.get('beta', BETA_PRIOR)
                entry['confidence'] = round(alpha / (alpha + beta), 3)
                ExperienceMemory.save(db)
                return

    # ── Lookup ─────────────────────────────────────────────────────

    @staticmethod
    def lookup(tags, fingerprint=None, max_results=8):
        """Find lessons relevant to the current context.

        Scoring:
          - Tag match: 10 points per matching tag
          - Fingerprint similarity: 0-15 points (reuses ErrorMemory approach)
          - Boosted by: confidence * log(hits + 1)

        Returns list of entry dicts, sorted by score descending.
        """
        db = ExperienceMemory.load()
        entries = db.get('entries', [])
        if not entries:
            return []

        tag_set = set(tags) if tags else set()
        scored = []

        for entry in entries:
            score = 0.0

            # Tag matching (10 pts each)
            entry_tags = set(entry.get('tags', []))
            tag_overlap = len(tag_set & entry_tags)
            score += tag_overlap * 10.0

            # Fingerprint similarity (0-15 pts)
            if fingerprint and entry.get('fingerprint'):
                fp_sim = ExperienceMemory._fingerprint_similarity(
                    fingerprint, entry['fingerprint']
                )
                score += fp_sim * 15.0

            # Confidence + hits boost
            confidence = entry.get('confidence', 0.5)
            hits = entry.get('hits', 1)
            score *= confidence * math.log(hits + 1, 2)

            # Skip very low-confidence lessons
            if confidence < 0.3:
                continue

            if score > 0:
                scored.append((score, entry))

        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in scored[:max_results]]

    # ── Injection Formatting ───────────────────────────────────────

    @staticmethod
    def format_for_injection(entries, budget=None):
        """Format lessons as terse rules for injection into the system prompt.

        Returns a string like:
            === LEARNED RULES (from past tasks) ===
            DO: Use WriteFile for every code block.
            DO: Create config files in the same step as code that reads them.
            DONT: Use placeholder code like 'pass' in function bodies.
            === END RULES ===
        """
        if budget is None:
            budget = MAX_INJECTION_CHARS
        if not entries:
            return ''

        # Sort by confidence * hits (most proven first)
        sorted_entries = sorted(
            entries,
            key=lambda e: e.get('confidence', 0) * math.log(e.get('hits', 1) + 1, 2),
            reverse=True,
        )

        lines = ['=== LEARNED RULES (from past tasks) ===']
        chars_used = len(lines[0])

        for entry in sorted_entries:
            lesson = entry.get('lesson', '')
            if not lesson:
                continue
            prefix = 'DO' if entry.get('type') == 'positive' else 'DONT'
            line = f"{prefix}: {lesson}"
            if chars_used + len(line) + 2 > budget:
                break
            lines.append(line)
            chars_used += len(line) + 1  # +1 for newline

        lines.append('=== END RULES ===')
        return '\n'.join(lines)

    # ── Statistics ─────────────────────────────────────────────────

    @staticmethod
    def update_stats(task_score):
        """Update aggregate statistics after a task is scored."""
        db = ExperienceMemory.load()
        stats = db.setdefault('stats', {})

        tasks_scored = stats.get('tasks_scored', 0) + 1
        stats['tasks_scored'] = tasks_scored

        # Running average of composite score
        old_avg = stats.get('avg_composite', 0.0)
        new_composite = task_score.get('composite', 0.0)
        stats['avg_composite'] = round(
            old_avg + (new_composite - old_avg) / tasks_scored, 3
        )

        # Grade distribution
        grade_dist = stats.setdefault('grade_distribution', {})
        grade = task_score.get('grade', 'F')
        grade_dist[grade] = grade_dist.get(grade, 0) + 1

        # Lesson counts
        stats['total_lessons_confirmed'] = sum(
            e.get('confirmed', 0) for e in db.get('entries', [])
        )

        ExperienceMemory.save(db)

    @staticmethod
    def get_stats():
        """Return aggregate statistics."""
        db = ExperienceMemory.load()
        stats = db.get('stats', {})
        entries = db.get('entries', [])

        return {
            'total_lessons': len(entries),
            'positive': sum(1 for e in entries if e.get('type') == 'positive'),
            'negative': sum(1 for e in entries if e.get('type') == 'negative'),
            'avg_confidence': round(
                sum(e.get('confidence', 0) for e in entries) / max(len(entries), 1), 3
            ),
            'tasks_scored': stats.get('tasks_scored', 0),
            'avg_composite': stats.get('avg_composite', 0.0),
            'grade_distribution': stats.get('grade_distribution', {}),
            'top_lessons': [
                {
                    'lesson': e.get('lesson', ''),
                    'confidence': e.get('confidence', 0),
                    'hits': e.get('hits', 0),
                    'type': e.get('type', ''),
                }
                for e in sorted(
                    entries,
                    key=lambda x: x.get('confidence', 0) * x.get('hits', 1),
                    reverse=True,
                )[:5]
            ],
        }

    # ── Internal Helpers ───────────────────────────────────────────

    @staticmethod
    def _merge_fingerprint(entry, new_fp):
        """Merge a new fingerprint into an existing entry (union of sets)."""
        existing_fp = entry.get('fingerprint', {})
        for key in ('tech_stack', 'libraries', 'file_exts'):
            merged = set(existing_fp.get(key, []))
            merged.update(new_fp.get(key, []))
            existing_fp[key] = sorted(merged)[:20]
        if new_fp.get('step_type'):
            existing_fp['step_type'] = new_fp['step_type']
        if new_fp.get('complexity_bucket'):
            existing_fp['complexity_bucket'] = new_fp['complexity_bucket']
        entry['fingerprint'] = existing_fp

    @staticmethod
    def _fingerprint_similarity(fp1, fp2):
        """Weighted Jaccard similarity between fingerprints. Returns 0.0-1.0."""
        if not fp1 or not fp2:
            return 0.0

        score = 0.0
        weights = 0.0

        # Tech stack (weight 2)
        s1 = set(fp1.get('tech_stack', []))
        s2 = set(fp2.get('tech_stack', []))
        if s1 or s2:
            jaccard = len(s1 & s2) / len(s1 | s2) if (s1 | s2) else 0.0
            score += jaccard * 2.0
            weights += 2.0

        # Libraries (weight 3)
        l1 = set(fp1.get('libraries', []))
        l2 = set(fp2.get('libraries', []))
        if l1 or l2:
            jaccard = len(l1 & l2) / len(l1 | l2) if (l1 | l2) else 0.0
            score += jaccard * 3.0
            weights += 3.0

        # File extensions (weight 1)
        e1 = set(fp1.get('file_exts', []))
        e2 = set(fp2.get('file_exts', []))
        if e1 or e2:
            jaccard = len(e1 & e2) / len(e1 | e2) if (e1 | e2) else 0.0
            score += jaccard * 1.0
            weights += 1.0

        # Step type (weight 1, binary)
        if fp1.get('step_type') and fp2.get('step_type'):
            score += (1.0 if fp1['step_type'] == fp2['step_type'] else 0.0)
            weights += 1.0

        # Complexity bucket (weight 0.5, binary)
        if fp1.get('complexity_bucket') and fp2.get('complexity_bucket'):
            score += (0.5 if fp1['complexity_bucket'] == fp2['complexity_bucket'] else 0.0)
            weights += 0.5

        return score / weights if weights > 0 else 0.0

    @staticmethod
    def _prune(db):
        """Remove lowest-value entries to stay under MAX_ENTRIES."""
        entries = db.get('entries', [])
        if len(entries) <= MAX_ENTRIES:
            return

        now = datetime.utcnow()

        def survival_score(entry):
            # Seeds get a large survival bonus
            is_seed = entry.get('source') == 'seed'
            seed_bonus = 100.0 if is_seed else 0.0

            confidence = entry.get('confidence', 0.5)
            hits = entry.get('hits', 1)

            # Recency factor (decays over 90 days)
            last_seen = entry.get('last_seen', '')
            try:
                last_dt = datetime.fromisoformat(last_seen)
                days_ago = (now - last_dt).days
                recency = max(0.1, 1.0 - (days_ago / 90.0))
            except (ValueError, TypeError):
                recency = 0.5

            return seed_bonus + (confidence * math.log(hits + 1, 2) * recency)

        entries.sort(key=survival_score, reverse=True)
        db['entries'] = entries[:PRUNE_TARGET]
        _safe_log(f"[Experience] Pruned from {len(entries)} to {PRUNE_TARGET} entries")
