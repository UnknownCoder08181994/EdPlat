from backend.qa.engine import resolve_query


class TestResolveQuery:
    def test_match_returns_answer(self):
        result = resolve_query('hello')
        assert result['type'] == 'answer'
        assert result['answerId'] == 'test-hello'
        assert 'Hello' in result['text']

    def test_no_match_returns_noMatch(self):
        result = resolve_query('xyzzy gibberish')
        assert result['type'] == 'noMatch'

    def test_empty_query_returns_noMatch(self):
        result = resolve_query('')
        assert result['type'] == 'noMatch'

    def test_followup_entry_returns_followUp(self):
        result = resolve_query('help me with options')
        assert result['type'] == 'followUp'
        assert 'question' in result
        assert len(result['options']) == 2

    def test_pending_followup_resolves(self):
        pending = {
            'options': [
                {'keywords': ['option', 'first'], 'answerId': 'test-followup-a'},
                {'keywords': ['option', 'second'], 'answerId': 'test-followup-b'},
            ],
        }
        result = resolve_query('first option', pending)
        assert result['type'] == 'answer'
        assert result['answerId'] == 'test-followup-a'

    def test_pending_followup_low_score_falls_through(self):
        pending = {
            'options': [
                {'keywords': ['zzzzz'], 'answerId': 'test-followup-a'},
            ],
        }
        result = resolve_query('hello', pending)
        assert result['type'] == 'answer'
        assert result['answerId'] == 'test-hello'

    def test_module_scoped_query(self):
        result = resolve_query('intro welcome', module_slug='test-module')
        assert result['type'] == 'answer'
        assert result['answerId'] == 'mod-intro'

    def test_unknown_module_falls_to_global(self):
        result = resolve_query('hello', module_slug='nonexistent-module')
        assert result['type'] == 'answer'
        assert result['answerId'] == 'test-hello'

    def test_video_attached_when_available(self):
        result = resolve_query('install copilot')
        assert result['type'] == 'answer'
        assert result['video']['src'] == 'test-video.mp4'

    def test_next_questions_attached(self):
        result = resolve_query('hello')
        assert 'nextQuestions' in result
        assert len(result['nextQuestions']) == 1

    def test_module_ref_attached_for_standalone(self):
        result = resolve_query('install copilot')
        assert 'moduleRef' in result
        assert result['moduleRef']['name'] == 'Copilot Basics'
