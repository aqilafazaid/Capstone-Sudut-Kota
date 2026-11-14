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
        log: [],
        telemetry: null,
        aiPending: null,
        aiCatalog: null,
        fpsSamples: null
    };

    const el = {};

    function cacheDom() {
        const ids = [
            'video-element', 'overlay-loading', 'overlay-error', 'overlay-play', 'error-detail',
            'active-cam-city', 'active-cam-name', 'ai-status-indicator', 'latency-value',
            'default-status-text', 'resolution-display', 'signal-meter',
            'camera-list-container', 'total-cams', 'search-input', 'ai-log-text',
            'toggle-lowlight', 'toggle-yolo', 'select-lowlight', 'select-yolo',
            'stat-mobil', 'stat-motor', 'stat-truk', 'stat-bus', 'stat-total', 'stat-fps',
            'stream-mode-badge', 'loading-text',
            'btn-volume', 'btn-reload', 'btn-fullscreen', 'btn-retry-overlay', 'operator-badge',
            'ai-engine-device', 'ai-engine-detect', 'ai-engine-encoder', 'ai-engine-enhance'
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
            (mode === 'ai' ? 'text-emerald-700 dark:text-emerald-300' : 'text-blue-700 dark:text-blue-300');
    }

    function isMixedContent(url) {
        return location.protocol === 'https:' && /^http:\/\//i.test(url || '');
    }

    /* FPS yang tampil: jumlah frame yang benar-benar didekode per detik
       nyata (totalVideoFrames / waktu), bukan angka kiriman server. Dengan
       definisi yang sama di engine, keduanya bisa dibandingkan langsung. */
    function paintFps() {
        const target = el['stat-fps'];
        const video = el['video-element'];
        if (!target || !video) return;

        const quality = typeof video.getVideoPlaybackQuality === 'function'
            ? video.getVideoPlaybackQuality() : null;
        const frames = quality
            ? Number(quality.totalVideoFrames || 0)
            : Number(video.webkitDecodedFrameCount || 0);

        /* Rata-rata sampai 2,5 dtk: cukup panjang agar jeda buffer tidak
           langsung memunculkan 0,0, tetapi tetap frame nyata / waktu nyata. */
        const now = performance.now();
        state.fpsSamples = (state.fpsSamples || []).concat([{ frames, at: now }])
            .filter(sample => now - sample.at <= 2500);
        const first = state.fpsSamples[0];
        if (!first) return;
        if (now - first.at < 1000) {
            if (state.fpsSamples.length === 1) target.textContent = '—';
            return;
        }
        if (video.readyState < 2 || video.paused) {
            target.textContent = '—';
            return;
        }
        target.textContent = ((frames - first.frames) / ((now - first.at) / 1000)).toFixed(1);
    }

    /* Latensi yang tampil: selisih waktu sekarang dengan waktu rekam frame
       yang sedang diputar. EXT-X-PROGRAM-DATE-TIME (ffmpeg) membuat hls.js
       tahu `playingDate`, jadi angkanya mengukur hasil akhir di peramban —
       termasuk buffer pemutar, bukan hanya waktu proses engine. */
    function paintLatency() {
        const target = el['latency-value'];
        if (!target) return;

        let ms = null;
        if (state.hls && state.hls.playingDate) {
            ms = Date.now() - state.hls.playingDate.getTime();
        }
        if (ms !== null && ms >= 0 && ms < 180000) {
            target.textContent = `Latensi ${(ms / 1000).toFixed(1)} dtk`;
            return;
        }
        const engineMs = state.telemetry && state.telemetry.latency_ms;
        target.textContent = engineMs ? `Latensi AI ${(engineMs / 1000).toFixed(2)} dtk` : 'Latensi —';
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
                                ? 'bg-emerald-500/15 text-emerald-800 dark:text-emerald-300 border-emerald-500/40'
                                : 'bg-red-500/15 text-red-800 dark:text-red-300 border-red-500/40'
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
    function canControl() {
        return !!(global.Auth && global.Auth.isOperator && global.Auth.isOperator());
    }

    /* Isi dropdown model dari katalog backend (`GET /api/ai`), bukan dari
       daftar hardcoded: nama harus sama dengan yang dikenal registry engine. */
    function paintAiCatalog(catalog) {
        if (!catalog) return;
        const lowlight = (catalog.lowlight || []).filter(item => item.name !== 'none');
        if (el['select-lowlight']) {
            el['select-lowlight'].innerHTML = lowlight
                .map(item => `<option value="${item.name}">${item.label || item.name}</option>`)
                .join('');
        }
        const yolo = catalog.yolo || [];
        if (el['select-yolo']) {
            el['select-yolo'].innerHTML = yolo.length
                ? yolo.map(item => `<option value="${item.name}">${item.label || item.name}</option>`).join('')
                : '<option value="">Tidak ada bobot</option>';
            /* Satu bobot per engine: pilihan hanya informasi, bukan kontrol. */
            el['select-yolo'].disabled = true;
        }
    }

    function paintAiPanel(ai) {
        if (!ai) return;
        const pending = state.aiPending;

        const lowlightBtn = el['toggle-lowlight'];
        const yoloBtn = el['toggle-yolo'];
        if (lowlightBtn) {
            lowlightBtn.textContent = pending && 'lowlight_enabled' in pending
                ? '…' : (ai.lowlight ? 'ON' : 'OFF');
            lowlightBtn.setAttribute('aria-checked', String(ai.lowlight));
            lowlightBtn.classList.toggle('active-mirnet', ai.lowlight);
        }
        if (yoloBtn) {
            yoloBtn.textContent = pending && 'yolo_enabled' in pending
                ? '…' : (ai.yolo ? 'ON' : 'OFF');
            yoloBtn.setAttribute('aria-checked', String(ai.yolo));
            yoloBtn.classList.toggle('active-yolo', ai.yolo);
        }
        if (el['select-lowlight']) {
            const variant = ai.lowlight_variant || '';
            const known = Array.from(el['select-lowlight'].options).some(o => o.value === variant);
            if (known) el['select-lowlight'].value = variant;
        }

        /* Beban kerja engine: bukti visual bahwa AI benar-benar berjalan di
           GPU atau CPU, dan seberapa cepat deteksi diperbarui. */
        const deviceText = (() => {
            let raw = String(ai.device || '').trim();
            if (!raw) return '—';
            if (/^cuda/i.test(raw)) {
                let name = raw.slice(4).trim();
                if (name.startsWith('(')) name = name.slice(1);
                if (name.endsWith(')')) name = name.slice(0, -1);
                name = name.trim();
                return 'GPU · ' + name;
            }
            return raw.toUpperCase();
        })();
        if (el['ai-engine-device']) el['ai-engine-device'].textContent = deviceText;
        if (el['ai-engine-detect']) {
            el['ai-engine-detect'].textContent = ai.detect_fps
                ? `${Number(ai.detect_fps).toLocaleString('id-ID', { maximumFractionDigits: 1 })}/dtk`
                : '—';
        }
        if (el['ai-engine-encoder']) {
            const encoder = String(ai.encoder || '');
            el['ai-engine-encoder'].textContent = encoder === 'h264_nvenc' ? 'NVENC'
                : encoder ? encoder.replace('lib', '').toUpperCase() : '—';
        }
        if (el['ai-engine-enhance']) {
            el['ai-engine-enhance'].textContent = ai.enhance_ms ? `${Math.round(ai.enhance_ms)} ms` : '—';
        }

        const active = ai.yolo || ai.lowlight;
        if (el['ai-status-indicator']) {
            el['ai-status-indicator'].innerHTML = active
                ? '<i class="fa-solid fa-circle-nodes text-emerald-400"></i> <span class="hidden sm:inline text-emerald-300 tracking-wide uppercase">AI ACTIVE</span>'
                : '<i class="fa-solid fa-power-off text-slate-400"></i> <span class="hidden sm:inline text-slate-300 tracking-wide uppercase">AI INACTIVE</span>';
        }
    }

    /* Kontrol AI mengubah parameter operator; Visitor dan tamu hanya boleh
       menonton. Backend juga menolak endpoint tulis untuk peran non-operator. */
    function syncOperatorBadge() {
        const badge = el['operator-badge'];
        const user = global.Auth ? global.Auth.user() : null;
        const canControl = !!user && (user.role === 'admin' || user.role === 'teknisi');

        if (badge) {
            badge.textContent = user
                ? `Akses: ${global.Auth.roleLabel(user.role)}${canControl ? '' : ' · hanya lihat'}`
                : 'Akses: Publik · hanya lihat';
            badge.className = 'text-[10px] font-black uppercase tracking-widest px-3 py-1.5 rounded-lg border sk-soft';
        }

        ['toggle-lowlight', 'toggle-yolo', 'select-lowlight'].forEach(id => {
            const node = el[id];
            if (!node) return;
            node.disabled = !canControl;
            node.title = canControl ? '' : 'Kontrol AI hanya untuk Teknisi atau Administrator.';
        });
        /* Bobot YOLO bukan pilihan: engine memakai file .pt di Yolo/Model. */
        if (el['select-yolo']) {
            el['select-yolo'].disabled = true;
            el['select-yolo'].title = 'Satu bobot YOLO per engine (file .pt di Yolo/Model).';
        }
    }

    /* Permintaan operator dianggap selesai saat keadaan engine (dari RTDB)
       sudah sama dengan yang diminta — bukan saat tombol diklik. */
    function pendingMatches(ai) {
        const p = state.aiPending;
        if (!p) return true;
        if ('lowlight_model' in p && ai.lowlight_variant !== p.lowlight_model) return false;
        if ('lowlight_enabled' in p && ai.lowlight !== p.lowlight_enabled) return false;
        if ('yolo_enabled' in p && ai.yolo !== p.yolo_enabled) return false;
        return true;
    }

    function commitAi(patch, description) {
        if (!state.activeId) return;
        if (!canControl()) {
            App.toast('Kontrol AI hanya untuk Teknisi atau Administrator.', 'error');
            return;
        }

        const id = state.activeId;
        state.aiPending = Object.assign({}, state.aiPending, patch);
        paintAiPanel(Store.getAi(id));
        log(description + ' — dikirim ke engine.');

        Store.setAiRemote(id, patch)
            .then(result => {
                Store.setAi(id, patch);
                App.toast(description, 'success', 2600);
                if (result && result.running === false) {
                    log('Engine node belum berjalan; permintaan dipakai saat engine mulai.');
                }
            })
            .catch(err => {
                state.aiPending = null;
                paintAiPanel(Store.getAi(id));
                const message = (err && err.message) || 'gagal';
                log('Kontrol AI ditolak: ' + message);
                App.toast('Kontrol AI gagal: ' + message, 'error', 4200);
            });
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
            /* Buffer & sinkronisasi live. Buffer besar membuat pemutar
               tertinggal dari siaran lalu melompat (terasa tersendat); buffer
               terlalu kecil membuang segmen saat jaringan goyah. Segmen kita
               2 detik, jadi ~12 detik buffer = 6 segmen: cukup untuk jitter
               tanpa menumpuk latensi. `capLevelToPlayerSize` sengaja tidak
               dipakai: bila elemen video belum punya ukuran saat init (panel
               tersembunyi / layout belum jalan) hls.js tidak memilih level
               dan tidak pernah memuat segmen. Stream ini satu bitrate. */
            state.hls = new Hls({
                enableWorker: true,
                lowLatencyMode: false,
                backBufferLength: 12,
                /* Buffer 8 detik supaya cepat menyusul live edge. Sinkronisasi
                   memakai detik (bukan jumlah segmen): segmen HLS kita ~2-3 dtk,
                   jadi 2 target duration = 6 dtk jeda yang tidak perlu. */
                maxBufferLength: 8,
                maxMaxBufferLength: 16,
                liveSyncDuration: 2.5,
                liveMaxLatencyDuration: 12,
                /* 1,5: mempercepat sebentar setelah tautan goyah supaya jeda
                   tidak menumpuk; hanya aktif saat tertinggal dari live edge. */
                maxLiveSyncPlaybackRate: 1.5,
                manifestLoadingTimeOut: 8000,
                manifestLoadingMaxRetry: 4,
                manifestLoadingRetryDelay: 500,
                levelLoadingTimeOut: 8000,
                levelLoadingMaxRetry: 4,
                levelLoadingRetryDelay: 500,
                fragLoadingTimeOut: 15000,
                fragLoadingMaxRetry: 5,
                fragLoadingRetryDelay: 400,
                fragLoadingMaxRetryTimeout: 8000
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

            /* Satu segmen berhasil masuk buffer = jaringan sehat; reset hitungan
               supaya gangguan lama tidak menghabiskan jatah percobaan. */
            state.hls.on(Hls.Events.FRAG_BUFFERED, () => { state.retries = 0; });

            state.hls.on(Hls.Events.ERROR, (event, data) => {
                if (!data.fatal) return;   // non-fatal ditangani hls.js sendiri

                if (data.type === Hls.ErrorTypes.NETWORK_ERROR && state.retries < 4) {
                    state.retries += 1;
                    const wait = Math.min(1000 * state.retries, 4000);
                    log(`Jaringan HLS terputus (${state.retries}/4), muat ulang dalam ${wait / 1000} dtk...`);
                    setTimeout(() => { if (state.hls) state.hls.startLoad(); }, wait);
                } else if (data.type === Hls.ErrorTypes.MEDIA_ERROR && state.retries < 4) {
                    state.retries += 1;
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
        state.telemetry = data;
        if (el['stat-mobil']) el['stat-mobil'].textContent = data.jumlah_mobil ?? 0;
        if (el['stat-motor']) el['stat-motor'].textContent = data.jumlah_motor ?? 0;
        if (el['stat-truk']) el['stat-truk'].textContent = data.jumlah_truk ?? 0;
        if (el['stat-bus']) el['stat-bus'].textContent = data.jumlah_bus ?? 0;
        if (el['stat-total']) el['stat-total'].textContent = data.total_kendaraan ?? 0;
        /* Kartu FPS diisi paintFps() dari frame yang benar-benar didekode,
           bukan dari server_fps — definisinya sama, sumber ukurnya di sini. */

        /* Panel AI mengikuti keadaan engine, bukan pilihan terakhir di
           peramban: setelah toggle, label berubah ketika engine benar-benar
           sudah berganti (polling 2 detik). */
        const ai = Store.getAi(state.activeId);
        if (state.aiPending && pendingMatches(ai)) {
            state.aiPending = null;
            log('Engine sudah menerapkan perubahan modul AI.');
        }
        paintAiPanel(ai);

        /* URL HLS sama untuk AI on/off, jadi badge mode cukup diperbarui dari
           telemetri — tanpa memuat ulang pemutar. */
        const mode = (ai.yolo || ai.lowlight) ? 'ai' : 'hls';
        if (mode !== state.mode) {
            state.mode = mode;
            setModeBadge(mode);
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
                    { lowlight_enabled: next },
                    `LowLight ${next ? 'diaktifkan' : 'dimatikan'} (${ai.lowlight_model}) pada ${state.activeId}.`
                );
            });
        }

        if (el['toggle-yolo']) {
            el['toggle-yolo'].addEventListener('click', () => {
                const ai = Store.getAi(state.activeId);
                const next = !ai.yolo;
                commitAi(
                    { yolo_enabled: next },
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
            el['select-yolo'].addEventListener('change', () => {
                /* Satu bobot YOLO per engine: pilihan hanya informasi. */
                log('Bobot YOLO mengikuti file di Yolo/Model; ganti berkasnya untuk berganti model.');
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

    /* --- Pagar fitur ------------------------------------------------------ */
    /* Administrator bisa mencabut "Kontrol Modul AI". Panel kontrolnya lalu
       disembunyikan; pemantauan gambar tetap berjalan — yang hilang hanya
       kemampuan mengubah modul, bukan tayangannya. */
    function applyFeatureGates() {
        const panel = document.getElementById('ai-panel');
        if (!panel) return;

        const auth = global.Auth;
        const allowed = !auth || !auth.isReady() || auth.can('ai');
        panel.classList.toggle('hidden-important', !allowed);
    }

    /* --- Inisialisasi ---------------------------------------------------- */
    function init() {
        cacheDom();
        if (!el['video-element']) return;

        applyFeatureGates();
        document.addEventListener('auth:change', applyFeatureGates);

        syncOperatorBadge();
        bindEvents();

        /* Katalog model (nama + label) berasal dari registry engine. */
        Store.aiCatalog()
            .then(catalog => { state.aiCatalog = catalog; paintAiCatalog(catalog); })
            .catch(err => log('Katalog model AI gagal dimuat: ' + ((err && err.message) || err)));
        setInterval(() => { paintLatency(); paintFps(); }, 1000);

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
        /* Tunggu daftar node dari backend sebelum menentukan node default.
           Fitur bisa dicabut Administrator; tamu tetap boleh menonton. */
        init: function () {
            const start = function () {
                Store.ready().then(() => ensureHls(init));
            };

            if (!global.Auth) { start(); return; }
            global.Auth.ready().then(function (user) {
                if (user && !global.Auth.can('cctv')) { global.App.blocked('cctv'); return; }
                start();
            }).catch(start);
        },
        select: selectCamera,
        refresh: applyStream
    };
})(window);
