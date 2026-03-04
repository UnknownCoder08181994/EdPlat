"""
Building with SmartSDK — Module Registry
"""

MODULE = {
    'title': 'Building with SmartSDK',
    'subtitle': 'Create real features using SmartSDK components. APIs, hooks, and state management patterns.',
    'category': 'smartsdk',
    'accent': 'pink',
    'difficulty': 'intermediate',
    'duration': '50 minutes',
    'ai_native': True,
    'author': {'name': 'Shane Anderson', 'role': 'AI/ML Data Operations Lead', 'initials': 'SA'},
    'description': 'Build a real AI-powered code review assistant using SmartSDK components. This hands-on module covers making authenticated API calls with retry logic, building custom React hooks for streaming AI responses, implementing state management with optimistic updates, composing components into a full feature, and testing patterns with mocked model calls. You will see the complete SmartSDK development lifecycle from API to production.',
    'learning_objectives': [
        'Make authenticated API calls with retry logic and request batching',
        'Build custom React hooks for AI model queries and streaming responses',
        "Implement state management with SmartSDK's built-in StateStore",
        'Compose SmartSDK components into a full code review feature',
        'Write unit, integration, and load tests for AI-powered features',
    ],
    'sections': [
        {'id': 'intro', 'title': 'Introduction', 'video': None, 'start': 0,
         'description': 'Project overview: building an AI-powered code review assistant, and the APIs, hooks, and patterns you will use.'},
        {'id': 'apis', 'title': 'Working with APIs', 'video': None, 'start': 0,
         'description': 'Authenticated requests to ModelRouter, streaming responses with async iterators, retry logic, and request batching.'},
        {'id': 'hooks', 'title': 'Custom Hooks', 'video': None, 'start': 0,
         'description': 'Building useModelQuery, useStreamResponse, useModelStatus, and a custom useCodeReview hook that composes them all.'},
        {'id': 'state', 'title': 'State Management', 'video': None, 'start': 0,
         'description': 'Using StateStore for conversation context, optimistic updates, cache invalidation, and conflict resolution.'},
        {'id': 'compose', 'title': 'Composing Components', 'video': None, 'start': 0,
         'description': 'Wiring hooks into React components, building a split-pane diff viewer, and rendering inline AI suggestions.'},
        {'id': 'testing', 'title': 'Testing Patterns', 'video': None, 'start': 0,
         'description': 'Mocking ModelRouter for unit tests, snapshot testing, integration tests with the SDK test server, and telemetry assertions.'},
        {'id': 'wrap-up', 'title': 'Wrap-Up & Next Steps', 'video': None, 'start': 0,
         'description': 'Review of the complete code review assistant and the full SmartSDK development lifecycle.'},
    ],
}
