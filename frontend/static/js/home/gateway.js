/* ============================================
   Gateway Section — Unified PCB Circuit Trace Generator
   All 3 grid canvases share one circuit layout so
   traces flow continuously across the squares.

   Phase 1: Dark squares appear, then traces draw
            themselves in progressively (no pulses).
   Phase 2: Once fully drawn, light pulses begin.
   ============================================ */

class GatewayGrain {
    constructor() {
        this.canvases = document.querySelectorAll('.gw-grain');
        if (!this.canvases.length) return;

        this.drawn = false;
        this.animating = false;
        this.designing = false;
        this.designDone = false;
        this._gen = 0;
        this.canvasData = new Map();

        // Design-in timing
        this.designDelay = 1.0;    // seconds after squares appear before traces start drawing
        this.designDuration = 4.0; // seconds to draw all traces
        this.designStart = null;

        // Shared circuit data
        this.allPaths = [];
        this.totalW = 0;
        this.totalH = 0;

        this.observer = new ResizeObserver(() => {
            if (this.drawn) return;
            this.drawAll();
        });
        this.canvases.forEach(c => this.observer.observe(c.parentElement));

        requestAnimationFrame(() => this.drawAll());
    }

    drawAll() {
        const grid = document.querySelector('.gw-right');
        if (!grid) return;
        const gridRect = grid.getBoundingClientRect();
        if (gridRect.width === 0 || gridRect.height === 0) return;

        this.totalW = gridRect.width;
        this.totalH = gridRect.height;

        // Collect actual square boundaries relative to grid
        const squares = [...document.querySelectorAll('.gw-img')].map(el => {
            const r = el.getBoundingClientRect();
            return {
                left: r.left - gridRect.left,
                top: r.top - gridRect.top,
                right: r.right - gridRect.left,
                bottom: r.bottom - gridRect.top,
                width: r.width,
                height: r.height
            };
        });
        this.squares = squares;

        // Generate one unified circuit in global coords
        const rng = this.seededRng(42);
        this.allPaths = [];
        this.generateUnifiedPCB(this.totalW, this.totalH, rng, this.allPaths, squares);

        // Assign each path a staggered start time (0–1 normalized)
        // pathDraw = 0.3, so max start must be 0.7 for all paths to finish by progress=1.0
        const pathRng = this.seededRng(99);
        this.pathTimings = this.allPaths.map((_, i) => {
            const base = i / this.allPaths.length;
            return Math.max(0, Math.min(0.7, base * 0.55 + pathRng() * 0.15));
        });

        // Set up each canvas
        this.canvases.forEach(canvas => {
            const parent = canvas.parentElement;
            const w = parent.offsetWidth;
            const h = parent.offsetHeight;
            if (w === 0 || h === 0) return;

            canvas.width = w;
            canvas.height = h;
            canvas.style.width = w + 'px';
            canvas.style.height = h + 'px';

            const parentRect = parent.getBoundingClientRect();
            const offsetX = parentRect.left - gridRect.left;
            const offsetY = parentRect.top - gridRect.top;

            const ctx = canvas.getContext('2d');

            // Draw just the dark background first
            this.drawDarkBase(ctx, w, h, offsetX, offsetY);

            // Filter paths for this region
            const localPaths = this.filterPathsForRegion(this.allPaths, offsetX, offsetY, w, h);
            const mappedPaths = localPaths.map(p =>
                p.map(pt => ({ x: pt.x - offsetX, y: pt.y - offsetY }))
            );

            // Cache the dark base so we never recompute grain per frame
            const baseFrame = ctx.getImageData(0, 0, w, h);

            this.canvasData.set(canvas, {
                ctx, w, h, offsetX, offsetY,
                paths: mappedPaths,
                staticFrame: null,
                baseFrame
            });
        });

        this.drawn = true;

        // Start the design-in animation
        this.designStart = performance.now() + this.designDelay * 1000;
        this.designing = true;
        this.designDone = false;
        this.animateDesign();
    }

    drawDarkBase(ctx, w, h, offsetX, offsetY) {
        ctx.fillStyle = '#080810';
        ctx.fillRect(0, 0, w, h);

        const cx = this.totalW * 0.5 - offsetX;
        const cy = this.totalH * 0.5 - offsetY;
        const bgGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, Math.max(this.totalW, this.totalH) * 0.7);
        bgGrad.addColorStop(0, 'rgba(15,15,30,0.4)');
        bgGrad.addColorStop(1, 'rgba(0,0,0,0)');
        ctx.fillStyle = bgGrad;
        ctx.fillRect(0, 0, w, h);

        // Grain
        const imageData = ctx.getImageData(0, 0, w, h);
        const data = imageData.data;
        const grainRng = this.seededRng(offsetX * 7 + offsetY * 13);
        for (let i = 0; i < data.length; i += 4) {
            const noise = (grainRng() - 0.5) * 8;
            data[i] = Math.max(0, Math.min(255, data[i] + noise));
            data[i + 1] = Math.max(0, Math.min(255, data[i + 1] + noise));
            data[i + 2] = Math.max(0, Math.min(255, data[i + 2] + noise));
        }
        ctx.putImageData(imageData, 0, 0);
    }

    /* Phase 1: Progressively draw traces */
    animateDesign() {
        const gen = this._gen;
        const loop = (now) => {
            if (gen !== this._gen || !this.designing) return;

            const elapsed = (now - this.designStart) / 1000;
            if (elapsed < 0) {
                requestAnimationFrame(loop);
                return;
            }

            const progress = Math.min(elapsed / this.designDuration, 1);

            // Redraw each canvas with partial paths
            for (const [canvas, data] of this.canvasData) {
                const { ctx, w, h, offsetX, offsetY, baseFrame } = data;

                // Restore cached dark base (no per-frame grain recalc)
                ctx.putImageData(baseFrame, 0, 0);

                // Draw paths progressively
                ctx.save();
                ctx.translate(-offsetX, -offsetY);
                ctx.lineCap = 'round';
                ctx.lineJoin = 'round';

                for (let pi = 0; pi < this.allPaths.length; pi++) {
                    const path = this.allPaths[pi];
                    const pathStart = this.pathTimings[pi];
                    // Each path takes 30% of the total duration to fully draw
                    const pathDraw = 0.3;
                    const pathProgress = Math.max(0, Math.min(1, (progress - pathStart) / pathDraw));

                    if (pathProgress <= 0) continue;

                    // Calculate total path length
                    let totalLen = 0;
                    for (let i = 1; i < path.length; i++) {
                        const dx = path[i].x - path[i - 1].x;
                        const dy = path[i].y - path[i - 1].y;
                        totalLen += Math.sqrt(dx * dx + dy * dy);
                    }

                    const drawLen = pathProgress * totalLen;

                    // Draw partial path
                    ctx.beginPath();
                    ctx.moveTo(path[0].x, path[0].y);

                    let accum = 0;
                    for (let i = 1; i < path.length; i++) {
                        const dx = path[i].x - path[i - 1].x;
                        const dy = path[i].y - path[i - 1].y;
                        const segLen = Math.sqrt(dx * dx + dy * dy);

                        if (accum + segLen <= drawLen) {
                            ctx.lineTo(path[i].x, path[i].y);
                            accum += segLen;
                        } else {
                            const remain = drawLen - accum;
                            const t = remain / segLen;
                            ctx.lineTo(
                                path[i - 1].x + dx * t,
                                path[i - 1].y + dy * t
                            );
                            break;
                        }
                    }

                    // Glow
                    ctx.strokeStyle = `rgba(255,255,255,${0.05 * pathProgress})`;
                    ctx.lineWidth = 6;
                    ctx.stroke();

                    // Trace
                    ctx.strokeStyle = `rgba(255,255,255,${0.3 * pathProgress})`;
                    ctx.lineWidth = 1.5;
                    ctx.stroke();

                    // Draw node at the drawing head
                    if (pathProgress < 1 && pathProgress > 0) {
                        // Find head position
                        let hx = path[0].x, hy = path[0].y, ha = 0;
                        for (let i = 1; i < path.length; i++) {
                            const dx2 = path[i].x - path[i - 1].x;
                            const dy2 = path[i].y - path[i - 1].y;
                            const sl = Math.sqrt(dx2 * dx2 + dy2 * dy2);
                            if (ha + sl >= drawLen) {
                                const tt = (drawLen - ha) / sl;
                                hx = path[i - 1].x + dx2 * tt;
                                hy = path[i - 1].y + dy2 * tt;
                                break;
                            }
                            ha += sl;
                            hx = path[i].x; hy = path[i].y;
                        }
                        // Small bright dot at head
                        const headGrad = ctx.createRadialGradient(hx, hy, 0, hx, hy, 8);
                        headGrad.addColorStop(0, 'rgba(255,255,255,0.6)');
                        headGrad.addColorStop(0.4, 'rgba(255,255,255,0.15)');
                        headGrad.addColorStop(1, 'rgba(255,255,255,0)');
                        ctx.fillStyle = headGrad;
                        ctx.fillRect(hx - 8, hy - 8, 16, 16);
                    }
                }

                // Draw nodes for completed paths
                const nodeMap = new Map();
                for (let pi = 0; pi < this.allPaths.length; pi++) {
                    const pathStart = this.pathTimings[pi];
                    const pathProgress = Math.max(0, Math.min(1, (progress - pathStart) / 0.3));
                    if (pathProgress < 1) continue;

                    const path = this.allPaths[pi];
                    for (const pt of path) {
                        const key = `${Math.round(pt.x)},${Math.round(pt.y)}`;
                        nodeMap.set(key, { x: pt.x, y: pt.y, count: (nodeMap.get(key)?.count || 0) + 1 });
                    }
                }

                for (const [, node] of nodeMap) {
                    const bright = node.count >= 2;
                    const r = bright ? 3 : 2;

                    if (bright) {
                        const grad = ctx.createRadialGradient(node.x, node.y, 0, node.x, node.y, r * 10);
                        grad.addColorStop(0, 'rgba(255,255,255,0.25)');
                        grad.addColorStop(0.3, 'rgba(255,255,255,0.08)');
                        grad.addColorStop(1, 'rgba(0,0,0,0)');
                        ctx.fillStyle = grad;
                        ctx.fillRect(node.x - r * 10, node.y - r * 10, r * 20, r * 20);
                    }

                    ctx.fillStyle = bright ? 'rgba(255,255,255,0.85)' : 'rgba(255,255,255,0.4)';
                    ctx.beginPath();
                    ctx.arc(node.x, node.y, r, 0, Math.PI * 2);
                    ctx.fill();
                }

                ctx.restore();
            }

            if (progress >= 1) {
                // Design complete — capture static frames and start pulses
                this.designing = false;
                this.designDone = true;
                if (this.onDesignDone) { this.onDesignDone(); }

                for (const [canvas, data] of this.canvasData) {
                    const { ctx, w, h, offsetX, offsetY } = data;
                    // Draw final full version
                    this.drawPCBRegion(ctx, w, h, offsetX, offsetY, this.totalW, this.totalH, this.allPaths);
                    data.staticFrame = ctx.getImageData(0, 0, w, h);
                }

                this.animate();
                return;
            }

            requestAnimationFrame(loop);
        };

        requestAnimationFrame(loop);
    }

    generateUnifiedPCB(w, h, rng, paths, squares) {
        const gridStep = Math.floor(Math.min(w, h) * 0.055);

        // Margins: horizontal lines must stay this far from each square's edges
        const yMarginPct = 0.16;
        const xMarginPx  = gridStep * 2;

        // Build safe zones per square
        const zones = (squares || []).map(sq => ({
            ...sq,
            safeTop:    sq.top    + sq.height * yMarginPct,
            safeBottom: sq.bottom - sq.height * yMarginPct,
            safeLeft:   sq.left   + xMarginPx,
            safeRight:  sq.right  - xMarginPx
        }));

        // Clamp a Y value so horizontal lines stay away from square edges
        const clampY = (y) => {
            for (const z of zones) {
                if (y >= z.top && y <= z.bottom) {
                    return Math.max(z.safeTop, Math.min(z.safeBottom, y));
                }
            }
            return y;
        };

        // Snap to grid then clamp to safe zone
        const safeSnapY = (rawY) => {
            const snapped = Math.round(rawY / gridStep) * gridStep;
            return clampY(snapped);
        };

        // Vertical trunks — these cross between squares, no Y clamping
        const trunkCount = 4 + Math.floor(rng() * 3);
        const trunks = [];
        const cols = Math.floor(w / gridStep);

        for (let t = 0; t < trunkCount; t++) {
            const col = 2 + Math.floor((cols - 4) * (t / (trunkCount - 1)) + (rng() - 0.5) * 2);
            const x = col * gridStep;
            const yStart = Math.floor(rng() * h * 0.08);
            const yEnd = h - Math.floor(rng() * h * 0.08);
            trunks.push({ x, yStart, yEnd });
            paths.push([{ x, y: yStart }, { x, y: yEnd }]);
        }

        // Horizontal connectors between adjacent trunks — clamped to safe Y zones
        for (let i = 0; i < trunks.length - 1; i++) {
            const a = trunks[i];
            const b = trunks[i + 1];
            const connCount = 2 + Math.floor(rng() * 3);
            for (let c = 0; c < connCount; c++) {
                const rawY = gridStep * (3 + Math.floor(rng() * (Math.floor(h / gridStep) - 5)));
                const y = clampY(rawY);
                paths.push([{ x: a.x, y }, { x: b.x, y }]);
            }
        }

        // Branches from trunks — horizontal segments clamped
        for (const trunk of trunks) {
            const branchCount = 4 + Math.floor(rng() * 4);
            for (let b = 0; b < branchCount; b++) {
                const rawY = trunk.yStart + rng() * (trunk.yEnd - trunk.yStart);
                const y = safeSnapY(rawY);
                const dir = rng() < 0.5 ? -1 : 1;
                const hLen = gridStep * (2 + Math.floor(rng() * 4));
                const bx2 = trunk.x + dir * hLen;

                const hasJog = rng() < 0.55;
                const jogDir = rng() < 0.5 ? -1 : 1;
                const jogLen = hasJog ? gridStep * (1 + Math.floor(rng() * 3)) * jogDir : 0;

                const pathPts = [{ x: trunk.x, y }, { x: bx2, y }];
                if (hasJog) {
                    const jogY = clampY(y + jogLen);
                    pathPts.push({ x: bx2, y: jogY });
                }
                paths.push(pathPts);

                // Sub-branches
                if (rng() < 0.35) {
                    const rawSby = y + (rng() < 0.5 ? -1 : 1) * gridStep * (1 + Math.floor(rng() * 2));
                    const sby = clampY(rawSby);
                    const sbx = trunk.x + dir * hLen * (0.4 + rng() * 0.3);
                    const sbLen = gridStep * (1 + Math.floor(rng() * 2));
                    const sbDir = rng() < 0.5 ? -1 : 1;
                    paths.push([
                        { x: sbx, y },
                        { x: sbx, y: sby },
                        { x: sbx + sbDir * sbLen, y: sby }
                    ]);
                }
            }
        }

        // Floating segments — also clamped
        const floatCount = 3 + Math.floor(rng() * 3);
        for (let f = 0; f < floatCount; f++) {
            const fx = rng() * w;
            const rawFy = rng() * h;
            const fy = clampY(rawFy);
            const fLen = gridStep * (1 + rng() * 2);
            const isVert = rng() < 0.5;
            if (isVert) {
                paths.push([{ x: fx, y: fy }, { x: fx, y: fy + fLen }]);
            } else {
                paths.push([{ x: fx, y: fy }, { x: fx + fLen, y: fy }]);
            }
        }
    }

    drawPCBRegion(ctx, w, h, offsetX, offsetY, totalW, totalH, paths) {
        ctx.fillStyle = '#080810';
        ctx.fillRect(0, 0, w, h);

        const cx = totalW * 0.5 - offsetX;
        const cy = totalH * 0.5 - offsetY;
        const bgGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, Math.max(totalW, totalH) * 0.7);
        bgGrad.addColorStop(0, 'rgba(15,15,30,0.4)');
        bgGrad.addColorStop(1, 'rgba(0,0,0,0)');
        ctx.fillStyle = bgGrad;
        ctx.fillRect(0, 0, w, h);

        const traceW = 1.5;
        const glowW = 6;

        ctx.save();
        ctx.translate(-offsetX, -offsetY);
        ctx.lineCap = 'round';
        ctx.lineJoin = 'round';

        for (const path of paths) {
            ctx.strokeStyle = 'rgba(255,255,255,0.05)';
            ctx.lineWidth = glowW;
            ctx.beginPath();
            ctx.moveTo(path[0].x, path[0].y);
            for (let i = 1; i < path.length; i++) ctx.lineTo(path[i].x, path[i].y);
            ctx.stroke();

            ctx.strokeStyle = 'rgba(255,255,255,0.3)';
            ctx.lineWidth = traceW;
            ctx.beginPath();
            ctx.moveTo(path[0].x, path[0].y);
            for (let i = 1; i < path.length; i++) ctx.lineTo(path[i].x, path[i].y);
            ctx.stroke();
        }

        const nodeMap = new Map();
        for (const path of paths) {
            for (const pt of path) {
                const key = `${Math.round(pt.x)},${Math.round(pt.y)}`;
                nodeMap.set(key, { x: pt.x, y: pt.y, count: (nodeMap.get(key)?.count || 0) + 1 });
            }
        }

        for (const [, node] of nodeMap) {
            const bright = node.count >= 2;
            const r = bright ? 3 : 2;
            if (bright) {
                const grad = ctx.createRadialGradient(node.x, node.y, 0, node.x, node.y, r * 10);
                grad.addColorStop(0, 'rgba(255,255,255,0.25)');
                grad.addColorStop(0.3, 'rgba(255,255,255,0.08)');
                grad.addColorStop(1, 'rgba(0,0,0,0)');
                ctx.fillStyle = grad;
                ctx.fillRect(node.x - r * 10, node.y - r * 10, r * 20, r * 20);
            }
            ctx.fillStyle = bright ? 'rgba(255,255,255,0.85)' : 'rgba(255,255,255,0.4)';
            ctx.beginPath();
            ctx.arc(node.x, node.y, r, 0, Math.PI * 2);
            ctx.fill();
        }

        ctx.restore();

        const imageData = ctx.getImageData(0, 0, w, h);
        const data = imageData.data;
        const grainRng = this.seededRng(offsetX * 7 + offsetY * 13);
        for (let i = 0; i < data.length; i += 4) {
            const noise = (grainRng() - 0.5) * 8;
            data[i] = Math.max(0, Math.min(255, data[i] + noise));
            data[i + 1] = Math.max(0, Math.min(255, data[i + 1] + noise));
            data[i + 2] = Math.max(0, Math.min(255, data[i + 2] + noise));
        }
        ctx.putImageData(imageData, 0, 0);
    }

    filterPathsForRegion(paths, ox, oy, w, h) {
        const margin = 30;
        return paths.filter(path =>
            path.some(pt =>
                pt.x >= ox - margin && pt.x <= ox + w + margin &&
                pt.y >= oy - margin && pt.y <= oy + h + margin
            )
        );
    }

    initGlobalPulses() {
        const paths = this.allPaths;
        if (paths.length === 0) return [];
        const rng = this.seededRng(42 * 97);
        const count = Math.min(6, paths.length);
        const pulses = [];
        const used = new Set();

        for (let i = 0; i < count; i++) {
            let idx, tries = 0;
            do { idx = Math.floor(rng() * paths.length); tries++; }
            while (used.has(idx) && tries < 30);
            used.add(idx);

            pulses.push({
                pathIdx: idx,
                progress: -(rng() * 0.5),
                speed: 0.06 + rng() * 0.04,
                opacity: 1,
                fading: false
            });
        }
        return pulses;
    }

    // Get set of path indices currently in use by any pulse
    _usedPathIndices() {
        const used = new Set();
        for (const p of this.globalPulses) used.add(p.pathIdx);
        return used;
    }

    /* Phase 2: Light pulses after design is complete */
    animate() {
        const gen = this._gen;
        this.globalPulses = this.initGlobalPulses();
        let lastTime = performance.now();

        const loop = (now) => {
            if (gen !== this._gen) return;
            const dt = (now - lastTime) / 1000;
            lastTime = now;
            const paths = this.allPaths;

            // Update global pulse state
            for (const pulse of this.globalPulses) {
                pulse.progress += pulse.speed * dt;

                if (pulse.progress >= 1 && !pulse.fading) {
                    pulse.fading = true;
                }

                if (pulse.fading) {
                    pulse.opacity -= dt * 0.5;
                    if (pulse.opacity <= 0) {
                        // Pick a new path that no other pulse is on
                        const used = this._usedPathIndices();
                        const rng = this.seededRng(now * 7 + this.globalPulses.indexOf(pulse));
                        let idx, tries = 0;
                        do { idx = Math.floor(rng() * paths.length); tries++; }
                        while (used.has(idx) && tries < 30);

                        pulse.pathIdx = idx;
                        pulse.progress = -0.1;
                        pulse.opacity = 1;
                        pulse.fading = false;
                        pulse.speed = 0.06 + rng() * 0.04;
                    }
                }
            }

            // Render each canvas with its static frame + global pulses
            for (const [canvas, data] of this.canvasData) {
                const { ctx, w, h, offsetX, offsetY, staticFrame } = data;
                if (!staticFrame) continue;
                ctx.putImageData(staticFrame, 0, 0);

                ctx.save();
                ctx.translate(-offsetX, -offsetY);

                for (const pulse of this.globalPulses) {
                    if (pulse.progress < 0 || (pulse.fading && pulse.opacity <= 0)) continue;
                    const path = paths[pulse.pathIdx];
                    if (!path || path.length < 2) continue;
                    this.drawPulse(ctx, path, Math.min(pulse.progress, 1), pulse.opacity);
                }

                ctx.restore();
            }

            requestAnimationFrame(loop);
        };
        requestAnimationFrame(loop);
    }

    reset() {
        this._gen++;
        this.designing = false;
        this.designDone = false;

        const gw = document.getElementById('gateway');
        if (gw) {
            gw.classList.remove('gw-sweep-active', 'gw-grid-ready');
        }

        for (const [canvas, data] of this.canvasData) {
            this.drawDarkBase(data.ctx, data.w, data.h, data.offsetX, data.offsetY);
            data.staticFrame = null;
        }

        this.designStart = performance.now() + this.designDelay * 1000;
        this.designing = true;
        this.animateDesign();
    }

    drawPulse(ctx, path, progress, opacity) {
        let totalLen = 0;
        const segLens = [];
        for (let i = 1; i < path.length; i++) {
            const dx = path[i].x - path[i - 1].x;
            const dy = path[i].y - path[i - 1].y;
            segLens.push(Math.sqrt(dx * dx + dy * dy));
            totalLen += segLens[segLens.length - 1];
        }
        if (totalLen === 0) return;

        const targetDist = progress * totalLen;
        let accum = 0, headX = path[0].x, headY = path[0].y;

        for (let i = 0; i < segLens.length; i++) {
            if (accum + segLens[i] >= targetDist) {
                const t = (targetDist - accum) / segLens[i];
                headX = path[i].x + (path[i + 1].x - path[i].x) * t;
                headY = path[i].y + (path[i + 1].y - path[i].y) * t;
                break;
            }
            accum += segLens[i];
            headX = path[i + 1].x;
            headY = path[i + 1].y;
        }

        const trailLen = totalLen * 0.25;
        const trailStart = Math.max(0, targetDist - trailLen);
        const steps = 12;

        for (let s = 0; s < steps; s++) {
            const t = s / steps;
            const dist = trailStart + (targetDist - trailStart) * t;
            let px = path[0].x, py = path[0].y, a = 0;

            for (let i = 0; i < segLens.length; i++) {
                if (a + segLens[i] >= dist) {
                    const tt = (dist - a) / segLens[i];
                    px = path[i].x + (path[i + 1].x - path[i].x) * tt;
                    py = path[i].y + (path[i + 1].y - path[i].y) * tt;
                    break;
                }
                a += segLens[i];
                px = path[i + 1].x; py = path[i + 1].y;
            }

            const brightness = t * t;
            const alpha = brightness * 0.4 * opacity;
            const r = 4 + brightness * 8;

            const grad = ctx.createRadialGradient(px, py, 0, px, py, r);
            grad.addColorStop(0, `rgba(255,255,255,${alpha})`);
            grad.addColorStop(0.4, `rgba(255,255,255,${alpha * 0.4})`);
            grad.addColorStop(1, 'rgba(255,255,255,0)');
            ctx.fillStyle = grad;
            ctx.fillRect(px - r, py - r, r * 2, r * 2);
        }

        const headAlpha = opacity;
        const outerR = 20;
        const outerGrad = ctx.createRadialGradient(headX, headY, 0, headX, headY, outerR);
        outerGrad.addColorStop(0, `rgba(255,255,255,${0.35 * headAlpha})`);
        outerGrad.addColorStop(0.3, `rgba(255,255,255,${0.12 * headAlpha})`);
        outerGrad.addColorStop(1, 'rgba(255,255,255,0)');
        ctx.fillStyle = outerGrad;
        ctx.fillRect(headX - outerR, headY - outerR, outerR * 2, outerR * 2);

        const coreR = 5;
        const coreGrad = ctx.createRadialGradient(headX, headY, 0, headX, headY, coreR);
        coreGrad.addColorStop(0, `rgba(255,255,255,${0.95 * headAlpha})`);
        coreGrad.addColorStop(0.5, `rgba(255,255,255,${0.5 * headAlpha})`);
        coreGrad.addColorStop(1, 'rgba(255,255,255,0)');
        ctx.fillStyle = coreGrad;
        ctx.fillRect(headX - coreR, headY - coreR, coreR * 2, coreR * 2);
    }

    seededRng(seed) {
        let s = Math.abs(Math.floor(seed)) || 1;
        return () => {
            s = (s * 16807 + 0) % 2147483647;
            return (s - 1) / 2147483646;
        };
    }
}

/* ============================================
   Gateway Subtitle Fade-In
   Fades in the subtitle text alongside the heading.
   ============================================ */
class GatewayTypewriter {
    constructor(onDone) {
        this.el = document.querySelector('.gw-subtitle');
        if (!this.el) { if (onDone) onDone(); return; }

        // Start hidden, fade in after short delay
        this.el.style.opacity = '0';
        this.el.style.transform = 'translateY(0.5vw)';
        this.el.style.transition = 'opacity 0.8s ease, transform 0.8s ease';

        setTimeout(() => {
            this.el.style.opacity = '1';
            this.el.style.transform = 'translateY(0)';
            // Fire onDone after fade completes
            setTimeout(() => { if (onDone) onDone(); }, 800);
        }, 500);
    }

    reset(onDone) {
        if (!this.el) { if (onDone) onDone(); return; }
        this.el.style.opacity = '0';
        this.el.style.transform = 'translateY(0.5vw)';
        setTimeout(() => {
            this.el.style.opacity = '1';
            this.el.style.transform = 'translateY(0)';
            setTimeout(() => { if (onDone) onDone(); }, 800);
        }, 500);
    }
}

/* ============================================
   Grid reveal coordinator
   Shows grid background after both design-in
   and typewriter complete.
   ============================================ */
function initGateway() {
    let designDone = false;
    let typeDone = false;

    const checkReady = () => {
        if (designDone && typeDone) {
            const gw = document.getElementById('gateway');
            if (gw) gw.classList.add('gw-grid-ready');
        }
    };

    const grain = new GatewayGrain();
    grain.onDesignDone = () => {
        designDone = true;
        // Sweep starts as soon as pulse dots begin
        const gw = document.getElementById('gateway');
        if (gw) gw.classList.add('gw-sweep-active');
        checkReady();
    };

    const tw = new GatewayTypewriter(() => {
        typeDone = true;
        checkReady();
    });

    window.gatewayGrain = grain;

    window.resetGateway = () => {
        designDone = false;
        typeDone = false;
        grain.reset();
        tw.reset(() => {
            typeDone = true;
            checkReady();
        });
    };
}

// Wait for splash to finish before starting gateway animations
document.addEventListener('start-gateway', () => initGateway());
// If splash was skipped, start immediately when cinematic-done fires
document.addEventListener('cinematic-done', () => {
    if (!window.gatewayGrain) initGateway();
});
