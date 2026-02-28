ANSWERS = {
    'prompting-engineering-intro-summary': (
        "Prompt Engineering is the practice of crafting effective instructions for AI "
        "code generation tools like GitHub Copilot. The quality of the code you receive "
        "is directly proportional to the quality of the context and instructions you "
        "provide. This module teaches you systematic techniques for writing prompts that "
        "produce cleaner, more accurate, and more maintainable code.\n\n"
        "You will learn about providing context through comments and function signatures, "
        "setting constraints to narrow the solution space, iterating on prompts to refine "
        "output, recognizing common patterns that work well, and avoiding anti-patterns "
        "that lead to poor suggestions."
    ),
    'prompting-engineering-intro-example': (
        "A practical example: instead of typing 'def process(data)' and hoping for the "
        "best, you write a detailed comment: '# Process a list of user records: validate "
        "email format, normalize phone numbers to E.164, remove duplicates by email, "
        "and return sorted by last name. Raise ValueError for empty input.' This level "
        "of specificity produces a complete, accurate implementation on the first try.\n\n"
        "Compare this to a vague prompt like '# process data' which might generate code "
        "that handles a completely different data structure or applies unwanted transformations."
    ),
}

SUGGESTIONS = [
    {'text': 'What is prompt engineering?', 'keywords': ['prompt', 'engineering', 'what', 'about']},
    {'text': 'Prompting best practices', 'keywords': ['best', 'practice', 'tips', 'improve']},
]

QA_ENTRIES = [
    {
        'keywords': ['prompt', 'engineering', 'what', 'about', 'overview', 'summary', 'summarize', 'video', 'recap'],
        'answer': 'prompting-engineering-intro-summary',
    },
    {
        'keywords': ['example', 'practical', 'demo', 'show', 'compare', 'good', 'bad'],
        'answer': 'prompting-engineering-intro-example',
    },
]

NEXT_QUESTIONS = {
    'prompting-engineering-intro-summary': [
        'Show me a good vs bad prompt comparison',
        'Tell me about the full-stack capstone module',
        'How does the SmartSDK component system work?',
    ],
    'prompting-engineering-intro-example': [
        'What does the integration capstone project cover?',
        'Explain SmartSDK fundamentals and architecture',
        'How do I start the GitHub Copilot onboarding?',
    ],
}
