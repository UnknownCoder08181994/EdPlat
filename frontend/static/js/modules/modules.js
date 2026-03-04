class ModulesCatalogue {
    constructor() {
        this.grid = document.getElementById('catalogue-grid');
        this.cards = Array.from(this.grid.querySelectorAll('.course-card'));
        this.pills = Array.from(document.querySelectorAll('.filter-pill'));
        this.searchInput = document.getElementById('toolbar-search');
        this.countEl = document.getElementById('toolbar-count');
        this.emptyEl = document.getElementById('catalogue-empty');
        this.activeFilter = 'all';
        this.searchTerm = '';
        this.activeTopic = '';
        this.activeDifficulty = '';
        this.debounceTimer = null;

        // Topic dropdown
        this.dropdown = document.getElementById('toolbar-topic-dropdown');
        this.dropdownBtn = document.getElementById('toolbar-topic-btn');
        this.dropdownMenu = document.getElementById('toolbar-topic-menu');
        this.dropdownLabel = this.dropdownBtn.querySelector('.toolbar-dropdown-label');
        this.dropdownItems = Array.from(this.dropdownMenu.querySelectorAll('.toolbar-dropdown-item'));

        // Difficulty dropdown
        this.diffDropdown = document.getElementById('toolbar-difficulty-dropdown');
        this.diffDropdownBtn = document.getElementById('toolbar-difficulty-btn');
        this.diffDropdownMenu = document.getElementById('toolbar-difficulty-menu');
        this.diffDropdownLabel = this.diffDropdownBtn.querySelector('.toolbar-dropdown-label');
        this.diffDropdownItems = Array.from(this.diffDropdownMenu.querySelectorAll('.toolbar-dropdown-item'));

        this.bindEvents();
        this.render();
    }

    bindEvents() {
        // Filter pills
        this.pills.forEach(pill => {
            pill.addEventListener('click', () => {
                this.pills.forEach(p => p.classList.remove('active'));
                pill.classList.add('active');
                this.activeFilter = pill.dataset.filter;
                this.render();
            });
        });

        // Search
        this.searchInput.addEventListener('input', () => {
            clearTimeout(this.debounceTimer);
            this.debounceTimer = setTimeout(() => {
                this.searchTerm = this.searchInput.value.trim().toLowerCase();
                this.render();
            }, 200);
        });

        // Topic dropdown
        this.dropdownBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            this.diffDropdown.classList.remove('open');
            this.dropdown.classList.toggle('open');
        });

        this.dropdownItems.forEach(item => {
            item.addEventListener('click', (e) => {
                e.stopPropagation();
                this.dropdownItems.forEach(i => i.classList.remove('active'));
                item.classList.add('active');
                this.activeTopic = item.dataset.value;
                this.dropdownLabel.textContent = item.textContent;
                this.dropdown.classList.remove('open');
                this.render();
            });
        });

        // Difficulty dropdown
        this.diffDropdownBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            this.dropdown.classList.remove('open');
            this.diffDropdown.classList.toggle('open');
        });

        this.diffDropdownItems.forEach(item => {
            item.addEventListener('click', (e) => {
                e.stopPropagation();
                this.diffDropdownItems.forEach(i => i.classList.remove('active'));
                item.classList.add('active');
                this.activeDifficulty = item.dataset.value;
                this.diffDropdownLabel.textContent = item.textContent;
                this.diffDropdown.classList.remove('open');
                this.render();
            });
        });

        // Close all dropdowns on outside click
        document.addEventListener('click', () => {
            this.dropdown.classList.remove('open');
            this.diffDropdown.classList.remove('open');
        });

        // Start buttons — mark empty-slug cards as Coming Soon
        document.querySelectorAll('.course-start-btn').forEach(btn => {
            var slug = btn.closest('.course-card').dataset.slug;
            if (!slug) {
                btn.textContent = 'Coming Soon';
                btn.classList.add('course-start-btn--disabled');
                btn.disabled = true;
                btn.closest('.course-card').classList.add('course-card--coming-soon');
            } else {
                btn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    var basePath = window.location.pathname.startsWith('/tutorials') ? '/tutorials/' : '/modules/';
                    window.location.href = basePath + slug;
                });
            }
        });
    }

    render() {
        var visible = 0;
        this.cards.forEach(card => {
            var tags = card.dataset.tags || '';
            var title = card.querySelector('.course-card-title').textContent.toLowerCase();
            var desc = card.querySelector('.course-card-desc').textContent.toLowerCase();
            var show = true;

            if (this.activeFilter !== 'all') {
                if (!tags.includes(this.activeFilter)) { show = false; }
            }
            if (this.activeTopic && show) {
                if (!tags.includes(this.activeTopic)) { show = false; }
            }
            if (this.activeDifficulty && show) {
                if (!tags.includes(this.activeDifficulty)) { show = false; }
            }
            if (this.searchTerm && show) {
                if (!title.includes(this.searchTerm) && !desc.includes(this.searchTerm)) { show = false; }
            }

            card.style.display = show ? '' : 'none';
            if (show) visible++;
        });

        var isTutorials = window.location.pathname.startsWith('/tutorials');
        var label = isTutorials ? (visible === 1 ? ' Tutorial' : ' Tutorials') : (visible === 1 ? ' Module' : ' Modules');
        this.countEl.textContent = visible + label;
        if (visible === 0) {
            this.emptyEl.classList.add('visible');
        } else {
            this.emptyEl.classList.remove('visible');
        }
    }
}

document.addEventListener('DOMContentLoaded', () => { new ModulesCatalogue(); });
