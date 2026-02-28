from backend.qa.general.greetings import ANSWERS as _a1, SUGGESTIONS as _s1, QA_ENTRIES as _q1
from backend.qa.general.greetings import NEXT_QUESTIONS as _nq1
from backend.qa.general.help import ANSWERS as _a2, SUGGESTIONS as _s2, QA_ENTRIES as _q2
from backend.qa.general.help import NEXT_QUESTIONS as _nq2

ANSWERS = {**_a1, **_a2}
SUGGESTIONS = _s1 + _s2
QA_ENTRIES = _q1 + _q2
NEXT_QUESTIONS = {**_nq1, **_nq2}
