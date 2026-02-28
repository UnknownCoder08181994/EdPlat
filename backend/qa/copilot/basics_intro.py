"""
Copilot Basics — Introduction (inactive, kept for future use)
"""

ANSWERS = {
    'copilot-basics-intro-summary': (
        "DevPod is a cloud-hosted virtual lab platform designed for "
        "hands-on technical training. It provisions isolated development "
        "environments on demand, giving each learner a dedicated workspace "
        "with pre-configured toolchains, editors, and runtime dependencies.\n\n"
        "Unlike local setups that vary between machines, DevPod ensures every "
        "participant starts from an identical baseline. The platform supports "
        "multiple language runtimes including Python, Node.js, Go, and Rust, "
        "each with curated extension packs and linting profiles.\n\n"
        "Environments spin up in under ninety seconds and persist across "
        "sessions. Your code, configuration, and terminal history are saved "
        "automatically so you can resume exactly where you left off. Resource "
        "tiers range from lightweight 2-vCPU instances for simple exercises to "
        "GPU-accelerated pods for machine learning workloads."
    ),
    'copilot-basics-intro-example': (
        "Consider a training scenario: your team needs to complete a "
        "microservices lab that requires Docker, a PostgreSQL database, and "
        "a Node.js API server. Without DevPod, each participant would spend "
        "the first hour installing dependencies and debugging version "
        "conflicts on their own machine.\n\n"
        "With DevPod, the instructor publishes a lab template that includes "
        "all dependencies pre-installed. Learners click a single button in "
        "the Cloud Portal, and within ninety seconds they have a running "
        "environment with Docker Compose already wired up. The database is "
        "seeded with sample data and the API server starts on port 3000.\n\n"
        "Another example is a Python data-science workshop. The template "
        "includes Jupyter, pandas, scikit-learn, and a curated dataset. "
        "Learners open their browser, connect to the DevPod, and start "
        "running notebook cells immediately with no setup friction."
    ),
}

SUGGESTIONS = [
    {'text': 'What is DevPod?',
     'keywords': ['devpod', 'what', 'introduction', 'about']},
    {'text': 'How does DevPod work?',
     'keywords': ['devpod', 'how', 'work', 'behind']},
    {'text': 'Show me a lab template example',
     'keywords': ['example', 'template', 'practical', 'demo']},
]

QA_ENTRIES = [
    {
        'keywords': ['what', 'devpod', 'introduction', 'about', 'overview',
                     'explain', 'summary', 'summarize', 'video', 'recap'],
        'answer': 'copilot-basics-intro-summary',
    },
    {
        'keywords': ['example', 'real', 'practical', 'use case', 'demo',
                     'scenario', 'show', 'template'],
        'answer': 'copilot-basics-intro-example',
    },
]

NEXT_QUESTIONS = {
    'copilot-basics-intro-summary': [
        'Show me a practical DevPod lab scenario',
        'How do I provision a new environment?',
        'What resource tiers are available?',
    ],
    'copilot-basics-intro-example': [
        'How do I create a lab template?',
        'What runtimes are pre-installed?',
        'Walk me through the provisioning steps',
    ],
}
