AgentChat.prototype.showTyping=function(){const msg=document.createElement('div');msg.className='chat-msg agent-msg typing-msg';msg.innerHTML=`
        <div class="msg-avatar">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="8" width="18" height="12" rx="2"/><circle cx="9" cy="14" r="1.5"/><circle cx="15" cy="14" r="1.5"/><path d="M9 18h6"/><line x1="12" y1="2" x2="12" y2="8"/><circle cx="12" cy="2" r="1.5" fill="currentColor"/></svg>
        </div>
        <div class="msg-content">
            <span class="msg-sender">AWMIT Assistant</span>
            <div class="msg-body">
                <span class="typing-label">Thinking</span>
                <span class="typing-dot"></span>
                <span class="typing-dot"></span>
                <span class="typing-dot"></span>
            </div>
        </div>
    `;this.messagesEl.appendChild(msg);this.scrollToBottom();return msg;};AgentChat.prototype.removeTyping=function(el){if(el&&el.parentNode)el.remove();};AgentChat.prototype.updateAutocomplete=async function(){const query=this.inputEl.value.trim();if(query.length<2){this.hideAutocomplete();return;}
try{const res=await fetch(`/api/suggestions?q=${encodeURIComponent(query)}`);const suggestions=await res.json();if(suggestions.length===0){this.hideAutocomplete();return;}
this.renderAutocomplete(suggestions);}catch(e){this.hideAutocomplete();}};AgentChat.prototype.renderAutocomplete=function(suggestions){this.autocompleteItems=suggestions;this.autocompleteIndex=-1;this.autocompleteEl.innerHTML=suggestions.map((s,i)=>`
        <div class="autocomplete-item" data-index="${i}">
            <svg class="autocomplete-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="11" cy="11" r="8"></circle>
                <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
            </svg>
            <span class="autocomplete-text">${s.text}</span>
        </div>
    `).join('');this.autocompleteEl.classList.add('visible');this.autocompleteEl.querySelectorAll('.autocomplete-item').forEach(item=>{item.addEventListener('click',()=>{this.selectAutocompleteItem(parseInt(item.dataset.index));});});};AgentChat.prototype.hideAutocomplete=function(){this.autocompleteEl.classList.remove('visible');this.autocompleteIndex=-1;this.autocompleteItems=[];};AgentChat.prototype.navigateAutocomplete=function(dir){const items=this.autocompleteEl.querySelectorAll('.autocomplete-item');if(items.length===0)return;this.autocompleteIndex+=dir;if(this.autocompleteIndex<0)this.autocompleteIndex=items.length-1;if(this.autocompleteIndex>=items.length)this.autocompleteIndex=0;items.forEach((item,i)=>{item.classList.toggle('active',i===this.autocompleteIndex);});};AgentChat.prototype.selectAutocompleteItem=function(index){const suggestion=this.autocompleteItems[index];if(!suggestion)return;this.inputEl.value=suggestion.text;this.hideAutocomplete();this.handleSend();};