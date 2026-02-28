ANSWERS = {
    'smartsdk-fundamentals-intro-summary': (
        "SmartSDK is the core development framework for building AI-powered features "
        "within the AWM ecosystem. It provides a collection of pre-built components, "
        "hooks, and utilities that abstract away the complexity of integrating machine "
        "learning models, data pipelines, and intelligent interfaces into your "
        "applications.\n\n"
        "At its core, SmartSDK follows a component-based architecture where each piece "
        "of AI functionality is encapsulated in a reusable module. These modules handle "
        "everything from model inference and data preprocessing to response formatting "
        "and error handling. Developers interact with SmartSDK through a clean API layer "
        "that hides the underlying complexity of model management and resource allocation.\n\n"
        "This module introduces the fundamental concepts you need to understand before "
        "building with SmartSDK: the component lifecycle, data flow patterns, the "
        "configuration system, and the development environment setup."
    ),
    'smartsdk-fundamentals-intro-example': (
        "A practical example: you want to add a text summarization feature to your "
        "application. Without SmartSDK, you would need to select a model, set up an "
        "inference pipeline, handle tokenization, manage API rate limits, format the "
        "output, and build error recovery. With SmartSDK, you import the Summarizer "
        "component, configure it with your parameters, and call its process method. "
        "The component handles all the infrastructure concerns internally.\n\n"
        "SmartSDK also provides built-in observability, so you can monitor response "
        "times, token usage, and error rates through the standard dashboard without "
        "any additional instrumentation."
    ),
}

SUGGESTIONS = [
    {'text': 'What is SmartSDK?', 'keywords': ['smartsdk', 'what', 'introduction', 'about']},
    {'text': 'SmartSDK components', 'keywords': ['component', 'module', 'architecture']},
]

QA_ENTRIES = [
    {
        'keywords': ['what', 'smartsdk', 'fundamentals', 'introduction', 'about', 'overview', 'summary', 'summarize', 'video', 'recap'],
        'answer': 'smartsdk-fundamentals-intro-summary',
    },
    {
        'keywords': ['example', 'practical', 'demo', 'show', 'use case', 'component'],
        'answer': 'smartsdk-fundamentals-intro-example',
    },
]

NEXT_QUESTIONS = {
    'smartsdk-fundamentals-intro-summary': [
        'Show me a practical SmartSDK example',
        'How do I build features with APIs and hooks?',
        'Explore Stratos for deployment and orchestration',
    ],
    'smartsdk-fundamentals-intro-example': [
        'How do I chain SmartSDK modules into a pipeline?',
        'Introduce me to Stratos orchestration',
        'What are effective prompting techniques?',
    ],
}
