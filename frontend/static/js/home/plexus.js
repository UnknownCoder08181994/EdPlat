/* Plexus network animation for Vision (page 2) */
(function () {
    const canvas = document.getElementById('plexus-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const section = canvas.closest('.fp-section');

    const NODE_COUNT = 80;
    const CONNECT_DIST = 160;
    const NODE_RADIUS = 2.8;
    let W, H, nodes = [], raf;

    function resize() {
        const rect = section.getBoundingClientRect();
        W = canvas.width = rect.width;
        H = canvas.height = rect.height;
    }

    function initNodes() {
        nodes = [];
        for (let i = 0; i < NODE_COUNT; i++) {
            nodes.push({
                x: Math.random() * W,
                y: Math.random() * H,
                vx: (Math.random() - 0.5) * 0.4,
                vy: (Math.random() - 0.5) * 0.4,
                r: NODE_RADIUS + Math.random() * 1.2
            });
        }
    }

    function draw() {
        ctx.clearRect(0, 0, W, H);

        // Draw connections
        for (let i = 0; i < nodes.length; i++) {
            for (let j = i + 1; j < nodes.length; j++) {
                const dx = nodes[i].x - nodes[j].x;
                const dy = nodes[i].y - nodes[j].y;
                const dist = Math.sqrt(dx * dx + dy * dy);
                if (dist < CONNECT_DIST) {
                    const alpha = (1 - dist / CONNECT_DIST) * 0.5;
                    ctx.beginPath();
                    ctx.moveTo(nodes[i].x, nodes[i].y);
                    ctx.lineTo(nodes[j].x, nodes[j].y);
                    ctx.strokeStyle = 'rgba(80, 80, 90, ' + alpha + ')';
                    ctx.lineWidth = 0.8;
                    ctx.stroke();
                }
            }
        }

        // Draw nodes
        for (let i = 0; i < nodes.length; i++) {
            const n = nodes[i];
            ctx.beginPath();
            ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
            ctx.fillStyle = 'rgba(90, 90, 100, 0.55)';
            ctx.fill();
        }
    }

    function update() {
        for (let i = 0; i < nodes.length; i++) {
            const n = nodes[i];
            n.x += n.vx;
            n.y += n.vy;
            if (n.x < 0 || n.x > W) n.vx *= -1;
            if (n.y < 0 || n.y > H) n.vy *= -1;
        }
    }

    function loop() {
        update();
        draw();
        raf = requestAnimationFrame(loop);
    }

    function start() {
        resize();
        initNodes();
        loop();
    }

    function stop() {
        if (raf) { cancelAnimationFrame(raf); raf = null; }
    }

    // Start/stop based on section visibility
    document.addEventListener('section-revealed', function (e) {
        if (e.detail.index === 1) {
            start();
        } else {
            stop();
        }
    });

    window.addEventListener('resize', function () {
        resize();
    });

    // Auto-start if section is already visible
    start();

    /* --- Focus subtitle fade-in (replaces typewriter) --- */
    window.resetFocusTypewriter = function () {
        // No-op — subtitle is now static HTML that fades in via CSS data-reveal
    };
})();
