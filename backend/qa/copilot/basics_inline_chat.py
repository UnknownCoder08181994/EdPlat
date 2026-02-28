"""
Copilot Basics — Collaboration Features (inactive, kept for future use)
"""

ANSWERS = {
    'copilot-basics-chat-summary': (
        "DevPod includes built-in collaboration features that let multiple "
        "users work inside the same environment simultaneously. The "
        "<strong>Share</strong> button in the top toolbar generates a "
        "session link that teammates can open in their browser.\n\n"
        "Each collaborator gets their own cursor and terminal instance. "
        "Edits appear in real time with color-coded highlights showing "
        "who changed what. A presence sidebar lists active participants "
        "and their current file location, similar to collaborative "
        "document editors.\n\n"
        "For instructor-led sessions, the <strong>Broadcast</strong> "
        "mode lets the host push their terminal and editor view to all "
        "connected participants. Learners see every keystroke and command "
        "as it happens, then switch back to independent mode to practice "
        "on their own.\n\n"
        "Collaboration history is logged automatically. The environment "
        "timeline shows a chronological list of edits, terminal commands, "
        "and file saves so the instructor can review each participant's "
        "progress after the session."
    ),
    'copilot-basics-chat-example': (
        "Here is a practical scenario. An instructor starts a pair-programming "
        "exercise and clicks <strong>Share</strong> to generate a link. "
        "Two students join the session and each receives a colored cursor. "
        "The instructor opens <strong>src/app.js</strong> and types a "
        "comment describing the task.\n\n"
        "Student A navigates to <strong>src/utils.js</strong> and begins "
        "writing a helper function. Student B opens the test file and adds "
        "assertions. Both edits appear live in the file explorer with "
        "modification indicators next to the changed files.\n\n"
        "When Student A finishes the helper, the instructor switches to "
        "Broadcast mode and walks through a code review. Everyone sees "
        "the same highlighted diff. After the review, the instructor "
        "switches back to independent mode and the students continue "
        "implementing the remaining features."
    ),
}

SUGGESTIONS = [
    {'text': 'How does collaboration work in DevPod?',
     'keywords': ['collaboration', 'share', 'pair', 'session']},
    {'text': 'Broadcast mode for instructors',
     'keywords': ['broadcast', 'instructor', 'demo', 'live']},
]

QA_ENTRIES = [
    {
        'keywords': ['collaboration', 'share', 'pair', 'session', 'live',
                     'summary', 'summarize', 'video', 'recap'],
        'answer': 'copilot-basics-chat-summary',
    },
    {
        'keywords': ['example', 'demo', 'show', 'practical', 'scenario',
                     'broadcast'],
        'answer': 'copilot-basics-chat-example',
    },
]
