/* ============================================
   AWM V2 — Agent Chat (UI-only thin client)
   ============================================ */

class AgentChat {
    constructor() {
        this.messagesEl = document.getElementById('chat-messages');
        this.inputEl = document.getElementById('chat-input');
        this.sendBtn = document.getElementById('chat-send');
        this.welcomeEl = document.getElementById('chat-welcome');
        this.autocompleteEl = document.getElementById('chat-autocomplete');

        this.pendingFollowUp = null;
        this.isTyping = false;
        this.autocompleteIndex = -1;
        this.autocompleteItems = [];
        this.cursorEl = document.getElementById('chat-input-cursor');

        this.bindEvents();
        this.initInputCursor();
        this.inputEl.focus();
    }

    /* ---- Event Binding ---- */
    bindEvents() {
        this.sendBtn.addEventListener('click', () => this.handleSend());

        this.inputEl.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                // If autocomplete is open and an item is highlighted, select it
                if (this.autocompleteIndex >= 0 && this.autocompleteItems.length > 0) {
                    e.preventDefault();
                    this.selectAutocompleteItem(this.autocompleteIndex);
                    return;
                }
                e.preventDefault();
                this.handleSend();
            } else if (e.key === 'ArrowDown') {
                e.preventDefault();
                this.navigateAutocomplete(1);
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                this.navigateAutocomplete(-1);
            } else if (e.key === 'Escape') {
                this.hideAutocomplete();
            }
        });

        this.inputEl.addEventListener('input', () => {
            this.updateAutocomplete();
        });

        document.addEventListener('click', (e) => {
            if (!this.autocompleteEl.contains(e.target) && e.target !== this.inputEl) {
                this.hideAutocomplete();
            }
        });
    }

    /* ---- Custom Input Cursor ---- */
    initInputCursor() {
        // Create a hidden measurer span
        this.measurer = document.createElement('span');
        this.measurer.style.cssText = 'position:absolute;visibility:hidden;white-space:pre;pointer-events:none;';
        document.body.appendChild(this.measurer);

        const sync = () => this.syncCursor();
        this.inputEl.addEventListener('input', sync);
        this.inputEl.addEventListener('click', sync);
        this.inputEl.addEventListener('keyup', sync);
        this.inputEl.addEventListener('focus', () => { this.cursorEl.style.display = ''; sync(); });
        this.inputEl.addEventListener('blur', () => { this.cursorEl.style.display = 'none'; });

        // Initial position
        this.syncCursor();
    }

    syncCursor() {
        const input = this.inputEl;
        const cursor = this.cursorEl;
        if (!cursor) return;

        // Copy font styles to measurer
        const cs = getComputedStyle(input);
        this.measurer.style.fontFamily = cs.fontFamily;
        this.measurer.style.fontSize = cs.fontSize;
        this.measurer.style.fontWeight = cs.fontWeight;
        this.measurer.style.letterSpacing = cs.letterSpacing;

        // Measure text up to caret position
        const pos = input.selectionStart || 0;
        const textBeforeCaret = input.value.substring(0, pos);
        this.measurer.textContent = textBeforeCaret || '';

        // Get input positioning
        const inputRect = input.getBoundingClientRect();
        const wrapperRect = input.parentElement.getBoundingClientRect();
        const textWidth = this.measurer.offsetWidth;

        // Position cursor relative to wrapper
        const left = (inputRect.left - wrapperRect.left) + textWidth;
        const top = (inputRect.top - wrapperRect.top) + parseFloat(cs.paddingTop);

        cursor.style.left = left + 'px';
        cursor.style.top = top + 'px';
        cursor.style.height = cs.fontSize;
    }

    /* ---- Send Message ---- */
    async handleSend() {
        const text = this.inputEl.value.trim();
        if (!text || this.isTyping) return;

        this.hideAutocomplete();
        this.inputEl.value = '';

        // Hide welcome screen
        if (this.welcomeEl) {
            this.welcomeEl.style.display = 'none';
        }

        // Dismiss any visible next-question chips
        this.dismissAllNextQuestions();

        // Add user message
        this.addMessage('user', text);

        // Show typing indicator
        this.isTyping = true;
        const typingEl = this.showTyping();

        try {
            const res = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: text,
                    pendingFollowUp: this.pendingFollowUp,
                }),
            });
            const data = await res.json();

            // Small delay to feel natural
            await new Promise(r => setTimeout(r, 500));
            this.removeTyping(typingEl);

            this.pendingFollowUp = null;

            if (data.type === 'answer') {
                this.addMessage('agent', data.text, data.video || null, data.nextQuestions || null, data.moduleRef || null);
            } else if (data.type === 'followUp') {
                this.addFollowUpMessage(data.question, data.options);
            } else {
                this.addMessage('agent', "I'm not sure I understand. Could you try rephrasing?");
            }
        } catch (err) {
            this.removeTyping(typingEl);
            this.addMessage('agent', "Sorry, something went wrong. Please try again.");
        }

        this.isTyping = false;
    }

    /* ---- Follow-Up Button Click ---- */
    async handleFollowUpClick(answerId, btnEl, allBtns) {
        if (this.isTyping) return;

        // Highlight selected button, disable others
        allBtns.forEach(b => {
            b.classList.add('followup-btn-disabled');
            b.disabled = true;
        });
        btnEl.classList.remove('followup-btn-disabled');
        btnEl.classList.add('followup-btn-selected');

        this.isTyping = true;
        const typingEl = this.showTyping();

        try {
            const res = await fetch('/api/chat/resolve', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ answerId }),
            });
            const data = await res.json();

            await new Promise(r => setTimeout(r, 500));
            this.removeTyping(typingEl);

            this.pendingFollowUp = null;

            if (data.type === 'answer') {
                this.addMessage('agent', data.text, data.video || null, data.nextQuestions || null, data.moduleRef || null);
            } else {
                this.addMessage('agent', "I'm not sure I understand. Could you try rephrasing?");
            }
        } catch (err) {
            this.removeTyping(typingEl);
            this.addMessage('agent', "Sorry, something went wrong. Please try again.");
        }

        this.isTyping = false;
    }

    /* ---- Render Messages ---- */
    scrollToBottom() {
        this.messagesEl.scrollTop = this.messagesEl.scrollHeight;
    }
}

/* ---- Welcome Subtitle Typewriter ---- */
function welcomeTypewriter() {
    const el = document.getElementById('welcome-typewriter');
    if (!el) return;

    const text = 'Ask about Modules, Tutorials, Pro Code tools, or anything else about AWMIT';
    let i = 0;
    const speed = 30;

    const cursor = document.querySelector('.welcome-cursor');

    // Delay start so stagger animations finish first
    setTimeout(() => {
        const type = () => {
            if (i < text.length) {
                el.textContent += text[i];
                i++;
                if (i >= text.length) {
                    if (cursor) {
                        cursor.style.animation = 'none';
                        cursor.style.opacity = '0';
                    }
                    // Start grid sweep after typing finishes
                    const sweep = document.querySelector('.chat-grid-sweep');
                    if (sweep) sweep.classList.add('sweep-go');
                }
                setTimeout(type, speed);
            }
        };
        type();
    }, 1200);
}

/* ---- Init ---- */
document.addEventListener('DOMContentLoaded', () => {
    new AgentChat();
    welcomeTypewriter();
});
