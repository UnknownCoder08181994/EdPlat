/* ============================================
   AWM V2 — Terminal Animation Engine (from V1)
   ============================================ */

document.addEventListener('DOMContentLoaded', () => {
    const terminalBody = document.getElementById('terminal-output');
    if (!terminalBody) return;

    const animator = new TerminalAnimator(terminalBody);

    // Wait for cinematic intro to finish before starting terminal
    let started = false;
    document.addEventListener('cinematic-done', () => {
        if (!started) {
            started = true;
            animator.start();
        }
    });

    // Safety fallback: start after 12s even if cinematic event never fires
    setTimeout(() => {
        if (!started) {
            started = true;
            animator.start();
        }
    }, 12000);
});

class TerminalAnimator {
    constructor(container) {
        this.container = container;
        this.currentDemo = 0;
        this.isRunning = false;

        this.demos = [
            { name: 'welcome.py', title: 'welcome.py', script: this.welcomeScript() },
            { name: 'terminal', title: 'terminal', script: this.journeyScript() },
            { name: 'init.py', title: 'init.py', script: this.initScript() },
        ];

        this.setupDots();
    }

    setupDots() {
        const dotsContainer = document.createElement('div');
        dotsContainer.className = 'terminal-demo-dots';
        this.demos.forEach((_, i) => {
            const dot = document.createElement('div');
            dot.className = 'demo-dot' + (i === 0 ? ' active' : '');
            dotsContainer.appendChild(dot);
        });
        this.container.closest('.terminal-window').appendChild(dotsContainer);

        this.toolLabel = document.createElement('div');
        this.toolLabel.className = 'terminal-tool-label';
        this.toolLabel.textContent = this.demos[0].name;
        this.container.closest('.terminal-body')?.prepend(this.toolLabel) ||
            this.container.prepend(this.toolLabel);
    }

    async start() {
        this.isRunning = true;
        while (this.isRunning) {
            const demo = this.demos[this.currentDemo];
            this.updateIndicators(this.currentDemo, demo);
            await this.runScript(demo.script);
            await this.sleep(2500);
            this.currentDemo = (this.currentDemo + 1) % this.demos.length;
        }
    }

    updateIndicators(index, demo) {
        const dots = this.container.closest('.terminal-window').querySelectorAll('.demo-dot');
        dots.forEach((d, i) => d.classList.toggle('active', i === index));

        const titleEl = this.container.closest('.terminal-window').querySelector('.terminal-title');
        if (titleEl) titleEl.textContent = demo.title;

        if (this.toolLabel) this.toolLabel.textContent = demo.name;
    }

    async runScript(script) {
        this.clear();
        for (const action of script) {
            if (!this.isRunning) return;
            await this.executeAction(action);
        }
    }

    async executeAction(action) {
        switch (action.type) {
            case 'line':
                this.addLine(action.html || this.escapeHtml(action.text || ''));
                await this.sleep(action.delay || 80);
                break;
            case 'type':
                await this.typeText(action.text, action.charDelay || 45, action.className || 't-plain');
                break;
            case 'ghost':
                await this.showGhost(action.text, action.delay || 600);
                break;
            case 'accept':
                this.acceptGhost();
                await this.sleep(action.delay || 300);
                break;
            case 'prompt':
                this.addPromptLine(action.text || '>>> ');
                await this.sleep(50);
                break;
            case 'output':
                this.addLine(action.html);
                await this.sleep(action.delay || 100);
                break;
            case 'pause':
                await this.sleep(action.duration || 1000);
                break;
            case 'newline':
                this.finishCurrentLine();
                await this.sleep(50);
                break;
        }
    }

    clear() {
        this.container.innerHTML = '';
        this.currentLineEl = null;
    }

    addLine(html) {
        const line = document.createElement('div');
        line.className = 'terminal-line';
        line.innerHTML = html;
        this.container.appendChild(line);
        this.scrollToBottom();
    }

    addPromptLine(prompt) {
        this.finishCurrentLine();
        const line = document.createElement('div');
        line.className = 'terminal-line terminal-cursor-line';
        line.innerHTML = `<span class="terminal-prompt">${this.escapeHtml(prompt)}</span><span class="line-content"></span><span class="terminal-cursor">&#9608;</span>`;
        this.container.appendChild(line);
        this.currentLineEl = line.querySelector('.line-content');
        this.scrollToBottom();
    }

    finishCurrentLine() {
        if (this.currentLineEl) {
            const cursorLine = this.currentLineEl.closest('.terminal-cursor-line');
            if (cursorLine) {
                const cursor = cursorLine.querySelector('.terminal-cursor');
                if (cursor) cursor.remove();
                cursorLine.classList.remove('terminal-cursor-line');
            }
        }
        this.currentLineEl = null;
    }

    async typeText(text, charDelay, className) {
        if (!this.currentLineEl) this.addPromptLine('>>> ');

        for (const char of text) {
            if (!this.isRunning) return;
            const span = document.createElement('span');
            span.className = className;
            span.textContent = char;
            this.currentLineEl.appendChild(span);
            this.scrollToBottom();
            await this.sleep(charDelay);
        }
    }

    async showGhost(text, delay) {
        if (!this.currentLineEl) return;
        await this.sleep(delay);

        const ghost = document.createElement('span');
        ghost.className = 't-ghost';
        ghost.textContent = text;
        this.currentLineEl.appendChild(ghost);
        this.scrollToBottom();
    }

    acceptGhost() {
        const ghosts = this.container.querySelectorAll('.t-ghost:not(.accepted)');
        ghosts.forEach(g => g.classList.add('accepted'));
    }

    scrollToBottom() {
        this.container.scrollTop = this.container.scrollHeight;
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    /* ---- Demo Scripts ---- */

    welcomeScript() {
        return [
            { type: 'line', html: '<span class="t-comment"># Welcome to AWM Institute</span>' },
            { type: 'pause', duration: 600 },
            { type: 'prompt', text: '>>> ' },
            { type: 'type', text: 'from awm import ', className: 't-plain', charDelay: 50 },
            { type: 'ghost', text: 'Student, Journey', delay: 400 },
            { type: 'pause', duration: 600 },
            { type: 'accept' },
            { type: 'newline' },
            { type: 'prompt', text: '>>> ' },
            { type: 'type', text: 'me = Student(', className: 't-plain', charDelay: 50 },
            { type: 'ghost', text: 'curious=True, ready=True)', delay: 400 },
            { type: 'pause', duration: 600 },
            { type: 'accept' },
            { type: 'newline' },
            { type: 'prompt', text: '>>> ' },
            { type: 'type', text: 'path = Journey(', className: 't-plain', charDelay: 50 },
            { type: 'ghost', text: 'track="ai_engineering")', delay: 400 },
            { type: 'pause', duration: 600 },
            { type: 'accept' },
            { type: 'newline' },
            { type: 'prompt', text: '>>> ' },
            { type: 'type', text: 'path.begin(me)', className: 't-plain', charDelay: 50 },
            { type: 'newline' },
            { type: 'pause', duration: 500 },
            { type: 'output', html: '<span class="t-info">\u25b6 Initializing your learning path...</span>' },
            { type: 'pause', duration: 400 },
            { type: 'output', html: '<span class="t-success">\u2713 12 modules loaded</span>' },
            { type: 'output', html: '<span class="t-success">\u2713 AI mentor assigned</span>' },
            { type: 'output', html: '<span class="t-success">\u2713 Your future starts now.</span>' },
            { type: 'pause', duration: 1500 },
        ];
    }

    journeyScript() {
        return [
            { type: 'line', html: '<span class="t-comment"># Build something extraordinary</span>' },
            { type: 'pause', duration: 600 },
            { type: 'prompt', text: '$ ' },
            { type: 'type', text: 'awm init --track fullstack', className: 't-plain', charDelay: 45 },
            { type: 'newline' },
            { type: 'pause', duration: 500 },
            { type: 'output', html: '<span class="t-info">\u2139 Setting up workspace...</span>' },
            { type: 'pause', duration: 400 },
            { type: 'output', html: '<span class="t-success">\u2713 Environment configured</span>' },
            { type: 'output', html: '<span class="t-success">\u2713 Tools ready: Python, React, Node</span>' },
            { type: 'pause', duration: 500 },
            { type: 'prompt', text: '$ ' },
            { type: 'type', text: 'awm launch --project my-first-app', className: 't-plain', charDelay: 45 },
            { type: 'newline' },
            { type: 'pause', duration: 500 },
            { type: 'output', html: '<span class="t-info">\u25b6 Compiling modules...</span>' },
            { type: 'pause', duration: 400 },
            { type: 'output', html: '<span class="t-info">\u25b6 Deploying to sandbox...</span>' },
            { type: 'pause', duration: 500 },
            { type: 'output', html: '<span class="t-success">\u2713 Live at https://you.awm.dev</span>' },
            { type: 'output', html: '<span class="t-success">\u2713 You just shipped your first project.</span>' },
            { type: 'pause', duration: 1500 },
        ];
    }

    initScript() {
        return [
            { type: 'line', html: '<span class="t-comment"># Your potential, unlocked</span>' },
            { type: 'pause', duration: 600 },
            { type: 'prompt', text: '>>> ' },
            { type: 'type', text: 'from awm.core import ', className: 't-plain', charDelay: 45 },
            { type: 'ghost', text: 'Skills, Mentor', delay: 400 },
            { type: 'pause', duration: 600 },
            { type: 'accept' },
            { type: 'newline' },
            { type: 'prompt', text: '>>> ' },
            { type: 'type', text: 'skills = Skills(', className: 't-plain', charDelay: 45 },
            { type: 'ghost', text: '["ml", "web", "cloud"])', delay: 400 },
            { type: 'pause', duration: 600 },
            { type: 'accept' },
            { type: 'newline' },
            { type: 'prompt', text: '>>> ' },
            { type: 'type', text: 'mentor = Mentor(', className: 't-plain', charDelay: 45 },
            { type: 'ghost', text: 'mode="hands_on")', delay: 400 },
            { type: 'pause', duration: 600 },
            { type: 'accept' },
            { type: 'newline' },
            { type: 'prompt', text: '>>> ' },
            { type: 'type', text: 'mentor.guide(skills)', className: 't-plain', charDelay: 45 },
            { type: 'newline' },
            { type: 'pause', duration: 500 },
            { type: 'output', html: '<span class="t-info">\u25b6 Mapping your skill graph...</span>' },
            { type: 'pause', duration: 400 },
            { type: 'output', html: '<span class="t-success">\u2713 3 learning paths generated</span>' },
            { type: 'output', html: '<span class="t-success">\u2713 Ready when you are.</span>' },
            { type: 'pause', duration: 1500 },
        ];
    }
}
