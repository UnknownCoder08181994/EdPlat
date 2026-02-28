/* ============================================
   AWM V2 — Section FX Engine (Optimized)
   - will-change hints for GPU compositing
   - rAF-based typing with char batching
   ============================================ */

class SectionFX {
    constructor() {
        document.addEventListener('section-revealed', (e) => {
            if (e.detail.index === 2) {
                this.reset();
                setTimeout(() => this.activate(), 400);
            }
        });
    }

    reset() {
        const rings = document.querySelectorAll('.lessons-preview .ring-fill:not(.done)');
        rings.forEach((ring) => {
            const circumference = 97.4;
            ring.style.transition = 'none';
            ring.style.strokeDashoffset = circumference;
            void ring.offsetWidth;
            ring.style.transition = '';
        });

        const scoreEl = document.getElementById('quiz-score');
        const completedEl = document.getElementById('quiz-completed');
        const streakEl = document.getElementById('quiz-streak');
        const scoreFill = document.querySelector('.score-fill');

        if (scoreEl) scoreEl.textContent = '0%';
        if (completedEl) completedEl.textContent = '0';
        if (streakEl) streakEl.textContent = '0';
        if (scoreFill) {
            scoreFill.style.transition = 'none';
            scoreFill.style.strokeDashoffset = 213.6;
            void scoreFill.offsetWidth;
            scoreFill.style.transition = '';
        }
    }

    activate() {
        this.animateLessonRings();
        this.animateQuizScore();
    }

    animateLessonRings() {
        const rings = document.querySelectorAll('.lessons-preview .ring-fill:not(.done)');
        rings.forEach((ring) => {
            const circumference = 97.4;
            const target = circumference * 0.4;
            setTimeout(() => {
                ring.style.strokeDashoffset = target;
            }, 600);
        });
    }

    animateQuizScore() {
        const scoreEl = document.getElementById('quiz-score');
        const completedEl = document.getElementById('quiz-completed');
        const streakEl = document.getElementById('quiz-streak');
        const scoreFill = document.querySelector('.score-fill');

        if (!scoreEl || !scoreFill) return;

        const targetScore = 92;
        const targetCompleted = 14;
        const targetStreak = 7;

        const circumference = 213.6;
        const offset = circumference * (1 - targetScore / 100);
        setTimeout(() => {
            scoreFill.style.strokeDashoffset = offset;
        }, 800);

        this.countUp(scoreEl, 0, targetScore, 1400, '%');
        this.countUp(completedEl, 0, targetCompleted, 1200, '');
        this.countUp(streakEl, 0, targetStreak, 1000, '');
    }

    countUp(el, from, to, duration, suffix) {
        if (!el) return;
        if (el._countUpId) cancelAnimationFrame(el._countUpId);

        const start = performance.now();
        const step = (now) => {
            const progress = Math.min((now - start) / duration, 1);
            const eased = 1 - Math.pow(1 - progress, 3);
            const value = Math.round(from + (to - from) * eased);
            el.textContent = value + suffix;
            if (progress < 1) {
                el._countUpId = requestAnimationFrame(step);
            }
        };
        setTimeout(() => {
            el._countUpId = requestAnimationFrame(step);
        }, 600);
    }
}

/* ============================================
   FAQ Accordion (Optimized)
   - will-change on cards during materialize
   - rAF typing loop with 2-char batching
   ============================================ */

class FAQCarousel {
    constructor() {
        this.track = document.querySelector('.faq-track');
        this.cards = [...document.querySelectorAll('.faq-card')];
        this.prevBtn = document.querySelector('.faq-arrow-prev');
        this.nextBtn = document.querySelector('.faq-arrow-next');
        if (!this.track || !this.cards.length) return;

        this.current = 0;
        this.total = this.cards.length;

        this.prevBtn?.addEventListener('click', () => this.go(this.current - 1));
        this.nextBtn?.addEventListener('click', () => this.go(this.current + 1));

        // Click card to select it
        this.cards.forEach((card, i) => {
            card.addEventListener('click', () => {
                if (i !== this.current) this.go(i);
            });
        });

        this.update();
    }

    go(index) {
        if (index < 0 || index >= this.total) return;
        this.current = index;
        this.update();
    }

    update() {
        // Toggle active class
        this.cards.forEach((card, i) => {
            card.classList.toggle('faq-card-active', i === this.current);
        });

        // Calculate track offset — position active card with left margin
        // Inactive cards = 20vw, active = 28vw, gap = 1.2vw
        const vw = window.innerWidth / 100;
        const inactiveW = 20 * vw;
        const activeW = 28 * vw;
        const gap = 1.2 * vw;

        let offset = 0;
        for (let i = 0; i < this.current; i++) {
            offset += inactiveW + gap;
        }

        this.track.style.transform = `translateX(-${offset}px)`;

        // Arrow states
        if (this.prevBtn) {
            this.prevBtn.classList.toggle('faq-arrow-disabled', this.current === 0);
        }
        if (this.nextBtn) {
            this.nextBtn.classList.toggle('faq-arrow-disabled', this.current === this.total - 1);
        }
    }
}

document.addEventListener('DOMContentLoaded', () => {
    new SectionFX();
    window._faqCarousel = new FAQCarousel();
});
