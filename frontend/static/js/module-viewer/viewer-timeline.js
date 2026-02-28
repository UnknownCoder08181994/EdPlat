/* Timeline methods for ModuleCoach */

ModuleCoach.prototype.initTimeline = function() {
    const duration = this.videoDuration;
    if (!duration) return;

    // Single-video timeline: one full-width segment for the current section
    this.timelineTrack.innerHTML = '';
    const seg = document.createElement('div');
    seg.className = 'viewer-timeline-segment active';
    seg.style.flex = 'none';
    seg.style.width = '100%';

    const fill = document.createElement('div');
    fill.className = 'viewer-timeline-segment-fill';
    seg.appendChild(fill);
    this.timelineTrack.appendChild(seg);

    // Build breakdown topic labels (not all sections — just current section's breakdown)
    this.timelineLabels.innerHTML = '';
    const breakdown = this.currentSection.breakdown || [];

    breakdown.forEach((item, i) => {
        const posPercent = duration > 0 ? (item.time / duration) * 100 : 0;

        // Label below the bar
        const label = document.createElement('div');
        label.className = 'viewer-timeline-label' + (i === 0 ? ' active' : '');
        label.dataset.breakdownIndex = i;
        label.style.left = posPercent + '%';
        label.innerHTML = '<span class="viewer-tl-text">' + item.label + '</span>';
        label.addEventListener('click', () => {
            if (this.videoEl.duration && !isNaN(this.videoEl.duration)) {
                this.videoEl.currentTime = Math.min(item.time, this.videoEl.duration);
                this.playVideo();
            }
        });
        this.timelineLabels.appendChild(label);

        // Marker on the progress bar track
        const marker = document.createElement('div');
        marker.className = 'viewer-timeline-marker';
        marker.style.left = posPercent + '%';
        this.timelineTrack.appendChild(marker);
    });

    // Set up drag-to-scrub + preview
    this.initTimelineDrag();
    this.initTimelinePreview();
};

/* ---- Drag-to-Scrub ---- */
ModuleCoach.prototype.initTimelineDrag = function() {
    this.isDragging = false;
    this.wasPlayingBeforeDrag = false;

    const getRatioFromEvent = (e) => {
        const rect = this.timelineTrack.getBoundingClientRect();
        const clientX = e.touches ? e.touches[0].clientX : e.clientX;
        return Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    };

    const startDrag = (e) => {
        if (!this.videoEl.duration || isNaN(this.videoEl.duration)) return;
        // Only start drag if click is near the track (not in labels below)
        const trackRect = this.timelineTrack.getBoundingClientRect();
        const clientY = e.touches ? e.touches[0].clientY : e.clientY;
        const hitPadding = trackRect.height * 3; // generous vertical hit zone around track
        if (clientY < trackRect.top - hitPadding || clientY > trackRect.bottom + hitPadding) return;
        e.preventDefault();
        this.isDragging = true;
        this.wasPlayingBeforeDrag = !this.videoEl.paused;
        this._userPaused = true;
        this.videoEl.pause();
        this.timelinePlayhead.classList.add('dragging');

        const ratio = getRatioFromEvent(e);
        this.videoEl.currentTime = ratio * this.videoEl.duration;
        this.updatePlayheadVisual(ratio);
    };

    const moveDrag = (e) => {
        if (!this.isDragging) return;
        e.preventDefault();
        const ratio = getRatioFromEvent(e);
        this.videoEl.currentTime = ratio * this.videoEl.duration;
        this.updatePlayheadVisual(ratio);
        this.updatePreviewAtRatio(ratio);
    };

    const endDrag = () => {
        if (!this.isDragging) return;
        this.isDragging = false;
        this.timelinePlayhead.classList.remove('dragging');
        if (this.wasPlayingBeforeDrag) {
            this.playVideo();
        }
        this.hidePreview();
    };

    // Mouse events
    this.timelineBar.addEventListener('mousedown', startDrag);
    document.addEventListener('mousemove', moveDrag);
    document.addEventListener('mouseup', endDrag);

    // Touch events
    this.timelineBar.addEventListener('touchstart', startDrag, { passive: false });
    document.addEventListener('touchmove', moveDrag, { passive: false });
    document.addEventListener('touchend', endDrag);
};

ModuleCoach.prototype.updatePlayheadVisual = function(ratio) {
    const pct = ratio * 100;
    this.timelinePlayhead.style.left = pct + '%';
    this.currentTimeEl.textContent = this.formatTime(ratio * this.videoEl.duration);

    // Update fill bar
    const seg = this.timelineTrack.querySelector('.viewer-timeline-segment');
    if (seg) {
        const fill = seg.querySelector('.viewer-timeline-segment-fill');
        if (fill) fill.style.width = Math.min(pct, 100) + '%';
    }
};

/* ---- Preview Thumbnail ---- */
ModuleCoach.prototype.initTimelinePreview = function() {
    this.previewEl = document.getElementById('timeline-preview');
    this.previewCanvas = document.getElementById('timeline-preview-canvas');
    this.previewCtx = this.previewCanvas.getContext('2d');
    this.previewTimeEl = document.getElementById('timeline-preview-time');
    this.previewVideo = document.getElementById('viewer-preview-video');
    this.previewPending = false;

    // Lazy-load preview video on first timeline hover (avoids double-downloading on page load)
    this.previewLoaded = false;
    if (this.previewVideo.readyState < 1) {
        this.previewVideo.addEventListener('loadedmetadata', () => {
            this.previewReady = true;
        });
    } else {
        this.previewReady = true;
        this.previewLoaded = true;
    }

    // Draw frame when preview video seeks
    this.previewVideo.addEventListener('seeked', () => {
        this.previewCtx.drawImage(this.previewVideo, 0, 0, 160, 90);
        this.previewPending = false;
    });

    // Show preview on hover — only near the track line (same hit-test as drag)
    this.timelineBar.addEventListener('mousemove', (e) => {
        if (this.isDragging) return; // Drag handles its own preview
        const trackRect = this.timelineTrack.getBoundingClientRect();
        const clientY = e.clientY;
        const hitPadding = trackRect.height * 3;
        if (clientY < trackRect.top - hitPadding || clientY > trackRect.bottom + hitPadding) {
            this.hidePreview();
            return;
        }
        const ratio = Math.max(0, Math.min(1, (e.clientX - trackRect.left) / trackRect.width));
        this.updatePreviewAtRatio(ratio);
        this.showPreview(ratio);
    });

    this.timelineBar.addEventListener('mouseleave', () => {
        if (!this.isDragging) {
            this.hidePreview();
        }
    });
};

ModuleCoach.prototype.updatePreviewAtRatio = function(ratio) {
    // Trigger lazy load of preview video on first hover
    if (!this.previewLoaded && this.previewVideo) {
        this.previewLoaded = true;
        this.previewVideo.load();
    }
    if (!this.previewReady || !this.previewVideo) return;

    const time = ratio * this.videoEl.duration;
    this.previewTimeEl.textContent = this.formatTime(time);

    // Only seek if not already pending a seek
    if (!this.previewPending) {
        this.previewPending = true;
        this.previewVideo.currentTime = time;
    }

    this.showPreview(ratio);
};

ModuleCoach.prototype.showPreview = function(ratio) {
    if (!this.previewEl) return;
    this.previewEl.classList.add('visible');
    this.previewEl.style.left = (ratio * 100) + '%';
};

ModuleCoach.prototype.hidePreview = function() {
    if (!this.previewEl) return;
    this.previewEl.classList.remove('visible');
};

/* ---- Progress Updates ---- */
ModuleCoach.prototype.updateTimelineProgress = function() {
    if (this.isDragging) return; // Skip during drag

    const video = this.videoEl;
    if (!video.duration || isNaN(video.duration)) return;

    const currentTime = video.currentTime;
    const duration = video.duration;

    // Update time displays
    this.currentTimeEl.textContent = this.formatTime(currentTime);
    this.totalTimeEl.textContent = this.formatTime(duration);

    // Update single segment fill bar
    const progress = currentTime / duration;
    const seg = this.timelineTrack.querySelector('.viewer-timeline-segment');
    if (seg) {
        const fill = seg.querySelector('.viewer-timeline-segment-fill');
        if (fill) fill.style.width = Math.min(progress * 100, 100) + '%';
    }

    // Update playhead position
    this.timelinePlayhead.style.left = (progress * 100) + '%';

    // Highlight active breakdown item based on current time
    this.updateActiveBreakdown(currentTime);
};

ModuleCoach.prototype.updateActiveBreakdown = function(currentTime) {
    if (!this.breakdownTimes.length) return;

    // Find the last breakdown whose time <= currentTime
    let activeIdx = 0;
    for (let i = this.breakdownTimes.length - 1; i >= 0; i--) {
        if (currentTime >= this.breakdownTimes[i]) {
            activeIdx = i;
            break;
        }
    }

    // Highlight the corresponding timeline label
    const timelineLabels = this.timelineLabels.querySelectorAll('.viewer-timeline-label');
    timelineLabels.forEach((label, i) => {
        label.classList.toggle('active', i === activeIdx);
    });

    // Also highlight the corresponding sidebar section item
    this.sectionsListEl.querySelectorAll('.viewer-section-item').forEach((item, i) => {
        item.classList.toggle('active', i === activeIdx);
    });
};

ModuleCoach.prototype.formatTime = function(seconds) {
    if (isNaN(seconds) || seconds < 0) return '0:00';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return mins + ':' + (secs < 10 ? '0' : '') + secs;
};

ModuleCoach.prototype.handleTimelineClick = function(e) {
    if (this.isDragging) return;
    // Only seek if click is near the track, not in the labels area
    const rect = this.timelineTrack.getBoundingClientRect();
    const hitPadding = rect.height * 3;
    if (e.clientY < rect.top - hitPadding || e.clientY > rect.bottom + hitPadding) return;
    const clickX = e.clientX - rect.left;
    const trackWidth = rect.width;
    const clickRatio = Math.max(0, Math.min(1, clickX / trackWidth));

    if (this.videoEl.duration && !isNaN(this.videoEl.duration)) {
        this.videoEl.currentTime = clickRatio * this.videoEl.duration;
    }
};
