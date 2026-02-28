# Topic 1 (intro) removed — file kept for future use
# from backend.qa.copilot.basics_intro import ANSWERS as _a1, SUGGESTIONS as _s1, QA_ENTRIES as _q1
# from backend.qa.copilot.basics_intro import NEXT_QUESTIONS as _nq1
from backend.qa.copilot.basics_onboarding import ANSWERS as _a8, SUGGESTIONS as _s8, QA_ENTRIES as _q8
from backend.qa.copilot.basics_onboarding import VIDEOS as _v8
from backend.qa.copilot.basics_onboarding import NEXT_QUESTIONS as _nq8
# Topics 2-6 removed — files kept for future use
# from backend.qa.copilot.basics_install import ANSWERS as _a2, SUGGESTIONS as _s2, QA_ENTRIES as _q2
# from backend.qa.copilot.basics_first_suggestion import ANSWERS as _a3, SUGGESTIONS as _s3, QA_ENTRIES as _q3
# from backend.qa.copilot.basics_shortcuts import ANSWERS as _a4, SUGGESTIONS as _s4, QA_ENTRIES as _q4
# from backend.qa.copilot.basics_inline_chat import ANSWERS as _a5, SUGGESTIONS as _s5, QA_ENTRIES as _q5
# from backend.qa.copilot.basics_wrap_up import ANSWERS as _a6, SUGGESTIONS as _s6, QA_ENTRIES as _q6
# from backend.qa.copilot.advanced_intro import ANSWERS as _a7, SUGGESTIONS as _s7, QA_ENTRIES as _q7

ANSWERS = {**_a8}
SUGGESTIONS = _s8
QA_ENTRIES = _q8
NEXT_QUESTIONS = {**_nq8}

# Video metadata — maps answer IDs to video info
VIDEOS = {**_v8}

MODULE_BANKS = {
    'copilot-basics': {
        'answers': {**_a8},
        'suggestions': _s8,
        'qa_entries': _q8,
        'videos': {**_v8},
        'next_questions': {**_nq8},
    },
    # 'advanced-copilot-patterns': { ... }  # re-enable with advanced module
}
