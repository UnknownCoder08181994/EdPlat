/* Chat methods for ModuleCoach */

ModuleCoach.prototype.handleSend = async function() {
    const text = this.inputEl.value.trim();
    if (!text || this.isTyping) return;

    this.inputEl.value = '';

    const welcome = this.messagesEl.querySelector('.viewer-welcome');
    if (welcome) welcome.style.display = 'none';

    this.addMessage('user', text);

    this.isTyping = true;
    const typingEl = this.showTyping();

    try {
        const res = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: text,
                pendingFollowUp: this.pendingFollowUp,
                moduleSlug: this.slug,
            }),
        });
        const data = await res.json();

        await new Promise(r => setTimeout(r, 500));
        this.removeTyping(typingEl);

        this.pendingFollowUp = null;

        if (data.type === 'answer') {
            this.addMessage('agent', data.text);
        } else if (data.type === 'followUp') {
            this.addFollowUpMessage(data.question, data.options);
        } else {
            this.addMessage('agent', "I'm not sure about that. Try asking about this section's content, or click a chip below for a quick recap.");
        }
    } catch (err) {
        this.removeTyping(typingEl);
        this.addMessage('agent', 'Sorry, something went wrong. Please try again.');
    }

    this.isTyping = false;
};

ModuleCoach.prototype.handleFollowUpClick = async function(answerId, btnEl, allBtns) {
    if (this.isTyping) return;

    allBtns.forEach(b => {
        b.classList.add('viewer-followup-btn-disabled');
        b.disabled = true;
    });
    btnEl.classList.remove('viewer-followup-btn-disabled');
    btnEl.classList.add('viewer-followup-btn-selected');

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
            this.addMessage('agent', data.text);
        } else {
            this.addMessage('agent', "I'm not sure I understand. Could you try rephrasing?");
        }
    } catch (err) {
        this.removeTyping(typingEl);
        this.addMessage('agent', 'Sorry, something went wrong. Please try again.');
    }

    this.isTyping = false;
};

ModuleCoach.prototype.addMessage = function(sender, text, video) {
    const msg = document.createElement('div');
    msg.className = `viewer-msg viewer-${sender}-msg`;

    const avatarSvg = sender === 'agent'
        ? '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="8" width="18" height="12" rx="2"/><circle cx="9" cy="14" r="1.5"/><circle cx="15" cy="14" r="1.5"/><path d="M9 18h6"/><line x1="12" y1="2" x2="12" y2="8"/><circle cx="12" cy="2" r="1.5" fill="currentColor"/></svg>'
        : '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>';

    const senderName = sender === 'agent' ? 'AWMIT Coach' : 'You';

    msg.innerHTML = `
        <div class="viewer-msg-avatar">${avatarSvg}</div>
        <div class="viewer-msg-content">
            <span class="viewer-msg-sender">${senderName}</span>
            <div class="viewer-msg-body"></div>
        </div>
    `;

    this.messagesEl.appendChild(msg);
    const bodyEl = msg.querySelector('.viewer-msg-body');

    const formattedText = this.formatMessage(text);

    if (sender === 'agent') {
        this.typewriterEffect(bodyEl, formattedText, () => {
            if (video && video.src) {
                this.appendVideoCard(bodyEl, video);
            }
        });
    } else {
        bodyEl.innerHTML = formattedText;
    }

    this.scrollToBottom();
};

ModuleCoach.prototype.addFollowUpMessage = function(question, options) {
    const msg = document.createElement('div');
    msg.className = 'viewer-msg viewer-agent-msg';

    msg.innerHTML = `
        <div class="viewer-msg-avatar">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="8" width="18" height="12" rx="2"/><circle cx="9" cy="14" r="1.5"/><circle cx="15" cy="14" r="1.5"/><path d="M9 18h6"/><line x1="12" y1="2" x2="12" y2="8"/><circle cx="12" cy="2" r="1.5" fill="currentColor"/></svg>
        </div>
        <div class="viewer-msg-content">
            <span class="viewer-msg-sender">AWMIT Coach</span>
            <div class="viewer-msg-body"></div>
        </div>
    `;

    this.messagesEl.appendChild(msg);
    const bodyEl = msg.querySelector('.viewer-msg-body');

    this.pendingFollowUp = { question, options };

    const formattedQ = this.formatMessage(question);
    this.typewriterEffect(bodyEl, formattedQ, () => {
        const optionsDiv = document.createElement('div');
        optionsDiv.className = 'viewer-followup-options';

        const btns = [];
        options.forEach(opt => {
            const btn = document.createElement('button');
            btn.className = 'viewer-followup-btn';
            btn.textContent = opt.label;
            btn.addEventListener('click', () => {
                this.handleFollowUpClick(opt.answerId, btn, btns);
            });
            optionsDiv.appendChild(btn);
            btns.push(btn);
        });

        bodyEl.appendChild(optionsDiv);
        this.scrollToBottom();
    });

    this.scrollToBottom();
};

ModuleCoach.prototype.formatMessage = function(text) {
    const allowedPattern = /<(\/?(strong|span|br)\b[^>]*)>|&#\d+;|&[a-z]+;/gi;
    const preserved = [];
    let safe = text.replace(allowedPattern, (match) => {
        const idx = preserved.length;
        preserved.push(match);
        return `\x00SAFE${idx}\x00`;
    });

    safe = safe
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/\n/g, '<br>');

    safe = safe.replace(/\x00SAFE(\d+)\x00/g, (_, idx) => preserved[parseInt(idx)]);

    return safe;
};

ModuleCoach.prototype.typewriterEffect = function(container, html, onComplete) {
    const tokens = [];
    let i = 0;
    while (i < html.length) {
        if (html[i] === '<') {
            let end = html.indexOf('>', i);
            if (end === -1) end = html.length - 1;
            tokens.push({ type: 'tag', value: html.slice(i, end + 1) });
            i = end + 1;
        } else if (html[i] === '&') {
            const semi = html.indexOf(';', i);
            if (semi !== -1 && semi - i < 10) {
                tokens.push({ type: 'char', value: html.slice(i, semi + 1) });
                i = semi + 1;
            } else {
                tokens.push({ type: 'char', value: html[i] });
                i++;
            }
        } else {
            tokens.push({ type: 'char', value: html[i] });
            i++;
        }
    }

    const cursor = document.createElement('span');
    cursor.className = 'typewriter-cursor';
    cursor.innerHTML = '&#9608;';
    container.innerHTML = '';
    container.appendChild(cursor);

    let tokenIndex = 0;
    const speed = 6;

    const typeNext = () => {
        if (tokenIndex >= tokens.length) {
            cursor.remove();
            if (onComplete) onComplete();
            return;
        }

        const token = tokens[tokenIndex];
        tokenIndex++;

        if (token.type === 'tag') {
            cursor.insertAdjacentHTML('beforebegin', token.value);
            typeNext();
        } else {
            cursor.insertAdjacentHTML('beforebegin', token.value);
            this.scrollToBottom();
            setTimeout(typeNext, speed);
        }
    };

    typeNext();
};

ModuleCoach.prototype.showTyping = function() {
    const msg = document.createElement('div');
    msg.className = 'viewer-msg viewer-agent-msg viewer-typing-msg';
    msg.innerHTML = `
        <div class="viewer-msg-avatar">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="8" width="18" height="12" rx="2"/><circle cx="9" cy="14" r="1.5"/><circle cx="15" cy="14" r="1.5"/><path d="M9 18h6"/><line x1="12" y1="2" x2="12" y2="8"/><circle cx="12" cy="2" r="1.5" fill="currentColor"/></svg>
        </div>
        <div class="viewer-msg-content">
            <span class="viewer-msg-sender">AWMIT Coach</span>
            <div class="viewer-msg-body">
                <span class="viewer-typing-label">Thinking</span>
                <span class="viewer-typing-dot"></span>
                <span class="viewer-typing-dot"></span>
                <span class="viewer-typing-dot"></span>
            </div>
        </div>
    `;
    this.messagesEl.appendChild(msg);
    this.scrollToBottom();
    return msg;
};

ModuleCoach.prototype.removeTyping = function(el) {
    if (el && el.parentNode) el.remove();
};
