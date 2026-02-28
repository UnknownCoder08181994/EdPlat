/* ============================================
   HumanoidCardReveal — Extension Methods
   Content animation, typewriter, and reset logic.
   Loaded after humanoid-ripple.js (core class).
   ============================================ */

HumanoidCardReveal.prototype.animateContentIn = function() {
    // Header fades in immediately after wave
    const header = document.querySelector('.humanoid-header');
    if (header) {
        header.classList.add('revealed');
    }

    // Typewriter for subtitle — starts after title words finish staggering (~800ms)
    this._later(() => this.startTypewriter(), 800);

    // Cards pop in staggered from center
    const animDuration = 600;
    this.cards.forEach((card, i) => {
        const delay = 10 + i * 120;
        this._later(() => {
            card.classList.add('summoned');
            // Play card preview video when card flies in
            const vid = card.querySelector('.hcard-vid');
            if (vid) { vid.currentTime = 0; vid.play(); }
        }, delay);
        // Spawn mesh burst when card lands (~40% through animation is the overshoot peak)
        this._later(() => {
            this.spawnMeshBurst(card);
        }, delay + animDuration * 0.35);
    });

    // Start neon race lines after content settles
    this._later(() => {
        if (window.neonGridLines) window.neonGridLines.init();
    }, 100);

    // Release animation fill mode after cards settle
    this._later(() => {
        this.cards.forEach(card => {
            card.style.opacity = '1';
            card.style.transform = 'scale(1) translateY(0)';
            card.style.animation = 'none';
        });
    }, 900);
};

HumanoidCardReveal.prototype.startTypewriter = function() {
    const el = document.querySelector('.hsub-typed');
    const cursor = document.querySelector('.hsub-cursor');
    if (!el) return;

    // Cancel any previous typewriter
    if (this._typeRafId) { cancelAnimationFrame(this._typeRafId); this._typeRafId = null; }

    const text = 'An interactive learning platform built for everyone. Hands-on modules, visual walkthroughs, and a built-in coach \u2014 all self-paced, all real-world.';
    let i = 0;
    const msPerChar = 22;
    let lastChar = performance.now();

    const step = (now) => {
        if (i >= text.length) {
            this._typeRafId = null;
            return;
        }
        const elapsed = now - lastChar;
        const charsToWrite = Math.min(Math.max(Math.floor(elapsed / msPerChar), 1), 3);
        const end = Math.min(i + charsToWrite, text.length);
        el.textContent += text.substring(i, end);
        i = end;
        lastChar = now;

        if (i < text.length) {
            this._typeRafId = requestAnimationFrame(step);
        } else {
            this._typeRafId = null;
        }
    };

    this._typeRafId = requestAnimationFrame(step);
};

HumanoidCardReveal.prototype.revealCards = function() {
    this.rematerializeBackdrop();
};

HumanoidCardReveal.prototype.resetPage2 = function() {
    // Cancel wave animation rAF (if wave was mid-progress)
    if (this._waveRafId) { cancelAnimationFrame(this._waveRafId); this._waveRafId = null; }

    // Cancel typewriter rAF
    if (this._typeRafId) { cancelAnimationFrame(this._typeRafId); this._typeRafId = null; }

    // Cancel all pending animateContentIn timers
    this._pendingTimers.forEach(id => clearTimeout(id));
    this._pendingTimers.length = 0;

    // Remove any leftover wave canvases
    const section = document.getElementById('humanoid');
    if (section) {
        section.querySelectorAll('.wave-canvas').forEach(c => c.remove());
    }

    // Reset header
    const header = document.querySelector('.humanoid-header');
    if (header) header.classList.remove('revealed');

    // Reset subtitle typewriter
    const typedEl = document.querySelector('.hsub-typed');
    if (typedEl) typedEl.textContent = '';

    // Reset cards — remove summoned, reset opacity/animation, pause preview videos
    this.cards.forEach(card => {
        card.classList.remove('summoned');
        card.style.opacity = '';
        card.style.transform = '';
        card.style.animation = '';
        const vid = card.querySelector('.hcard-vid');
        if (vid) vid.pause();
    });

    // Hide grid background
    if (section) section.classList.remove('h2-grid-ready');

    // Hide backdrop (bluefield) — wave will re-reveal it
    if (this.backdrop) {
        const labVid = this.backdrop.querySelector('.h2-lab-video');
        if (labVid) labVid.pause();
        this.backdrop.style.opacity = '0';
        this.backdrop.style.clipPath = '';
        this.backdrop.classList.remove('lab-active');
    }

    // Restore humanoid overlay (was hidden after wave)
    if (section) {
        const overlay = section.querySelector('.humanoid-overlay');
        if (overlay) overlay.style.display = '';
    }

    // Reset humanoid video to beginning so it replays
    if (this.vid) {
        this.vid.currentTime = 0;
        this.vid.pause();
    }

    // Allow the wave sequence to fire again
    this.fired = false;
};
