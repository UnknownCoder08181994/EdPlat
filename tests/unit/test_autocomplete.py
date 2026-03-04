from backend.qa.engine import get_autocomplete


class TestAutocomplete:
    def test_returns_matching_suggestions(self):
        results = get_autocomplete('install')
        texts = [r['text'] for r in results]
        assert 'How do I install Copilot?' in texts

    def test_empty_query_returns_empty(self):
        assert get_autocomplete('') == []

    def test_limit_respected(self):
        results = get_autocomplete('hello', limit=1)
        assert len(results) <= 1

    def test_results_sorted_by_score(self):
        results = get_autocomplete('install copilot')
        assert results[0]['text'] == 'How do I install Copilot?'

    def test_no_match_returns_empty(self):
        assert get_autocomplete('xyzzy') == []

    def test_module_scoped_suggestions(self):
        results = get_autocomplete('intro', module_slug='test-module')
        assert len(results) >= 1
        assert results[0]['text'] == 'Module intro'

    def test_module_scoped_no_match(self):
        results = get_autocomplete('xyzzy', module_slug='test-module')
        assert results == []
