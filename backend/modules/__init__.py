"""
AWM Institute of Technology — Module Loader
============================================
Imports all per-module registries and builds the combined MODULES dict.

Registry files for building_smartsdk and advanced_copilot_patterns are kept
in their folders for future use — they just aren't loaded here yet.
Intermediate and advanced difficulty levels are supported by the data model;
re-enable by uncommenting the imports and dict entries below.
"""

from backend.modules.copilot_basics.registry import MODULE as _copilot_basics
# from backend.modules.building_smartsdk.registry import MODULE as _building_smartsdk
# from backend.modules.advanced_copilot_patterns.registry import MODULE as _advanced_copilot
from backend.modules.flask_dashboard_practice.registry import PRACTICE as _flask_dashboard

MODULES = {
    'copilot-basics': _copilot_basics,
    # 'building-smartsdk': _building_smartsdk,          # intermediate
    # 'advanced-copilot-patterns': _advanced_copilot,    # advanced
}

PRACTICES = {
    'flask-dashboard': _flask_dashboard,
}


def get_module(slug):
    """Return module dict or None."""
    return MODULES.get(slug)


def get_all_modules():
    """Return all modules as list of (slug, data) tuples."""
    return list(MODULES.items())


def get_practice(slug):
    """Return practice dict or None."""
    return PRACTICES.get(slug)


def get_all_practices():
    """Return all practices as list of (slug, data) tuples."""
    return list(PRACTICES.items())
