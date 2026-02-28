/* ============================================
   HeroAnimation — Phases 3 & 4
   Galaxy explosion, text reveals, terminal typing,
   galaxy video fade-in. Runs on page 1 after splash.
   ============================================ */

class HeroAnimation {
    constructor() {}

    async play() {
        // Galaxy is immediately visible and playing — no fade-in
        const galaxyBg = document.querySelector('.hero-galaxy-bg');
        const galaxyVid = document.querySelector('.hero-galaxy-vid');
        if (galaxyBg) galaxyBg.style.opacity = '1';
        if (galaxyVid) galaxyVid.play();

        // Unlock scrolling + show scroll indicator as soon as galaxy plays
        document.dispatchEvent(new CustomEvent('cinematic-done'));

        // Kill particle canvas immediately
        const heroBgCanvas = document.querySelector('.hero-bg-canvas');
        if (heroBgCanvas) {
            heroBgCanvas.style.opacity = '0';
            if (window.heroBg) window.heroBg.pause();
        }

        // Show bg elements immediately
        const bgEls = document.querySelectorAll('.hero-grid-overlay, .hero-orb, .hero-scanlines');
        bgEls.forEach(el => { el.style.opacity = '1'; });

        // Now add hero-animating (hides text/terminal, but galaxy is already visible)
        document.body.classList.add('hero-animating');

        // Explosion effect on top of the now-visible galaxy
        const hero = document.getElementById('hero');
        const explosion = document.createElement('div');
        explosion.className = 'galaxy-explosion';
        if (hero) hero.appendChild(explosion);

        const ring = document.createElement('div');
        ring.className = 'galaxy-explosion-ring';
        if (hero) hero.appendChild(ring);

        // Pre-lock terminal size BEFORE any content reveals to prevent layout shift
        const line3 = document.querySelector('[data-cinematic="line3"]');
        let typedEl, cursorEl, bodyEl, titleEl, controlsEl;
        const text = '>>> Starts Here.';
        if (line3) {
            typedEl = line3.querySelector('.headline-typed');
            cursorEl = line3.querySelector('.headline-cursor');
            bodyEl = line3.querySelector('.headline-terminal-body');
            titleEl = line3.querySelector('.headline-terminal-title');
            controlsEl = line3.querySelector('.headline-terminal-controls');

            if (typedEl && bodyEl) {
                typedEl.textContent = text;
                const fullH = bodyEl.scrollHeight;
                const fullW = bodyEl.scrollWidth;
                bodyEl.style.height = fullH + 'px';
                bodyEl.style.width = fullW + 'px';
                const terminalW = line3.scrollWidth;
                line3.style.width = terminalW + 'px';
                typedEl.textContent = '';
            }
        }

        // Wait for explosion peak then clean up
        await this.sleep(800);
        explosion.remove();
        await this.sleep(400);
        ring.remove();

        // Reveal "The Future of" with sweep highlight
        const line1 = document.querySelector('[data-cinematic="line1"]');
        if (line1) {
            line1.style.position = 'relative';
            line1.classList.add('cinematic-reveal-line1');

            const sweep = document.createElement('div');
            sweep.className = 'sweep-highlight';
            line1.appendChild(sweep);
            await this.sleep(100);
            sweep.classList.add('animate');
        }

        await this.sleep(300);

        // "AWM" — snap in
        const line2 = document.querySelector('[data-cinematic="line2"]');
        if (line2) {
            line2.style.transition = 'none';
            line2.style.opacity = '1';
        }

        await this.sleep(300);

        // Terminal: CRT clip-path reveal → fade in content → type
        if (line3) {
            if (titleEl) titleEl.style.opacity = '0';
            if (controlsEl) controlsEl.style.opacity = '0';

            line3.style.filter = 'none';
            line3.style.transform = 'none';
            line3.classList.add('cinematic-reveal-terminal');

            await this.sleep(650);

            if (titleEl) {
                titleEl.style.transition = 'opacity 0.3s ease';
                titleEl.style.opacity = '1';
            }
            if (controlsEl) {
                controlsEl.style.transition = 'opacity 0.3s ease';
                controlsEl.style.opacity = '1';
            }
            await this.sleep(350);

            if (cursorEl) cursorEl.classList.add('visible');
            await this.sleep(300);

            if (typedEl) {
                for (let i = 0; i < text.length; i++) {
                    typedEl.textContent += text[i];
                    await this.sleep(70);
                }
            }
            await this.sleep(300);
            await this.sleep(900);
        }

        await this.sleep(100);

        // Settle — done
        document.body.classList.remove('hero-animating');
        document.body.classList.add('cinematic-done');
        document.querySelectorAll('.sweep-highlight').forEach(s => s.remove());
    }

    sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }
}
