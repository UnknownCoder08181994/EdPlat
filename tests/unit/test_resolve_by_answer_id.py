from backend.qa.engine import resolve_by_answer_id


class TestResolveByAnswerId:
    def test_valid_id_returns_answer(self):
        result = resolve_by_answer_id('test-hello')
        assert result['type'] == 'answer'
        assert result['answerId'] == 'test-hello'

    def test_invalid_id_returns_noMatch(self):
        result = resolve_by_answer_id('nonexistent-id')
        assert result['type'] == 'noMatch'

    def test_empty_id_returns_noMatch(self):
        result = resolve_by_answer_id('')
        assert result['type'] == 'noMatch'

    def test_video_attached_if_available(self):
        result = resolve_by_answer_id('test-copilot-install')
        assert 'video' in result
        assert result['video']['src'] == 'test-video.mp4'

    def test_module_ref_attached(self):
        result = resolve_by_answer_id('test-copilot-install')
        assert 'moduleRef' in result
        assert result['moduleRef']['name'] == 'Copilot Basics'
