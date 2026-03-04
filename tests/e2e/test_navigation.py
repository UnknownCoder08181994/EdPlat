import pytest

pytestmark = pytest.mark.e2e


class TestNavigation:
    def test_home_page_loads(self, page):
        pg, base = page
        pg.goto(base + '/')
        assert pg.title() != ''

    def test_modules_page_loads(self, page):
        pg, base = page
        pg.goto(base + '/modules')
        assert 'Modules' in pg.title()

    def test_tutorials_page_loads(self, page):
        pg, base = page
        pg.goto(base + '/tutorials')
        pg.wait_for_selector('.course-card')
        cards = pg.locator('.course-card')
        assert cards.count() == 12

    def test_chat_page_loads(self, page):
        pg, base = page
        pg.goto(base + '/chat')
        assert 'Chat' in pg.title()

    def test_404_for_bad_module(self, page):
        pg, base = page
        resp = pg.goto(base + '/modules/nonexistent')
        assert resp.status == 404
