ANSWERS = {
    'general-help': (
        "I'm the AWMIT Agent. I handle basic greetings and can point you "
        "in the right direction. Just say hi or ask what I can do!"
    ),
}

SUGGESTIONS = [
    {'text': 'What can the AWMIT Agent do?', 'keywords': ['what', 'can', 'do', 'help', 'awmit', 'agent']},
]

QA_ENTRIES = [
    {'keywords': ['help', 'what can you do', 'what do you do', 'how do you work', 'capabilities', 'awmit', 'agent'], 'answer': 'general-help'},
]

NEXT_QUESTIONS = {
    'general-help': [
        'Walk me through getting Copilot access',
        'Give me an overview of SmartSDK',
        'Explain the Stratos deployment platform',
    ],
}
