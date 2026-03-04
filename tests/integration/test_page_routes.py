class TestPageRoutes:
    def test_index(self, client):
        assert client.get('/').status_code == 200

    def test_vision(self, client):
        assert client.get('/vision').status_code == 200

    def test_faq(self, client):
        assert client.get('/faq').status_code == 200

    def test_modules(self, client):
        resp = client.get('/modules')
        assert resp.status_code == 200
        assert b'Copilot Basics' in resp.data

    def test_contact(self, client):
        assert client.get('/contact').status_code == 200

    def test_chat(self, client):
        assert client.get('/chat').status_code == 200

    def test_tutorials(self, client):
        assert client.get('/tutorials').status_code == 200

    def test_favicon(self, client):
        assert client.get('/favicon.ico').status_code == 204

    def test_module_detail_valid(self, client):
        resp = client.get('/modules/copilot-basics')
        assert resp.status_code == 200
        assert b'Copilot Basics' in resp.data

    def test_module_detail_invalid(self, client):
        assert client.get('/modules/nonexistent').status_code == 404

    def test_module_viewer_valid(self, client):
        resp = client.get('/modules/copilot-basics/onboarding')
        assert resp.status_code == 200
        assert b'MODULE_DATA' in resp.data

    def test_module_viewer_invalid_slug(self, client):
        assert client.get('/modules/nonexistent/onboarding').status_code == 404

    def test_module_viewer_invalid_section(self, client):
        assert client.get('/modules/copilot-basics/nonexistent').status_code == 404

    def test_tutorials_detail_redirects(self, client):
        resp = client.get('/tutorials/flask-dashboard')
        assert resp.status_code == 302
        assert '/tutorials/flask-dashboard/build' in resp.headers['Location']

    def test_tutorials_detail_invalid(self, client):
        assert client.get('/tutorials/nonexistent').status_code == 404

    def test_tutorials_viewer_valid(self, client):
        assert client.get('/tutorials/flask-dashboard/build').status_code == 200

    def test_tutorials_viewer_invalid_section(self, client):
        assert client.get('/tutorials/flask-dashboard/nonexistent').status_code == 404
