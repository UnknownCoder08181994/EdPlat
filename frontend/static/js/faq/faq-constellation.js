/* ============================================
   FAQ Constellation Background
   Floating nodes with pulsing glows connected
   by shimmering lines — a neural-network feel.
   Only runs when FAQ section is active.
   ============================================ */

(function () {
    const canvas = document.getElementById('faq-constellation');
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    let width, height, nodes, animId, running = false;
    const NODE_COUNT = 65;
    const CONNECT_DIST = 180;
    const MOUSE_RADIUS = 200;
    let mouse = { x: -9999, y: -9999 };

    const COLORS = [
        { r: 139, g: 92, b: 246 },   // violet
        { r: 34, g: 211, b: 238 },   // cyan
        { r: 96, g: 165, b: 250 },   // blue
        { r: 244, g: 114, b: 182 },  // pink
        { r: 167, g: 139, b: 250 },  // lavender
    ];

    function resize() {
        width = canvas.width = window.innerWidth;
        height = canvas.height = window.innerHeight;
    }

    function createNodes() {
        nodes = [];
        for (let i = 0; i < NODE_COUNT; i++) {
            const color = COLORS[Math.floor(Math.random() * COLORS.length)];
            nodes.push({
                x: Math.random() * width,
                y: Math.random() * height,
                vx: (Math.random() - 0.5) * 0.4,
                vy: (Math.random() - 0.5) * 0.4,
                radius: Math.random() * 2 + 1,
                color,
                pulseOffset: Math.random() * Math.PI * 2,
                pulseSpeed: 0.01 + Math.random() * 0.02,
            });
        }
    }

    function drawNode(node, t) {
        const pulse = 0.5 + 0.5 * Math.sin(t * node.pulseSpeed + node.pulseOffset);
        const { r, g, b } = node.color;
        const glowRadius = node.radius + pulse * 6;

        // Outer glow
        const grad = ctx.createRadialGradient(node.x, node.y, 0, node.x, node.y, glowRadius);
        grad.addColorStop(0, `rgba(${r},${g},${b},${0.6 + pulse * 0.3})`);
        grad.addColorStop(0.4, `rgba(${r},${g},${b},${0.15 + pulse * 0.1})`);
        grad.addColorStop(1, `rgba(${r},${g},${b},0)`);

        ctx.beginPath();
        ctx.arc(node.x, node.y, glowRadius, 0, Math.PI * 2);
        ctx.fillStyle = grad;
        ctx.fill();

        // Core dot
        ctx.beginPath();
        ctx.arc(node.x, node.y, node.radius, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${r},${g},${b},${0.8 + pulse * 0.2})`;
        ctx.fill();
    }

    function drawConnections(t) {
        for (let i = 0; i < nodes.length; i++) {
            for (let j = i + 1; j < nodes.length; j++) {
                const dx = nodes[i].x - nodes[j].x;
                const dy = nodes[i].y - nodes[j].y;
                const dist = Math.sqrt(dx * dx + dy * dy);

                if (dist < CONNECT_DIST) {
                    const opacity = (1 - dist / CONNECT_DIST) * 0.25;
                    const { r: r1, g: g1, b: b1 } = nodes[i].color;
                    const { r: r2, g: g2, b: b2 } = nodes[j].color;

                    // Shimmer along the line
                    const shimmer = 0.5 + 0.5 * Math.sin(t * 0.003 + i + j);
                    const alpha = opacity * (0.5 + shimmer * 0.5);

                    const grad = ctx.createLinearGradient(
                        nodes[i].x, nodes[i].y, nodes[j].x, nodes[j].y
                    );
                    grad.addColorStop(0, `rgba(${r1},${g1},${b1},${alpha})`);
                    grad.addColorStop(1, `rgba(${r2},${g2},${b2},${alpha})`);

                    ctx.beginPath();
                    ctx.moveTo(nodes[i].x, nodes[i].y);
                    ctx.lineTo(nodes[j].x, nodes[j].y);
                    ctx.strokeStyle = grad;
                    ctx.lineWidth = 0.5 + (1 - dist / CONNECT_DIST) * 0.8;
                    ctx.stroke();
                }
            }
        }

        // Mouse connections
        for (let i = 0; i < nodes.length; i++) {
            const dx = nodes[i].x - mouse.x;
            const dy = nodes[i].y - mouse.y;
            const dist = Math.sqrt(dx * dx + dy * dy);

            if (dist < MOUSE_RADIUS) {
                const opacity = (1 - dist / MOUSE_RADIUS) * 0.35;
                const { r, g, b } = nodes[i].color;

                ctx.beginPath();
                ctx.moveTo(nodes[i].x, nodes[i].y);
                ctx.lineTo(mouse.x, mouse.y);
                ctx.strokeStyle = `rgba(${r},${g},${b},${opacity})`;
                ctx.lineWidth = 0.6;
                ctx.stroke();
            }
        }
    }

    function update() {
        for (const node of nodes) {
            node.x += node.vx;
            node.y += node.vy;

            // Gentle mouse repulsion
            const dx = node.x - mouse.x;
            const dy = node.y - mouse.y;
            const dist = Math.sqrt(dx * dx + dy * dy);
            if (dist < MOUSE_RADIUS && dist > 0) {
                const force = (1 - dist / MOUSE_RADIUS) * 0.02;
                node.vx += (dx / dist) * force;
                node.vy += (dy / dist) * force;
            }

            // Damping
            node.vx *= 0.999;
            node.vy *= 0.999;

            // Wrap around edges
            if (node.x < -20) node.x = width + 20;
            if (node.x > width + 20) node.x = -20;
            if (node.y < -20) node.y = height + 20;
            if (node.y > height + 20) node.y = -20;
        }
    }

    function render(t) {
        if (!running) return;

        ctx.clearRect(0, 0, width, height);
        drawConnections(t);
        for (const node of nodes) {
            drawNode(node, t);
        }
        update();
        animId = requestAnimationFrame(render);
    }

    function start() {
        if (running) return;
        running = true;
        resize();
        if (!nodes || nodes.length === 0) createNodes();
        animId = requestAnimationFrame(render);
    }

    function stop() {
        running = false;
        if (animId) cancelAnimationFrame(animId);
    }

    // Track mouse over the FAQ section
    const faqSection = document.getElementById('faq');
    if (faqSection) {
        faqSection.addEventListener('mousemove', (e) => {
            mouse.x = e.clientX;
            mouse.y = e.clientY;
        });
        faqSection.addEventListener('mouseleave', () => {
            mouse.x = -9999;
            mouse.y = -9999;
        });
    }

    // Start/stop based on section visibility
    document.addEventListener('section-revealed', (e) => {
        if (e.detail.index === 3) {
            start();
        } else {
            stop();
        }
    });

    // Handle resize
    window.addEventListener('resize', () => {
        if (running) {
            resize();
        }
    });

    // Expose for manual control
    window.faqConstellation = { start, stop };
})();
