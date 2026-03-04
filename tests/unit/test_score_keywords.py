from backend.qa.engine import _score_keywords


class TestScoreKeywords:
    def test_exact_word_at_boundary(self):
        score = _score_keywords('install copilot', ['install'])
        assert score >= 10  # phrase boundary match + word match

    def test_multiple_keywords_accumulate(self):
        score = _score_keywords('install copilot', ['install', 'copilot'])
        assert score > _score_keywords('install copilot', ['install'])

    def test_partial_prefix_match(self):
        score = _score_keywords('inst', ['install'])
        assert score >= 2

    def test_no_match(self):
        assert _score_keywords('banana', ['copilot']) == 0

    def test_empty_query(self):
        assert _score_keywords('', ['hello']) == 0

    def test_empty_keywords(self):
        assert _score_keywords('hello', []) == 0

    def test_single_word_meets_threshold(self):
        score = _score_keywords('hello', ['hello'])
        assert score >= 5  # must meet resolve_query threshold

    def test_case_insensitive(self):
        assert _score_keywords('copilot', ['Copilot']) > 0

    def test_keyword_prefix_of_word(self):
        score = _score_keywords('installation', ['install'])
        assert score >= 2  # install.startswith(install) or install starts with install
