ANSWERS = {
    'stratos-setup-intro-summary': (
        "Stratos is the deployment and orchestration platform within the AWM ecosystem. "
        "It handles everything from local development environment setup to production "
        "deployment pipelines. This module walks you through the initial installation, "
        "the setup wizard that configures your project structure, and the core concepts "
        "you need to understand before building workflows.\n\n"
        "Stratos uses a declarative configuration approach where you define your desired "
        "infrastructure state in configuration files, and the platform handles provisioning "
        "and management. The setup wizard generates the initial project scaffold including "
        "directory structure, configuration templates, and development server settings."
    ),
    'stratos-setup-intro-example': (
        "A practical walkthrough: you run the Stratos CLI installer, which detects your "
        "operating system and installs the appropriate binaries. Then you run 'stratos init' "
        "in your project directory, and the setup wizard asks a series of questions about "
        "your project type, preferred language, and deployment targets. It generates a "
        "complete project scaffold with all necessary configuration files."
    ),
}

SUGGESTIONS = [
    {'text': 'What is Stratos?', 'keywords': ['stratos', 'what', 'introduction', 'about']},
    {'text': 'How to set up Stratos', 'keywords': ['setup', 'install', 'configure', 'start']},
]

QA_ENTRIES = [
    {
        'keywords': ['stratos', 'what', 'setup', 'set up', 'install', 'introduction', 'summary', 'summarize', 'video', 'recap'],
        'answer': 'stratos-setup-intro-summary',
    },
    {
        'keywords': ['example', 'walkthrough', 'demo', 'show', 'practical', 'step'],
        'answer': 'stratos-setup-intro-example',
    },
]

NEXT_QUESTIONS = {
    'stratos-setup-intro-summary': [
        'Show me a practical installation walkthrough',
        'How does workflow automation work in Stratos?',
        'What is the prompt engineering module about?',
    ],
    'stratos-setup-intro-example': [
        'Explain Stratos workflow triggers and pipelines',
        'How do I write better prompts for Copilot?',
        'What is the SmartSDK development framework?',
    ],
}
