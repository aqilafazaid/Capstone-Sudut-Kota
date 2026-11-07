/* ==========================================================================
   MAIN.JS — Pengendali halaman CCTV
   --------------------------------------------------------------------------
   Tanggung jawab:
     1. daftar node per zona (dari Store)
     2. pemutar HLS + status sinyal
     3. panel kontrol AI (toggle + pilihan model)
     4. kartu statistik dari telemetri

   Catatan integrasi Firebase: file ini hanya berbicara dengan Store.
   Saat RTDB aktif, ganti implementasi Store — di sini cukup tambahkan
   pemanggilan Store.setAi() yang sudah ada, tanpa mengubah alur di bawah.
   ========================================================================== */

(function (global) {
    'use strict';

    const HLS_SCRIPT = 'https://cdn.jsdelivr.net/npm/hls.js@1.4.0/dist/hls.min.js';

    const state = {
        activeId: null,
        hls: null,
        unsubscribeTelemetry: null,
        retries: 0,
        mode: null,
        log: []
    };

    const el = {};

    function cacheDom() {
        const ids = [
            'video-element', 'overlay-loading', 'overlay-error', 'overlay-play', 'error-detail',
            'active-cam-city', 'active-cam-name', 'ai-status-indicator', 'desktop-traffic-status',
            'desktop-traffic-text', 'default-status-text', 'resolution-display', 'signal-meter',
            'camera-list-container', 'total-cams', 'search-input', 'ai-log-text',
            'toggle-lowlight', 'toggle-yolo', 'select-lowlight', 'select-yolo',
            'stat-mobil', 'stat-motor', 'stat-truk', 'stat-bus', 'stat-total', 'stat-fps',
            'stream-mode-badge', 'loading-text',
            'btn-volume', 'btn-reload', 'btn-fullscreen', 'btn-retry-overlay', 'operator-badge'
        ];
        ids.forEach(id => { el[id] = document.getElementById(id); });
    }

    /* --- Log ------------------------------------------------------------- */
    function log(message) {
        const stamp = new Date().toLocaleTimeString('id-ID', { hour12: false });
        state.log.push(`[${stamp}] ${message}`);
        if (state.log.length > 30) state.log.shift();
        if (el['ai-log-text']) el['ai-log-text'].textContent = '> ' + message;
        console.debug('[CCTV]', message);
    }

    /* --- Utilitas -------------------------------------------------------- */
    function aiActive(ai) {
        return !!(ai && (ai.yolo || ai.lowlight));
    }

    function setModeBadge(mode) {
        const badge = el['stream-mode-badge'];
        if (!badge) return;
        const text = mode === 'ai' ? 'HLS · AI AKTIF' : 'HLS · TANPA AI';
        badge.textContent = text;
        badge.className = 'text-[10px] font-black uppercase tracking-widest px-2.5 py-1 rounded-md border sk-line ' +
            (mode === 'ai' ? 'text-emerald-600 dark:text-emerald-300' : 'text-blue-600 dark:text-blue-300');
    }

    function isMixedContent(url) {
        return location.protocol === 'https:' && /^http:\/\//i.test(url || '');
    }

    function trafficLevel(total) {
        if (total >= 80) return { text: 'KEPADATAN TINGGI', cls: 'text-red-400' };
        if (total >= 40) return { text: 'ARUS PADAT', cls: 'text-yellow-400' };
        return { text: 'ARUS LANCAR', cls: 'text-emerald-400' };
    }

    function setSignalBars(active) {
        const bars = el['signal-meter'] ? el['signal-meter'].querySelectorAll('.bar') : [];
        bars.forEach((bar, index) => bar.classList.toggle('active', index < active));
    }

    /* --- Daftar kamera --------------------------------------------------- */
    function renderList() {
        const container = el['camera-list-container'];
        if (!container) return;

        const groups = Store.byZone();
        const total = Store.list().length;
        if (el['total-cams']) el['total-cams'].textContent = `${total} NODE`;

        const activeCam = state.activeId ? Store.get(state.activeId) : null;
        const openZone = activeCam ? activeCam.zona : (groups[0] ? groups[0].zona : null);

        container.innerHTML = groups.map((group) => {
            const isOpen = group.zona === openZone;
            const items = group.cameras.map(cam => {
                const online = cam.aktif;
                const isActive = cam.id === state.activeId;
                return `
                    <div class="cam-item ${isActive ? 'active' : ''}" data-cam-id="${cam.id}">
                        <i class="fa-solid fa-camera play-icon text-slate-500 text-base"></i>
                        <span class="cam-name flex-1">${cam.nama}</span>
                        <span class="text-[10px] px-2 py-0.5 rounded border ${
                            online
                                ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/40'
                                : 'bg-red-500/15 text-red-700 dark:text-red-300 border-red-500/40'
                        }">${online ? 'LIVE' : 'OFF'}</span>
                    </div>`;
            }).join('');

            return `
                <div class="accordion-group" data-zone="${group.zona}">
                    <div class="group-header ${isOpen ? 'active' : ''}" data-toggle-group>
                        <div class="group-title">
                            <i class="fa-solid fa-map-location-dot text-[#3b82f6] mr-2"></i> ${group.zona}
                        </div>
                        <i class="fa-solid fa-chevron-down text-slate-500 text-xs"></i>
                    </div>
                    <div class="group-body ${isOpen ? 'open' : ''}">${items}</div>
                </div>`;
        }).join('');

        applySearchFilter();
    }

    /** Pastikan grup yang memuat kamera aktif dalam keadaan terbuka. */
    function openGroupOf(camId) {
        const item = document.querySelector(`#camera-list-container .cam-item[data-cam-id="${camId}"]`);
        if (!item) return;
        const group = item.closest('.accordion-group');
        if (!group) return;
        const body = group.querySelector('.group-body');
        const header = group.querySelector('.group-header');
        if (body) body.classList.add('open');
        if (header) header.classList.add('active');
    }

    function applySearchFilter() {
        const term = (el['search-input'] ? el['search-input'].value : '').trim().toLowerCase();
        document.querySelectorAll('#camera-list-container .accordion-group').forEach(group => {
            let visible = 0;
            group.querySelectorAll('.cam-item').forEach(item => {
                const match = !term || item.textContent.toLowerCase().includes(term);
                item.style.display = match ? 'flex' : 'none';
                if (match) visible += 1;
            });
            const body = group.querySelector('.group-body');
            const header = group.querySelector('.group-header');
            group.style.display = visible > 0 ? 'block' : 'none';
            if (term) {
                if (visible > 0) {
                    body.classList.add('open');
                    header.classList.add('active');
                }
            }
        });
    }

    /* --- Panel AI -------------------------------------------------------- */
    function paintAiPanel(ai) {
        if (!ai) return;

        const lowlightBtn = el['toggle-lowlight'];
        const yoloBtn = el['toggle-yolo'];
        if (lowlightBtn) {
            lowlightBtn.textContent = ai.lowlight ? 'ON' : 'OFF';
            lowlightBtn.setAttribute('aria-checked', String(ai.lowlight));
            lowlightBtn.classList.toggle('active-mirnet', ai.lowlight);
        }
        if (yoloBtn) {
            yoloBtn.textContent = ai.yolo ? 'ON' : 'OFF';
            yoloBtn.setAttribute('aria-checked', String(ai.yolo));
            yoloBtn.classList.toggle('active-yolo', ai.yolo);
        }
        if (el['select-lowlight']) el['select-lowlight'].value = ai.lowlight_model;
        if (el['select-yolo']) el['select-yolo'].value = ai.yolo_model;

        const active = ai.yolo || ai.lowlight;
        if (el['ai-status-indicator']) {
            el['ai-status-indicator'].innerHTML = active
                ? '<i class="fa-solid fa-circle-nodes text-emerald-400"></i> <span class="hidden sm:inline text-emerald-300 tracking-wide uppercase">AI ACTIVE</span>'
                : '<i class="fa-solid fa-power-off text-slate-400"></i> <span class="hidden sm:inline text-slate-300 tracking-wide uppercase">AI INACTIVE</span>';
        }
    }

    /* Panel kontrol AI terbuka untuk semua peran, termasuk visitor tanpa akun.
       Badge hanya menandai siapa yang sedang mengubah parameter. */
    function syncOperatorBadge() {
        const badge = el['operator-badge'];
        if (!badge) return;

        const user = global.Auth ? global.Auth.user() : null;
        badge.textContent = user ? `Akses: ${global.Auth.roleLabel(user.role)}` : 'Akses: Publik';
        badge.className = 'text-[10px] font-black uppercase tracking-widest px-3 py-1.5 rounded-lg border ' +
            'bg-blue-900/30 text-blue-300 border-blue-500/40';

        ['toggle-lowlight', 'toggle-yolo', 'select-lowlight', 'select-yolo'].forEach(id => {
            const node = el[id];
            if (!node) return;
            node.disabled = false;
            node.title = '';
        });
    }

    function commitAi(patch, description) {
        if (!state.activeId) return;

        const ai = Store.setAi(state.activeId, patch);
        paintAiPanel(ai);
        log(description);
        App.toast(description, 'success', 2400);
        applyStream();
    }

    /* --- Pemutar --------------------------------------------------------- */
    function destroyPlayer() {
        if (state.hls) {
            try { state.hls.destroy(); } catch (err) { /* diabaikan */ }
            state.hls = null;
        }
        if (el['video-element']) {
            el['video-element'].removeAttribute('src');
            el['video-element'].load();
        }
    }

    function showError(message) {
        if (el['overlay-loading']) el['overlay-loading'].classList.add('hidden-important');
        if (el['overlay-error']) {
            el['overlay-error'].classList.remove('hidden');
            el['overlay-error'].classList.add('flex');
        }
        if (el['error-detail'] && message) el['error-detail'].textContent = message;
        if (el['resolution-display']) el['resolution-display'].textContent = 'OFFLINE';
        setSignalBars(0);
    }

    function hideError() {
        if (el['overlay-error']) {
            el['overlay-error'].classList.add('hidden');
            el['overlay-error'].classList.remove('flex');
        }
    }

    function loadHls(url) {
        if (!el['video-element']) return;

        if (Hls.isSupported && Hls.isSupported()) {
            state.hls = new Hls({
                manifestLoadingTimeOut: 10000,
                manifestLoadingMaxRetry: 2,
                levelLoadingTimeOut: 10000,
                enableWorker: true
            });

            state.hls.loadSource(url);
            state.hls.attachMedia(el['video-element']);

            state.hls.on(Hls.Events.MANIFEST_PARSED, () => {
                state.retries = 0;
                el['video-element'].play().catch(() => {
                    el['video-element'].muted = true;
                    el['video-element'].play().catch(() => {
                        if (el['overlay-play']) el['overlay-play'].classList.remove('hidden');
                    });
                });
            });

            state.hls.on(Hls.Events.ERROR, (event, data) => {
                if (!data.fatal) return;
                if (data.type === Hls.ErrorTypes.NETWORK_ERROR && state.retries < 2) {
                    state.retries += 1;
                    log(`Galat jaringan HLS (percobaan ${state.retries}/2), memuat ulang manifest...`);
                    state.hls.startLoad();
                } else if (data.type === Hls.ErrorTypes.MEDIA_ERROR) {
                    log('Galat media HLS, mencoba memulihkan dekoder...');
                    state.hls.recoverMediaError();
                } else {
                    log('Manifest tidak dapat dimuat: ' + url);
                    showError('Manifest HLS tidak dapat dimuat. Periksa apakah stream sedang berjalan dan dapat diakses dari peramban.');
                    destroyPlayer();
                }
            });
        } else if (el['video-element'].canPlayType('application/vnd.apple.mpegurl')) {
            el['video-element'].src = url;
            el['video-element'].play().catch(() => {
                if (el['overlay-play']) el['overlay-play'].classList.remove('hidden');
            });
        } else {
            showError('Peramban ini tidak mendukung pemutaran HLS.');
        }
    }

    /**
     * Satu sumber per node: HLS. Server lokal mengubah RTSP menjadi m3u8 untuk
     * mode AI maupun non-AI, jadi peramban selalu memutar URL yang sama.
     */
    function applyStream() {
        const cam = Store.get(state.activeId);
        if (!cam) return;

        const ai = Store.getAi(cam.id);
        const mode = aiActive(ai) ? 'ai' : 'hls';
        const url = Store.hlsUrl(cam);
        state.mode = mode;

        destroyPlayer();
        state.retries = 0;
        hideError();
        if (el['overlay-play']) el['overlay-play'].classList.add('hidden');
        if (el['overlay-loading']) {
            el['overlay-loading'].classList.remove('hidden-important');
            el['overlay-loading'].classList.remove('hidden');
        }
        if (el['resolution-display']) el['resolution-display'].textContent = 'DETECTING...';
        setSignalBars(0);
        setModeBadge(mode);

        if (!cam.aktif) {
            log(`Node ${cam.id} ditandai OFFLINE - stream tidak dimuat.`);
            showError('Node ini ditandai OFFLINE pada data. Aktifkan di dashboard setelah server stream menyala.');
            return;
        }

        if (!url) {
            if (el['default-status-text']) el['default-status-text'].textContent = 'ALAMAT SERVER BELUM DIATUR';
            log(`Node ${cam.id} tidak punya URL HLS dan backendBase kosong.`);
            showError('Alamat server lokal belum diatur. Isi localStorage "sudutkota.backend" dengan URL server, mis. http://127.0.0.1:5000.');
            return;
        }

        if (isMixedContent(url)) {
            showError('Stream memakai HTTP sedangkan halaman ini HTTPS — peramban memblokir mixed content. Pakai URL tunnel HTTPS untuk server lokal.');
            log('Mixed content terdeteksi: ' + url);
            return;
        }

        log(`Memuat HLS ${cam.nama}...`);
        console.debug('[CCTV] URL', url);
        loadHls(url);
    }

    function selectCamera(id) {
        const cam = Store.get(id);
        if (!cam) return;

        state.activeId = id;

        if (el['active-cam-city']) el['active-cam-city'].textContent = cam.zona || cam.kota || 'TANPA ZONA';
        if (el['active-cam-name']) el['active-cam-name'].textContent = cam.nama || cam.id;

        document.querySelectorAll('#camera-list-container .cam-item').forEach(item => {
            item.classList.toggle('active', item.dataset.camId === id);
        });
        openGroupOf(id);

        paintAiPanel(Store.getAi(id));
        applyStream();

        if (state.unsubscribeTelemetry) state.unsubscribeTelemetry();
        state.unsubscribeTelemetry = Store.subscribeTelemetry(id, updateStats);
    }

    function updateStats(data) {
        if (el['stat-mobil']) el['stat-mobil'].textContent = data.jumlah_mobil ?? 0;
        if (el['stat-motor']) el['stat-motor'].textContent = data.jumlah_motor ?? 0;
        if (el['stat-truk']) el['stat-truk'].textContent = data.jumlah_truk ?? 0;
        if (el['stat-bus']) el['stat-bus'].textContent = data.jumlah_bus ?? 0;
        if (el['stat-total']) el['stat-total'].textContent = data.total_kendaraan ?? 0;
        if (el['stat-fps']) el['stat-fps'].textContent = data.status === 'OFFLINE' ? '—' : (data.server_fps ?? 0);

        const level = trafficLevel(data.total_kendaraan || 0);
        if (el['desktop-traffic-status'] && data.status !== 'OFFLINE') {
            el['desktop-traffic-status'].classList.remove('hidden');
            el['desktop-traffic-status'].classList.add('flex');
            if (el['desktop-traffic-text']) {
                el['desktop-traffic-text'].innerHTML =
                    `${level.text} &middot; <span class="text-white">${data.total_kendaraan}</span> kendaraan`;
            }
        } else if (el['desktop-traffic-status']) {
            el['desktop-traffic-status'].classList.add('hidden');
            el['desktop-traffic-status'].classList.remove('flex');
        }

        if (el['default-status-text']) {
            el['default-status-text'].textContent = data.status === 'OFFLINE'
                ? 'NODE OFFLINE'
                : (state.mode === 'ai' ? 'STREAMING HLS · AI AKTIF' : 'STREAMING HLS · TANPA AI');
        }
    }

    /* --- Event ----------------------------------------------------------- */
    function bindEvents() {
        const video = el['video-element'];

        if (video) {
            video.addEventListener('loadedmetadata', () => {
                if (el['resolution-display']) {
                    el['resolution-display'].textContent = `${video.videoWidth}x${video.videoHeight}`;
                }
            });

            video.addEventListener('playing', () => {
                if (el['overlay-loading']) el['overlay-loading'].classList.add('hidden-important');
                hideError();
                if (el['overlay-play']) el['overlay-play'].classList.add('hidden');
                setSignalBars(4);
            });

            video.addEventListener('waiting', () => setSignalBars(2));
            video.addEventListener('error', () => {
                setSignalBars(0);
                log('Elemen video melaporkan galat.');
            });
        }

        if (el['overlay-play']) {
            el['overlay-play'].addEventListener('click', () => {
                el['overlay-play'].classList.add('hidden');
                if (video) video.play().catch(() => App.toast('Peramban menolak memutar otomatis. Klik lagi.', 'error'));
            });
        }

        if (el['btn-retry-overlay']) el['btn-retry-overlay'].addEventListener('click', () => applyStream());

        if (el['btn-reload']) el['btn-reload'].addEventListener('click', () => { log('Muat ulang manual.'); applyStream(); });

        if (el['btn-volume']) {
            el['btn-volume'].addEventListener('click', () => {
                if (!video) return;
                video.muted = !video.muted;
                el['btn-volume'].innerHTML = video.muted
                    ? '<i class="fa-solid fa-volume-xmark text-sm"></i>'
                    : '<i class="fa-solid fa-volume-high text-sm text-[#3b82f6]"></i>';
            });
        }

        if (el['btn-fullscreen']) {
            el['btn-fullscreen'].addEventListener('click', () => {
                const wrapper = document.querySelector('.video-wrapper');
                if (!wrapper) return;
                if (!document.fullscreenElement) {
                    (wrapper.requestFullscreen || wrapper.webkitRequestFullscreen || function () {}).call(wrapper);
                } else {
                    document.exitFullscreen();
                }
            });
        }

        if (el['search-input']) {
            el['search-input'].addEventListener('input', applySearchFilter);
        }

        const container = el['camera-list-container'];
        if (container) {
            container.addEventListener('click', (event) => {
                const item = event.target.closest('.cam-item');
                if (item && item.dataset.camId) {
                    selectCamera(item.dataset.camId);
                    return;
                }
                const header = event.target.closest('[data-toggle-group]');
                if (header) {
                    header.classList.toggle('active');
                    const body = header.nextElementSibling;
                    if (body) body.classList.toggle('open');
                }
            });
        }

        if (el['toggle-lowlight']) {
            el['toggle-lowlight'].addEventListener('click', () => {
                const ai = Store.getAi(state.activeId);
                const next = !ai.lowlight;
                commitAi(
                    { lowlight: next },
                    `LowLight ${next ? 'diaktifkan' : 'dimatikan'} (${ai.lowlight_model}) pada ${state.activeId}.`
                );
            });
        }

        if (el['toggle-yolo']) {
            el['toggle-yolo'].addEventListener('click', () => {
                const ai = Store.getAi(state.activeId);
                const next = !ai.yolo;
                commitAi(
                    { yolo: next },
                    `Deteksi YOLO ${next ? 'diaktifkan' : 'dimatikan'} (${ai.yolo_model}) pada ${state.activeId}.`
                );
            });
        }

        if (el['select-lowlight']) {
            el['select-lowlight'].addEventListener('change', (event) => {
                commitAi({ lowlight_model: event.target.value }, `Model low-light diset ke ${event.target.value}.`);
            });
        }

        if (el['select-yolo']) {
            el['select-yolo'].addEventListener('change', (event) => {
                commitAi({ yolo_model: event.target.value }, `Model YOLO diset ke ${event.target.value}.`);
            });
        }

        document.addEventListener('auth:change', syncOperatorBadge);
        document.addEventListener('store:change', () => {
            renderList();
            if (state.activeId && !Store.get(state.activeId)) {
                const fallback = Store.firstPlayable();
                if (fallback) selectCamera(fallback.id);
            }
        });
    }

    /* --- Inisialisasi ---------------------------------------------------- */
    function init() {
        cacheDom();
        if (!el['video-element']) return;

        syncOperatorBadge();
        bindEvents();

        const start = Store.firstPlayable();
        if (!start) {
            showError('Belum ada node CCTV pada data.');
            return;
        }

        state.activeId = start.id;
        renderList();
        selectCamera(start.id);
        log(`Engine siap. Node default: ${start.id} (${start.nama}).`);
    }

    /* Muat hls.js bila belum tersedia (mis. skrip CDN gagal). */
    function ensureHls(callback) {
        if (global.Hls) { callback(); return; }
        const script = document.createElement('script');
        script.src = HLS_SCRIPT;
        script.onload = callback;
        script.onerror = () => console.error('[CCTV] Gagal memuat hls.js');
        document.head.appendChild(script);
    }

    global.CctvPlayer = {
        /* Tunggu daftar node dari backend sebelum menentukan node default. */
        init: function () {
            Store.ready().then(() => ensureHls(init));
        },
        select: selectCamera,
        refresh: applyStream
    };
})(window);
