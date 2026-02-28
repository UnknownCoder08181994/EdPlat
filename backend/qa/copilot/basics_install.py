"""
Copilot Basics — Environment Setup (inactive, kept for future use)
"""

ANSWERS = {
    'copilot-basics-install-summary': (
        "Connecting to your DevPod environment requires a modern browser "
        "and valid portal credentials. Navigate to the Cloud Portal, locate "
        "your provisioned instance on the <strong>My Environments</strong> "
        "page, and click <strong>Connect</strong>.\n\n"
        "The web-based IDE loads inside your browser tab with a full "
        "terminal, file explorer, and editor panel. Extensions listed in "
        "the lab template are pre-installed automatically. If the template "
        "specifies a startup script, it runs on first connect and output "
        "appears in the integrated terminal.\n\n"
        "For local IDE access, install the DevPod CLI using the package "
        "manager for your operating system. Run "
        "<strong>devpod connect &lt;instance-id&gt;</strong> to open an "
        "SSH tunnel. Your local VS Code or JetBrains IDE can then attach "
        "to the remote environment via the Remote SSH extension."
    ),
    'copilot-basics-install-example': (
        "Here is a typical first-connect experience. You open the Cloud "
        "Portal, navigate to My Environments, and see your DevPod listed "
        "as <strong>Running</strong> with a green status indicator. You "
        "click Connect and the browser IDE loads in a new tab.\n\n"
        "The terminal at the bottom shows the startup script output: "
        "dependencies installing, database seeding, and the dev server "
        "starting on port 8080. Within thirty seconds a notification "
        "appears offering to open a preview of the running application.\n\n"
        "Alternatively, you open a local terminal, run "
        "<strong>devpod connect dp-abc123</strong>, and VS Code opens "
        "with the remote workspace attached. File edits are synchronized "
        "in real time and the integrated terminal runs commands directly "
        "on the cloud instance."
    ),
}

SUGGESTIONS = [
    {'text': 'How to connect to DevPod',
     'keywords': ['connect', 'setup', 'browser', 'ide']},
    {'text': 'DevPod CLI access',
     'keywords': ['cli', 'local', 'ssh', 'remote']},
]

QA_ENTRIES = [
    {
        'keywords': ['connect', 'setup', 'browser', 'ide', 'start',
                     'summary', 'summarize', 'video', 'recap'],
        'answer': 'copilot-basics-install-summary',
    },
    {
        'keywords': ['example', 'walkthrough', 'step', 'demo', 'show'],
        'answer': 'copilot-basics-install-example',
    },
]
