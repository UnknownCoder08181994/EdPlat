/* Input handlers for FullpageScroll */
FullpageScroll.prototype.bindWheel = function() {
    let wheelTimeout = null;
    let accumulated = 0;
    let edgeGestureReady = false; // true after a full gesture lands at edge
    let edgeGestureDir = 0;
    let edgeGestureTimer = null;
    let faqCooldown = false;
    let faqEdgeReady = false;  // true after one scroll at boundary (needs 2nd scroll to leave)
    let faqEdgeTimer = null;

    window.addEventListener('wheel', (e) => {
        if (this.isLocked || this.isTransitioning) {
            e.preventDefault();
            return;
        }

        // Sections with scrollable children: scroll the child with edge-snap support
        const currentSection = this.sections[this.current];
        if (currentSection) {
            const scrollEl = this.getScrollableChild(currentSection);
            if (scrollEl && scrollEl !== currentSection) {
                const scrollTop = scrollEl.scrollTop;
                const scrollHeight = scrollEl.scrollHeight;
                const clientHeight = scrollEl.clientHeight;
                const hasOverflow = scrollHeight > clientHeight + 5;

                if (hasOverflow) {
                    const atBottom = scrollTop + clientHeight >= scrollHeight - 5;
                    const atTop = scrollTop <= 5;
                    const dir = e.deltaY > 0 ? 1 : -1; // 1=down, -1=up

                    // At edge and scrolling further past it
                    if ((dir === 1 && atBottom) || (dir === -1 && atTop)) {
                        // If we already flagged ready from a previous gesture, snap now
                        if (edgeGestureReady && edgeGestureDir === dir) {
                            edgeGestureReady = false;
                            if (edgeGestureTimer) { clearTimeout(edgeGestureTimer); edgeGestureTimer = null; }
                            // Fall through to snap logic below
                        } else {
                            // First gesture hitting edge — flag it, absorb events
                            if (edgeGestureTimer) clearTimeout(edgeGestureTimer);
                            edgeGestureDir = dir;
                            edgeGestureTimer = setTimeout(() => {
                                edgeGestureReady = true;
                                edgeGestureTimer = setTimeout(() => {
                                    edgeGestureReady = false;
                                    edgeGestureTimer = null;
                                }, 1500);
                            }, 300);
                            e.preventDefault();
                            return;
                        }
                    } else {
                        // Not at edge — scroll normally, reset edge state
                        e.preventDefault();
                        scrollEl.scrollTop += e.deltaY;
                        edgeGestureReady = false;
                        edgeGestureDir = 0;
                        if (edgeGestureTimer) { clearTimeout(edgeGestureTimer); edgeGestureTimer = null; }
                        return;
                    }
                }
            }
        }

        // FAQ carousel intercept: scroll cards, only allow section change at boundaries
        if (this.current === 2 && window._faqCarousel) {
            const fc = window._faqCarousel;
            const dir = e.deltaY > 0 ? 1 : -1; // 1=down, -1=up
            const atFirst = fc.current === 0;
            const atLast = fc.current === fc.total - 1;

            if (dir === -1 && !atFirst) {
                e.preventDefault();
                if (!faqCooldown) {
                    fc.go(fc.current - 1);
                    faqCooldown = true;
                    setTimeout(() => { faqCooldown = false; }, 400);
                }
                faqEdgeReady = false;
                accumulated = 0;
                return;
            }
            if (dir === 1 && !atLast) {
                e.preventDefault();
                if (!faqCooldown) {
                    fc.go(fc.current + 1);
                    faqCooldown = true;
                    setTimeout(() => { faqCooldown = false; }, 400);
                }
                faqEdgeReady = false;
                accumulated = 0;
                return;
            }

            // At boundary — require a second scroll gesture to leave
            if ((dir === -1 && atFirst) || (dir === 1 && atLast)) {
                if (!faqEdgeReady) {
                    // First scroll at edge — absorb it, flag ready
                    e.preventDefault();
                    faqEdgeReady = true;
                    if (faqEdgeTimer) clearTimeout(faqEdgeTimer);
                    faqEdgeTimer = setTimeout(() => { faqEdgeReady = false; }, 1500);
                    accumulated = 0;
                    return;
                }
                // Second scroll at edge — clear flag and fall through to section change
                faqEdgeReady = false;
                if (faqEdgeTimer) { clearTimeout(faqEdgeTimer); faqEdgeTimer = null; }
            }
        }

        e.preventDefault();

        accumulated += e.deltaY;

        if (wheelTimeout) clearTimeout(wheelTimeout);
        wheelTimeout = setTimeout(() => { accumulated = 0; }, 200);

        if (Math.abs(accumulated) > 50) {
            if (accumulated > 0) {
                this.goTo(this.current + 1);
            } else {
                this.goTo(this.current - 1);
            }
            accumulated = 0;
        }
    }, { passive: false });
};

FullpageScroll.prototype.bindTouch = function() {
    window.addEventListener('touchstart', (e) => {
        this.touchStartY = e.touches[0].clientY;
        this.touchStartX = e.touches[0].clientX;
    }, { passive: true });

    window.addEventListener('touchend', (e) => {
        if (this.isLocked || this.isTransitioning) return;

        const deltaY = this.touchStartY - e.changedTouches[0].clientY;
        const deltaX = this.touchStartX - e.changedTouches[0].clientX;

        // Only vertical swipes
        if (Math.abs(deltaY) < 50 || Math.abs(deltaX) > Math.abs(deltaY)) return;

        // Sections with scrollable children: only snap if at the scroll edge
        const currentSection = this.sections[this.current];
        if (currentSection) {
            const scrollEl = this.getScrollableChild(currentSection);
            if (scrollEl && scrollEl !== currentSection) {
                const st = scrollEl.scrollTop;
                const sh = scrollEl.scrollHeight;
                const ch = scrollEl.clientHeight;
                const atTop = st <= 5;
                const atBottom = st + ch >= sh - 5;
                if (deltaY > 0 && !atBottom) return; // swiping to next but not at bottom
                if (deltaY < 0 && !atTop) return;    // swiping to prev but not at top
            }
        }

        if (deltaY > 0) {
            this.goTo(this.current + 1);
        } else {
            this.goTo(this.current - 1);
        }
    }, { passive: true });
};

FullpageScroll.prototype.bindKeyboard = function() {
    window.addEventListener('keydown', (e) => {
        if (this.isLocked || this.isTransitioning) return;

        switch (e.key) {
            case 'ArrowDown':
            case 'PageDown':
            case ' ':
                e.preventDefault();
                this.goTo(this.current + 1);
                break;
            case 'ArrowUp':
            case 'PageUp':
                e.preventDefault();
                this.goTo(this.current - 1);
                break;
            case 'Home':
                e.preventDefault();
                this.goTo(0);
                break;
            case 'End':
                e.preventDefault();
                this.goTo(this.total - 1);
                break;
        }
    });
};

// bindDots removed — replaced by bindPill in fullpage-core.js
FullpageScroll.prototype.bindDots = function() {};

document.addEventListener('DOMContentLoaded', () => {
    const fp = new FullpageScroll();
    window._fpInstance = fp;

    // Home nav link on homepage scrolls to gateway (section 0)
    const homeLink = document.querySelector('[data-nav-home]');
    if (homeLink && document.getElementById('fp-wrapper')) {
        homeLink.href = '#gateway';
        homeLink.addEventListener('click', () => {
            fp.goTo(0);
        });
    }

    // data-scroll-to links scroll to a section by index
    document.querySelectorAll('[data-scroll-to]').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const target = parseInt(link.dataset.scrollTo, 10);
            fp.goTo(target);
        });
    });
});
