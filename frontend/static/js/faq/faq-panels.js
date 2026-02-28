/* ============================================
   FAQ Binary / Code Fragments Background
   3D perspective code snippets floating L→R
   with depth layers, glow, and rotation.
   Only fades out at the far right edge.
   ============================================ */

(function () {
    const canvas = document.getElementById('faq-panels');
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    let W, H, fragments, running = false, animId;

    const FRAG_COUNT = 55;

    const CODE_SNIPPETS = [
        // Binary
        '01001010', '11010011', '10110100', '00101101',
        '01110010', '11001001', '10010110', '01101011',
        '00110011', '11100101', '01011100', '10001110',
        // Hex
        '0x4F49', '0xDEAD', '0xBEEF', '0xCAFE',
        '0xFF', '0x00', '0xA3B7',
        // HTML / JSX
        '<div>', '</div>', '<span/>', '<code/>',
        '<init>', '</>', '<App />', '<main>',
        // Keywords
        'const', 'let', 'var', 'return',
        'async', 'await', 'import', 'export',
        'function', 'class', 'extends', 'new',
        'if', 'else', 'for', 'while',
        'try', 'catch', 'throw', 'finally',
        'null', 'undefined', 'void', 'typeof',
        'true', 'false', 'this', 'super',
        // Operators & syntax
        '=> {', '...args', '?.', '??',
        '===', '!==', '&&', '||',
        '[ ]', '{ }', '( )', ';',
        // Expressions
        'console.log()', '.map()', '.filter()',
        '.reduce()', '.forEach()', '.push()',
        'fetch()', 'JSON.parse()', 'Promise.all()',
        'useState()', 'useEffect()', 'require()',
        // Dev stuff
        '// TODO', '/* */', 'npm install',
        'git commit', 'git push', 'node index.js',
        'python main.py', 'docker run', 'ssh root@',
    ];

    // Color categories
    function getColor(text) {
        if (/^[01]+$/.test(text) || text.startsWith('0x'))
            return { r: 34, g: 211, b: 238 };    // cyan — binary/hex
        if (text.startsWith('<') || text.startsWith('</'))
            return { r: 244, g: 114, b: 182 };    // pink — HTML tags
        if (/^(const|let|var|return|async|await|import|export|function|class|extends|new|if|else|for|while|try|catch|throw|finally|null|undefined|void|typeof|true|false|this|super)$/.test(text))
            return { r: 139, g: 92, b: 246 };     // violet — keywords
        if (text.startsWith('.') || text.includes('('))
            return { r: 52, g: 211, b: 153 };     // green — methods
        if (text.startsWith('//') || text.startsWith('/*'))
            return { r: 100, g: 116, b: 139 };    // gray — comments
        return { r: 226, g: 232, b: 240 };         // off-white — everything else
    }

    function resize() {
        W = canvas.width = window.innerWidth;
        H = canvas.height = window.innerHeight;
    }

    function createFragments() {
        fragments = [];
        for (let i = 0; i < FRAG_COUNT; i++) {
            fragments.push(makeFrag(true));
        }
        // Sort by depth so far-away ones draw first
        fragments.sort((a, b) => a.depth - b.depth);
    }

    function makeFrag(randomX) {
        const text = CODE_SNIPPETS[Math.floor(Math.random() * CODE_SNIPPETS.length)];
        // Depth layer: 0 = far back, 1 = front
        const depth = Math.random();
        const size = 10 + depth * 18;
        const color = getColor(text);

        return {
            text,
            x: randomX ? Math.random() * W : -150 - Math.random() * 400,
            y: 30 + Math.random() * (H - 60),
            speed: 0.12 + depth * 0.55,
            yDrift: (Math.random() - 0.5) * 0.15,
            size,
            depth,
            color,
            opacity: 0,
            maxOpacity: 0.04 + depth * 0.35,
            fadeIn: true,
            fadeSpeed: 0.002 + Math.random() * 0.003,
            // 3D rotation
            rotY: Math.random() * Math.PI * 2,
            rotSpeed: (Math.random() - 0.5) * 0.012,
            // Slight vertical bob
            bobOffset: Math.random() * Math.PI * 2,
            bobSpeed: 0.005 + Math.random() * 0.01,
            bobAmp: 0.3 + Math.random() * 0.6,
            // Glow pulse
            glowPhase: Math.random() * Math.PI * 2,
            glowSpeed: 0.008 + Math.random() * 0.015,
        };
    }

    function drawFrag(f, t) {
        if (f.opacity <= 0) return;

        // 3D Y-axis rotation — scale X by cos to fake perspective
        const scaleX = Math.cos(f.rotY);
        // Skip rendering when nearly edge-on (invisible)
        if (Math.abs(scaleX) < 0.08) return;

        const { r, g, b } = f.color;
        const glowPulse = 0.6 + 0.4 * Math.sin(t * f.glowSpeed + f.glowPhase);

        ctx.save();
        ctx.globalAlpha = f.opacity * Math.abs(scaleX);

        // Position with vertical bob
        const bobY = Math.sin(t * f.bobSpeed + f.bobOffset) * f.bobAmp;
        ctx.translate(f.x, f.y + bobY);

        // 3D scale transform
        ctx.scale(scaleX, 1);

        // Slight skew for perspective feel based on depth
        const skew = (1 - f.depth) * 0.05 * Math.sin(f.rotY);
        ctx.transform(1, skew, 0, 1, 0, 0);

        ctx.font = `${f.size}px 'JetBrains Mono', 'Courier New', monospace`;

        // Glow layer (behind text)
        const glowAlpha = f.opacity * glowPulse * 0.5 * f.depth;
        if (glowAlpha > 0.01) {
            ctx.shadowColor = `rgba(${r},${g},${b},${glowAlpha})`;
            ctx.shadowBlur = 8 + f.depth * 16;
            ctx.shadowOffsetX = 0;
            ctx.shadowOffsetY = 0;
        }

        // Text color — brighter for closer fragments
        const brightness = 0.6 + f.depth * 0.4;
        ctx.fillStyle = `rgba(${Math.round(r * brightness)},${Math.round(g * brightness)},${Math.round(b * brightness)},1)`;
        ctx.fillText(f.text, 0, 0);

        // Second pass: sharper inner glow for close fragments
        if (f.depth > 0.6) {
            ctx.shadowBlur = 4;
            ctx.shadowColor = `rgba(${r},${g},${b},${glowAlpha * 0.8})`;
            ctx.globalAlpha = f.opacity * Math.abs(scaleX) * 0.3;
            ctx.fillText(f.text, 0, 0);
        }

        ctx.restore();
    }

    function update() {
        for (let i = 0; i < fragments.length; i++) {
            const f = fragments[i];
            f.x += f.speed;
            f.y += f.yDrift;
            f.rotY += f.rotSpeed;

            // Fade in — hold at max until near right edge
            if (f.fadeIn) {
                f.opacity += f.fadeSpeed;
                if (f.opacity >= f.maxOpacity) {
                    f.opacity = f.maxOpacity;
                    f.fadeIn = false;
                }
            } else {
                // Only fade out in the last 15% of screen
                if (f.x > W * 0.85) {
                    const fadeZone = W * 0.15;
                    const progress = (f.x - W * 0.85) / fadeZone;
                    f.opacity = f.maxOpacity * (1 - progress);
                    if (f.opacity <= 0) f.opacity = 0;
                }
            }

            // Recycle when off screen or fully faded at edge
            if (f.x > W + 100 || (f.opacity <= 0 && !f.fadeIn && f.x > W * 0.8)) {
                fragments[i] = makeFrag(false);
            }
        }
    }

    function render(t) {
        if (!running) return;

        ctx.clearRect(0, 0, W, H);

        for (const f of fragments) {
            drawFrag(f, t);
        }

        update();
        animId = requestAnimationFrame(render);
    }

    function start() {
        if (running) return;
        running = true;
        resize();
        if (!fragments) createFragments();
        animId = requestAnimationFrame(render);
    }

    function stop() {
        running = false;
        if (animId) cancelAnimationFrame(animId);
    }

    document.addEventListener('section-revealed', (e) => {
        if (e.detail.index === 3) start();
        else stop();
    });

    window.addEventListener('resize', () => {
        if (running) {
            resize();
            fragments = null;
            createFragments();
        }
    });

    window.faqPanels = { start, stop };
})();
