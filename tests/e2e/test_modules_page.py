import pytest

pytestmark = pytest.mark.e2e


class TestModulesPage:
    def test_12_cards_visible(self, page):
        pg, base = page
        pg.goto(base + '/modules')
        pg.wait_for_selector('.course-card')
        assert pg.locator('.course-card').count() == 12

    def test_toolbar_count(self, page):
        pg, base = page
        pg.goto(base + '/modules')
        pg.wait_for_selector('#toolbar-count')
        assert '12' in pg.locator('#toolbar-count').text_content()

    def test_search_filters_cards(self, page):
        pg, base = page
        pg.goto(base + '/modules')
        pg.wait_for_selector('#toolbar-search')
        pg.fill('#toolbar-search', 'Copilot')
        pg.wait_for_timeout(600)
        visible = pg.locator('.course-card:not([style*="display: none"])')
        assert visible.count() < 12

    def test_module_detail_has_start_button(self, page):
        pg, base = page
        pg.goto(base + '/modules/copilot-basics')
        pg.wait_for_selector('.course-start-btn')
        assert pg.locator('.course-start-btn').count() >= 1
