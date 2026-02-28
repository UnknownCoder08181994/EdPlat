ANSWERS = {
    'stratos-workflows-intro-summary': (
        "Stratos Workflows allow you to automate multi-step processes within your "
        "development and deployment pipeline. A workflow is a sequence of tasks triggered "
        "by events such as code pushes, pull request merges, scheduled timers, or manual "
        "triggers. Each task in the workflow can execute shell commands, call APIs, run "
        "tests, build artifacts, or deploy to target environments.\n\n"
        "This module covers the workflow definition syntax, event trigger configuration, "
        "pipeline composition, deployment hooks, and monitoring. You will learn how to "
        "create workflows that are reliable, observable, and maintainable."
    ),
    'stratos-workflows-intro-example': (
        "A common workflow example: on every push to the main branch, Stratos triggers "
        "a pipeline that runs unit tests, builds a Docker image, pushes it to a registry, "
        "deploys to staging, runs integration tests against staging, and if all checks "
        "pass, promotes the release to production. Each step has retry logic, timeout "
        "limits, and notification hooks for Slack or email."
    ),
}

SUGGESTIONS = [
    {'text': 'What are Stratos workflows?', 'keywords': ['workflow', 'what', 'about', 'stratos']},
    {'text': 'Workflow triggers', 'keywords': ['trigger', 'event', 'automate']},
]

QA_ENTRIES = [
    {
        'keywords': ['workflow', 'workflows', 'what', 'about', 'trigger', 'automate', 'summary', 'summarize', 'video', 'recap'],
        'answer': 'stratos-workflows-intro-summary',
    },
    {
        'keywords': ['example', 'demo', 'show', 'pipeline', 'practical', 'deploy', 'workflow'],
        'answer': 'stratos-workflows-intro-example',
    },
]

NEXT_QUESTIONS = {
    'stratos-workflows-intro-summary': [
        'Show me a CI/CD workflow pipeline example',
        'How do I engineer prompts for better code output?',
        'What is the full-stack integration capstone?',
    ],
    'stratos-workflows-intro-example': [
        'How do I configure the Stratos environment?',
        'Explain prompt engineering best practices',
        'What does the full-stack project involve?',
    ],
}
