import pytest

pytestmark = pytest.mark.e2e


class TestModuleViewer:
    def test_viewer_page_loads(self, page):
        pg, base = page
        pg.goto(base + '/modules/copilot-basics/onboarding')
        assert pg.locator('#viewer-video').count() >= 1

    def test_sidebar_has_sections(self, page):
        pg, base = page
        pg.goto(base + '/modules/copilot-basics/onboarding')
        pg.wait_for_selector('.viewer-section-item')
        assert pg.locator('.viewer-section-item').count() >= 1

    def test_chat_input_present(self, page):
        pg, base = page
        pg.goto(base + '/modules/copilot-basics/onboarding')
        assert pg.locator('#viewer-chat-input').count() >= 1

    def test_module_data_injected(self, page):
        pg, base = page
        pg.goto(base + '/modules/copilot-basics/onboarding')
        slug = pg.evaluate('window.MODULE_DATA.slug')
        assert slug == 'copilot-basics'

    def test_back_link_present(self, page):
        pg, base = page
        pg.goto(base + '/modules/copilot-basics/onboarding')
        pg.wait_for_selector('.viewer-back-link')
        assert 'Back to Overview' in pg.locator('.viewer-back-link').text_content()

    def test_tutorials_viewer_loads(self, page):
        pg, base = page
        pg.goto(base + '/tutorials/flask-dashboard/build')
        assert pg.locator('#viewer-video').count() >= 1
