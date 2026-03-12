"""Unit tests for backend/services/error_memory.py"""

import os
import json
import pytest


class TestErrorMemory:
    @pytest.fixture(autouse=True)
    def setup_db(self, mock_config, monkeypatch):
        """Point ErrorMemory.DB_PATH to temp storage."""
        import services.error_memory as em_module
        self.db_path = os.path.join(mock_config, 'error_memory.json')
        monkeypatch.setattr(em_module, 'DB_PATH', self.db_path)
        # Start with no DB file
        if os.path.isfile(self.db_path):
            os.remove(self.db_path)

    def test_load_empty(self):
        from services.error_memory import ErrorMemory
        db = ErrorMemory.load()
        assert isinstance(db, dict)
        assert 'entries' in db

    def test_save_and_load(self):
        from services.error_memory import ErrorMemory
        db = {"version": 2, "entries": [{"id": "t1", "sig": "test:sig"}]}
        ErrorMemory.save(db)
        loaded = ErrorMemory.load()
        assert len(loaded['entries']) == 1

    def test_ensure_seeded_creates_db(self):
        from services.error_memory import ErrorMemory, SEED_ENTRIES
        assert not os.path.isfile(self.db_path)
        ErrorMemory.ensure_seeded()
        assert os.path.isfile(self.db_path)
        db = ErrorMemory.load()
        assert len(db['entries']) == len(SEED_ENTRIES)

    def test_ensure_seeded_adds_missing(self):
        from services.error_memory import ErrorMemory, SEED_ENTRIES
        # Create DB with only 1 seed entry
        db = {"version": 2, "entries": [dict(SEED_ENTRIES[0])]}
        ErrorMemory.save(db)
        ErrorMemory.ensure_seeded()
        db = ErrorMemory.load()
        assert len(db['entries']) == len(SEED_ENTRIES)


class TestComputeSignature:
    def test_module_not_found(self):
        from services.error_memory import ErrorMemory
        sig = ErrorMemory.compute_signature({'type': 'module_not_found', 'module': 'flask.app'})
        assert sig == 'module_not_found:flask'

    def test_import_error(self):
        from services.error_memory import ErrorMemory
        sig = ErrorMemory.compute_signature({'type': 'import', 'message': 'cannot import name X'})
        assert sig.startswith('import:')

    def test_syntax_error(self):
        from services.error_memory import ErrorMemory
        sig = ErrorMemory.compute_signature({'type': 'syntax', 'message': 'invalid syntax'})
        assert sig.startswith('syntax:')

    def test_runtime_error(self):
        from services.error_memory import ErrorMemory
        sig = ErrorMemory.compute_signature({'type': 'runtime', 'errorType': 'TypeError', 'message': 'unsupported'})
        assert sig.startswith('runtime:TypeError:')

    def test_unknown_type(self):
        from services.error_memory import ErrorMemory
        sig = ErrorMemory.compute_signature({'type': 'exotic', 'message': 'weird error'})
        assert sig.startswith('unknown:')


class TestEscalationTiers:
    def test_tier1(self):
        from services.error_memory import ErrorMemory
        entry = {'hits': 1, 'failed': 0}
        assert ErrorMemory.compute_tier(entry) == 1

    def test_tier2(self):
        from services.error_memory import ErrorMemory
        entry = {'hits': 4, 'failed': 0}
        assert ErrorMemory.compute_tier(entry) == 2

    def test_tier3(self):
        from services.error_memory import ErrorMemory
        entry = {'hits': 7, 'failed': 0}
        assert ErrorMemory.compute_tier(entry) == 3

    def test_failures_accelerate(self):
        from services.error_memory import ErrorMemory
        # 2 hits + 2 failures * 0.5 = effective 3 → tier 2
        entry = {'hits': 2, 'failed': 2}
        assert ErrorMemory.compute_tier(entry) == 2


class TestContextFingerprinting:
    def test_empty_workspace(self, workspace_dir):
        from services.error_memory import ErrorMemory
        fp = ErrorMemory.compute_fingerprint(workspace_dir)
        assert 'tech_stack' in fp
        assert 'libraries' in fp

    def test_python_workspace(self, workspace_dir):
        from services.error_memory import ErrorMemory
        with open(os.path.join(workspace_dir, 'app.py'), 'w') as f:
            f.write('print("hello")')
        fp = ErrorMemory.compute_fingerprint(workspace_dir)
        assert '.py' in fp['file_exts']
        assert 'python' in fp['tech_stack']

    def test_requirements_detected(self, workspace_dir):
        from services.error_memory import ErrorMemory
        with open(os.path.join(workspace_dir, 'requirements.txt'), 'w') as f:
            f.write('flask>=2.0\nrequests\n')
        fp = ErrorMemory.compute_fingerprint(workspace_dir)
        assert 'python' in fp['tech_stack']
        assert 'flask' in fp['libraries']
        assert 'requests' in fp['libraries']

    def test_complexity_to_bucket(self):
        from services.error_memory import ErrorMemory
        assert ErrorMemory._complexity_to_bucket(1) == 'trivial'
        assert ErrorMemory._complexity_to_bucket(4) == 'simple'
        assert ErrorMemory._complexity_to_bucket(6) == 'medium'
        assert ErrorMemory._complexity_to_bucket(8) == 'complex'
        assert ErrorMemory._complexity_to_bucket(10) == 'massive'

    def test_fingerprint_similarity_identical(self):
        from services.error_memory import ErrorMemory
        fp = {'tech_stack': ['python'], 'libraries': ['flask'], 'file_exts': ['.py'], 'step_type': 'implementation', 'complexity_bucket': 'medium'}
        assert ErrorMemory.fingerprint_similarity(fp, fp) == 1.0

    def test_fingerprint_similarity_disjoint(self):
        from services.error_memory import ErrorMemory
        fp1 = {'tech_stack': ['python'], 'libraries': ['flask'], 'file_exts': ['.py'], 'step_type': 'planning', 'complexity_bucket': 'simple'}
        fp2 = {'tech_stack': ['javascript'], 'libraries': ['express'], 'file_exts': ['.js'], 'step_type': 'implementation', 'complexity_bucket': 'complex'}
        sim = ErrorMemory.fingerprint_similarity(fp1, fp2)
        assert sim == 0.0

    def test_fingerprint_similarity_empty(self):
        from services.error_memory import ErrorMemory
        assert ErrorMemory.fingerprint_similarity({}, {}) == 0.0
        assert ErrorMemory.fingerprint_similarity(None, None) == 0.0


class TestMultiArmedBandit:
    def test_sample_best_fix_single(self):
        from services.error_memory import ErrorMemory
        entry = {'fixes': [{'strategy': 'Use pip install flask', 'alpha': 5, 'beta': 1}]}
        fix = ErrorMemory.sample_best_fix(entry)
        assert fix == 'Use pip install flask'

    def test_sample_best_fix_no_fixes(self):
        from services.error_memory import ErrorMemory
        entry = {'fix': 'legacy fix text', 'fixes': []}
        fix = ErrorMemory.sample_best_fix(entry)
        assert fix == 'legacy fix text'

    def test_rank_fixes_ordering(self):
        from services.error_memory import ErrorMemory
        entry = {
            'fixes': [
                {'strategy': 'Bad fix', 'alpha': 1, 'beta': 5},
                {'strategy': 'Good fix', 'alpha': 5, 'beta': 1},
            ]
        }
        ranked = ErrorMemory.rank_fixes(entry)
        assert ranked[0] == 'Good fix'

    def test_rank_fixes_no_fixes(self):
        from services.error_memory import ErrorMemory
        entry = {'fix': 'Only fix'}
        ranked = ErrorMemory.rank_fixes(entry)
        assert ranked == ['Only fix']


class TestRecord:
    @pytest.fixture(autouse=True)
    def setup_db(self, mock_config, monkeypatch):
        import services.error_memory as em_module
        self.db_path = os.path.join(mock_config, 'error_memory.json')
        monkeypatch.setattr(em_module, 'DB_PATH', self.db_path)
        if os.path.isfile(self.db_path):
            os.remove(self.db_path)
        from services.error_memory import ErrorMemory
        ErrorMemory.save({"version": 2, "entries": []})

    def test_record_new_error(self):
        from services.error_memory import ErrorMemory
        error_class = {'type': 'module_not_found', 'module': 'pandas'}
        ErrorMemory.record(error_class, 'pip install pandas', True)
        db = ErrorMemory.load()
        assert len(db['entries']) == 1
        entry = db['entries'][0]
        assert entry['sig'] == 'module_not_found:pandas'
        assert entry['confirmed'] == 1

    def test_record_updates_existing(self):
        from services.error_memory import ErrorMemory
        error_class = {'type': 'module_not_found', 'module': 'pandas'}
        ErrorMemory.record(error_class, 'pip install pandas', True)
        ErrorMemory.record(error_class, 'pip install pandas', True)
        db = ErrorMemory.load()
        assert len(db['entries']) == 1
        assert db['entries'][0]['hits'] == 2
        assert db['entries'][0]['confirmed'] == 2

    def test_record_failure(self):
        from services.error_memory import ErrorMemory
        error_class = {'type': 'module_not_found', 'module': 'numpy'}
        ErrorMemory.record(error_class, 'pip install numpy', False)
        db = ErrorMemory.load()
        entry = db['entries'][0]
        assert entry['failed'] == 1
        assert entry['confirmed'] == 0


class TestRecordPlanningMistake:
    @pytest.fixture(autouse=True)
    def setup_db(self, mock_config, monkeypatch):
        import services.error_memory as em_module
        self.db_path = os.path.join(mock_config, 'error_memory.json')
        monkeypatch.setattr(em_module, 'DB_PATH', self.db_path)
        if os.path.isfile(self.db_path):
            os.remove(self.db_path)
        from services.error_memory import ErrorMemory
        ErrorMemory.save({"version": 2, "entries": []})

    def test_record_planning_mistake(self):
        from services.error_memory import ErrorMemory
        ErrorMemory.record_planning_mistake(
            'mixed_imports', 'Mixed flat and package imports', 'Use flat layout',
        )
        db = ErrorMemory.load()
        assert len(db['entries']) == 1
        assert db['entries'][0]['sig'] == 'planning:mixed_imports'
        assert db['entries'][0]['type'] == 'planning'


class TestLookup:
    @pytest.fixture(autouse=True)
    def setup_db(self, mock_config, monkeypatch):
        import services.error_memory as em_module
        self.db_path = os.path.join(mock_config, 'error_memory.json')
        monkeypatch.setattr(em_module, 'DB_PATH', self.db_path)
        if os.path.isfile(self.db_path):
            os.remove(self.db_path)

    def test_lookup_empty(self):
        from services.error_memory import ErrorMemory
        ErrorMemory.save({"version": 2, "entries": []})
        results = ErrorMemory.lookup(step_type='implementation')
        assert results == []

    def test_lookup_by_exact_match(self):
        from services.error_memory import ErrorMemory
        ErrorMemory.save({"version": 2, "entries": [{
            "id": "t1", "sig": "module_not_found:flask", "type": "module_not_found",
            "tags": ["execution"], "pattern": "flask", "confidence": 1.0,
            "hits": 3, "failed": 0, "confirmed": 3,
            "fixes": [{"strategy": "pip install flask", "alpha": 4, "beta": 1}],
            "fingerprint": {},
        }]})
        error_class = {'type': 'module_not_found', 'module': 'flask'}
        results = ErrorMemory.lookup(error_class=error_class)
        assert len(results) == 1
        assert results[0]['sig'] == 'module_not_found:flask'


class TestFormatForPrompt:
    def test_empty(self):
        from services.error_memory import ErrorMemory
        result = ErrorMemory.format_for_prompt([])
        assert result == ''

    def test_tier1_format(self):
        from services.error_memory import ErrorMemory
        entries = [{
            '_tier': 1, 'fix': 'Use pip install flask',
            'fixes': [{'strategy': 'Use pip install flask', 'alpha': 3, 'beta': 1}],
        }]
        result = ErrorMemory.format_for_prompt(entries)
        assert 'Note:' in result

    def test_tier3_format(self):
        from services.error_memory import ErrorMemory
        entries = [{
            '_tier': 3, 'fix': 'Always check imports',
            'fixes': [{'strategy': 'Always check imports', 'alpha': 8, 'beta': 1}],
            'failed': 5,
        }]
        result = ErrorMemory.format_for_prompt(entries)
        assert 'CRITICAL' in result
        assert 'YOU MUST' in result


class TestCorrectiveFixes:
    @pytest.fixture(autouse=True)
    def setup_db(self, mock_config, monkeypatch):
        import services.error_memory as em_module
        self.db_path = os.path.join(mock_config, 'error_memory.json')
        monkeypatch.setattr(em_module, 'DB_PATH', self.db_path)
        if os.path.isfile(self.db_path):
            os.remove(self.db_path)

    def test_get_corrective_fixes_empty(self):
        from services.error_memory import ErrorMemory
        ErrorMemory.save({"version": 2, "entries": []})
        results = ErrorMemory.get_corrective_fixes(file_ext='.py')
        assert results == []

    def test_get_corrective_fixes_with_match(self):
        from services.error_memory import ErrorMemory
        ErrorMemory.ensure_seeded()
        # Seed entry seed_009 has auto_fix with file_pattern '*.py'
        results = ErrorMemory.get_corrective_fixes(file_ext='.py', on_write=True)
        # Should find the Unicode replacement auto_fix
        assert len(results) > 0

    def test_get_corrective_fixes_by_filename(self):
        from services.error_memory import ErrorMemory
        ErrorMemory.ensure_seeded()
        results = ErrorMemory.get_corrective_fixes(filename='requirements.txt', on_write=True)
        # Seed entry seed_001 has auto_fix for requirements.txt
        matched_sigs = [e.get('sig', '') for e, _ in results]
        assert any('pip_nodejs_tools' in s for s in matched_sigs)


class TestMigration:
    @pytest.fixture(autouse=True)
    def setup_db(self, mock_config, monkeypatch):
        import services.error_memory as em_module
        self.db_path = os.path.join(mock_config, 'error_memory.json')
        monkeypatch.setattr(em_module, 'DB_PATH', self.db_path)
        if os.path.isfile(self.db_path):
            os.remove(self.db_path)

    def test_migrate_v1_entry(self):
        from services.error_memory import ErrorMemory
        entry = {
            'id': 'old1', 'sig': 'module_not_found:flask',
            'type': 'module_not_found', 'fix': 'pip install flask',
            'confirmed': 3, 'failed': 0,
            'last_confirmed': '2025-01-01T00:00:00',
        }
        migrated = ErrorMemory.migrate_entry(entry)
        assert 'fixes' in migrated
        assert 'fingerprint' in migrated
        assert len(migrated['fixes']) == 1
        assert migrated['fixes'][0]['strategy'] == 'pip install flask'

    def test_migrate_db_v1_to_v2(self):
        from services.error_memory import ErrorMemory
        db = {"version": 1, "entries": [
            {'id': 'old1', 'sig': 'test', 'fix': 'do this', 'confirmed': 1, 'failed': 0,
             'last_confirmed': '2025-01-01T00:00:00'},
        ]}
        ErrorMemory.save(db)
        migrated = ErrorMemory.migrate_db(db)
        assert migrated['version'] == 2

    def test_corrupted_json_handled(self):
        from services.error_memory import ErrorMemory
        with open(self.db_path, 'w') as f:
            f.write('not valid json{{{')
        db = ErrorMemory.load()
        assert db == {"version": 2, "entries": []}
        assert os.path.isfile(self.db_path + '.corrupt')
