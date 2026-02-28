/* ============================================
   FAQ Space Glass Shatter Background
   Voronoi crack pattern with glowing refraction
   edges + subtle starfield behind the glass.
   Mouse parallax shifts the crack highlights.
   Only active when FAQ section is visible.
   ============================================ */

(function () {
    const canvas = document.getElementById('faq-shatter');
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    let W, H, shards, stars, running = false, animId;
    let mouse = { x: 0.5, y: 0.5 }; // normalized 0-1

    const SHARD_POINTS = 28;
    const STAR_COUNT = 120;

    /* ---- Resize ---- */
    function resize() {
        W = canvas.width = window.innerWidth;
        H = canvas.height = window.innerHeight;
    }

    /* ---- Stars ---- */
    function createStars() {
        stars = [];
        for (let i = 0; i < STAR_COUNT; i++) {
            stars.push({
                x: Math.random() * W,
                y: Math.random() * H,
                r: Math.random() * 1.2 + 0.3,
                twinkleSpeed: 0.005 + Math.random() * 0.015,
                twinkleOffset: Math.random() * Math.PI * 2,
                brightness: 0.3 + Math.random() * 0.7,
            });
        }
    }

    function drawStars(t) {
        for (const s of stars) {
            const twinkle = 0.4 + 0.6 * Math.sin(t * s.twinkleSpeed + s.twinkleOffset);
            const alpha = s.brightness * twinkle;
            ctx.beginPath();
            ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
            ctx.fillStyle = `rgba(200, 220, 255, ${alpha * 0.6})`;
            ctx.fill();
        }
    }

    /* ---- Voronoi Shatter ---- */
    function generateShards() {
        // Random seed points
        const points = [];
        // Impact point near center
        const cx = W * (0.4 + Math.random() * 0.2);
        const cy = H * (0.35 + Math.random() * 0.3);

        // Dense points near impact
        for (let i = 0; i < 12; i++) {
            const angle = (Math.PI * 2 * i) / 12 + (Math.random() - 0.5) * 0.4;
            const dist = 30 + Math.random() * 150;
            points.push({
                x: cx + Math.cos(angle) * dist,
                y: cy + Math.sin(angle) * dist,
            });
        }

        // Spread points across the screen
        for (let i = 0; i < SHARD_POINTS - 12; i++) {
            points.push({
                x: Math.random() * W,
                y: Math.random() * H,
            });
        }

        // Build Voronoi edges using brute-force neighbor detection
        // For each pair of points, find the midpoint/perpendicular to create shard edges
        shards = { points, edges: [], cx, cy };

        // Generate crack lines radiating from impact
        const crackLines = [];

        // Main radial cracks from impact point
        const numRadial = 8 + Math.floor(Math.random() * 5);
        for (let i = 0; i < numRadial; i++) {
            const angle = (Math.PI * 2 * i) / numRadial + (Math.random() - 0.5) * 0.3;
            const segments = [];
            let px = cx, py = cy;
            const len = 200 + Math.random() * Math.max(W, H) * 0.6;
            const steps = 5 + Math.floor(Math.random() * 8);

            for (let s = 0; s < steps; s++) {
                const segLen = len / steps;
                const wobble = (Math.random() - 0.5) * 0.4;
                const a = angle + wobble;
                const nx = px + Math.cos(a) * segLen;
                const ny = py + Math.sin(a) * segLen;
                segments.push({ x1: px, y1: py, x2: nx, y2: ny });
                px = nx;
                py = ny;
            }
            crackLines.push(segments);
        }

        // Concentric ring cracks
        const numRings = 2 + Math.floor(Math.random() * 2);
        for (let r = 0; r < numRings; r++) {
            const radius = 80 + r * (100 + Math.random() * 80);
            const arcSegments = 10 + Math.floor(Math.random() * 8);
            const startAngle = Math.random() * Math.PI * 2;
            const arcSpan = Math.PI * (1.2 + Math.random() * 0.8);

            for (let s = 0; s < arcSegments; s++) {
                const a1 = startAngle + (arcSpan * s) / arcSegments;
                const a2 = startAngle + (arcSpan * (s + 1)) / arcSegments;
                const wobble1 = (Math.random() - 0.5) * 15;
                const wobble2 = (Math.random() - 0.5) * 15;
                crackLines.push([{
                    x1: cx + Math.cos(a1) * (radius + wobble1),
                    y1: cy + Math.sin(a1) * (radius + wobble1),
                    x2: cx + Math.cos(a2) * (radius + wobble2),
                    y2: cy + Math.sin(a2) * (radius + wobble2),
                }]);
            }
        }

        // Secondary branching cracks
        for (const line of [...crackLines]) {
            for (const seg of line) {
                if (Math.random() > 0.6) {
                    const mx = (seg.x1 + seg.x2) / 2;
                    const my = (seg.y1 + seg.y2) / 2;
                    const branchAngle = Math.atan2(seg.y2 - seg.y1, seg.x2 - seg.x1) +
                        (Math.random() > 0.5 ? 1 : -1) * (0.3 + Math.random() * 0.8);
                    const branchLen = 30 + Math.random() * 80;
                    crackLines.push([{
                        x1: mx,
                        y1: my,
                        x2: mx + Math.cos(branchAngle) * branchLen,
                        y2: my + Math.sin(branchAngle) * branchLen,
                    }]);
                }
            }
        }

        shards.crackLines = crackLines;
    }

    function drawShatter(t) {
        const { crackLines, cx, cy } = shards;

        // Mouse-based light position (parallax offset from center)
        const lightX = cx + (mouse.x - 0.5) * 300;
        const lightY = cy + (mouse.y - 0.5) * 200;

        // Draw each crack line
        for (const line of crackLines) {
            for (const seg of line) {
                const mx = (seg.x1 + seg.x2) / 2;
                const my = (seg.y1 + seg.y2) / 2;

                // Distance from light source affects glow intensity
                const distToLight = Math.sqrt((mx - lightX) ** 2 + (my - lightY) ** 2);
                const maxDist = Math.max(W, H) * 0.7;
                const lightIntensity = Math.max(0, 1 - distToLight / maxDist);

                // Subtle animated shimmer
                const shimmer = 0.6 + 0.4 * Math.sin(t * 0.002 + seg.x1 * 0.01 + seg.y1 * 0.01);

                // Base crack line (dark)
                ctx.beginPath();
                ctx.moveTo(seg.x1, seg.y1);
                ctx.lineTo(seg.x2, seg.y2);
                ctx.strokeStyle = `rgba(180, 210, 255, ${0.04 + lightIntensity * 0.08 * shimmer})`;
                ctx.lineWidth = 0.5;
                ctx.stroke();

                // Glow layer (refraction)
                const glowAlpha = lightIntensity * shimmer * 0.25;
                if (glowAlpha > 0.02) {
                    ctx.beginPath();
                    ctx.moveTo(seg.x1, seg.y1);
                    ctx.lineTo(seg.x2, seg.y2);
                    ctx.strokeStyle = `rgba(160, 200, 255, ${glowAlpha})`;
                    ctx.lineWidth = 2;
                    ctx.stroke();

                    // Bright refraction edge (thin white core)
                    ctx.beginPath();
                    ctx.moveTo(seg.x1, seg.y1);
                    ctx.lineTo(seg.x2, seg.y2);
                    ctx.strokeStyle = `rgba(220, 240, 255, ${glowAlpha * 0.6})`;
                    ctx.lineWidth = 0.5;
                    ctx.stroke();
                }
            }
        }

        // Impact point glow
        const impactPulse = 0.5 + 0.5 * Math.sin(t * 0.003);
        const impactGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, 120 + impactPulse * 30);
        impactGrad.addColorStop(0, `rgba(180, 210, 255, ${0.04 + impactPulse * 0.03})`);
        impactGrad.addColorStop(0.5, `rgba(140, 180, 240, ${0.02 + impactPulse * 0.01})`);
        impactGrad.addColorStop(1, 'rgba(100, 150, 220, 0)');
        ctx.fillStyle = impactGrad;
        ctx.fillRect(cx - 160, cy - 160, 320, 320);

        // Mouse light refraction hotspot
        const mouseGrad = ctx.createRadialGradient(lightX, lightY, 0, lightX, lightY, 250);
        mouseGrad.addColorStop(0, 'rgba(180, 210, 255, 0.03)');
        mouseGrad.addColorStop(0.4, 'rgba(140, 180, 240, 0.015)');
        mouseGrad.addColorStop(1, 'rgba(100, 150, 220, 0)');
        ctx.fillStyle = mouseGrad;
        ctx.fillRect(lightX - 260, lightY - 260, 520, 520);
    }

    /* ---- Glass surface (subtle reflection) ---- */
    function drawGlassSurface() {
        // Faint diagonal reflection streak
        const grad = ctx.createLinearGradient(0, 0, W, H * 0.6);
        grad.addColorStop(0, 'rgba(255, 255, 255, 0)');
        grad.addColorStop(0.3, 'rgba(255, 255, 255, 0.008)');
        grad.addColorStop(0.5, 'rgba(255, 255, 255, 0.015)');
        grad.addColorStop(0.7, 'rgba(255, 255, 255, 0.005)');
        grad.addColorStop(1, 'rgba(255, 255, 255, 0)');
        ctx.fillStyle = grad;
        ctx.fillRect(0, 0, W, H);
    }

    /* ---- Render loop ---- */
    function render(t) {
        if (!running) return;
        ctx.clearRect(0, 0, W, H);

        drawStars(t);
        drawGlassSurface();
        drawShatter(t);

        animId = requestAnimationFrame(render);
    }

    function start() {
        if (running) return;
        running = true;
        resize();
        if (!shards) generateShards();
        if (!stars || stars.length === 0) createStars();
        animId = requestAnimationFrame(render);
    }

    function stop() {
        running = false;
        if (animId) cancelAnimationFrame(animId);
    }

    /* ---- Mouse tracking ---- */
    const faqSection = document.getElementById('faq');
    if (faqSection) {
        faqSection.addEventListener('mousemove', (e) => {
            mouse.x = e.clientX / window.innerWidth;
            mouse.y = e.clientY / window.innerHeight;
        });
    }

    /* ---- Section visibility ---- */
    document.addEventListener('section-revealed', (e) => {
        if (e.detail.index === 3) {
            start();
        } else {
            stop();
        }
    });

    window.addEventListener('resize', () => {
        if (running) {
            resize();
            shards = null;
            generateShards();
            stars = null;
            createStars();
        }
    });

    window.faqShatter = { start, stop };
})();
