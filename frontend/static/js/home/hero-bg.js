/* ============================================
   AWM V2 — Futuristic Particle Network Background
   Flowing neural-net particles with connecting
   lines, depth, and reactive mouse interaction
   ============================================ */

class HeroBackground {
    constructor(canvas) {
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');
        this.dpr = Math.min(window.devicePixelRatio || 1, 2);
        this.mouse = { x: -1000, y: -1000 };
        this.smoothMouse = { x: -1000, y: -1000 };
        this.time = 0;
        this.particles = [];
        this.connectionDistance = 140;
        this.mouseRadius = 200;

        this.resize();
        this.initParticles();
        this.bindEvents();
        this.animate();
    }

    resize() {
        this.w = window.innerWidth;
        this.h = window.innerHeight;
        this.canvas.width = Math.round(this.w * this.dpr);
        this.canvas.height = Math.round(this.h * this.dpr);
        this.canvas.style.width = this.w + 'px';
        this.canvas.style.height = this.h + 'px';
        this.ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    }

    initParticles() {
        this.particles = [];
        const area = this.w * this.h;
        let count = Math.min(Math.floor(area / 6000), 250);

        // Reduce particles on small screens for performance
        if (this.w < 768) {
            count = Math.min(count, 60);
        } else if (this.w < 1024) {
            count = Math.min(count, 120);
        }

        for (let i = 0; i < count; i++) {
            this.particles.push(this.createParticle());
        }
    }

    createParticle() {
        const depth = Math.random(); // 0 = far, 1 = near
        return {
            x: Math.random() * this.w,
            y: Math.random() * this.h,
            vx: (Math.random() - 0.5) * 0.4 * (0.3 + depth * 0.7),
            vy: (Math.random() - 0.5) * 0.3 * (0.3 + depth * 0.7),
            baseVx: (Math.random() - 0.5) * 0.4,
            baseVy: (Math.random() - 0.5) * 0.3,
            size: 1 + depth * 2.5,
            depth: depth,
            alpha: 0.15 + depth * 0.45,
            hue: Math.random() < 0.6 ? 260 + Math.random() * 30 : 210 + Math.random() * 30, // purple or blue
            pulsePhase: Math.random() * Math.PI * 2,
            pulseSpeed: 0.5 + Math.random() * 1.5,
        };
    }

    bindEvents() {
        let resizeTimer;
        window.addEventListener('resize', () => {
            clearTimeout(resizeTimer);
            resizeTimer = setTimeout(() => {
                this.resize();
                this.initParticles();
            }, 200);
        });

        window.addEventListener('mousemove', (e) => {
            this.mouse.x = e.clientX;
            this.mouse.y = e.clientY;
        });

        window.addEventListener('mouseleave', () => {
            this.mouse.x = -1000;
            this.mouse.y = -1000;
        });
    }

    pause() {
        this.paused = true;
    }

    resume() {
        if (!this.paused) return;
        this.paused = false;
        this.animate();
    }

    animate() {
        if (this.paused) return;

        this.time += 0.016;
        this.smoothMouse.x += (this.mouse.x - this.smoothMouse.x) * 0.08;
        this.smoothMouse.y += (this.mouse.y - this.smoothMouse.y) * 0.08;

        this.update();
        this.draw();
        requestAnimationFrame(() => this.animate());
    }

    update() {
        const w = this.w;
        const h = this.h;
        const mx = this.smoothMouse.x;
        const my = this.smoothMouse.y;

        for (const p of this.particles) {
            // Base movement with drift
            const drift = Math.sin(this.time * 0.2 + p.pulsePhase) * 0.05;
            p.x += p.vx + drift;
            p.y += p.vy + Math.cos(this.time * 0.15 + p.pulsePhase) * 0.03;

            // Mouse — gentle repulsion (push away, no clustering)
            const dx = mx - p.x;
            const dy = my - p.y;
            const dist = Math.sqrt(dx * dx + dy * dy);
            if (dist < this.mouseRadius && dist > 1) {
                const force = (1 - dist / this.mouseRadius) * 0.004 * p.depth;
                p.x -= dx * force;
                p.y -= dy * force;
            }

            // Wrap around edges
            if (p.x < -20) p.x = w + 20;
            if (p.x > w + 20) p.x = -20;
            if (p.y < -20) p.y = h + 20;
            if (p.y > h + 20) p.y = -20;
        }
    }

    draw() {
        const ctx = this.ctx;
        const w = this.w;
        const h = this.h;
        const particles = this.particles;
        const mx = this.smoothMouse.x;
        const my = this.smoothMouse.y;
        const time = this.time;

        // Clear
        ctx.clearRect(0, 0, w, h);

        // Draw connections
        const connDist = this.connectionDistance;
        const connDistSq = connDist * connDist;

        for (let i = 0; i < particles.length; i++) {
            const a = particles[i];
            for (let j = i + 1; j < particles.length; j++) {
                const b = particles[j];
                const dx = a.x - b.x;
                const dy = a.y - b.y;
                const distSq = dx * dx + dy * dy;

                if (distSq < connDistSq) {
                    const dist = Math.sqrt(distSq);
                    const opacity = (1 - dist / connDist) * 0.15 * Math.min(a.depth, b.depth) * 1.5;

                    if (opacity > 0.01) {
                        // Determine line color — blend between purple and cyan
                        const midDepth = (a.depth + b.depth) / 2;
                        const r = Math.round(120 + midDepth * 47);
                        const g = Math.round(100 + midDepth * 40);
                        const bv = Math.round(200 + midDepth * 50);

                        ctx.beginPath();
                        ctx.moveTo(a.x, a.y);
                        ctx.lineTo(b.x, b.y);
                        ctx.strokeStyle = `rgba(${r}, ${g}, ${bv}, ${opacity})`;
                        ctx.lineWidth = 0.5 + midDepth * 0.5;
                        ctx.stroke();
                    }
                }
            }
        }

        // Draw mouse connections (subtle, only nearby + deep particles)
        if (mx > 0 && my > 0) {
            for (const p of particles) {
                if (p.depth < 0.5) continue; // skip far-away particles
                const dx = mx - p.x;
                const dy = my - p.y;
                const dist = Math.sqrt(dx * dx + dy * dy);

                if (dist < this.mouseRadius * 0.6) {
                    const opacity = (1 - dist / (this.mouseRadius * 0.6)) * 0.08 * p.depth;
                    ctx.beginPath();
                    ctx.moveTo(p.x, p.y);
                    ctx.lineTo(mx, my);
                    ctx.strokeStyle = `rgba(167, 139, 250, ${opacity})`;
                    ctx.lineWidth = 0.4;
                    ctx.stroke();
                }
            }
        }

        // Draw particles
        for (const p of particles) {
            const pulse = Math.sin(time * p.pulseSpeed + p.pulsePhase) * 0.3 + 0.7;
            const size = p.size * pulse;
            const alpha = p.alpha * pulse;

            // Check if near mouse (very subtle glow boost)
            let mouseBoost = 0;
            if (mx > 0 && my > 0) {
                const dx = mx - p.x;
                const dy = my - p.y;
                const dist = Math.sqrt(dx * dx + dy * dy);
                if (dist < this.mouseRadius) {
                    mouseBoost = (1 - dist / this.mouseRadius) * 0.15;
                }
            }

            // Outer glow
            const glowSize = size * 4;
            const gradient = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, glowSize);
            const hue = p.hue;
            gradient.addColorStop(0, `hsla(${hue}, 70%, 70%, ${(alpha * 0.3 + mouseBoost * 0.2)})`);
            gradient.addColorStop(0.4, `hsla(${hue}, 60%, 60%, ${(alpha * 0.1 + mouseBoost * 0.05)})`);
            gradient.addColorStop(1, `hsla(${hue}, 50%, 50%, 0)`);

            ctx.beginPath();
            ctx.arc(p.x, p.y, glowSize, 0, Math.PI * 2);
            ctx.fillStyle = gradient;
            ctx.fill();

            // Core
            ctx.beginPath();
            ctx.arc(p.x, p.y, size * (1 + mouseBoost * 0.5), 0, Math.PI * 2);
            ctx.fillStyle = `hsla(${hue}, 60%, 80%, ${alpha + mouseBoost * 0.3})`;
            ctx.fill();

            // Bright center point
            if (p.depth > 0.7) {
                ctx.beginPath();
                ctx.arc(p.x, p.y, size * 0.3, 0, Math.PI * 2);
                ctx.fillStyle = `rgba(255, 255, 255, ${alpha * 0.6})`;
                ctx.fill();
            }
        }

        // Central ambient glow
        const cx = w * 0.5;
        const cy = h * 0.45;
        const glowRadius = Math.min(w, h) * 0.5;
        const centralPulse = Math.sin(time * 0.3) * 0.02 + 1;
        const cGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, glowRadius * centralPulse);
        cGrad.addColorStop(0, 'rgba(167, 139, 250, 0.04)');
        cGrad.addColorStop(0.3, 'rgba(129, 140, 248, 0.02)');
        cGrad.addColorStop(0.6, 'rgba(96, 165, 250, 0.01)');
        cGrad.addColorStop(1, 'rgba(0, 0, 0, 0)');
        ctx.fillStyle = cGrad;
        ctx.fillRect(0, 0, w, h);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const canvas = document.getElementById('hero-canvas');
    if (canvas) window.heroBg = new HeroBackground(canvas);
});
