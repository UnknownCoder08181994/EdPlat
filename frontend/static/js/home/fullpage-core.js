/* ============================================
   AWM V2 — Fullpage Snap Scroll Controller
   Wheel / touch / keyboard driven section snapping
   with dot navigation and reveal animations.
   Inactive sections have content hidden (display:none)
   for performance — only active section is rendered.
   Section indices: 0=Gateway, 1=Vision, 2=FAQ
   ============================================ */

class FullpageScroll {
    constructor() {
        this.wrapper = document.getElementById('fp-wrapper');
        this.sections = [...document.querySelectorAll('.fp-section')];
        this.pill = document.getElementById('fp-pill');
        this.pillTextTrack = this.pill ? this.pill.querySelector('.pill-text-track') : null;
        this.pillBars = this.pill ? [...this.pill.querySelectorAll('.pill-bar')] : [];
        this.sectionNames = ['Home', 'Vision', 'FAQ'];

        this.current = 0;
        this.total = this.sections.length;
        this.isTransitioning = false;
        this.isLocked = false;

        this.touchStartY = 0;
        this.touchStartX = 0;

        this.init();
    }

    init() {
        // Set initial state — only active section content is visible
        this.sections.forEach((section, i) => {
            if (i === 0) {
                section.classList.add('fp-active');
            } else {
                section.classList.add('fp-below');
                section.querySelector('.section-content, .vision-content, .gw-split')
                    ?.classList.add('fp-hidden');
            }
        });

        this.bindWheel();
        this.bindTouch();
        this.bindKeyboard();
        this.bindPill();
    }

    /* Find scrollable element — prefers a scrollable child over the section itself */
    getScrollableChild(section) {
        // Check children first (e.g. .faq-content)
        for (const child of section.children) {
            const cOverflow = getComputedStyle(child).overflowY;
            if (cOverflow === 'auto' || cOverflow === 'scroll') return child;
        }

        // Fall back to section itself
        const sOverflow = getComputedStyle(section).overflowY;
        if (sOverflow === 'auto' || sOverflow === 'scroll') return section;

        return null;
    }

    goTo(index) {
        if (index < 0 || index >= this.total || index === this.current) return;
        if (this.isTransitioning) return;

        this.isTransitioning = true;
        const prev = this.current;
        this.current = index;
        const direction = index > prev ? 'down' : 'up';

        const prevSection = this.sections[prev];
        const nextSection = this.sections[index];

        const overlay = document.getElementById('page-fade-overlay');

        // Phase 1: Fade to black
        if (overlay) {
            overlay.style.pointerEvents = 'all';
            overlay.style.opacity = '1';
        }

        // After black, swap sections
        setTimeout(() => {
            // Force all reveal elements to hidden state with no transition
            const revealEls = nextSection.querySelectorAll('[data-reveal]');
            revealEls.forEach(el => {
                el.style.transition = 'none';
                el.style.opacity = '0';
                el.style.transform = 'translateY(2vw)';
            });

            // Unhide next section content
            const nextContent = nextSection.querySelector('.section-content, .vision-content, .gw-split');
            if (nextContent) {
                nextContent.classList.remove('fp-hidden');
                void nextContent.offsetHeight; // commit opacity:0 to render
            }

            // Kill prev section content
            const prevContent = prevSection.querySelector('.section-content, .vision-content, .gw-split');
            if (prevContent) prevContent.classList.add('fp-hidden');

            // Resume neon grid lines when entering vision (page 1)
            if (index === 1) {
                try { if (window.neonGridLines) window.neonGridLines.resume(); } catch (_) {}
            }

            // Play globe video when entering FAQ (page 2)
            if (index === 2) {
                const globeVid = document.querySelector('.faq-bg-video');
                if (globeVid) globeVid.play();
            }

            // Pause ALL vision (page 1) videos when leaving
            if (prev === 1) {
                const labVid = document.querySelector('.h2-lab-video');
                if (labVid) labVid.pause();
                document.querySelectorAll('.hcard-vid').forEach(v => v.pause());
                try { if (window.neonGridLines) window.neonGridLines.pause(); } catch (_) {}
            }

            // Pause globe video when leaving FAQ (page 2)
            if (prev === 2) {
                const globeVid = document.querySelector('.faq-bg-video');
                if (globeVid) globeVid.pause();
            }

            // Swap section positions (instant, behind black overlay)
            this.sections.forEach((section, i) => {
                section.classList.remove('fp-active', 'fp-above', 'fp-below');
                if (i === index) {
                    section.classList.add('fp-active');
                } else if (i < index) {
                    section.classList.add('fp-above');
                } else {
                    section.classList.add('fp-below');
                }
            });

            // Update pill
            this.updatePill(index, direction);

            // Trigger reveal animations
            this.revealSection(index, direction);

            // Nav background
            const nav = document.getElementById('main-nav');
            if (nav) nav.classList.toggle('scrolled', index > 0);

            // Phase 2: Fade from black (reveal new section)
            requestAnimationFrame(() => {
                if (overlay) {
                    overlay.style.opacity = '0';
                    overlay.addEventListener('transitionend', () => {
                        overlay.style.pointerEvents = 'none';
                    }, { once: true });
                }
                this.isTransitioning = false;
            });
        }, 350);
    }

    revealSection(index, direction) {
        const section = this.sections[index];
        if (!section) return;

        // Gateway (section 0): replay PCB design + typewriter
        if (index === 0 && window.resetGateway) {
            window.resetGateway();
        }

        // Vision (section 1): replay videos + typewriter
        if (index === 1) {
            if (window.resetFocusTypewriter) window.resetFocusTypewriter();
            document.querySelectorAll('.hcard-vid').forEach(v => {
                v.currentTime = 0;
                v.play().catch(() => {});
            });
        }

        // Cards / reveal elements — staggered entrance via inline styles
        // (inline styles override all CSS specificity / animation fill issues)
        const revealEls = section.querySelectorAll('[data-reveal]');
        revealEls.forEach((el, i) => {
            const delay = 150 + i * 100;
            setTimeout(() => {
                el.style.transition = 'opacity 0.6s ease, transform 0.6s ease';
                el.style.opacity = '1';
                el.style.transform = 'translateY(0)';
            }, delay);
        });

        // Dispatch event for other systems (telemetry, counters)
        document.dispatchEvent(new CustomEvent('section-revealed', {
            detail: { index, direction }
        }));
    }

    updatePill(index, direction) {
        if (!this.pill || !this.pillTextTrack) return;

        // Update bars
        this.pillBars.forEach((bar, i) => {
            bar.classList.toggle('pill-bar-active', i === index);
        });

        // Animate text
        const track = this.pillTextTrack;
        const currentText = track.querySelector('.pill-text-active');
        const newLabel = this.sectionNames[index] || '';

        if (!currentText) {
            track.innerHTML = '';
            const span = document.createElement('span');
            span.className = 'pill-text pill-text-active';
            span.textContent = newLabel;
            track.appendChild(span);
            return;
        }

        if (currentText.textContent === newLabel) return;

        const exitClass = direction === 'down' ? 'pill-text-exiting-up' : 'pill-text-exiting-down';
        const enterClass = direction === 'down' ? 'pill-text-entering-up' : 'pill-text-entering-down';

        // Create incoming text
        const incoming = document.createElement('span');
        incoming.className = 'pill-text ' + enterClass;
        incoming.textContent = newLabel;
        track.appendChild(incoming);

        // Animate outgoing
        currentText.classList.remove('pill-text-active');
        currentText.classList.add(exitClass);

        // Clean up after animation
        let cleaned = false;
        const cleanup = () => {
            if (cleaned) return;
            cleaned = true;
            currentText.remove();
            incoming.classList.remove(enterClass);
            incoming.classList.add('pill-text-active');
        };

        incoming.addEventListener('animationend', cleanup, { once: true });
        setTimeout(cleanup, 400);
    }

    bindPill() {
        if (!this.pill) return;

        // Click bars to navigate directly
        this.pillBars.forEach(bar => {
            bar.addEventListener('click', (e) => {
                e.stopPropagation();
                if (this.isLocked || this.isTransitioning) return;
                const target = parseInt(bar.dataset.target, 10);
                this.goTo(target);
            });
        });

        // Click text area to cycle
        const track = this.pillTextTrack;
        if (track) {
            track.addEventListener('click', () => {
                if (this.isLocked || this.isTransitioning) return;
                const next = (this.current + 1) % this.total;
                this.goTo(next);
            });
        }
    }
}
