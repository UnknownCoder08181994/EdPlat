/* ============================================
   MODULES PAGE — Scroll-triggered staggered FX
   IntersectionObserver drives glitch-in / text-reveal.
   Cards animate when entering viewport, reset when
   leaving, and re-animate on every scroll-back.
   ============================================ */

class ModulePageFX {
    constructor() {
        // Cancel any previous timers (hot-reload / bfcache)
        if (window._fxTimers) {
            window._fxTimers.forEach(id => clearTimeout(id));
        }
        window._fxTimers = [];

        // ---- Header blocks (hero, filters, toolbar) — one-shot entrance ----
        this.headerBlocks = [
            document.querySelector('.catalogue-hero'),
            document.querySelector('.catalogue-filters-row'),
            document.querySelector('.catalogue-toolbar'),
        ].filter(Boolean);

        this.animateHeaders();

        // ---- Cards — scroll-triggered ----
        this.cards = Array.from(document.querySelectorAll('.course-card'));

        if (this.cards.length > 0) {
            // Prepare every card as invisible
            this.cards.forEach(card => {
                card.classList.add('fx-hidden', 'fx-text-hidden');
                card.style.opacity = '';
                card._fxAnimating = false;
            });

            this.setupObserver();
        }

        // ---- Detail / viewer blocks (if present on other pages sharing this script) ----
        this.otherBlocks = [];
        ['.detail-back-link', '.detail-breadcrumb', '.detail-hero',
         '.detail-section-heading', '.detail-sidebar-card',
         '.viewer-header', '.viewer-timeline', '.viewer-sidebar'].forEach(sel => {
            var el = document.querySelector(sel);
            if (el) this.otherBlocks.push({ el: el, isCard: (sel === '.viewer-sidebar' || sel === '.detail-sidebar-card') });
        });
        document.querySelectorAll('.detail-section-card, .detail-chapter-card').forEach(el => {
            this.otherBlocks.push({ el: el, isCard: true });
        });
        var tvEl = document.querySelector('.viewer-video-container');
        if (tvEl) this.otherBlocks.push({ el: tvEl, isTv: true });

        if (this.otherBlocks.length > 0) this.animateOtherBlocks();
    }

    /* ---- Header entrance (sequential, one-shot) ---- */
    animateHeaders() {
        var delay = 60;
        this.headerBlocks.forEach(el => {
            el.classList.add('fx-hidden', 'fx-text-hidden');
            el.style.opacity = '';
            var d = delay;
            window._fxTimers.push(setTimeout(() => {
                el.classList.remove('fx-hidden');
                void el.offsetHeight;
                el.classList.add('fx-glitch');
            }, d));
            window._fxTimers.push(setTimeout(() => {
                el.classList.remove('fx-text-hidden');
                el.classList.add('fx-text-reveal');
            }, d + 400));
            window._fxTimers.push(setTimeout(() => {
                el.classList.remove('fx-glitch', 'fx-text-reveal');
            }, d + 850));
            delay += 120;
        });
    }

    /* ---- IntersectionObserver for cards ---- */
    setupObserver() {
        this.pendingEnter = new Set();
        this.batchTimer = null;

        this.observer = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                var card = entry.target;
                if (entry.isIntersecting) {
                    // Skip if already animating or already visible
                    if (card._fxAnimating || !card.classList.contains('fx-hidden')) return;
                    this.pendingEnter.add(card);
                    this.scheduleBatch();
                } else {
                    // Only reset if the card was fully visible (done animating)
                    // and has now scrolled out of view
                    if (card._fxAnimating) return;
                    if (!card.classList.contains('fx-hidden')) {
                        this.resetCard(card);
                    }
                    this.pendingEnter.delete(card);
                }
            });
        }, {
            threshold: 0.1,
        });

        this.cards.forEach(card => this.observer.observe(card));
    }

    /* Batch cards that enter in the same frame and stagger them L→R, T→B */
    scheduleBatch() {
        if (this.batchTimer) return;
        this.batchTimer = requestAnimationFrame(() => {
            this.batchTimer = null;
            if (this.pendingEnter.size === 0) return;

            // Sort by DOM order so stagger goes left→right, top→bottom
            var batch = Array.from(this.pendingEnter).sort((a, b) => {
                return this.cards.indexOf(a) - this.cards.indexOf(b);
            });
            this.pendingEnter.clear();

            batch.forEach((card, i) => {
                var stagger = i * 120;
                this.animateCardIn(card, stagger);
            });
        });
    }

    animateCardIn(card, delay) {
        // Clear any pending timers
        if (card._fxTimers) {
            card._fxTimers.forEach(id => clearTimeout(id));
        }
        card._fxTimers = [];
        card._fxAnimating = true;

        // Ensure starting state
        card.classList.add('fx-hidden', 'fx-text-hidden');
        card.classList.remove('fx-glitch', 'fx-text-reveal');

        // Glitch in
        card._fxTimers.push(setTimeout(() => {
            card.classList.remove('fx-hidden');
            void card.offsetHeight;
            card.classList.add('fx-glitch');
        }, delay));

        // Text reveal
        card._fxTimers.push(setTimeout(() => {
            card.classList.remove('fx-text-hidden');
            card.classList.add('fx-text-reveal');
        }, delay + 350));

        // Cleanup animation classes, mark done
        card._fxTimers.push(setTimeout(() => {
            card.classList.remove('fx-glitch', 'fx-text-reveal');
            card._fxAnimating = false;
        }, delay + 900));
    }

    resetCard(card) {
        if (card._fxTimers) {
            card._fxTimers.forEach(id => clearTimeout(id));
            card._fxTimers = [];
        }
        card._fxAnimating = false;
        card.classList.remove('fx-glitch', 'fx-text-reveal');
        card.classList.add('fx-hidden', 'fx-text-hidden');
    }

    /* ---- Other page blocks (detail / viewer) — unchanged one-shot ---- */
    animateOtherBlocks() {
        var delay = 60;
        this.otherBlocks.forEach(block => {
            var el = block.el;
            var isTv = block.isTv;
            el.classList.add('fx-hidden');
            if (!isTv) el.classList.add('fx-text-hidden');
            el.style.opacity = '';
            var d = delay;
            window._fxTimers.push(setTimeout(() => {
                el.classList.remove('fx-hidden');
                void el.offsetHeight;
                el.classList.add(isTv ? 'fx-tv-on' : 'fx-glitch');
            }, d));
            if (!isTv) {
                window._fxTimers.push(setTimeout(() => {
                    el.classList.remove('fx-text-hidden');
                    el.classList.add('fx-text-reveal');
                }, d + 400));
            }
            window._fxTimers.push(setTimeout(() => {
                el.classList.remove('fx-glitch', 'fx-tv-on', 'fx-text-reveal');
            }, d + 850));
            delay += block.isCard ? 150 : 120;
        });
    }
}

function startFX() {
    requestAnimationFrame(() => {
        requestAnimationFrame(() => {
            window.modulePageFX = new ModulePageFX();
        });
    });
}

document.addEventListener('DOMContentLoaded', startFX);
window.addEventListener('pageshow', (e) => {
    if (e.persisted) {
        window.modulePageFX = new ModulePageFX();
    }
});
