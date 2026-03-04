class TestCacheHeaders:
    def test_js_gets_immutable(self, client):
        resp = client.get('/static/js/shared/lazy-video.js')
        assert 'immutable' in resp.headers.get('Cache-Control', '')

    def test_css_gets_immutable(self, client):
        resp = client.get('/static/css/main.built.css')
        assert 'immutable' in resp.headers.get('Cache-Control', '')

    def test_other_static_gets_no_cache(self, client):
        resp = client.get('/static/favicon.svg')
        assert 'no-cache' in resp.headers.get('Cache-Control', '')

    def test_vary_header(self, client):
        resp = client.get('/')
        assert resp.headers.get('Vary') == 'Accept-Encoding'
