ANSWERS = {
    'smartsdk-building-intro-summary': (
        "Building with SmartSDK takes the foundational knowledge from the Fundamentals "
        "module and applies it to real feature development. This module focuses on "
        "practical patterns for working with APIs, creating custom hooks, managing "
        "application state, and composing components into complex features.\n\n"
        "You will learn how to chain SmartSDK components together to create multi-step "
        "AI pipelines, how to handle asynchronous operations and streaming responses, "
        "and how to test your AI-powered features effectively."
    ),
    'smartsdk-building-intro-example': (
        "A real-world example: building a document analysis feature that extracts key "
        "entities, generates a summary, and provides interactive Q&A, all using "
        "SmartSDK's component composition pattern. Each step in the pipeline is a "
        "separate component that can be tested and configured independently."
    ),
}

SUGGESTIONS = [
    {'text': 'Building with SmartSDK overview', 'keywords': ['building', 'overview', 'what']},
]

QA_ENTRIES = [
    {
        'keywords': ['building', 'build', 'develop', 'create', 'feature', 'api', 'hooks', 'overview', 'summary', 'summarize', 'video', 'recap'],
        'answer': 'smartsdk-building-intro-summary',
    },
    {
        'keywords': ['example', 'practical', 'demo', 'show', 'pipeline', 'composition'],
        'answer': 'smartsdk-building-intro-example',
    },
]

NEXT_QUESTIONS = {
    'smartsdk-building-intro-summary': [
        'Show me the composition pattern example',
        'How does Stratos handle deployment pipelines?',
        'Tips for crafting effective AI prompts',
    ],
    'smartsdk-building-intro-example': [
        'Explain how Stratos orchestration works',
        'What makes a good prompt for code generation?',
        'Describe the capstone integration project',
    ],
}
