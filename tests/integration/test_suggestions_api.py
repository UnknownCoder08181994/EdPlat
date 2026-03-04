class TestSuggestionsApi:
    def test_with_query(self, client):
        resp = client.get('/api/suggestions?q=install')
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_empty_query(self, client):
        assert client.get('/api/suggestions?q=').get_json() == []

    def test_no_query_param(self, client):
        assert client.get('/api/suggestions').get_json() == []

    def test_module_scoped(self, client):
        data = client.get('/api/suggestions?q=intro&module=test-module').get_json()
        assert len(data) >= 1

    def test_chips_returns_list(self, client):
        resp = client.get('/api/chips')
        assert resp.status_code == 200
        assert isinstance(resp.get_json(), list)
