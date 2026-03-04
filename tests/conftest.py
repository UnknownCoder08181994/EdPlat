import pytest
from app import app as flask_app
from backend import qa


@pytest.fixture()
def app():
    flask_app.config.update({'TESTING': True})
    yield flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


# ---- Sample QA data for tests ----

SAMPLE_ANSWERS = {
    'test-hello': 'Hello! How can I help you?',
    'test-copilot-install': 'To install Copilot, go to VS Code extensions.',
    'test-copilot-shortcut': 'Press Tab to accept a Copilot suggestion.',
    'test-followup-a': 'Answer for follow-up option A.',
    'test-followup-b': 'Answer for follow-up option B.',
}

SAMPLE_QA_ENTRIES = [
    {'keywords': ['hello', 'hi', 'hey'], 'answer': 'test-hello'},
    {'keywords': ['install', 'copilot', 'setup'], 'answer': 'test-copilot-install'},
    {'keywords': ['shortcut', 'keyboard', 'tab'], 'answer': 'test-copilot-shortcut'},
    {
        'keywords': ['help', 'options'],
        'followUp': {
            'question': 'What do you need help with?',
            'options': [
                {'label': 'Option A', 'keywords': ['option', 'first'], 'answerId': 'test-followup-a'},
                {'label': 'Option B', 'keywords': ['option', 'second'], 'answerId': 'test-followup-b'},
            ],
        },
    },
]

SAMPLE_SUGGESTIONS = [
    {'text': 'How do I install Copilot?', 'keywords': ['install', 'copilot']},
    {'text': 'What are the shortcuts?', 'keywords': ['shortcut', 'keyboard']},
    {'text': 'Hello', 'keywords': ['hello', 'hi']},
]

SAMPLE_VIDEOS = {
    'test-copilot-install': {'src': 'test-video.mp4', 'poster': 'test-poster.jpg'},
}

SAMPLE_NEXT_QUESTIONS = {
    'test-hello': [
        {'text': 'How do I install Copilot?', 'answerId': 'test-copilot-install'},
    ],
}

SAMPLE_MODULE_BANKS = {
    'test-module': {
        'answers': {
            'mod-intro': 'Welcome to the test module.',
            'mod-detail': 'Here is a module detail.',
        },
        'qa_entries': [
            {'keywords': ['intro', 'welcome', 'start'], 'answer': 'mod-intro'},
            {'keywords': ['detail', 'more'], 'answer': 'mod-detail'},
        ],
        'suggestions': [
            {'text': 'Module intro', 'keywords': ['intro', 'welcome']},
        ],
        'videos': {'mod-intro': {'src': 'mod-video.mp4'}},
        'next_questions': {},
    },
}

SAMPLE_ANSWER_MODULE_MAP = {
    'test-copilot-install': {'name': 'Copilot Basics', 'slug': 'copilot-basics'},
}


@pytest.fixture(autouse=True)
def inject_qa_data():
    orig = {
        'answer_bank': qa.answer_bank.copy(),
        'qa_bank': qa.qa_bank[:],
        'suggestion_bank': qa.suggestion_bank[:],
        'video_bank': qa.video_bank.copy(),
        'next_questions_bank': qa.next_questions_bank.copy(),
        'module_banks': qa.module_banks.copy(),
        'answer_module_map': qa.answer_module_map.copy(),
    }

    qa.answer_bank.update(SAMPLE_ANSWERS)
    qa.qa_bank.extend(SAMPLE_QA_ENTRIES)
    qa.suggestion_bank.extend(SAMPLE_SUGGESTIONS)
    qa.video_bank.update(SAMPLE_VIDEOS)
    qa.next_questions_bank.update(SAMPLE_NEXT_QUESTIONS)
    qa.module_banks.update(SAMPLE_MODULE_BANKS)
    qa.answer_module_map.update(SAMPLE_ANSWER_MODULE_MAP)

    yield

    qa.answer_bank.clear()
    qa.answer_bank.update(orig['answer_bank'])
    qa.qa_bank.clear()
    qa.qa_bank.extend(orig['qa_bank'])
    qa.suggestion_bank.clear()
    qa.suggestion_bank.extend(orig['suggestion_bank'])
    qa.video_bank.clear()
    qa.video_bank.update(orig['video_bank'])
    qa.next_questions_bank.clear()
    qa.next_questions_bank.update(orig['next_questions_bank'])
    qa.module_banks.clear()
    qa.module_banks.update(orig['module_banks'])
    qa.answer_module_map.clear()
    qa.answer_module_map.update(orig['answer_module_map'])
