"""Unit tests for backend/services/experience_memory.py"""

import os
import json
import pytest


class TestExperienceMemory:
    @pytest.fixture(autouse=True)
    def setup_db(self, mock_config, monkeypatch):
        """Point ExperienceMemory.DB_PATH to temp storage."""
        import services.experience_memory as em_module
        self.db_path = os.path.join(mock_config, 'experience_memory.json')
        monkeypatch.setattr(em_module, 'DB_PATH', self.db_path)
        # Start with no DB file
        if os.path.isfile(self.db_path):
            os.remove(self.db_path)

    def test_load_empty(self):
        from services.experience_memory import ExperienceMemory
        db = ExperienceMemory.load()
        assert isinstance(db, dict)
        assert 'entries' in db or db == {"version": 1, "entries": [], "stats": {}}

    def test_save_and_load(self):
        from services.experience_memory import ExperienceMemory
        db = {"version": 1, "entries": [{"id": "test1", "sig": "test_sig", "lesson": "Test lesson"}], "stats": {}}
        ExperienceMemory.save(db)
        loaded = ExperienceMemory.load()
        assert len(loaded['entries']) == 1
        assert loaded['entries'][0]['id'] == 'test1'

    def test_ensure_seeded_creates_db(self):
        from services.experience_memory import ExperienceMemory, SEED_LESSONS
        assert not os.path.isfile(self.db_path)
        ExperienceMemory.ensure_seeded()
        assert os.path.isfile(self.db_path)
        db = ExperienceMemory.load()
        assert len(db['entries']) == len(SEED_LESSONS)

    def test_ensure_seeded_idempotent(self):
        from services.experience_memory import ExperienceMemory, SEED_LESSONS
        ExperienceMemory.ensure_seeded()
        count1 = len(ExperienceMemory.load()['entries'])
        ExperienceMemory.ensure_seeded()
        count2 = len(ExperienceMemory.load()['entries'])
        assert count1 == count2

    def test_compute_sig(self):
        from services.experience_memory import ExperienceMemory
        sig1 = ExperienceMemory._compute_sig("ALWAYS use WriteFile to save code")
        sig2 = ExperienceMemory._compute_sig("always use writefile to save code")
        # Both should produce the same signature (normalized)
        assert sig1 == sig2
        # Different text should produce different sigs
        sig3 = ExperienceMemory._compute_sig("Something completely different")
        assert sig1 != sig3

    def test_record_new_lesson(self):
        from services.experience_memory import ExperienceMemory
        # Start with empty DB
        ExperienceMemory.save({"version": 1, "entries": [], "stats": {}})
        ExperienceMemory.record(
            lesson="Always test before deploying",
            lesson_type="positive",
            tags=["implementation", "testing"],
            reward_score=0.8,
        )
        db = ExperienceMemory.load()
        assert len(db['entries']) == 1
        entry = db['entries'][0]
        assert entry['lesson'] == "Always test before deploying"
        assert entry['type'] == 'positive'
        assert entry['confirmed'] == 1  # reward_score >= 0.6

    def test_record_skips_short_lesson(self):
        from services.experience_memory import ExperienceMemory
        ExperienceMemory.save({"version": 1, "entries": [], "stats": {}})
        ExperienceMemory.record(
            lesson="short",
            lesson_type="positive",
            tags=["test"],
        )
        db = ExperienceMemory.load()
        assert len(db['entries']) == 0

    def test_record_updates_existing(self):
        from services.experience_memory import ExperienceMemory
        ExperienceMemory.save({"version": 1, "entries": [], "stats": {}})
        lesson = "Always verify imports before completing a step"
        ExperienceMemory.record(lesson=lesson, lesson_type="positive", tags=["imports"], reward_score=0.8)
        ExperienceMemory.record(lesson=lesson, lesson_type="positive", tags=["imports", "code_quality"], reward_score=0.9)
        db = ExperienceMemory.load()
        assert len(db['entries']) == 1
        entry = db['entries'][0]
        assert entry['hits'] == 2
        assert entry['confirmed'] == 2

    def test_record_low_reward_increments_failed(self):
        from services.experience_memory import ExperienceMemory
        ExperienceMemory.save({"version": 1, "entries": [], "stats": {}})
        lesson = "Some lesson that should be tested properly"
        ExperienceMemory.record(lesson=lesson, lesson_type="negative", tags=["test"], reward_score=0.2)
        db = ExperienceMemory.load()
        entry = db['entries'][0]
        assert entry['failed'] == 1

    def test_confirm(self):
        from services.experience_memory import ExperienceMemory
        ExperienceMemory.save({"version": 1, "entries": [
            {"id": "test_id", "sig": "s", "alpha": 2, "beta": 1, "confirmed": 1, "hits": 1,
             "last_confirmed": "", "last_seen": "", "confidence": 0.667}
        ], "stats": {}})
        ExperienceMemory.confirm("test_id")
        db = ExperienceMemory.load()
        entry = db['entries'][0]
        assert entry['alpha'] == 3
        assert entry['confirmed'] == 2
        assert entry['hits'] == 2
        assert entry['last_confirmed'] != ''

    def test_confirm_nonexistent_id(self):
        from services.experience_memory import ExperienceMemory
        ExperienceMemory.save({"version": 1, "entries": [], "stats": {}})
        # Should not raise
        ExperienceMemory.confirm("nonexistent_id")

    def test_penalize(self):
        from services.experience_memory import ExperienceMemory
        ExperienceMemory.save({"version": 1, "entries": [
            {"id": "test_id", "sig": "s", "alpha": 2, "beta": 1, "failed": 0, "hits": 1,
             "last_seen": "", "confidence": 0.667}
        ], "stats": {}})
        ExperienceMemory.penalize("test_id")
        db = ExperienceMemory.load()
        entry = db['entries'][0]
        assert entry['beta'] == 2
        assert entry['failed'] == 1

    def test_lookup_returns_list(self):
        from services.experience_memory import ExperienceMemory
        ExperienceMemory.ensure_seeded()
        results = ExperienceMemory.lookup(tags=['implementation'])
        assert isinstance(results, list)

    def test_lookup_empty_db(self):
        from services.experience_memory import ExperienceMemory
        ExperienceMemory.save({"version": 1, "entries": [], "stats": {}})
        results = ExperienceMemory.lookup(tags=['implementation'])
        assert results == []

    def test_lookup_with_tags(self):
        from services.experience_memory import ExperienceMemory
        ExperienceMemory.ensure_seeded()
        results = ExperienceMemory.lookup(tags=['implementation', 'tool_usage'])
        # Should find seed lessons with these tags
        assert len(results) > 0

    def test_format_for_injection_empty(self):
        from services.experience_memory import ExperienceMemory
        result = ExperienceMemory.format_for_injection([])
        assert result == ''

    def test_format_for_injection_with_entries(self):
        from services.experience_memory import ExperienceMemory
        entries = [
            {'lesson': 'Always use WriteFile', 'type': 'positive', 'confidence': 0.9, 'hits': 5},
            {'lesson': 'Never use placeholders', 'type': 'negative', 'confidence': 0.8, 'hits': 3},
        ]
        result = ExperienceMemory.format_for_injection(entries)
        assert 'LEARNED RULES' in result
        assert 'DO:' in result
        assert 'DONT:' in result

    def test_format_for_injection_respects_budget(self):
        from services.experience_memory import ExperienceMemory
        entries = [
            {'lesson': 'A' * 200, 'type': 'positive', 'confidence': 0.9, 'hits': 5},
            {'lesson': 'B' * 200, 'type': 'positive', 'confidence': 0.8, 'hits': 3},
            {'lesson': 'C' * 200, 'type': 'positive', 'confidence': 0.7, 'hits': 2},
        ]
        result = ExperienceMemory.format_for_injection(entries, budget=300)
        assert len(result) < 500  # Should be capped

    def test_update_stats(self):
        from services.experience_memory import ExperienceMemory
        ExperienceMemory.save({"version": 1, "entries": [], "stats": {}})
        ExperienceMemory.update_stats({'composite': 0.85, 'grade': 'A'})
        db = ExperienceMemory.load()
        stats = db['stats']
        assert stats['tasks_scored'] == 1
        assert stats['avg_composite'] == 0.85
        assert stats['grade_distribution']['A'] == 1

    def test_get_stats(self):
        from services.experience_memory import ExperienceMemory
        ExperienceMemory.ensure_seeded()
        stats = ExperienceMemory.get_stats()
        assert 'total_lessons' in stats
        assert 'positive' in stats
        assert 'negative' in stats
        assert 'avg_confidence' in stats
        assert stats['total_lessons'] > 0

    def test_fingerprint_similarity(self):
        from services.experience_memory import ExperienceMemory
        fp1 = {'tech_stack': ['python'], 'libraries': ['flask'], 'file_exts': ['.py'], 'step_type': 'implementation', 'complexity_bucket': 'medium'}
        fp2 = {'tech_stack': ['python'], 'libraries': ['flask'], 'file_exts': ['.py'], 'step_type': 'implementation', 'complexity_bucket': 'medium'}
        sim = ExperienceMemory._fingerprint_similarity(fp1, fp2)
        assert sim == 1.0

    def test_fingerprint_similarity_zero(self):
        from services.experience_memory import ExperienceMemory
        fp1 = {'tech_stack': ['python'], 'libraries': ['flask'], 'file_exts': ['.py'], 'step_type': 'implementation', 'complexity_bucket': 'medium'}
        fp2 = {'tech_stack': ['javascript'], 'libraries': ['express'], 'file_exts': ['.js'], 'step_type': 'planning', 'complexity_bucket': 'complex'}
        sim = ExperienceMemory._fingerprint_similarity(fp1, fp2)
        assert sim < 0.5

    def test_fingerprint_similarity_empty(self):
        from services.experience_memory import ExperienceMemory
        assert ExperienceMemory._fingerprint_similarity({}, {}) == 0.0
        assert ExperienceMemory._fingerprint_similarity(None, None) == 0.0

    def test_merge_fingerprint(self):
        from services.experience_memory import ExperienceMemory
        entry = {'fingerprint': {'tech_stack': ['python'], 'libraries': ['flask'], 'file_exts': ['.py']}}
        new_fp = {'tech_stack': ['javascript'], 'libraries': ['express'], 'file_exts': ['.js'], 'step_type': 'planning'}
        ExperienceMemory._merge_fingerprint(entry, new_fp)
        fp = entry['fingerprint']
        assert 'python' in fp['tech_stack']
        assert 'javascript' in fp['tech_stack']
        assert fp['step_type'] == 'planning'

    def test_corrupted_json_handled(self):
        from services.experience_memory import ExperienceMemory
        # Write corrupted JSON
        with open(self.db_path, 'w') as f:
            f.write('not valid json{{{')
        db = ExperienceMemory.load()
        assert db == {"version": 1, "entries": [], "stats": {}}
        # Should have created a .corrupt backup
        assert os.path.isfile(self.db_path + '.corrupt')
