"""
Advanced DevPod Patterns (inactive, kept for future use)
"""

ANSWERS = {
    'copilot-advanced-intro-summary': (
        "Advanced DevPod Patterns takes your cloud lab skills to the next "
        "level. This module covers techniques beyond basic provisioning, "
        "including custom template authoring where you define reusable "
        "environment blueprints for your team, resource scaling where "
        "you adjust CPU and memory mid-session, and multi-service "
        "orchestration using Docker Compose within your pod.\n\n"
        "You will learn how to create persistent storage volumes, configure "
        "environment variables securely using the secrets manager, and set "
        "up automated health checks that restart crashed services. These "
        "techniques are designed for developers who are comfortable with "
        "the basics and want to build production-like lab environments."
    ),
    'copilot-advanced-intro-example': (
        "A practical example of an advanced pattern: you need to create a "
        "lab template for a microservices workshop. Instead of configuring "
        "each service manually, you write a DevPod template manifest that "
        "specifies three containers, a shared network, and a seeded "
        "database. Learners provision the entire stack with one click.\n\n"
        "Another example is resource scaling. Midway through a machine "
        "learning exercise the model training requires more memory. You "
        "open the resource panel and upgrade from the Standard tier to "
        "the GPU-accelerated tier without losing your workspace state. "
        "Training resumes immediately on the upgraded hardware."
    ),
}

SUGGESTIONS = [
    {'text': 'What are advanced DevPod patterns?',
     'keywords': ['advanced', 'pattern', 'technique', 'what']},
    {'text': 'Custom template authoring',
     'keywords': ['custom', 'template', 'author', 'blueprint']},
]

QA_ENTRIES = [
    {
        'keywords': ['advanced', 'pattern', 'technique', 'overview', 'what',
                     'summary', 'summarize', 'video', 'recap'],
        'answer': 'copilot-advanced-intro-summary',
    },
    {
        'keywords': ['example', 'demo', 'show', 'practical', 'custom',
                     'template', 'scaling'],
        'answer': 'copilot-advanced-intro-example',
    },
]
