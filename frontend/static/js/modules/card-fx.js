/* ============================================
   Modules Page — Agentic FX Controller
   Glitch power-on → text reveal for ALL page
   blocks (hero, filters, toolbar, cards).
   Border circuit for cards.
   ============================================ */

class ModulePageFX {
    constructor() {
        // Prevent overlapping runs — cancel any previous instance's timers
        if (window._fxTimers) {
            window._fxTimers.forEach(id => clearTimeout(id));
        }
        window._fxTimers = [];

        // All blocks to animate in sequence (top to bottom)
        this.blocks = [
            // Catalogue page elements
            { el: document.querySelector('.catalogue-hero'),        isCard: false },
            { el: document.querySelector('.catalogue-filters-row'), isCard: false },
            { el: document.querySelector('.catalogue-toolbar'),     isCard: false },
        ];

        // Catalogue cards
        document.querySelectorAll('.course-card').forEach(card => {
            this.blocks.push({ el: card, isCard: true });
        });

        // Detail page elements
        this.blocks.push({ el: document.querySelector('.detail-back-link'), isCard: false });
        this.blocks.push({ el: document.querySelector('.detail-breadcrumb'), isCard: false });
        this.blocks.push({ el: document.querySelector('.detail-hero'), isCard: false });
        document.querySelectorAll('.detail-section-card').forEach(card => {
            this.blocks.push({ el: card, isCard: true });
        });
        this.blocks.push({ el: document.querySelector('.detail-sidebar-card'), isCard: true });
        this.blocks.push({ el: document.querySelector('.detail-topics-heading'), isCard: false });
        document.querySelectorAll('.detail-chapter-card').forEach(card => {
            this.blocks.push({ el: card, isCard: true });
        });

        // Viewer page elements
        this.blocks.push({ el: document.querySelector('.viewer-header'), isCard: false });
        this.blocks.push({ el: document.querySelector('.viewer-video-container'), isCard: false, isTv: true });
        this.blocks.push({ el: document.querySelector('.viewer-timeline'), isCard: false });
        this.blocks.push({ el: document.querySelector('.viewer-sidebar'), isCard: true });

        // Filter out any null elements
        this.blocks = this.blocks.filter(b => b.el);

        if (this.blocks.length === 0) return;

        this.initEntrance();
    }

    /* ---- Sequential glitch power-on → text reveal ---- */
    initEntrance() {
        let runningDelay = 60;

        this.blocks.forEach(block => {
            const el = block.el;
            const isCard = block.isCard;
            const myDelay = runningDelay;
            const isTv = block.isTv;

            // Reset: remove any leftover animation classes from a prior run
            el.classList.remove('fx-glitch', 'fx-tv-on', 'fx-text-reveal', 'fx-text-hidden');

            // Start: element invisible, text hidden
            el.classList.add('fx-hidden');
            if (!isTv) el.classList.add('fx-text-hidden');

            // Phase 1: Power on the shell (TV turn-on or glitch)
            window._fxTimers.push(setTimeout(() => {
                el.style.opacity = '';  // clear inline hide
                el.classList.remove('fx-hidden');
                void el.offsetHeight;   // force reflow — commit hidden→visible before animation
                el.classList.add(isTv ? 'fx-tv-on' : 'fx-glitch');
            }, myDelay));

            // Phase 2: After glitch settles, reveal children with stagger (skip for TV)
            if (!isTv) {
                window._fxTimers.push(setTimeout(() => {
                    el.classList.remove('fx-text-hidden');
                    el.classList.add('fx-text-reveal');
                }, myDelay + 400));
            }

            // Phase 3: Clean up
            window._fxTimers.push(setTimeout(() => {
                el.classList.remove('fx-glitch', 'fx-tv-on', 'fx-text-reveal');
            }, myDelay + 850));

            // Stagger: next block starts while this one is mid-glitch
            runningDelay += isCard ? 150 : 120;
        });
    }
}

/* ---- Initialize on DOM ready ---- */
function startFX() {
    // Double-rAF ensures at least one frame has painted (opacity:0 visible)
    // before the animation begins — prevents the browser from batching
    // the initial hidden state with the animation start on fast loads.
    requestAnimationFrame(() => {
        requestAnimationFrame(() => {
            window.modulePageFX = new ModulePageFX();
        });
    });
}

document.addEventListener('DOMContentLoaded', startFX);

// Handle bfcache: when user navigates back/forward, DOMContentLoaded
// won't fire again. Re-run FX so the entrance animation always plays.
// Run immediately (no double-rAF needed — page was already painted).
window.addEventListener('pageshow', (e) => {
    if (e.persisted) {
        window.modulePageFX = new ModulePageFX();
    }
});
