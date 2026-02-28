ANSWERS = {
    'fullstack-integration-intro-summary': (
        "Full-Stack AI Integration is the capstone module that brings together everything "
        "you have learned across the AWM ecosystem. You will build a complete production-ready "
        "application that combines GitHub Copilot for accelerated development, SmartSDK for "
        "AI-powered features, and Stratos for deployment and orchestration.\n\n"
        "This module follows a project-based approach where each section adds a new layer "
        "to the application. By the end, you will have a working system with a backend API, "
        "SmartSDK integration layer, frontend components, CI/CD pipeline, monitoring, and "
        "production deployment, all built using the tools and techniques from previous modules."
    ),
    'fullstack-integration-intro-example': (
        "The project you will build is an intelligent document processing platform. Users "
        "upload documents through a web interface, the SmartSDK layer extracts key information "
        "and generates summaries, the backend stores and indexes the results, and a Stratos "
        "pipeline handles the deployment and scaling. Copilot assists you throughout the "
        "entire development process, from scaffolding the initial project to writing tests."
    ),
}

SUGGESTIONS = [
    {'text': 'What is Full-Stack AI Integration?', 'keywords': ['fullstack', 'what', 'about', 'integration']},
    {'text': 'What will I build?', 'keywords': ['build', 'project', 'create', 'make']},
]

QA_ENTRIES = [
    {
        'keywords': ['fullstack', 'what', 'about', 'integration', 'overview', 'build', 'summary', 'summarize', 'video', 'recap'],
        'answer': 'fullstack-integration-intro-summary',
    },
    {
        'keywords': ['build', 'project', 'example', 'create', 'demo', 'practical'],
        'answer': 'fullstack-integration-intro-example',
    },
]

NEXT_QUESTIONS = {
    'fullstack-integration-intro-summary': [
        'Show me the capstone project example',
        'Introduce me to the SmartSDK framework',
        'How do I install and set up Stratos?',
    ],
    'fullstack-integration-intro-example': [
        'How do SmartSDK components fit together?',
        'Guide me through configuring Stratos',
        'What are the key prompt engineering principles?',
    ],
}
