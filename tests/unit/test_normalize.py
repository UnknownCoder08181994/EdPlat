from backend.qa.engine import normalize


class TestNormalize:
    def test_basic_lowercase(self):
        assert normalize('Hello World') == 'hello world'

    def test_strips_punctuation(self):
        assert normalize('What is Copilot?') == 'what is copilot'

    def test_collapses_whitespace(self):
        assert normalize('too   many    spaces') == 'too many spaces'

    def test_strips_leading_trailing(self):
        assert normalize('  padded  ') == 'padded'

    def test_empty_string(self):
        assert normalize('') == ''

    def test_none_input(self):
        assert normalize(None) == ''

    def test_only_punctuation(self):
        assert normalize('???!!!') == ''

    def test_preserves_digits(self):
        assert normalize('step 1: install') == 'step 1 install'

    def test_mixed_case_punctuation_whitespace(self):
        assert normalize('  How do I install Copilot??  ') == 'how do i install copilot'

    def test_underscores_preserved(self):
        assert normalize('my_function') == 'my_function'
