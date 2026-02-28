/* Message rendering methods for AgentChat */

AgentChat.prototype.addMessage = function(sender, text, video, nextQuestions, moduleRef) {
    const msg = document.createElement('div');
    msg.className = `chat-msg ${sender}-msg`;

    const avatarSvg = sender === 'agent'
        ? '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="8" width="18" height="12" rx="2"/><circle cx="9" cy="14" r="1.5"/><circle cx="15" cy="14" r="1.5"/><path d="M9 18h6"/><line x1="12" y1="2" x2="12" y2="8"/><circle cx="12" cy="2" r="1.5" fill="currentColor"/></svg>'
        : '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>';

    const senderName = sender === 'agent' ? 'AWMIT Assistant' : 'You';
    const formattedText = this.formatMessage(text);

    msg.innerHTML = `
        <div class="msg-avatar">${avatarSvg}</div>
        <div class="msg-content">
            <span class="msg-sender">${senderName}</span>
            <div class="msg-body"></div>
        </div>
    `;

    this.messagesEl.appendChild(msg);

    const bodyEl = msg.querySelector('.msg-body');

    if (sender === 'agent') {
        this.typewriterEffect(bodyEl, formattedText, () => {
            if (video && video.src) {
                this.appendVideoCard(bodyEl, video);
            }
            if (moduleRef && moduleRef.url) {
                this.appendModuleRef(bodyEl, moduleRef);
            }
            if (nextQuestions && nextQuestions.length > 0) {
                this.appendNextQuestions(bodyEl, nextQuestions);
            }
        });
    } else {
        bodyEl.innerHTML = formattedText;
    }

    this.scrollToBottom();
};

AgentChat.prototype.appendModuleRef = function(container, ref) {
    const wrapper = document.createElement('div');
    wrapper.className = 'msg-module-ref';

    wrapper.innerHTML =
        '<span class="msg-module-ref-label">Referenced Module</span>' +
        '<a class="msg-module-ref-btn" href="' + ref.url + '">' +
            '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" ' +
                'stroke="currentColor" stroke-width="2" stroke-linecap="round" ' +
                'stroke-linejoin="round">' +
                '<rect x="2" y="3" width="20" height="14" rx="2"/>' +
                '<line x1="8" y1="21" x2="16" y2="21"/>' +
                '<line x1="12" y1="17" x2="12" y2="21"/>' +
            '</svg>' +
            '<span>' + ref.name + '</span>' +
            '<svg class="msg-module-ref-arrow" width="12" height="12" ' +
                'viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
                'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
                '<path d="M5 12h14M12 5l7 7-7 7"/>' +
            '</svg>' +
        '</a>';

    container.appendChild(wrapper);
    this.scrollToBottom();
};

AgentChat.prototype.addFollowUpMessage = function(question, options) {
    const msg = document.createElement('div');
    msg.className = 'chat-msg agent-msg';

    msg.innerHTML = `
        <div class="msg-avatar">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="8" width="18" height="12" rx="2"/><circle cx="9" cy="14" r="1.5"/><circle cx="15" cy="14" r="1.5"/><path d="M9 18h6"/><line x1="12" y1="2" x2="12" y2="8"/><circle cx="12" cy="2" r="1.5" fill="currentColor"/></svg>
        </div>
        <div class="msg-content">
            <span class="msg-sender">AWMIT Assistant</span>
            <div class="msg-body"></div>
        </div>
    `;

    this.messagesEl.appendChild(msg);
    const bodyEl = msg.querySelector('.msg-body');

    this.pendingFollowUp = { question, options };

    const formattedQ = this.formatMessage(question);
    this.typewriterEffect(bodyEl, formattedQ, () => {
        const optionsDiv = document.createElement('div');
        optionsDiv.className = 'followup-options';

        const btns = [];
        options.forEach(opt => {
            const btn = document.createElement('button');
            btn.className = 'followup-btn';
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

AgentChat.prototype.formatMessage = function(text) {
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

AgentChat.prototype.typewriterEffect = function(container, html, onComplete) {
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

/* ---- Suggested Next Questions ---- */

AgentChat.prototype.appendNextQuestions = function(container, questions) {
    const wrapper = document.createElement('div');
    wrapper.className = 'next-questions';

    const label = document.createElement('span');
    label.className = 'next-questions-label';
    label.textContent = 'Suggested';
    wrapper.appendChild(label);

    questions.forEach(qText => {
        const chip = document.createElement('button');
        chip.className = 'next-question-chip';
        chip.textContent = qText;
        chip.addEventListener('click', () => {
            this.handleNextQuestionClick(qText);
        });
        wrapper.appendChild(chip);
    });

    container.appendChild(wrapper);
    this.scrollToBottom();
};

AgentChat.prototype.handleNextQuestionClick = function(text) {
    if (this.isTyping) return;
    this.dismissAllNextQuestions();
    this.inputEl.value = text;
    this.handleSend();
};

AgentChat.prototype.dismissAllNextQuestions = function() {
    const groups = this.messagesEl.querySelectorAll('.next-questions');
    groups.forEach(g => g.remove());
};
