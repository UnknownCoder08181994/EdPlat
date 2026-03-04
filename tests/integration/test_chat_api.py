import json


class TestChatApi:
    def _post_chat(self, client, data):
        return client.post('/api/chat',
                           data=json.dumps(data),
                           content_type='application/json')

    def test_valid_query(self, client):
        resp = self._post_chat(client, {'message': 'hello'})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['type'] == 'answer'

    def test_no_match(self, client):
        data = self._post_chat(client, {'message': 'xyzzy gibberish'}).get_json()
        assert data['type'] == 'noMatch'

    def test_empty_message(self, client):
        data = self._post_chat(client, {'message': ''}).get_json()
        assert data['type'] == 'noMatch'

    def test_with_pending_followup(self, client):
        pending = {
            'options': [
                {'keywords': ['option', 'first'], 'answerId': 'test-followup-a'},
            ],
        }
        data = self._post_chat(client, {
            'message': 'first option',
            'pendingFollowUp': pending,
        }).get_json()
        assert data['type'] == 'answer'
        assert data['answerId'] == 'test-followup-a'

    def test_with_module_slug(self, client):
        data = self._post_chat(client, {
            'message': 'intro welcome',
            'moduleSlug': 'test-module',
        }).get_json()
        assert data['type'] == 'answer'
        assert data['answerId'] == 'mod-intro'

    def test_invalid_body_returns_400(self, client):
        resp = client.post('/api/chat',
                           data='"just a string"',
                           content_type='application/json')
        assert resp.status_code == 400

    def test_resolve_valid(self, client):
        resp = client.post('/api/chat/resolve',
                           data=json.dumps({'answerId': 'test-hello'}),
                           content_type='application/json')
        data = resp.get_json()
        assert data['type'] == 'answer'
        assert data['answerId'] == 'test-hello'

    def test_resolve_invalid(self, client):
        resp = client.post('/api/chat/resolve',
                           data=json.dumps({'answerId': 'nonexistent'}),
                           content_type='application/json')
        assert resp.get_json()['type'] == 'noMatch'

    def test_resolve_invalid_body(self, client):
        resp = client.post('/api/chat/resolve',
                           data='"not a dict"',
                           content_type='application/json')
        assert resp.status_code == 400
