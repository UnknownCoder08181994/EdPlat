document.addEventListener('DOMContentLoaded', () => {
    initNavScrollEffect();
    initMobileNav();

    const params = new URLSearchParams(window.location.search);
    const skipParam = params.has('skip');
    const alreadyDone = sessionStorage.getItem('cinematic-done') === '1';
    const skipCinematic = alreadyDone || skipParam;

    if (skipCinematic) {
        if (skipParam) {
            params.delete('skip');
            const qs = params.toString();
            history.replaceState(null, '', window.location.pathname + (qs ? '?' + qs : ''));
        }

        const splashEl = document.getElementById('splash-overlay');
        if (splashEl) splashEl.classList.add('hidden');
        document.body.classList.add('cinematic-done');

        const fadeOverlay = document.getElementById('page-fade-overlay');
        const revealDelay = fadeOverlay ? 400 : 0;

        setTimeout(() => {
            const gateway = document.getElementById('gateway');
            if (gateway) gateway.classList.add('gw-revealed');
            document.dispatchEvent(new CustomEvent('start-gateway'));
            document.dispatchEvent(new CustomEvent('cinematic-done'));
        }, revealDelay);

        return;
    }

    document.dispatchEvent(new CustomEvent('lock-scroll'));
    const splash = new SplashIntro();

    splash.play().then(() => {
        sessionStorage.setItem('cinematic-done', '1');
        document.body.classList.remove('splash-playing');

        const gateway = document.getElementById('gateway');
        if (gateway) gateway.classList.add('gw-revealed');

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
        document.dispatchEvent(new CustomEvent('start-gateway'));
        document.dispatchEvent(new CustomEvent('cinematic-done'));
    });
});

function initNavScrollEffect() {
    const nav = document.getElementById('main-nav');
    if (!nav) return;
    window.addEventListener('scroll', () => {
        nav.classList.toggle('scrolled', window.scrollY > 50);
    }, { passive: true });
}

function initMobileNav() {
    const hamburger = document.getElementById('nav-hamburger');
    const navLinks = document.getElementById('nav-links');
    if (!hamburger || !navLinks) return;

    hamburger.addEventListener('click', () => {
        const isOpen = navLinks.classList.toggle('open');
        hamburger.classList.toggle('open');
        hamburger.setAttribute('aria-expanded', String(isOpen));
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
