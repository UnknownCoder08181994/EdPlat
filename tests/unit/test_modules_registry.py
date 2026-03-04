from backend.modules import get_module, get_practice, get_all_modules, get_all_practices


class TestModulesRegistry:
    def test_get_module_valid_slug(self):
        module = get_module('copilot-basics')
        assert module is not None
        assert module['title'] == 'Copilot Basics'

    def test_get_module_invalid_slug(self):
        assert get_module('nonexistent') is None

    def test_get_module_none(self):
        assert get_module(None) is None

    def test_get_practice_valid_slug(self):
        practice = get_practice('flask-dashboard')
        assert practice is not None
        assert practice['title'] == 'Create a Flask Dashboard'

    def test_get_practice_invalid_slug(self):
        assert get_practice('nonexistent') is None

    def test_get_all_modules(self):
        modules = get_all_modules()
        slugs = [slug for slug, _ in modules]
        assert 'copilot-basics' in slugs

    def test_get_all_practices(self):
        practices = get_all_practices()
        slugs = [slug for slug, _ in practices]
        assert 'flask-dashboard' in slugs

    def test_module_has_required_fields(self):
        module = get_module('copilot-basics')
        for key in ['title', 'subtitle', 'category', 'accent', 'difficulty', 'duration', 'sections', 'author']:
            assert key in module, f"Missing: {key}"

    def test_section_has_required_fields(self):
        module = get_module('copilot-basics')
        section = module['sections'][0]
        for key in ['id', 'title', 'video', 'description', 'breakdown']:
            assert key in section, f"Missing: {key}"

    def test_copilot_basics_has_onboarding_section(self):
        module = get_module('copilot-basics')
        section_ids = [s['id'] for s in module['sections']]
        assert 'onboarding' in section_ids
