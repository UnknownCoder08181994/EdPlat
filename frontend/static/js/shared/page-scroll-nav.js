/* page-scroll-nav.js — scroll/swipe/keyboard triggers page navigation
   Config via window.__pageNav = { prev, next, current, faqCarousel, waitForSplash }  */
(function(){
    var cfg = window.__pageNav;
    if (!cfg) return;

    var prev = cfg.prev || null;
    var next = cfg.next || null;
    var overlay = document.getElementById('page-fade-overlay');
    var navigating = false;
    var locked = !!cfg.waitForSplash;
    var accumulated = 0;
    var wheelTimer = null;

    /* Wait for splash/cinematic to finish before enabling scroll nav */
    if (locked) {
        document.addEventListener('cinematic-done', function(){ locked = false; }, { once: true });
        /* Safety: unlock after 12s in case event never fires */
        setTimeout(function(){ locked = false; }, 12000);
    }

    /* FAQ carousel edge-scroll state */
    var faqEdgeReady = false;
    var faqEdgeTimer = null;
    var faqCooldown = false;

    function go(url) {
        if (navigating || !url) return;
        navigating = true;
        if (overlay) {
            overlay.style.pointerEvents = 'all';
            overlay.style.transition = 'opacity 0.35s ease';
            overlay.style.opacity = '1';
            setTimeout(function(){ window.location.href = url; }, 360);
        } else {
            window.location.href = url;
        }
    }

    /* ---- Wheel ---- */
    window.addEventListener('wheel', function(e) {
        if (navigating || locked) { e.preventDefault(); return; }
        var dir = e.deltaY > 0 ? 1 : -1;

        /* FAQ carousel: scroll through cards first */
        if (cfg.faqCarousel && window._faqCarousel) {
            var fc = window._faqCarousel;
            var atFirst = fc.current === 0;
            var atLast  = fc.current === fc.total - 1;

            if (dir === 1 && !atLast) {
                e.preventDefault();
                if (!faqCooldown) { fc.go(fc.current + 1); faqCooldown = true; setTimeout(function(){ faqCooldown = false; }, 400); }
                faqEdgeReady = false; accumulated = 0; return;
            }
            if (dir === -1 && !atFirst) {
                e.preventDefault();
                if (!faqCooldown) { fc.go(fc.current - 1); faqCooldown = true; setTimeout(function(){ faqCooldown = false; }, 400); }
                faqEdgeReady = false; accumulated = 0; return;
            }

            /* At edge — require a second scroll to leave */
            if ((dir === -1 && atFirst) || (dir === 1 && atLast)) {
                if (!faqEdgeReady) {
                    e.preventDefault();
                    faqEdgeReady = true;
                    if (faqEdgeTimer) clearTimeout(faqEdgeTimer);
                    faqEdgeTimer = setTimeout(function(){ faqEdgeReady = false; }, 1500);
                    accumulated = 0; return;
                }
                faqEdgeReady = false;
                if (faqEdgeTimer) { clearTimeout(faqEdgeTimer); faqEdgeTimer = null; }
            }
        }

        e.preventDefault();
        accumulated += e.deltaY;
        if (wheelTimer) clearTimeout(wheelTimer);
        wheelTimer = setTimeout(function(){ accumulated = 0; }, 200);

        if (Math.abs(accumulated) > 50) {
            go(accumulated > 0 ? next : prev);
            accumulated = 0;
        }
    }, { passive: false });

    /* ---- Touch ---- */
    var ty = 0, tx = 0;
    window.addEventListener('touchstart', function(e){ ty = e.touches[0].clientY; tx = e.touches[0].clientX; }, { passive: true });
    window.addEventListener('touchend', function(e){
        if (navigating || locked) return;
        var dy = ty - e.changedTouches[0].clientY;
        var dx = tx - e.changedTouches[0].clientX;
        if (Math.abs(dy) < 50 || Math.abs(dx) > Math.abs(dy)) return;
        go(dy > 0 ? next : prev);
    }, { passive: true });

    /* ---- Keyboard ---- */
    window.addEventListener('keydown', function(e){
        if (navigating || locked) return;
        if (e.key === 'ArrowDown' || e.key === 'PageDown') { if (next) { e.preventDefault(); go(next); } }
        else if (e.key === 'ArrowUp' || e.key === 'PageUp') { if (prev) { e.preventDefault(); go(prev); } }
    });

    /* ---- Pill navigation ---- */
    var pill = document.getElementById('fp-pill');
    if (pill) {
        var bars = pill.querySelectorAll('.pill-bar[data-href]');
        bars.forEach(function(bar){
            bar.style.cursor = 'pointer';
            bar.addEventListener('click', function(){ go(bar.dataset.href); });
        });
        var track = pill.querySelector('.pill-text-track');
        if (track) {
            track.style.cursor = 'pointer';
            track.addEventListener('click', function(){ go(next); });
        }
    }
})();
