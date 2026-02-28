/* ============================================
   SplashIntro — AWM glitch decode + mesh text build
   Independent overlay, only on fresh load/refresh.
   ============================================ */

class SplashIntro {
    constructor() {
        this.overlay = null;
        this.splashEl = document.getElementById('splash-overlay');
    }

    async play() {
        document.body.classList.add('splash-playing');
        this.createOverlay();

        await this.phase1_pause();
        await this.phase2_instituteReveal();

        // Clean up cinematic overlay (text already faded)
        if (this.overlay) this.overlay.remove();

        // Splash overlay remains visible (solid white).
        // nav.js handles the cross-fade transition to the home page.
        document.dispatchEvent(new CustomEvent('splash-done'));
    }

    /* ---- Phase 1: Brief pause on white ---- */
    async phase1_pause() {
        await this.sleep(300);
    }

    /* ---- Phase 2: AWM Decode + Mesh Text Build + Fade Out ---- */
    async phase2_instituteReveal() {
        const targetLetters = ['A', 'W', 'M'];
        const glitchChars = '▓█▒░╗╣║╠╬╦╝■□◆◇⬡⬢⟐⟁∎⊞⊡⧫';

        const reveal = document.createElement('div');
        reveal.className = 'institute-reveal';
        reveal.innerHTML = `
            <div class="institute-awm">
                ${targetLetters.map(l => `<span class="decode-letter locked">${l}</span>`).join('')}
            </div>
            <div class="institute-divider"></div>
            <div class="institute-name">Institute of Technology</div>
        `;
        document.body.appendChild(reveal);

        const letterEls = reveal.querySelectorAll('.decode-letter');
        const letterWidths = [];
        letterEls.forEach(el => {
            letterWidths.push(el.getBoundingClientRect().width);
        });

        letterEls.forEach((el, i) => {
            el.style.width = letterWidths[i] + 'px';
            el.classList.remove('locked');
            el.classList.add('scrambling');
            el.textContent = '\u00A0';
        });

        const glitchFlicker = document.createElement('div');
        glitchFlicker.className = 'glitch-flicker';
        document.body.appendChild(glitchFlicker);

        this.overlay.style.transition = 'opacity 0.8s ease';
        this.overlay.style.opacity = '0.5';

        await this.sleep(200);
        reveal.classList.add('visible');

        await this.sleep(300);

        const scrambleIntervals = [];
        letterEls.forEach(el => {
            const interval = setInterval(() => {
                el.textContent = glitchChars[Math.floor(Math.random() * glitchChars.length)];
            }, 60);
            scrambleIntervals.push(interval);
        });

        await this.sleep(500);

        for (let i = 0; i < targetLetters.length; i++) {
            glitchFlicker.classList.add('fire');
            await this.sleep(60);
            glitchFlicker.classList.remove('fire');

            clearInterval(scrambleIntervals[i]);
            letterEls[i].textContent = targetLetters[i];
            letterEls[i].classList.remove('scrambling');
            letterEls[i].classList.add('locked', 'lock-flash');

            await this.sleep(250);
        }

        await this.sleep(200);

        const flash = document.createElement('div');
        flash.className = 'screen-flash';
        document.body.appendChild(flash);
        await this.sleep(50);
        flash.classList.add('fire');

        // Divider expands
        const divider = reveal.querySelector('.institute-divider');
        if (divider) divider.classList.add('expand');

        // Build "Institute of Technology" with mesh construction
        const nameEl = reveal.querySelector('.institute-name');
        if (nameEl) await this.buildMeshText(nameEl);

        // Fade in graduate silhouette above AWM
        const gradImg = document.createElement('img');
        gradImg.src = '/static/pictures/grad_person.png';
        gradImg.className = 'splash-grad-person';
        gradImg.draggable = false;
        reveal.appendChild(gradImg);

        await this.sleep(1200);

        // Clean up
        flash.remove();
        glitchFlicker.remove();
        scrambleIntervals.forEach(i => clearInterval(i));

        // ---- Fade everything to white ----
        reveal.style.transition = 'opacity 0.8s ease';
        reveal.style.opacity = '0';

        if (this.overlay) {
            this.overlay.style.transition = 'opacity 0.8s ease';
            this.overlay.style.opacity = '0';
        }

        await this.sleep(800);
        reveal.remove();
    }

    /* ---- Typewriter Text Construction ---- */
    async buildMeshText(nameEl) {
        const text = nameEl.textContent;
        nameEl.textContent = '';
        nameEl.style.color = 'rgba(100,100,110,0.8)';

        // Blinking block cursor — zero-width so it never shifts text
        const cursor = document.createElement('span');
        cursor.textContent = '\u2588';
        cursor.style.cssText = 'display: inline-block; width: 0; overflow: visible; animation: institute-cursor-blink 0.6s step-end infinite; color: rgba(80,80,90,0.7);';

        // Add cursor blink keyframes if not already present
        if (!document.getElementById('inst-cursor-style')) {
            const style = document.createElement('style');
            style.id = 'inst-cursor-style';
            style.textContent = '@keyframes institute-cursor-blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }';
            document.head.appendChild(style);
        }

        nameEl.appendChild(cursor);

        // Type each character one by one
        for (let i = 0; i < text.length; i++) {
            const char = text[i];
            const span = document.createElement('span');
            if (char === ' ') {
                span.innerHTML = '&nbsp;';
            } else {
                span.textContent = char;
            }
            nameEl.insertBefore(span, cursor);
            await this.sleep(28);
        }

        // Typing done — pause with cursor visible
        await this.sleep(200);

        // Stop cursor blink, fade it out
        cursor.style.animation = 'none';
        cursor.style.transition = 'opacity 0.2s ease';
        cursor.style.opacity = '0';

        await this.sleep(200);
        cursor.remove();

        // Clean up injected style
        const cursorStyle = document.getElementById('inst-cursor-style');
        if (cursorStyle) cursorStyle.remove();
    }

    /* ---- Helpers ---- */

    createOverlay() {
        this.overlay = document.createElement('div');
        this.overlay.className = 'cinematic-overlay';
        this.overlay.id = 'cinematic-overlay';

        const flare = document.createElement('div');
        flare.className = 'lens-flare';
        this.overlay.appendChild(flare);

        document.body.appendChild(this.overlay);
    }

    sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }
}
