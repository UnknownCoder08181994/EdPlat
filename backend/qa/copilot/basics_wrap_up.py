"""
Copilot Basics — Wrap-Up (inactive, kept for future use)
"""

ANSWERS = {
    'copilot-basics-wrapup-summary': (
        "Congratulations on completing the DevPod Basics module. You have "
        "covered the essential skills needed to work effectively in a "
        "cloud-hosted lab environment. Here is a recap of each section.\n\n"
        "You learned that DevPod provisions isolated development environments "
        "on demand with pre-configured toolchains and dependencies. Connecting "
        "is as simple as clicking a button in the Cloud Portal or using the "
        "CLI to attach your local editor.\n\n"
        "You completed your first lab exercise using the edit-run-validate "
        "loop: modifying source files, running test suites, and interpreting "
        "results. You explored collaboration features including shared cursors, "
        "Broadcast mode, and session history.\n\n"
        "The most important takeaway is that DevPod removes environment "
        "friction so you can focus on learning. Always read the lab "
        "instructions before diving into code, use keyboard shortcuts to "
        "stay efficient, and leverage collaboration tools during group "
        "exercises. Next, explore the SmartSDK module to start building "
        "AI-powered features."
    ),
    'copilot-basics-wrapup-example': (
        "To consolidate your skills, here is a recommended workflow for "
        "future labs. Start by reading the lab overview in the instructions "
        "panel on the right side of the IDE. Identify the files you need "
        "to edit and the test commands you need to run.\n\n"
        "Open the relevant files using <strong>Ctrl+P</strong> for quick "
        "navigation. Make your changes incrementally, saving and running "
        "tests after each meaningful edit rather than waiting until the "
        "end. Use the split terminal to keep logs visible.\n\n"
        "If you get stuck, use the collaboration link to invite a peer "
        "or the AI Coach in the sidebar to ask questions about the current "
        "module topic. After completing all exercises, click "
        "<strong>DevPod: Submit Lab</strong> from the command palette to "
        "record your results.\n\n"
        "Next steps: proceed to the SmartSDK Fundamentals module to learn "
        "about component architecture, or jump to Prompt Engineering for "
        "techniques that improve AI-assisted code generation."
    ),
}

SUGGESTIONS = [
    {'text': 'Recap the DevPod basics module',
     'keywords': ['recap', 'summary', 'wrap', 'review', 'key']},
    {'text': 'What should I learn next?',
     'keywords': ['next', 'learn', 'continue', 'advance']},
]

QA_ENTRIES = [
    {
        'keywords': ['recap', 'summary', 'wrap', 'review', 'key',
                     'takeaway', 'summarize', 'video'],
        'answer': 'copilot-basics-wrapup-summary',
    },
    {
        'keywords': ['next', 'learn', 'continue', 'advance', 'recommend',
                     'workflow', 'example'],
        'answer': 'copilot-basics-wrapup-example',
    },
]
