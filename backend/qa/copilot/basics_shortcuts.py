"""
Copilot Basics — Keyboard Shortcuts (inactive, kept for future use)
"""

ANSWERS = {
    'copilot-basics-shortcuts-summary': (
        "Mastering keyboard shortcuts in the DevPod web IDE makes your "
        "lab workflow significantly faster. The most important shortcut "
        "is <strong>Ctrl+S</strong> to save, which also triggers the "
        "auto-format pipeline if a formatter is configured in the lab "
        "template.\n\n"
        "To open the integrated terminal, press <strong>Ctrl+`</strong>. "
        "Split the terminal into side-by-side panes with "
        "<strong>Ctrl+Shift+5</strong> so you can run the dev server in "
        "one pane and execute tests in another. Switch between panes "
        "using <strong>Alt+Left</strong> and <strong>Alt+Right</strong>.\n\n"
        "The command palette, opened with <strong>Ctrl+Shift+P</strong>, "
        "gives you access to every available action. Type a few characters "
        "to filter the list. Common commands include "
        "<strong>DevPod: Reset Environment</strong> to restore the lab "
        "to its starting state, and <strong>DevPod: Submit Lab</strong> "
        "to finalize your work for grading.\n\n"
        "File navigation shortcuts also save time. Use "
        "<strong>Ctrl+P</strong> to fuzzy-search files by name, "
        "<strong>Ctrl+G</strong> to jump to a specific line number, and "
        "<strong>Ctrl+Shift+F</strong> to search across the entire project."
    ),
    'copilot-basics-shortcuts-example': (
        "Here is a practical session using keyboard shortcuts. You are "
        "working on a lab exercise and need to edit a route handler, run "
        "tests, and check logs simultaneously. You press "
        "<strong>Ctrl+P</strong> and type <strong>health</strong> to open "
        "the health-check route file instantly.\n\n"
        "After making your edits, you press <strong>Ctrl+S</strong> to "
        "save and the formatter cleans up your indentation automatically. "
        "You press <strong>Ctrl+`</strong> to open the terminal and run "
        "<strong>npm test</strong>. Two tests fail, so you press "
        "<strong>Ctrl+Shift+5</strong> to split the terminal and tail "
        "the server logs in the second pane.\n\n"
        "The logs reveal a missing environment variable. You press "
        "<strong>Ctrl+Shift+P</strong>, type <strong>Reset</strong>, and "
        "select <strong>DevPod: Reset Environment</strong> to restore "
        "the default configuration. After the reset completes in a few "
        "seconds, you re-run the tests and all pass. The entire debug "
        "cycle takes under two minutes."
    ),
}

SUGGESTIONS = [
    {'text': 'Essential DevPod shortcuts',
     'keywords': ['shortcut', 'keyboard', 'keybind', 'hotkey']},
    {'text': 'How to use the command palette',
     'keywords': ['command', 'palette', 'search', 'action']},
]

QA_ENTRIES = [
    {
        'keywords': ['shortcut', 'keyboard', 'keybind', 'hotkey', 'keys',
                     'summary', 'summarize', 'video', 'recap'],
        'answer': 'copilot-basics-shortcuts-summary',
    },
    {
        'keywords': ['example', 'demo', 'show', 'workflow', 'practical'],
        'answer': 'copilot-basics-shortcuts-example',
    },
]
