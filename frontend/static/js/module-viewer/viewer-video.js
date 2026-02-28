/* Video control and section completion methods for ModuleCoach */

ModuleCoach.prototype.playVideo = function() {
    var self = this;
    this._userPaused = false;
    this._autoRetried = false;
    this._playGuard = true;
    setTimeout(function() { self._playGuard = false; }, 300);
    this.videoOverlay.classList.add('hidden');
    this.videoEl.play().catch(function() {
        if (self._autoRetried) return;
        self._playGuard = false;
        self.videoOverlay.classList.remove('hidden');
    });
};

ModuleCoach.prototype.togglePlayPause = function() {
    if (this._playGuard) return;
    if (this.videoEl.paused) {
        this._userPaused = false;
        this.videoEl.play().catch(function() {});
    } else {
        this._userPaused = true;
        this.videoEl.pause();
    }
};

ModuleCoach.prototype.updateOverlayIcon = function() {
    const svg = this.playBtn.querySelector('svg');
    if (!svg) return;
    if (this.videoEl.paused) {
        svg.innerHTML = '<polygon points="7 3 21 12 7 21 7 3"/>';
    } else {
        svg.innerHTML = '<rect x="5" y="3" width="5" height="18"/><rect x="14" y="3" width="5" height="18"/>';
    }
};



ModuleCoach.prototype.toggleMute = function() {
    this.videoEl.muted = !this.videoEl.muted;
    this.updateMuteIcon();
};

ModuleCoach.prototype.updateMuteIcon = function() {
    const icon = this.muteBtn.querySelector('.mute-icon');
    if (icon) {
        if (this.videoEl.muted) {
            icon.innerHTML = '<path d="M11 5L6 9H2v6h4l5 4V5z"/><line x1="23" y1="9" x2="17" y2="15"/><line x1="17" y1="9" x2="23" y2="15"/>';
        } else {
            icon.innerHTML = '<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/>';
        }
    }
};

ModuleCoach.prototype.toggleFullscreen = function() {
    const wrapper = document.getElementById('viewer-video-wrapper');
    if (document.fullscreenElement) {
        document.exitFullscreen();
    } else {
        wrapper.requestFullscreen().catch(() => {});
    }
};

ModuleCoach.prototype.markCurrentSectionComplete = function() {
    const idx = this.currentSectionIndex;
    if (this.completedSections.has(idx)) return;

    this.completedSections.add(idx);

    // Add completed class to sidebar section item
    const items = this.sectionsListEl.querySelectorAll('.viewer-section-item');
    if (items[idx]) {
        items[idx].classList.add('completed');
    }

    // AWMIT Coach section completion message
    const section = this.currentSection;
    const summary = this.getSectionSummary(section, idx);

    // Check if there's a next section
    const nextIdx = idx + 1;
    let nextPrompt = '';
    if (nextIdx < this.sections.length) {
        const next = this.sections[nextIdx];
        nextPrompt = '\n\nUp next: <strong>' + next.title + '</strong>. Click it in the sidebar to continue.';
    } else {
        nextPrompt = '\n\nThat\'s ' + this.sections.length + ' topics of hands-on, technical knowledge.\n\nHead back to <strong>Modules</strong> and keep stacking. Every module you complete builds on the last.';
    }

    this.addMessage('agent', '<strong>' + section.title + '</strong> — Complete!\n\n' + summary + nextPrompt);
};

ModuleCoach.prototype.getSectionSummary = function(section, index) {
    const key = this.slug + '::' + section.id;
    const summaries = {
        // COPILOT BASICS
        'copilot-basics::intro':
            'Covered what GitHub Copilot is — an AI pair-programming tool powered by OpenAI Codex that runs directly inside VS Code. You learned how it predicts entire lines and blocks of code from context and comments, and why it\'s reshaping how developers write software.',
        'copilot-basics::install':
            'Walked through installing the GitHub Copilot extension from the VS Code Marketplace, authenticating with your GitHub account, verifying your subscription status, and configuring the extension settings including language-specific enable/disable toggles.',
        'copilot-basics::first-suggestion':
            'Wrote your first function with Copilot generating the implementation from a comment. Covered accepting suggestions with Tab, cycling through alternatives with Alt+] and Alt+[, and rejecting suggestions with Escape. You saw how Copilot reads function signatures and docstrings to infer intent.',
        'copilot-basics::shortcuts':
            'Learned the essential keyboard shortcuts: Tab to accept, Esc to dismiss, Alt+\\ to manually trigger a suggestion, Ctrl+Enter to open the Copilot completions panel with 10 alternative solutions, and word-by-word acceptance with Ctrl+Right Arrow.',
        'copilot-basics::inline-chat':
            'Used Copilot\'s inline chat (Ctrl+I) to have a conversation directly in your editor — asking it to explain code, refactor functions, generate tests, and fix bugs without leaving your current file. Covered how to scope the conversation to selected code vs. the full file.',
        'copilot-basics::wrap-up':
            'Recap of the full workflow: install, authenticate, write comments to drive suggestions, use keyboard shortcuts for speed, and leverage inline chat for complex tasks. You\'re set up to use Copilot as a daily productivity tool.',

        // BUILDING WITH SMARTSDK
        'building-smartsdk::intro':
            'Set the stage for building real features with SmartSDK — reviewing the architecture from fundamentals, introducing the project you\'ll build (an AI-powered code review assistant), and outlining the APIs, hooks, and state patterns you\'ll use.',
        'building-smartsdk::apis':
            'Worked with SmartSDK\'s API layer: making authenticated requests to the ModelRouter, handling streaming responses with async iterators, implementing retry logic with exponential backoff, and using the built-in request batching for bulk operations.',
        'building-smartsdk::hooks':
            'Built custom React hooks with SmartSDK: useModelQuery for single requests with caching, useStreamResponse for real-time streaming output, useModelStatus for health checks, and a custom useCodeReview hook that composes the others into a clean interface for the code review feature.',
        'building-smartsdk::state':
            'Implemented state management patterns: using SmartSDK\'s built-in StateStore for persisting conversation context across requests, optimistic updates for faster UI feedback, cache invalidation strategies, and conflict resolution when multiple requests modify the same state.',
        'building-smartsdk::compose':
            'Composed SmartSDK components into a full feature: wiring the useCodeReview hook into React components, building a split-pane diff viewer, rendering AI suggestions inline with syntax highlighting, and handling user accept/reject actions that feed back into the model.',
        'building-smartsdk::testing':
            'Covered testing patterns for SmartSDK features: mocking the ModelRouter for unit tests, snapshot testing AI-rendered outputs, integration tests with the SmartSDK test server, load testing with concurrent model calls, and using the built-in telemetry assertions.',
        'building-smartsdk::wrap-up':
            'Reviewed the complete code review assistant you built: API calls, custom hooks, state management, composed UI, and test coverage. You\'ve seen the full SmartSDK development lifecycle from API to production-ready feature.',

        // ADVANCED COPILOT PATTERNS
        'advanced-copilot-patterns::intro':
            'Set the context for advanced Copilot usage — moving beyond basic suggestions to multi-file generation, test-driven development with AI, and leveraging workspace-level context for architecture-aware completions.',
        'advanced-copilot-patterns::multi-file':
            'Generated entire feature scaffolds across multiple files: using Copilot Chat with workspace context to create a model, controller, service, and test file simultaneously. Covered the /new command for project scaffolding and how to guide generation with a clear folder structure.',
        'advanced-copilot-patterns::tdd':
            'Practiced test-driven prompting: writing the test first, then asking Copilot to generate the implementation that passes it. Covered how Copilot reads test assertions to infer behavior, generating edge case tests from implementation code, and the red-green-refactor cycle with AI.',
        'advanced-copilot-patterns::arch-aware':
            'Leveraged workspace context for architecture-aware completions: how Copilot reads neighboring files, imports, and type definitions to generate code that follows your existing patterns. Covered .github/copilot-instructions.md for project-level AI configuration.',
        'advanced-copilot-patterns::refactor':
            'Used Copilot for large-scale refactoring: renaming across files, extracting functions and classes, converting callback-based code to async/await, migrating from one library to another, and using inline chat to explain refactoring decisions.',
        'advanced-copilot-patterns::debugging':
            'Leveraged Copilot for debugging: /fix command to auto-fix errors, pasting stack traces into chat for root cause analysis, using /explain to understand unfamiliar code, generating logging statements at key points, and stepping through logic with AI-assisted analysis.',
        'advanced-copilot-patterns::custom-inst':
            'Configured custom instructions in .github/copilot-instructions.md: setting coding standards, preferred libraries, naming conventions, documentation style, and architectural patterns that Copilot should follow for your entire project.',
        'advanced-copilot-patterns::workspace':
            'Mastered workspace context management: how to use @workspace to reference your entire project, the #file and #selection references for scoping, managing context window limits, and strategies for helping Copilot understand large monorepos.',
        'advanced-copilot-patterns::collab':
            'Set up Copilot for team collaboration: shared custom instructions, team-level settings via organization policies, code review workflows with Copilot-generated PR descriptions, and knowledge sharing through Copilot-assisted documentation.',
        'advanced-copilot-patterns::wrap-up':
            'Full review of advanced Copilot patterns: multi-file generation, TDD with AI, architecture-aware completions, large-scale refactoring, debugging workflows, custom instructions, workspace context, and team collaboration. You\'re operating at an advanced level.',

    };

    return summaries[key] || this.getFallbackSummary(section, index);
};

ModuleCoach.prototype.getFallbackSummary = function(section, index) {
    const title = section.title.toLowerCase();
    if (title.includes('intro')) return 'Covered the foundations — what this section is about, the key concepts, and what you\'ll build by the end.';
    if (title.includes('wrap') || title.includes('next')) return 'Recapped everything covered and outlined clear next steps on your learning path.';
    return 'Section locked in — another key piece of the puzzle added to your toolkit.';
};

