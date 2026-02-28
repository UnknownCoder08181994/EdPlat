/* ============================================
   AWM V2 — Main JS
   Splash (phases 1-2) is independent overlay.
   Gateway (page 0) is revealed after splash.
   Hero (page 1) is pre-set to final state — no
   cinematic animation since gateway is the intro.
   HOME always goes to gateway — no splash replay.
   ============================================ */

document.addEventListener('DOMContentLoaded', () => {
    initNavScrollEffect();
    initMobileNav();

    // Skip cinematic on back-navigation reloads (flag set by destroyHero)
    // or when navigating from a subpage via HOME link (skip param)
    const skipCinematic = sessionStorage.getItem('hero-destroyed') ||
                          new URLSearchParams(window.location.search).has('skip');
    if (skipCinematic) {
        sessionStorage.removeItem('hero-destroyed');
        // Clean up the ?skip param from URL without reload
        if (window.location.search.includes('skip')) {
            history.replaceState(null, '', window.location.pathname);
        }
        // Skip splash only — hide splash overlay, set hero final state
        const splashEl = document.getElementById('splash-overlay');
        if (splashEl) splashEl.classList.add('hidden');
        document.body.classList.add('cinematic-done');
        setHeroFinalState();

        // Wait for page-fade-overlay to finish fading out, then play gateway entrance
        const fadeOverlay = document.getElementById('page-fade-overlay');
        const revealDelay = fadeOverlay ? 400 : 0; // 350ms fade + small buffer
        setTimeout(() => {
            const gateway = document.getElementById('gateway');
            if (gateway) gateway.classList.add('gw-revealed');
            document.dispatchEvent(new CustomEvent('start-gateway'));
            document.dispatchEvent(new CustomEvent('cinematic-done'));
        }, revealDelay);
    } else {
        // Lock scrolling during splash
        document.dispatchEvent(new CustomEvent('lock-scroll'));

        // Run splash → then cross-fade to home page
        const splash = new SplashIntro();

        splash.play().then(() => {
            setHeroFinalState();

            // 1. Show fp-wrapper behind the still-visible white splash overlay
            document.body.classList.remove('splash-playing');

            // 2. Wait two frames so the browser paints gateway at opacity:0
            requestAnimationFrame(() => {
                requestAnimationFrame(() => {
                    // 3. Start gateway entrance animation
                    const gateway = document.getElementById('gateway');
                    if (gateway) gateway.classList.add('gw-revealed');
                    document.dispatchEvent(new CustomEvent('start-gateway'));

                    // 4. Cross-fade: smoothly fade splash overlay to reveal home page
                    const splashEl = document.getElementById('splash-overlay');
                    if (splashEl) {
                        splashEl.style.transition = 'opacity 0.7s ease';
                        splashEl.style.opacity = '0';
                        splashEl.addEventListener('transitionend', () => {
                            splashEl.classList.add('hidden');
                            splashEl.style.transition = '';
                        }, { once: true });
                    }

                    document.body.classList.add('cinematic-done');
                    document.dispatchEvent(new CustomEvent('cinematic-done'));
                });
            });
        });
    }
});

/* ---- Set Hero to final visual state (no animation) ---- */
function setHeroFinalState() {
    const galaxyBg = document.querySelector('.hero-galaxy-bg');
    if (galaxyBg) {
        galaxyBg.style.transition = 'none';
        galaxyBg.style.opacity = '1';
    }
    const galaxyVid = document.querySelector('.hero-galaxy-vid');
    if (galaxyVid) galaxyVid.play();
    // Show terminal text immediately
    const typedEl = document.querySelector('.headline-typed');
    if (typedEl) typedEl.textContent = '>>> Starts Here.';
    const cursorEl = document.querySelector('.headline-cursor');
    if (cursorEl) cursorEl.classList.add('visible');
    // Remove background layers hidden behind the full-opacity galaxy video
    document.querySelectorAll('.hero-bg-canvas, .hero-grid-overlay, .hero-orb, .hero-scanlines, .hero-bottom-fade')
        .forEach(el => el.remove());
}

/* ---- Nav Scroll ---- */
function initNavScrollEffect() {
    const nav = document.getElementById('main-nav');
    if (!nav) return;
    window.addEventListener('scroll', () => {
        nav.classList.toggle('scrolled', window.scrollY > 50);
    }, { passive: true });
}

/* ---- Mobile Nav Toggle ---- */
function initMobileNav() {
    const hamburger = document.getElementById('nav-hamburger');
    const navLinks = document.getElementById('nav-links');
    if (!hamburger || !navLinks) return;

    hamburger.addEventListener('click', () => {
        const isOpen = navLinks.classList.toggle('open');
        hamburger.classList.toggle('open');
        hamburger.setAttribute('aria-expanded', isOpen);
    });

    navLinks.querySelectorAll('.nav-link').forEach(link => {
        link.addEventListener('click', () => {
            navLinks.classList.remove('open');
            hamburger.classList.remove('open');
            hamburger.setAttribute('aria-expanded', 'false');
        });
    });

    document.addEventListener('click', (e) => {
        if (!hamburger.contains(e.target) && !navLinks.contains(e.target)) {
            navLinks.classList.remove('open');
            hamburger.classList.remove('open');
            hamburger.setAttribute('aria-expanded', 'false');
        }
    });
}
