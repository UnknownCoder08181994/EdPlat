/* Video card rendering for AgentChat (split from chat-messages.js) */

AgentChat.prototype.appendVideoCard = function(container, video) {
    var card = document.createElement('div');
    card.className = 'msg-video-card';

    var moduleBtn = '';
    if (video.moduleUrl) {
        moduleBtn =
            '<a class="msg-video-module-btn" href="' + video.moduleUrl + '">' +
                '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>' +
                'View in Module' +
            '</a>';
    }

    var videoSrc = '/static/videos/' + video.src;

    card.innerHTML =
        '<div class="msg-video-header">' +
            '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>' +
            '<span class="msg-video-label">' + (video.label || 'Watch Video') + '</span>' +
            moduleBtn +
        '</div>' +
        '<div class="msg-video-wrapper">' +
            '<div class="msg-video-inner">' +
                '<video class="msg-video-player" preload="metadata" disablepictureinpicture disableremoteplayback controlslist="nofullscreen nodownload noremoteplayback noplaybackrate">' +
                    '<source src="' + videoSrc + '" type="video/mp4">' +
                '</video>' +
                '<div class="msg-video-overlay">' +
                    '<button class="msg-play-btn">' +
                        '<svg viewBox="0 0 24 24" fill="currentColor" stroke="none">' +
                            '<polygon points="7 3 21 12 7 21 7 3"/>' +
                        '</svg>' +
                    '</button>' +
                '</div>' +
                '<div class="msg-video-controls">' +
                    '<button class="msg-ctrl-btn msg-mute-btn" title="Mute / Unmute">' +
                        '<svg class="msg-mute-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
                            '<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>' +
                            '<path d="M19.07 4.93a10 10 0 0 1 0 14.14"/>' +
                            '<path d="M15.54 8.46a5 5 0 0 1 0 7.07"/>' +
                        '</svg>' +
                    '</button>' +
                    '<button class="msg-ctrl-btn msg-expand-btn" title="Fullscreen">' +
                        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
                            '<path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/>' +
                        '</svg>' +
                    '</button>' +
                '</div>' +
            '</div>' +
            '<div class="msg-video-timeline">' +
                '<span class="msg-timeline-time msg-timeline-current">0:00</span>' +
                '<div class="msg-timeline-bar">' +
                    '<div class="msg-timeline-track">' +
                        '<div class="msg-timeline-fill"></div>' +
                    '</div>' +
                    '<div class="msg-timeline-playhead"></div>' +
                    '<div class="msg-timeline-preview">' +
                        '<canvas class="msg-timeline-canvas" width="160" height="90"></canvas>' +
                        '<span class="msg-timeline-preview-time">0:00</span>' +
                    '</div>' +
                '</div>' +
                '<span class="msg-timeline-time msg-timeline-total">0:00</span>' +
            '</div>' +
            '<video class="msg-preview-video" muted preload="none" style="display:none">' +
                '<source src="' + videoSrc + '" type="video/mp4">' +
            '</video>' +
        '</div>';

    container.appendChild(card);

    // --- Element refs ---
    var videoEl  = card.querySelector('video');
    var wrapper  = card.querySelector('.msg-video-wrapper');
    var overlay  = card.querySelector('.msg-video-overlay');
    var playSvg  = card.querySelector('.msg-play-btn svg');
    var muteBtn  = card.querySelector('.msg-mute-btn');
    var muteIcon = card.querySelector('.msg-mute-icon');
    var expandBtn = card.querySelector('.msg-expand-btn');

    if (videoEl && overlay && wrapper) {
        // --- State flags (same as module viewer) ---
        var _userPaused = false;
        var _autoRetried = false;
        var _playGuard = false;
        var _pauseTimer = null;
        var hasStarted = false;

        function playVideo() {
            _userPaused = false;
            _autoRetried = false;
            _playGuard = true;
            setTimeout(function() { _playGuard = false; }, 300);
            overlay.classList.add('hidden');
            videoEl.play().catch(function() {
                if (_autoRetried) return;
                _playGuard = false;
                overlay.classList.remove('hidden');
            });
        }

        function togglePlayPause() {
            if (_playGuard) return;
            if (videoEl.paused) {
                _userPaused = false;
                videoEl.play().catch(function() {});
            } else {
                _userPaused = true;
                videoEl.pause();
            }
        }

        function updateOverlayIcon() {
            if (videoEl.paused) {
                playSvg.innerHTML = '<polygon points="7 3 21 12 7 21 7 3"/>';
            } else {
                playSvg.innerHTML = '<rect x="5" y="3" width="5" height="18"/><rect x="14" y="3" width="5" height="18"/>';
            }
        }

        function updateMuteIcon() {
            if (!muteIcon) return;
            if (videoEl.muted) {
                muteIcon.innerHTML = '<path d="M11 5L6 9H2v6h4l5 4V5z"/><line x1="23" y1="9" x2="17" y2="15"/><line x1="17" y1="9" x2="23" y2="15"/>';
            } else {
                muteIcon.innerHTML = '<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/>';
            }
        }

        overlay.addEventListener('click', function() { playVideo(); });
        videoEl.addEventListener('click', function() { togglePlayPause(); });

        videoEl.addEventListener('play', function() {
            clearTimeout(_pauseTimer);
            hasStarted = true;
            overlay.classList.add('hidden');
            updateOverlayIcon();
        });

        videoEl.addEventListener('pause', function() {
            if (hasStarted) {
                if (!_userPaused && !_autoRetried) {
                    _autoRetried = true;
                    videoEl.play().catch(function() {});
                    return;
                }
                clearTimeout(_pauseTimer);
                _pauseTimer = setTimeout(function() {
                    if (videoEl.paused && hasStarted) {
                        updateOverlayIcon();
                        overlay.classList.remove('hidden');
                    }
                }, 200);
            }
        });

        videoEl.addEventListener('ended', function() {
            clearTimeout(_pauseTimer);
            hasStarted = false;
            updateOverlayIcon();
            overlay.classList.remove('hidden');
        });

        if (muteBtn) {
            muteBtn.addEventListener('click', function(e) {
                e.stopPropagation();
                videoEl.muted = !videoEl.muted;
                updateMuteIcon();
            });
            videoEl.addEventListener('volumechange', function() { updateMuteIcon(); });
        }

        if (expandBtn) {
            expandBtn.addEventListener('click', function(e) {
                e.stopPropagation();
                if (document.fullscreenElement === wrapper) {
                    document.exitFullscreen();
                } else {
                    wrapper.classList.add('fs-active');
                    wrapper.requestFullscreen().catch(function() {});
                }
            });
            wrapper.addEventListener('fullscreenchange', function() {
                if (document.fullscreenElement === wrapper) {
                    wrapper.classList.add('fs-active');
                } else {
                    wrapper.classList.remove('fs-active');
                }
            });
        }

        // --- Timeline scrubber ---
        var tlBar      = card.querySelector('.msg-timeline-bar');
        var tlTrack    = card.querySelector('.msg-timeline-track');
        var tlFill     = card.querySelector('.msg-timeline-fill');
        var tlPlayhead = card.querySelector('.msg-timeline-playhead');
        var tlCurrent  = card.querySelector('.msg-timeline-current');
        var tlTotal    = card.querySelector('.msg-timeline-total');

        if (tlBar && tlTrack && tlFill && tlPlayhead) {
            var isDragging = false;
            var wasPlayingBeforeDrag = false;

            function formatTime(s) {
                if (isNaN(s) || s < 0) return '0:00';
                var m = Math.floor(s / 60);
                var sec = Math.floor(s % 60);
                return m + ':' + (sec < 10 ? '0' : '') + sec;
            }

            function getRatio(e) {
                var rect = tlTrack.getBoundingClientRect();
                var x = e.touches ? e.touches[0].clientX : e.clientX;
                return Math.max(0, Math.min(1, (x - rect.left) / rect.width));
            }

            function updateVisual(ratio) {
                var pct = ratio * 100;
                tlPlayhead.style.left = pct + '%';
                tlFill.style.width = pct + '%';
                if (tlCurrent) tlCurrent.textContent = formatTime(ratio * videoEl.duration);
            }

            function initTimeline() {
                if (tlTotal) tlTotal.textContent = formatTime(videoEl.duration);
                if (tlCurrent) tlCurrent.textContent = '0:00';
            }

            videoEl.addEventListener('loadedmetadata', initTimeline);
            if (videoEl.readyState >= 1 && videoEl.duration) initTimeline();

            videoEl.addEventListener('timeupdate', function() {
                if (isDragging) return;
                var d = videoEl.duration;
                if (!d || isNaN(d)) return;
                var ratio = videoEl.currentTime / d;
                tlPlayhead.style.left = (ratio * 100) + '%';
                tlFill.style.width = (ratio * 100) + '%';
                if (tlCurrent) tlCurrent.textContent = formatTime(videoEl.currentTime);
            });

            tlBar.addEventListener('click', function(e) {
                if (isDragging) return;
                if (!videoEl.duration || isNaN(videoEl.duration)) return;
                var ratio = getRatio(e);
                videoEl.currentTime = ratio * videoEl.duration;
                updateVisual(ratio);
            });

            var startDrag = function(e) {
                if (!videoEl.duration || isNaN(videoEl.duration)) return;
                e.preventDefault();
                isDragging = true;
                wasPlayingBeforeDrag = !videoEl.paused;
                _userPaused = true;
                videoEl.pause();
                tlPlayhead.classList.add('dragging');
                var ratio = getRatio(e);
                videoEl.currentTime = ratio * videoEl.duration;
                updateVisual(ratio);
            };

            var moveDrag = function(e) {
                if (!isDragging) return;
                e.preventDefault();
                var ratio = getRatio(e);
                videoEl.currentTime = ratio * videoEl.duration;
                updateVisual(ratio);
            };

            var endDrag = function() {
                if (!isDragging) return;
                isDragging = false;
                tlPlayhead.classList.remove('dragging');
                if (wasPlayingBeforeDrag) {
                    playVideo();
                }
            };

            tlBar.addEventListener('mousedown', startDrag);
            document.addEventListener('mousemove', moveDrag);
            document.addEventListener('mouseup', endDrag);
            tlBar.addEventListener('touchstart', startDrag, { passive: false });
            document.addEventListener('touchmove', moveDrag, { passive: false });
            document.addEventListener('touchend', endDrag);

            // --- Timeline preview on hover ---
            var previewVideo  = card.querySelector('.msg-preview-video');
            var previewEl     = card.querySelector('.msg-timeline-preview');
            var previewCanvas = card.querySelector('.msg-timeline-canvas');
            var previewTime   = card.querySelector('.msg-timeline-preview-time');
            var previewCtx    = previewCanvas ? previewCanvas.getContext('2d') : null;
            var previewLoaded = false;

            if (previewEl && previewVideo && previewCanvas && previewCtx) {
                previewVideo.addEventListener('seeked', function() {
                    previewCtx.drawImage(previewVideo, 0, 0, 160, 90);
                });

                tlBar.addEventListener('mouseenter', function() {
                    if (!previewLoaded && previewVideo.preload === 'none') {
                        previewVideo.preload = 'auto';
                        previewVideo.load();
                        previewLoaded = true;
                    }
                    previewEl.classList.add('visible');
                });

                tlBar.addEventListener('mousemove', function(e) {
                    if (!videoEl.duration || isNaN(videoEl.duration)) return;
                    var rect = tlTrack.getBoundingClientRect();
                    var x = e.clientX - rect.left;
                    var ratio = Math.max(0, Math.min(1, x / rect.width));
                    var seekTime = ratio * videoEl.duration;

                    var pct = ratio * 100;
                    previewEl.style.left = pct + '%';
                    if (previewTime) previewTime.textContent = formatTime(seekTime);

                    if (previewVideo.readyState >= 1) {
                        previewVideo.currentTime = seekTime;
                    }
                });

                tlBar.addEventListener('mouseleave', function() {
                    previewEl.classList.remove('visible');
                });
            }
        }
    }

    this.scrollToBottom();
};
