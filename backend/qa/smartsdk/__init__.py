from backend.qa.smartsdk.fundamentals_intro import ANSWERS as _a1, SUGGESTIONS as _s1, QA_ENTRIES as _q1
from backend.qa.smartsdk.fundamentals_intro import NEXT_QUESTIONS as _nq1
from backend.qa.smartsdk.building_intro import ANSWERS as _a2, SUGGESTIONS as _s2, QA_ENTRIES as _q2
from backend.qa.smartsdk.building_intro import NEXT_QUESTIONS as _nq2

ANSWERS = {**_a1, **_a2}
SUGGESTIONS = _s1 + _s2
QA_ENTRIES = _q1 + _q2
NEXT_QUESTIONS = {**_nq1, **_nq2}

MODULE_BANKS = {
    'smartsdk-fundamentals': {
        'answers': {**_a1},
        'suggestions': _s1,
        'qa_entries': _q1,
        'next_questions': {**_nq1},
    },
    'building-smartsdk': {
        'answers': {**_a2},
        'suggestions': _s2,
        'qa_entries': _q2,
        'next_questions': {**_nq2},
    },
}
