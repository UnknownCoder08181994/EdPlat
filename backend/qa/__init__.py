"""
AWM Institute of Technology — Q&A Loader
=========================================
Merges all category banks into unified answer_bank, suggestion_bank, qa_bank.
Also builds per-module scoped banks for the module viewer AI Coach.
"""

from backend.qa.general import ANSWERS as _ga, SUGGESTIONS as _gs, QA_ENTRIES as _gq
from backend.qa.general import NEXT_QUESTIONS as _gnq
from backend.qa.copilot import ANSWERS as _ca, SUGGESTIONS as _cs, QA_ENTRIES as _cq
from backend.qa.copilot import MODULE_BANKS as _copilot_banks
from backend.qa.copilot import VIDEOS as _copilot_videos
from backend.qa.copilot import NEXT_QUESTIONS as _cnq
from backend.qa.smartsdk import ANSWERS as _sa, SUGGESTIONS as _ss, QA_ENTRIES as _sq
from backend.qa.smartsdk import MODULE_BANKS as _smartsdk_banks
from backend.qa.smartsdk import NEXT_QUESTIONS as _snq
from backend.qa.stratos import ANSWERS as _ta, SUGGESTIONS as _ts, QA_ENTRIES as _tq
from backend.qa.stratos import MODULE_BANKS as _stratos_banks
from backend.qa.stratos import NEXT_QUESTIONS as _tnq
from backend.qa.prompting import ANSWERS as _pa, SUGGESTIONS as _ps, QA_ENTRIES as _pq
from backend.qa.prompting import MODULE_BANKS as _prompting_banks
from backend.qa.prompting import NEXT_QUESTIONS as _pnq
from backend.qa.fullstack import ANSWERS as _fa, SUGGESTIONS as _fs, QA_ENTRIES as _fq
from backend.qa.fullstack import MODULE_BANKS as _fullstack_banks
from backend.qa.fullstack import NEXT_QUESTIONS as _fnq

# ---- Unified banks (global chat) ----
answer_bank: dict = {}
suggestion_bank: list = []
qa_bank: list = []

def _merge(answers, suggestions, entries):
    for key in answers:
        if key in answer_bank:
            raise ValueError(f"Duplicate answer ID: {key}")
    answer_bank.update(answers)
    suggestion_bank.extend(suggestions)
    qa_bank.extend(entries)

_merge(_ga, _gs, _gq)
_merge(_ca, _cs, _cq)
_merge(_sa, _ss, _sq)
_merge(_ta, _ts, _tq)
_merge(_pa, _ps, _pq)
_merge(_fa, _fs, _fq)

# ---- Video metadata (answer ID → video info) ----
video_bank: dict = {}
video_bank.update(_copilot_videos)

# ---- Next-question suggestions (answer ID → list of 3 strings) ----
next_questions_bank: dict = {}
next_questions_bank.update(_gnq)
next_questions_bank.update(_cnq)
next_questions_bank.update(_snq)
next_questions_bank.update(_tnq)
next_questions_bank.update(_pnq)
next_questions_bank.update(_fnq)

# ---- Per-module scoped banks (module viewer AI Coach) ----
module_banks: dict = {}
module_banks.update(_copilot_banks)
module_banks.update(_smartsdk_banks)
module_banks.update(_stratos_banks)
module_banks.update(_prompting_banks)
module_banks.update(_fullstack_banks)

# ---- Answer → module map (for standalone chat module references) ----
# Maps answer IDs to their parent module slug + display name so the engine
# can append "Refer to the X module" when answering outside a module.
_MODULE_DISPLAY = {
    'copilot-basics':              'Copilot Basics',
    'smartsdk-fundamentals':       'SmartSDK Fundamentals',
    'building-smartsdk':           'Building with SmartSDK',
    'stratos-setup':               'Stratos Setup',
    'stratos-workflows':           'Stratos Workflows',
    'prompt-engineering':          'Prompt Engineering',
    'fullstack-ai-integration':    'Full-Stack AI Integration',
}

answer_module_map: dict = {}   # answer_id → {'slug': str, 'name': str}
for _slug, _bank in module_banks.items():
    _display = _MODULE_DISPLAY.get(_slug, _slug.replace('-', ' ').title())
    for _aid in _bank.get('answers', {}):
        answer_module_map[_aid] = {'slug': _slug, 'name': _display}

# ---- Dynamic "modules available" answer ----
# Maps slug prefix → display name.  Add a row when a new category is created;
# the answer text is rebuilt automatically from whichever prefixes have banks.
_TOPIC_META = {
    'copilot':   'GitHub Copilot',
    'smartsdk':  'SmartSDK',
    'building':  'SmartSDK',
    'stratos':   'Stratos',
    'prompt':    'Prompt Engineering',
    'fullstack': 'Full-Stack AI Integration',
}


def _build_modules_answer() -> str | None:
    """Generate a short answer listing every loaded topic."""
    seen: dict[str, list[str]] = {}          # display_name → [sub-slug, …]
    for slug in module_banks:
        for prefix, label in _TOPIC_META.items():
            if slug.startswith(prefix) or prefix in slug:
                seen.setdefault(label, []).append(slug)
                break
    if not seen:
        return None
    parts = ['Here\'s what we cover at AWMIT:\n']
    for i, name in enumerate(seen, 1):
        parts.append(f'<strong>{i}. {name}</strong>')
    parts.append('\nPick any topic and I can tell you more about it.')
    return '\n'.join(parts)


_modules_text = _build_modules_answer()
if _modules_text:
    answer_bank['general-modules'] = _modules_text
    qa_bank.append({
        'keywords': [
            'modules', 'topics', 'available', 'what modules',
            'courses', 'what topics', 'catalog', 'list modules',
            'what do you cover', 'subjects',
        ],
        'answer': 'general-modules',
    })
    suggestion_bank.append(
        {'text': 'What modules are available?',
         'keywords': ['modules', 'available', 'topics']},
    )
    # Next-question chips — varied phrasing to avoid near-duplicate texts
    _seen_names: list[str] = []
    for slug in module_banks:
        for prefix, label in _TOPIC_META.items():
            if (slug.startswith(prefix) or prefix in slug) \
                    and label not in _seen_names:
                _seen_names.append(label)
                break
    _NQ_TEMPLATES = [
        'Explore the {} module',
        'What does {} cover?',
        'Dive into {} basics',
    ]
    next_questions_bank['general-modules'] = [
        tmpl.format(n) for tmpl, n in zip(_NQ_TEMPLATES, _seen_names[:3])
    ]
