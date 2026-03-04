(function(){
var canvas = document.getElementById('plexus-canvas');
if (!canvas) return;
var ctx = canvas.getContext('2d');
var section = canvas.closest('.fp-section') || canvas.closest('.standalone-vision') || canvas.parentElement;
if (!section) return;

var NODE_COUNT = 35;
var CONNECT_DIST = 140;
var CONNECT_DIST2 = CONNECT_DIST * CONNECT_DIST;
var NODE_RADIUS = 2.4;
var W, H, nodes = [], raf, active = false;
var FRAME_MS = 50;
var lastFrame = 0;
var STOP_AFTER = 20000;
var startTime = 0;

function resize() {
    var rect = section.getBoundingClientRect();
    W = canvas.width = rect.width;
    H = canvas.height = rect.height;
}

function initNodes() {
    nodes = [];
    for (var i = 0; i < NODE_COUNT; i++) {
        nodes.push({
            x: Math.random() * W,
            y: Math.random() * H,
            vx: (Math.random() - 0.5) * 0.3,
            vy: (Math.random() - 0.5) * 0.3,
            r: NODE_RADIUS + Math.random() * 0.8
        });
    }
}

function draw() {
    ctx.clearRect(0, 0, W, H);
    for (var i = 0; i < nodes.length; i++) {
        for (var j = i + 1; j < nodes.length; j++) {
            var dx = nodes[i].x - nodes[j].x;
            var dy = nodes[i].y - nodes[j].y;
            var d2 = dx * dx + dy * dy;
            if (d2 < CONNECT_DIST2) {
                var ratio = d2 / CONNECT_DIST2;
                var alpha = (1 - ratio) * 0.3;
                ctx.beginPath();
                ctx.moveTo(nodes[i].x, nodes[i].y);
                ctx.lineTo(nodes[j].x, nodes[j].y);
                ctx.strokeStyle = 'rgba(80,80,90,' + alpha + ')';
                ctx.lineWidth = 0.7;
                ctx.stroke();
            }
        }
    }
    for (var i = 0; i < nodes.length; i++) {
        var n = nodes[i];
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
        ctx.fillStyle = 'rgba(90,90,100,0.5)';
        ctx.fill();
    }
}

function update() {
    for (var i = 0; i < nodes.length; i++) {
        var n = nodes[i];
        n.x += n.vx;
        n.y += n.vy;
        if (n.x < 0 || n.x > W) n.vx *= -1;
        if (n.y < 0 || n.y > H) n.vy *= -1;
    }
}

function loop(now) {
    if (!active) return;
    if (now - startTime > STOP_AFTER) { active = false; return; }
    if (now - lastFrame < FRAME_MS) { raf = requestAnimationFrame(loop); return; }
    lastFrame = now;
    update();
    draw();
    raf = requestAnimationFrame(loop);
}

function start() {
    if (active) return;
    resize();
    initNodes();
    active = true;
    startTime = performance.now();
    lastFrame = 0;
    loop(startTime);
}

function stop() {
    active = false;
    if (raf) { cancelAnimationFrame(raf); raf = null; }
}

document.addEventListener('section-revealed', function(e) {
    if (e.detail.index === 1) start(); else stop();
});
window.addEventListener('resize', resize);
start();
window.resetFocusTypewriter = function(){};
})();
