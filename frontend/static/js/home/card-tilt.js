/* ============================================
   V3 Card Tilt Controller
   Mouse-tracked 3D rotation with spring lerp
   + sibling dimming on hover
   Entirely additive — delete this file to revert
   ============================================ */

class CardTilt {
    constructor() {
        this.cards = [];
        this.container = null;
        this.rafId = null;
        this.currentHovered = null;

        // Tilt limits
        this.maxRotateX = 8;    // degrees
        this.maxRotateY = 12;   // degrees
        this.liftY = -12;       // px hover lift
        this.scaleHover = 1.03;
        this.dimScale = 0.98;   // scale for dimmed siblings

        // Spring lerp factor (0.08=smooth, 0.15=snappy)
        this.lerp = 0.12;

        // Per-card spring state
        this.states = new Map();

        this._onEnter = this._onEnter.bind(this);
        this._onMove = this._onMove.bind(this);
        this._onLeave = this._onLeave.bind(this);
    }

    init() {
        // Skip on touch devices — tilt is mouse-only
        if ('ontouchstart' in window || navigator.maxTouchPoints > 0) return;

        this.container = document.getElementById('vision-cards');
        if (!this.container) return;

        this.cards = [...this.container.querySelectorAll('.hcard')];
        if (this.cards.length === 0) return;

        this.cards.forEach(card => {
            this.states.set(card, {
                currentRX: 0, currentRY: 0,
                currentScale: 1, currentLift: 0,
                currentBrightness: 1,
                targetRX: 0, targetRY: 0,
                targetScale: 1, targetLift: 0,
                targetBrightness: 1
            });

            card.addEventListener('mouseenter', this._onEnter);
            card.addEventListener('mousemove', this._onMove);
            card.addEventListener('mouseleave', this._onLeave);
        });

        this._animate();
    }

    _onEnter(e) {
        const card = e.currentTarget;
        if (!card.dataset.tiltReady) return;

        this.currentHovered = card;
        const st = this.states.get(card);
        st.targetScale = this.scaleHover;
        st.targetLift = this.liftY;
        st.targetBrightness = 1.08;

        // Dim siblings
        this.cards.forEach(c => {
            if (c !== card && c.dataset.tiltReady) {
                c.classList.add('hcard-dimmed');
                const s = this.states.get(c);
                s.targetScale = this.dimScale;
            }
        });
    }

    _onMove(e) {
        const card = e.currentTarget;
        if (!card.dataset.tiltReady) return;

        const rect = card.getBoundingClientRect();
        const cx = rect.left + rect.width / 2;
        const cy = rect.top + rect.height / 2;

        // -1 to 1 normalized
        const nx = (e.clientX - cx) / (rect.width / 2);
        const ny = (e.clientY - cy) / (rect.height / 2);

        const st = this.states.get(card);
        st.targetRY = nx * this.maxRotateY;
        st.targetRX = -ny * this.maxRotateX;
    }

    _onLeave(e) {
        const card = e.currentTarget;
        this.currentHovered = null;

        const st = this.states.get(card);
        st.targetRX = 0;
        st.targetRY = 0;
        st.targetScale = 1;
        st.targetLift = 0;
        st.targetBrightness = 1;

        // Un-dim siblings
        this.cards.forEach(c => {
            c.classList.remove('hcard-dimmed');
            const s = this.states.get(c);
            if (c !== card) s.targetScale = 1;
        });
    }

    _animate() {
        const f = this.lerp;

        this.states.forEach((st, card) => {
            if (!card.dataset.tiltReady) return;

            st.currentRX += (st.targetRX - st.currentRX) * f;
            st.currentRY += (st.targetRY - st.currentRY) * f;
            st.currentScale += (st.targetScale - st.currentScale) * f;
            st.currentLift += (st.targetLift - st.currentLift) * f;
            st.currentBrightness += (st.targetBrightness - st.currentBrightness) * f;

            card.style.transform =
                `perspective(800px) ` +
                `rotateX(${st.currentRX.toFixed(2)}deg) ` +
                `rotateY(${st.currentRY.toFixed(2)}deg) ` +
                `translateY(${st.currentLift.toFixed(1)}px) ` +
                `scale(${st.currentScale.toFixed(4)})`;

            card.style.filter = `brightness(${st.currentBrightness.toFixed(3)})`;
        });

        this.rafId = requestAnimationFrame(() => this._animate());
    }

    destroy() {
        if (this.rafId) cancelAnimationFrame(this.rafId);

        this.cards.forEach(card => {
            card.removeEventListener('mouseenter', this._onEnter);
            card.removeEventListener('mousemove', this._onMove);
            card.removeEventListener('mouseleave', this._onLeave);
            card.style.transform = '';
            card.style.filter = '';
            card.classList.remove('hcard-dimmed');
            delete card.dataset.tiltReady;
        });

        this.states.clear();
    }
}

// Global instance — init() called from vision-ripple.js after materialize completes
window.cardTilt = new CardTilt();
