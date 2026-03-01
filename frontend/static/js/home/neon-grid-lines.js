/* ============================================
   Neon Grid Race Lines — Silver Edition
   Tracer lines race along the grid behind cards.
   Fires in 10-second bursts, staggered from
   the grid sweep animation (fires at 5-7s mark).
   ============================================ */

class NeonGridLines {
    constructor() {
        this.canvas = null;
        this.ctx = null;
        this.lines = [];
        this.running = false;
        this.dpr = Math.min(window.devicePixelRatio || 1, 2);

        this.gridSpacing = 46; // ~2.4vw at 1920px, recalculated on resize

        this.maxLines = 10;
        this.spawnInterval = 180;
        this.lastSpawn = 0;

        // 10-second cycle
        this.cycleInterval = 10000;
        this.initTime = 0;

        this.hLines = [];
        this.vLines = [];

        // Silver color palette
        this.colors = [
            { r: 110, g: 115, b: 130 },
            { r: 120, g: 125, b: 140 },
            { r: 100, g: 105, b: 120 },
            { r: 130, g: 135, b: 150 },
        ];
    }

    init() {
        const section = document.getElementById('vision');
        if (!section || this.canvas) return;

        this.canvas = document.createElement('canvas');
        this.canvas.className = 'h2-neon-lines-canvas';

        // Insert after grid sweep div
        const sweep = section.querySelector('.h2-grid-sweep');
        if (sweep && sweep.nextSibling) {
            section.insertBefore(this.canvas, sweep.nextSibling);
        } else {
            section.appendChild(this.canvas);
        }

        this.ctx = this.canvas.getContext('2d');
        this.resize();
        this.bindEvents();

        this.canvas.style.opacity = '0';
        requestAnimationFrame(() => {
            this.canvas.style.opacity = '1';
        });

        this.running = true;
        this.initTime = performance.now();
        this.lastTime = this.initTime;
        this.lastSpawn = this.initTime;
        this.animate(this.lastTime);
    }

    resize() {
        const parent = this.canvas.parentElement;
        if (!parent) return;

        const rect = parent.getBoundingClientRect();
        this.w = rect.width || window.innerWidth;
        this.h = rect.height || window.innerHeight;
        this.canvas.width = Math.round(this.w * this.dpr);
        this.canvas.height = Math.round(this.h * this.dpr);
        this.ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);

        // Match CSS grid spacing (2.4vw)
        this.gridSpacing = Math.round(this.w * 0.024);

        this.hLines = [];
        this.vLines = [];
        for (let y = 0; y <= this.h; y += this.gridSpacing) {
            this.hLines.push(y);
        }
        for (let x = 0; x <= this.w; x += this.gridSpacing) {
            this.vLines.push(x);
        }
    }

    spawnLine() {
        const isH = Math.random() < 0.5;
        const fromStart = Math.random() < 0.5;

        let gridLine, startPos, dir;

        if (isH) {
            gridLine = this.hLines[Math.floor(Math.random() * this.hLines.length)];
            startPos = fromStart ? -80 : this.w + 80;
            dir = fromStart ? 1 : -1;
        } else {
            gridLine = this.vLines[Math.floor(Math.random() * this.vLines.length)];
            startPos = fromStart ? -80 : this.h + 80;
            dir = fromStart ? 1 : -1;
        }

        const color = this.colors[Math.floor(Math.random() * this.colors.length)];
        const speed = 120 + Math.random() * 180;
        const tailLen = 60 + Math.random() * 120;
        const maxTravel = (isH ? this.w : this.h) + 160 + tailLen;

        return {
            isH,
            gridLine,
            headPos: startPos,
            dir,
            speed,
            tailLen,
            maxTravel,
            traveled: 0,
            color,
            opacity: 0.6 + Math.random() * 0.3,
            width: 1 + Math.random() * 1,
            alive: true,
        };
    }

    update(dt) {
        const now = performance.now();

        // 10-second cycle — burst at 5-7s mark (when grid sweep is paused)
        const cyclePos = (now - this.initTime) % this.cycleInterval;
        const inBurstWindow = cyclePos >= 5000 && cyclePos < 7000;

        if (inBurstWindow && now - this.lastSpawn > this.spawnInterval && this.lines.length < this.maxLines) {
            this.lines.push(this.spawnLine());
            this.lastSpawn = now;
            this.spawnInterval = 150 + Math.random() * 200;
        }

        for (const l of this.lines) {
            l.headPos += l.dir * l.speed * dt;
            l.traveled += l.speed * dt;
            if (l.traveled > l.maxTravel) l.alive = false;
        }

        this.lines = this.lines.filter(l => l.alive);
    }

    draw() {
        const ctx = this.ctx;
        ctx.clearRect(0, 0, this.w, this.h);

        for (const l of this.lines) {
            const { isH, gridLine, headPos, dir, tailLen, color, opacity, width } = l;
            if (gridLine == null || !isFinite(gridLine) || !isFinite(headPos)) continue;
            const tailPos = headPos - dir * tailLen;
            const { r, g, b } = color;

            let x1, y1, x2, y2;
            if (isH) {
                x1 = tailPos; y1 = gridLine;
                x2 = headPos; y2 = gridLine;
            } else {
                x1 = gridLine; y1 = tailPos;
                x2 = gridLine; y2 = headPos;
            }

            // Glow pass
            const glowGrad = ctx.createLinearGradient(x1, y1, x2, y2);
            glowGrad.addColorStop(0, `rgba(${r},${g},${b},0)`);
            glowGrad.addColorStop(0.5, `rgba(${r},${g},${b},${opacity * 0.12})`);
            glowGrad.addColorStop(1, `rgba(${r},${g},${b},${opacity * 0.35})`);
            ctx.beginPath();
            ctx.moveTo(x1, y1);
            ctx.lineTo(x2, y2);
            ctx.strokeStyle = glowGrad;
            ctx.lineWidth = width + 4;
            ctx.lineCap = 'round';
            ctx.stroke();

            // Main line
            const grad = ctx.createLinearGradient(x1, y1, x2, y2);
            grad.addColorStop(0, `rgba(${r},${g},${b},0)`);
            grad.addColorStop(0.4, `rgba(${r},${g},${b},${opacity * 0.4})`);
            grad.addColorStop(0.8, `rgba(${r},${g},${b},${opacity * 0.7})`);
            grad.addColorStop(1, `rgba(${r},${g},${b},${opacity})`);
            ctx.beginPath();
            ctx.moveTo(x1, y1);
            ctx.lineTo(x2, y2);
            ctx.strokeStyle = grad;
            ctx.lineWidth = width;
            ctx.lineCap = 'round';
            ctx.stroke();

            // Head dot
            const hx = isH ? headPos : gridLine;
            const hy = isH ? gridLine : headPos;
            const hr = Math.min(r + 40, 255);
            const hg = Math.min(g + 40, 255);
            const hb = Math.min(b + 40, 255);
            const headGlow = ctx.createRadialGradient(hx, hy, 0, hx, hy, 6);
            headGlow.addColorStop(0, `rgba(${hr},${hg},${hb},${opacity * 0.8})`);
            headGlow.addColorStop(0.4, `rgba(${r},${g},${b},${opacity * 0.5})`);
            headGlow.addColorStop(1, `rgba(${r},${g},${b},0)`);
            ctx.beginPath();
            ctx.arc(hx, hy, 6, 0, Math.PI * 2);
            ctx.fillStyle = headGlow;
            ctx.fill();
        }
    }

    animate(now) {
        if (!this.running) return;

        const dt = Math.min((now - this.lastTime) / 1000, 0.05);
        this.lastTime = now;

        this.update(dt);
        this.draw();

        requestAnimationFrame(t => this.animate(t));
    }

    pause() {
        this.running = false;
    }

    resume() {
        if (this.running) return;
        this.running = true;
        this.lastTime = performance.now();
        this.animate(this.lastTime);
    }

    bindEvents() {
        let timer;
        window.addEventListener('resize', () => {
            clearTimeout(timer);
            timer = setTimeout(() => this.resize(), 200);
        }, { passive: true });

        document.addEventListener('visibilitychange', () => {
            if (document.hidden) this.pause();
            else if (this._onSection) this.resume();
        });

        document.addEventListener('section-revealed', (e) => {
            if (e.detail && e.detail.index === 1) {
                this._onSection = true;
                if (this.canvas && !this.running) this.resume();
            } else {
                this._onSection = false;
                this.pause();
            }
        });
    }
}

/* Neon grid race lines disabled — grid sweep used instead */
// document.addEventListener('DOMContentLoaded', () => {
//     window.neonGridLines = new NeonGridLines();
// });
