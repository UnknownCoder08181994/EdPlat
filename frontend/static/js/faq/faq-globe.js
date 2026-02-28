/* ============================================
   FAQ Floating Particles — Light theme
   Drifting dots that gently float upward and
   pulse in opacity. Ambient, alive.
   ============================================ */

(function () {
    const canvas = document.getElementById('faq-particles');
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    let W, H, running = false, animId;
    let particles = [];

    const COUNT = 80;
    const MAX_RADIUS = 5;
    const MIN_RADIUS = 1.5;

    function resize() {
        W = canvas.width = canvas.parentElement.offsetWidth;
        H = canvas.height = canvas.parentElement.offsetHeight;
    }

    function init() {
        particles = [];
        for (let i = 0; i < COUNT; i++) {
            particles.push({
                x: Math.random() * W,
                y: Math.random() * H,
                r: MIN_RADIUS + Math.random() * (MAX_RADIUS - MIN_RADIUS),
                vx: (Math.random() - 0.5) * 0.35,
                vy: -0.2 - Math.random() * 0.3,              // drift upward
                phase: Math.random() * Math.PI * 2,           // pulse offset
                pulseSpeed: 0.0008 + Math.random() * 0.001,
                baseAlpha: 0.12 + Math.random() * 0.18,       // 0.12 – 0.30
            });
        }
    }

    function draw(t) {
        ctx.clearRect(0, 0, W, H);

        for (const p of particles) {
            // Update position
            p.x += p.vx;
            p.y += p.vy;

            // Wrap around edges
            if (p.y < -10) { p.y = H + 10; p.x = Math.random() * W; }
            if (p.x < -10) p.x = W + 10;
            if (p.x > W + 10) p.x = -10;

            // Pulsing alpha
            const pulse = Math.sin(t * p.pulseSpeed + p.phase);
            const alpha = p.baseAlpha + pulse * 0.08;

            ctx.beginPath();
            ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
            ctx.fillStyle = `rgba(150, 155, 175, ${Math.max(0.04, alpha)})`;
            ctx.fill();
        }
    }

    function render(t) {
        if (!running) return;
        draw(t);
        animId = requestAnimationFrame(render);
    }

    function start() {
        if (running) return;
        running = true;
        resize();
        if (!particles.length) init();
        animId = requestAnimationFrame(render);
    }

    function stop() {
        running = false;
        if (animId) cancelAnimationFrame(animId);
    }

    document.addEventListener('section-revealed', (e) => {
        if (e.detail.index === 2) start();
        else stop();
    });

    window.addEventListener('resize', () => {
        if (running) {
            resize();
            init();
        }
    });

    window.faqParticles = { start, stop };
})();
