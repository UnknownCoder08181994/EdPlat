/* ============================================
   Vision Card Reveal Controller
   - No-video mode: cards animate in on section entry
   - Lab bg shown directly, no wave transition
   Extension: vision-ripple-ext.js (content animation + reset)
   ============================================ */

class VisionCardReveal {
    constructor() {
        this.cards = document.querySelectorAll('.hcard');
        this.backdrop = document.getElementById('vision-cards-backdrop');
        this.vid = document.querySelector('.vision-vid');
        this.fired = false;
        this.checking = false;
        this._waveRafId = null;
        this._pendingTimers = [];

        if (this.cards.length === 0) return;

        this.bindEvents();
    }

    bindEvents() {
        if (this.vid) {
            this.vid.addEventListener('loadedmetadata', () => {
                this.startTimeCheck();
            });

            if (this.vid.duration) {
                this.startTimeCheck();
            }
        }

        document.addEventListener('section-revealed', (e) => {
            const section = document.getElementById('vision');
            if (e.detail.index === 1) {
                // Entering vision — activate void door + portal emergence
                if (section) {
                    section.classList.add('h2-grid-ready');
                    section.classList.add('portal-active');
                    // Play portal screen videos
                    section.querySelectorAll('.screen-vid').forEach(v => {
                        v.currentTime = 0; v.play();
                    });
                    // Reveal header
                    const header = section.querySelector('.vision-header');
                    if (header) header.classList.add('revealed');
                    // Typewriter
                    setTimeout(() => this.startTypewriter(), 800);
                    // After emergence animations finish, add settled class for hover drift
                    setTimeout(() => {
                        section.querySelectorAll('.portal-screen').forEach(s => {
                            s.classList.add('emerged', 'settled');
                        });
                    }, 2500);
                }
            } else if (e.detail.index === 2) {
                // Entering features — reveal cards
                if (!this.vid) {
                    this.revealCardsNoVideo();
                }
            } else {
                // Leaving — reset
                this.resetPage2();
                if (section) {
                    section.classList.remove('portal-active');
                    section.querySelectorAll('.portal-screen').forEach(s => {
                        s.classList.remove('emerged', 'settled');
                    });
                    section.querySelectorAll('.screen-vid').forEach(v => v.pause());
                }
            }
        });
    }

    startTimeCheck() {
        if (this.checking) return;
        this.checking = true;

        const triggerTime = 3.55;

        this.vid.addEventListener('timeupdate', () => {
            if (!this.fired && this.vid.currentTime >= triggerTime) {
                this.fired = true;
                this.revealCards();
            }
        });
    }

    /* ------ No-video: animate cards immediately ------ */
    revealCardsNoVideo() {
        this.animateContentIn();
    }

    /* ------ Wave: replaces video with new page from left→right ------ */
    rematerializeBackdrop() {
        if (!this.backdrop) return;

        const section = this.backdrop.closest('.fp-section');
        if (!section) return;

        // Start bluefield video right as the wave begins
        const labVid = this.backdrop.querySelector('.h2-lab-video');
        if (labVid) { labVid.currentTime = 0; labVid.play(); }

        const el = this.backdrop;
        const labBg = el.querySelector('.h2-lab-bg');
        const sRect = section.getBoundingClientRect();
        const w = sRect.width;
        const h = sRect.height;

        // Show real lab bg immediately, but clip it to 0 width — wave expands it
        el.style.opacity = '1';
        if (labBg) labBg.style.opacity = '1';
        el.classList.add('lab-active');
        el.style.clipPath = 'inset(0 100% 0 0)';

        // Canvas on SECTION for techy edge tiles (above video z-0, below backdrop z-2 is tricky,
        // so put it at z-3 — just above backdrop, below content z-10)
        const canvas = document.createElement('canvas');
        canvas.className = 'wave-canvas';
        canvas.width = w;
        canvas.height = h;
        canvas.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;z-index:3;pointer-events:none;';
        section.appendChild(canvas);

        const ctx = canvas.getContext('2d');

        const tileSize = w < 768 ? 28 : 14;
        const cols = Math.ceil(w / tileSize);
        const rows = Math.ceil(h / tileSize);

        const jitter = new Float32Array(cols * rows);
        for (let i = 0; i < jitter.length; i++) {
            jitter[i] = (Math.random() - 0.5) * 0.06;
        }

        const duration = 1200;
        const waveWidth = 0.15;
        const start = performance.now();

        const animate = (now) => {
            // Bail out if reset happened while wave was running
            if (this._waveRafId === null) { canvas.remove(); return; }

            const elapsed = now - start;
            const progress = Math.min(elapsed / duration, 1);
            const waveFront = -waveWidth + progress * (1 + waveWidth * 2);

            ctx.clearRect(0, 0, w, h);

            // 1) Expand backdrop clip-path to reveal real lab bg behind the wave
            const settledNorm = Math.min(Math.max(waveFront - waveWidth, 0), 1);
            const clipRight = Math.max(100 - settledNorm * 100, 0);
            el.style.clipPath = `inset(0 ${clipRight}% 0 0)`;

            // 2) Techy edge tiles at wave front
            for (let col = 0; col < cols; col++) {
                const colNorm = col / cols;

                for (let row = 0; row < rows; row++) {
                    const idx = row * cols + col;
                    const tilePos = colNorm + jitter[idx];
                    const behindWave = waveFront - tilePos;

                    if (behindWave < 0) continue;

                    const tileProgress = Math.min(behindWave / waveWidth, 1);
                    const ease = tileProgress * tileProgress * tileProgress;

                    if (ease >= 0.98) continue; // settled — handled by the solid rect

                    const x = col * tileSize;
                    const y = row * tileSize;
                    const offsetX = (1 - ease) * -40;
                    const offsetY = (1 - ease) * (jitter[idx] * 200);
                    const size = tileSize * (0.6 + ease * 0.4);

                    const colorShift = ease * ease;
                    const gray = Math.round((1 - colorShift) * 200 + Math.random() * 40);
                    const blueTile = (idx % 5 === 0 || idx % 7 === 0);
                    const blueBoost = blueTile ? Math.round((1 - ease) * 55) : 0;
                    const r = Math.min(gray + Math.round((1 - ease) * 8), 255);
                    const g = Math.min(gray + Math.round((1 - ease) * 12) + (blueBoost >> 1), 255);
                    const b = Math.min(gray + Math.round((1 - ease) * 20) + blueBoost, 255);

                    ctx.globalAlpha = 0.4 + ease * 0.6;
                    ctx.fillStyle = `rgb(${r},${g},${b})`;
                    ctx.fillRect(
                        x + offsetX + (tileSize - size) * 0.5,
                        y + offsetY + (tileSize - size) * 0.5,
                        size, size
                    );
                }
            }

            // 3) Right of wave: transparent — video stays visible (nothing drawn)

            if (progress < 1) {
                this._waveRafId = requestAnimationFrame(animate);
            } else {
                this._waveRafId = null;

                // Wave done — remove clip-path, fade out canvas
                el.style.clipPath = '';

                canvas.style.transition = 'opacity 0.1s ease';
                canvas.style.opacity = '0';
                setTimeout(() => canvas.remove(), 150);

                // Bluefield now covers everything — pause vision video
                // and hide overlay behind it (no purpose once covered)
                if (this.vid) this.vid.pause();
                const overlay = section.querySelector('.vision-overlay');
                if (overlay) overlay.style.display = 'none';

                // Animate content in after wave
                this.animateContentIn();
            }
        };

        this._waveRafId = requestAnimationFrame(animate);
    }

    spawnMeshBurst(card) {
        const accent = card.dataset.accent;
        const colors = {
            cyan: 'rgba(140,145,160,',
            purple: 'rgba(140,145,160,',
            mixed: 'rgba(140,145,160,'
        };
        const base = colors[accent] || colors.cyan;
        const rect = card.getBoundingClientRect();
        const container = card.closest('.vision-content') || card.parentElement;
        const containerRect = container.getBoundingClientRect();

        const count = 35;
        const gridSize = 14; // match lab grid sub-grid

        for (let n = 0; n < count; n++) {
            const sq = document.createElement('div');
            sq.className = 'mesh-burst-sq';

            // Scatter around the card — biased toward edges
            const side = Math.random();
            let x, y;
            if (side < 0.25) {
                // left edge
                x = rect.left - containerRect.left - Math.random() * 80;
                y = rect.top - containerRect.top + Math.random() * rect.height;
            } else if (side < 0.5) {
                // right edge
                x = rect.right - containerRect.left + Math.random() * 80;
                y = rect.top - containerRect.top + Math.random() * rect.height;
            } else if (side < 0.75) {
                // top edge
                x = rect.left - containerRect.left + Math.random() * rect.width;
                y = rect.top - containerRect.top - Math.random() * 60;
            } else {
                // bottom edge
                x = rect.left - containerRect.left + Math.random() * rect.width;
                y = rect.bottom - containerRect.top + Math.random() * 60;
            }

            // Snap to grid for that digital feel
            x = Math.round(x / gridSize) * gridSize;
            y = Math.round(y / gridSize) * gridSize;

            const size = gridSize - 2;
            const opacity = 0.15 + Math.random() * 0.5;
            const delay = Math.random() * 200;
            const duration = 300 + Math.random() * 400;

            sq.style.cssText = `
                position: absolute;
                left: ${x}px;
                top: ${y}px;
                width: ${size}px;
                height: ${size}px;
                background: ${base}${opacity});
                border: 1px solid ${base}${opacity * 0.8});
                pointer-events: none;
                z-index: 3;
                opacity: 0;
                animation: mesh-sq-flash ${duration}ms ease-out ${delay}ms forwards;
            `;

            container.appendChild(sq);

            // Self-remove
            setTimeout(() => sq.remove(), delay + duration + 50);
        }
    }

    /* Schedule a timeout that can be cancelled by resetPage2 */
    _later(fn, ms) {
        const id = setTimeout(() => {
            const idx = this._pendingTimers.indexOf(id);
            if (idx !== -1) this._pendingTimers.splice(idx, 1);
            fn();
        }, ms);
        this._pendingTimers.push(id);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    new VisionCardReveal();
});
