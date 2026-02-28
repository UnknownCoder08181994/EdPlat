"""
Copilot Basics — First Lab Exercise (inactive, kept for future use)
"""

ANSWERS = {
    'copilot-basics-suggestion-summary': (
        "Your first lab exercise in DevPod walks you through the core "
        "workflow of editing, running, and validating code inside a cloud "
        "environment. The exercise begins with a pre-loaded project that "
        "contains a partially implemented REST API.\n\n"
        "Open the file explorer on the left and navigate to "
        "<strong>src/routes/health.js</strong>. The file contains a stub "
        "endpoint that returns a placeholder response. Your task is to "
        "replace the stub with a proper health-check handler that returns "
        "the server uptime, memory usage, and current timestamp.\n\n"
        "After editing, open the integrated terminal and run "
        "<strong>npm test</strong>. The test suite validates your handler "
        "against expected response shapes. Green checkmarks confirm each "
        "assertion passes. If a test fails, the diff output shows exactly "
        "which field is missing or malformed.\n\n"
        "This edit-run-validate loop is the foundation for every lab in "
        "the curriculum. Mastering it here ensures you can focus on the "
        "actual learning objectives in later modules rather than tooling."
    ),
    'copilot-basics-suggestion-example': (
        "Here is a concrete walkthrough. You open "
        "<strong>src/routes/health.js</strong> and see the stub function "
        "returning an empty object. You replace it with three lines: "
        "one reading <strong>process.uptime()</strong>, one reading "
        "<strong>process.memoryUsage().heapUsed</strong>, and one calling "
        "<strong>new Date().toISOString()</strong>.\n\n"
        "You save the file, switch to the terminal, and type "
        "<strong>npm test</strong>. The runner executes four assertions: "
        "status code 200, presence of the uptime field, presence of the "
        "memory field, and a valid ISO timestamp. All four pass on the "
        "first attempt.\n\n"
        "Next you experiment by adding a <strong>version</strong> field "
        "pulled from <strong>package.json</strong>. The test suite does "
        "not require it, but the bonus assertion at the end awards extra "
        "credit when it detects the field. This teaches the habit of "
        "reading test expectations before coding."
    ),
}

SUGGESTIONS = [
    {'text': 'How does the first lab work?',
     'keywords': ['first', 'lab', 'exercise', 'health', 'endpoint']},
    {'text': 'Tips for passing lab tests',
     'keywords': ['tips', 'pass', 'test', 'validate']},
]

QA_ENTRIES = [
    {
        'keywords': ['first', 'lab', 'exercise', 'health', 'endpoint',
                     'summary', 'summarize', 'video', 'recap'],
        'answer': 'copilot-basics-suggestion-summary',
    },
    {
        'keywords': ['example', 'demo', 'show', 'walkthrough', 'practical'],
        'answer': 'copilot-basics-suggestion-example',
    },
]
