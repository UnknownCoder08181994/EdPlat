ANSWERS = {
    'general-hello': (
        "Hello! I'm the AWMIT Agent. How can I help you today?"
    ),
    'general-thanks': "You're welcome! Let me know if there's anything else.",
}

SUGGESTIONS = [
    {'text': 'Say hello', 'keywords': ['hello', 'hi', 'hey']},
    {'text': 'Thanks', 'keywords': ['thanks', 'thank you']},
]

QA_ENTRIES = [
    {'keywords': ['hello', 'hi', 'hey', 'howdy', 'greetings', 'sup', 'yo'], 'answer': 'general-hello'},
    {'keywords': ['thanks', 'thank you', 'thx', 'ty', 'appreciate'], 'answer': 'general-thanks'},
]

NEXT_QUESTIONS = {
    'general-hello': [
        'What can you help me with?',
        'How does the Copilot access request work?',
        'Show me the full course catalog',
    ],
    'general-thanks': [
        'Tell me about prompt engineering',
        'Introduce me to GitHub Copilot',
        'Which learning topics are covered?',
    ],
}
