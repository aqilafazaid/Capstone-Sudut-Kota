/* ==========================================================================
   STORE.JS — Lapisan data frontend
   --------------------------------------------------------------------------
   SEMUA akses data halaman lewat modul ini. Sumber kebenaran node adalah
   backend lokal (SQLite lewat /api/nodes), bukan localStorage dan bukan
   Firebase. localStorage hanya dipakai sebagai cache baca dan menyimpan
   token operator.

   Bentuk node dari GET /api/nodes:
     { id, channel, nama, zona, jalan, kota, aktif, status,
       hls_url, stream }
   Field `rtsp` SENGAJA tidak ada di daftar; hanya GET /api/nodes/<id>
   (header X-SK-Token) yang mengembalikannya untuk form edit.

   AI status per node masih memakai localStorage sampai engine AI
   tersambung ke backend.
   ========================================================================== */

(function (global) {
    'use strict';

    /* v3: cache node lama (sebelum pembersihan database) tidak boleh dipakai
       lagi — kalau backend sempat mati, direktori akan tampil dari cache usang. */
    const NODES_CACHE_KEY = 'sudutkota.nodes.cache.v3';
    const AI_KEY = 'sudutkota.ai.v1';

    const DEFAULT_AI = {
        lowlight: false,
        lowlight_model: 'MirNet',
        yolo: true,
        yolo_model: 'YOLOv8n'
    };

    /* ---------------------------------------------------------------------
       Cache baca + token operator
       --------------------------------------------------------------------- */
    function readJson(key, fallback) {
        try {
            const raw = localStorage.getItem(key);
            return raw ? JSON.parse(raw) : fallback;
        } catch (err) {
            console.warn('[Store] Gagal membaca', key, err);
            return fallback;
        }
    }

    function writeJson(key, value) {
        try {
            localStorage.setItem(key, JSON.stringify(value));
        } catch (err) {
            console.warn('[Store] Gagal menyimpan', key, err);
        }
    }

    async function readResponse(response) {
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            const error = new Error(data.error || ('HTTP ' + response.status));
            error.status = response.status;
            throw error;
        }
        return data;
    }

    /** GET publik: daftar node tidak memuat RTSP. */
    async function apiRead(path) {
        const response = await SK_CONFIG.apiFetch(path, {
            headers: { 'Accept': 'application/json' }
        });
        return readResponse(response);
    }

    /** Request tulis/detail: bawa Firebase ID token (Authorization: Bearer). */
    async function apiRequest(path, options) {
        const opts = Object.assign({ method: 'GET' }, options || {});
        const headers = Object.assign({ 'Accept': 'application/json' }, opts.headers || {});
        if (opts.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json';

        const token = global.Auth ? await global.Auth.idToken() : '';
        if (token) headers['Authorization'] = 'Bearer ' + token;
        opts.headers = headers;

        const response = await SK_CONFIG.apiFetch(path, opts);
        if (response.status === 401 && global.Auth) {
            const fresh = await global.Auth.idToken(true);
            if (fresh) {
                opts.headers['Authorization'] = 'Bearer ' + fresh;
                return readResponse(await SK_CONFIG.apiFetch(path, opts));
            }
        }
        return readResponse(response);
    }

    let nodes = readJson(NODES_CACHE_KEY, []);
    if (!Array.isArray(nodes)) nodes = [];

    let serverConfig = {
        allow_test_sources: false,
        stream_autostart: true,
        write_token_required: true
    };
    let backendOnline = false;
    let readyPromise = null;

    const statsCache = new Map();
    /* Agregat statistik dari Firebase (GET /api/stats/telemetry) — satu-satunya
       sumber angka. Tidak ada simulasi di peramban. */
    let statsTelemetry = null;
    let statsLoadedAt = null;
    let statsLoading = null;

    function emptyBucket() {
        return { mobil: 0, motor: 0, truk: 0, bus: 0, total: 0 };
    }

    function firebaseHour(nodeId, dayKey, hour) {
        const today = statsTelemetry && statsTelemetry.hourly ? statsTelemetry.hourly[nodeId] : null;
        if (!today || dayKey !== dateKey(new Date())) return emptyBucket();
        return Object.assign(emptyBucket(), today[hour] || {});
    }

    function firebaseDay(nodeId, dayKey) {
        const day = statsTelemetry && statsTelemetry.daily ? statsTelemetry.daily[dayKey] : null;
        if (!day || !day[nodeId]) return emptyBucket();
        return Object.assign(emptyBucket(), day[nodeId]);
    }

    let aiState = readJson(AI_KEY, {});
    if (typeof aiState !== 'object' || aiState === null) aiState = {};

    /* ---------------------------------------------------------------------
       Event bus sederhana
       --------------------------------------------------------------------- */
    function emit(type, detail) {
        document.dispatchEvent(new CustomEvent(type, { detail: detail }));
    }

    /* ---------------------------------------------------------------------
       Telemetri live (RTDB)
       Angka kartu CCTV diambil dari snapshot engine AI di Firebase lewat
       backend (`GET /api/stats/live`). Tidak ada simulasi di peramban: node
       yang belum mengirim snapshot tampil 0 dengan status OFFLINE.
       --------------------------------------------------------------------- */
    const OFFLINE_SNAPSHOT = {
        status: 'OFFLINE', jumlah_mobil: 0, jumlah_motor: 0, jumlah_truk: 0,
        jumlah_bus: 0, total_kendaraan: 0, server_fps: 0, stale: true
    };

    let liveSnapshots = {};
    let livePromise = null;

    function fetchLive() {
        if (livePromise) return livePromise;
        livePromise = apiRead('stats/live')
            .then(data => {
                liveSnapshots = (data && data.nodes) ? data.nodes : {};
                return liveSnapshots;
            })
            .catch(err => {
                liveSnapshots = {};
                console.warn('[Store] Telemetri live tidak tersedia:', err.message || err);
                return liveSnapshots;
            })
            .finally(() => { livePromise = null; });
        return livePromise;
    }

    /* ---------------------------------------------------------------------
       Statistik
       Seluruh angka berasal dari agregat Firebase (`GET /api/stats/telemetry`).
       Tidak ada model simulasi di sini: bila RTDB belum punya sampel, halaman
       menampilkan nol dengan penanda "belum ada data".
       --------------------------------------------------------------------- */
    const DAY_LABEL = ['Min', 'Sen', 'Sel', 'Rab', 'Kam', 'Jum', 'Sab'];
    const MONTH_LABEL = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des'];

    /**
     * Definisi periode. `unit` menentukan lebar bucket, `days` panjang rentang
     * (null = sejak sampel Firebase paling awal). Rata-rata & puncak per bucket.
     */
    const PERIODS = {
        '1d': { label: '1 Hari', unit: 'hour', days: 1, bucketName: 'Jam', avgLabel: 'Rata-rata / Jam', peakLabel: 'Jam Tersibuk' },
        '1w': { label: '1 Minggu', unit: 'day', days: 7, bucketName: 'Tanggal', avgLabel: 'Rata-rata / Hari', peakLabel: 'Hari Tersibuk' },
        '1m': { label: '1 Bulan', unit: 'day', days: 30, bucketName: 'Tanggal', avgLabel: 'Rata-rata / Hari', peakLabel: 'Hari Tersibuk' },
        '3m': { label: '3 Bulan', unit: 'week', days: 91, bucketName: 'Minggu', avgLabel: 'Rata-rata / Minggu', peakLabel: 'Minggu Tersibuk' },
        '1y': { label: '1 Tahun', unit: 'month', days: 365, bucketName: 'Bulan', avgLabel: 'Rata-rata / Bulan', peakLabel: 'Bulan Tersibuk' },
        '5y': { label: '5 Tahun', unit: 'quarter', days: 1826, bucketName: 'Kuartal', avgLabel: 'Rata-rata / Kuartal', peakLabel: 'Kuartal Tersibuk' },
        all: { label: 'Seluruhnya', unit: 'year', days: null, bucketName: 'Tahun', avgLabel: 'Rata-rata / Tahun', peakLabel: 'Tahun Tersibuk' }
    };

    function dateKey(date) {
        return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
    }

    function startOfDay(date) {
        return new Date(date.getFullYear(), date.getMonth(), date.getDate());
    }

    function addDays(date, days) {
        return new Date(date.getFullYear(), date.getMonth(), date.getDate() + days);
    }

    function startOfWeek(date) {
        const day = (date.getDay() + 6) % 7; // Senin = 0
        return addDays(startOfDay(date), -day);
    }

    function shortDate(date) {
        return `${date.getDate()} ${MONTH_LABEL[date.getMonth()]} ${date.getFullYear()}`;
    }

    /** Tanggal sampel Firebase paling awal; fallback bila arsip kosong. */
    function earliestTelemetryDay(fallback) {
        const daily = statsTelemetry && statsTelemetry.daily ? Object.keys(statsTelemetry.daily) : [];
        let earliest = null;
        daily.forEach(text => {
            const date = new Date(`${text}T00:00:00`);
            if (!isNaN(date) && (!earliest || date < earliest)) earliest = date;
        });
        return earliest || fallback;
    }

    function bucketOf(date, unit, withWeekday) {
        const year = date.getFullYear();
        const month = date.getMonth();

        switch (unit) {
            case 'day':
                return {
                    key: dateKey(date),
                    label: withWeekday
                        ? `${DAY_LABEL[date.getDay()]} ${date.getDate()}/${month + 1}`
                        : `${date.getDate()}/${month + 1}`
                };
            case 'week': {
                const monday = startOfWeek(date);
                return {
                    key: dateKey(monday),
                    label: `${monday.getDate()}/${monday.getMonth() + 1}`
                };
            }
            case 'month':
                return { key: `${year}-${String(month + 1).padStart(2, '0')}`, label: `${MONTH_LABEL[month]} ${String(year).slice(2)}` };
            case 'quarter':
                return { key: `${year}-Q${Math.floor(month / 3) + 1}`, label: `Q${Math.floor(month / 3) + 1} ${year}` };
            default:
                return { key: String(year), label: String(year) };
        }
    }

    /* ---------------------------------------------------------------------
       API publik
       --------------------------------------------------------------------- */
    const Store = {
        /** Muat konfigurasi + daftar node dari backend sekali per halaman. */
        ready() {
            if (readyPromise) return readyPromise;
            readyPromise = (async () => {
                try {
                    const [list, config] = await Promise.all([
                        apiRead('nodes'),
                        apiRead('config').catch(() => null)
                    ]);
                    nodes = Array.isArray(list) ? list : [];
                    if (config) serverConfig = Object.assign(serverConfig, config);
                    writeJson(NODES_CACHE_KEY, nodes);
                    backendOnline = true;
                } catch (err) {
                    backendOnline = false;
                    readyPromise = null;
                    console.warn('[Store] Backend tidak tersedia:', err);
                    const cached = readJson(NODES_CACHE_KEY, []);
                    nodes = Array.isArray(cached) ? cached : [];
                    document.dispatchEvent(new CustomEvent('store:offline', { detail: { error: String(err) } }));
                }
                return nodes;
            })();
            return readyPromise;
        },

        isOnline() { return backendOnline; },

        config() { return { ...serverConfig }; },

        /** Semua node, urut sesuai backend. */
        list() {
            return nodes.map(n => ({ ...n }));
        },

        get(id) {
            const found = nodes.find(n => n.id === id);
            return found ? { ...found } : null;
        },

        /** Detail penuh (termasuk RTSP) untuk form edit; butuh token. */
        fetchDetail(id) {
            return apiRequest('nodes/' + encodeURIComponent(id));
        },

        /** URL m3u8 yang diputar peramban: hls_url dari API atau turunan id. */
        hlsUrl(cam) {
            if (!cam) return '';
            if (cam.hls_url) return SK_CONFIG.withBackend(cam.hls_url);
            return SK_CONFIG.withBackend('/hls/' + encodeURIComponent(cam.id) + '/index.m3u8');
        },

        firstPlayable() {
            return nodes.find(n => n.aktif) || nodes[0] || null;
        },

        byZone() {
            const groups = new Map();
            nodes.forEach(cam => {
                const key = cam.zona || 'Tanpa Zona';
                if (!groups.has(key)) groups.set(key, []);
                groups.get(key).push({ ...cam });
            });
            return [...groups.entries()].map(([zona, cameras]) => ({ zona, cameras }));
        },

        zones() {
            return [...new Set(nodes.map(n => n.zona).filter(Boolean))].sort();
        },

        /** Buat atau perbarui node. RTSP hanya dikirim, tidak disimpan di cache. */
        async upsert(camera) {
            const isEdit = !!camera.id;
            const payload = { ...camera };
            ['url_m3u8', 'hls_url', 'stream', 'status', 'updated_at'].forEach(key => delete payload[key]);
            if (isEdit) delete payload.id;

            const data = isEdit
                ? await apiRequest('nodes/' + encodeURIComponent(camera.id), {
                    method: 'PUT', body: JSON.stringify(payload)
                })
                : await apiRequest('nodes', { method: 'POST', body: JSON.stringify(payload) });

            const index = nodes.findIndex(n => n.id === data.id);
            if (index >= 0) nodes[index] = data;
            else nodes.push(data);

            statsCache.clear();
            writeJson(NODES_CACHE_KEY, nodes);
            emit('store:change', { type: isEdit ? 'update' : 'create', id: data.id });
            return data.id;
        },

        async remove(id) {
            await apiRequest('nodes/' + encodeURIComponent(id), { method: 'DELETE' });

            const before = nodes.length;
            nodes = nodes.filter(n => n.id !== id);
            if (nodes.length === before) return false;
            delete aiState[id];
            statsCache.clear();
            writeJson(NODES_CACHE_KEY, nodes);
            writeJson(AI_KEY, aiState);
            emit('store:change', { type: 'delete', id });
            return true;
        },


        /* --- Status AI per node (pengganti /cctv_nodes/{id}/ai_status) --- */
        aiDefaults() {
            return { ...DEFAULT_AI };
        },

        getAi(id) {
            return { ...DEFAULT_AI, ...(aiState[id] || {}) };
        },

        setAi(id, patch) {
            aiState[id] = { ...this.getAi(id), ...patch };
            writeJson(AI_KEY, aiState);
            emit('ai:change', { id, ai: { ...aiState[id] } });
            return { ...aiState[id] };
        },

        /* --- Telemetri (snapshot RTDB) --- */
        getTelemetry(id) {
            const cam = this.get(id);
            if (!cam) return null;
            return { ...OFFLINE_SNAPSHOT, ...(liveSnapshots[id] || {}) };
        },

        /** Polling 2 detik ke /api/stats/live; mengembalikan fungsi berhenti. */
        subscribeTelemetry(id, callback) {
            let stopped = false;

            const tick = async () => {
                if (!stopped) await fetchLive();
                if (stopped) return;
                callback({ ...OFFLINE_SNAPSHOT, ...(liveSnapshots[id] || {}) });
            };

            tick();
            const timer = setInterval(tick, 2000);
            return () => { stopped = true; clearInterval(timer); };
        },

        onChange(callback) {
            const handler = (event) => callback(event.detail);
            document.addEventListener('store:change', handler);
            return () => document.removeEventListener('store:change', handler);
        },

        onAiChange(callback) {
            const handler = (event) => callback(event.detail);
            document.addEventListener('ai:change', handler);
            return () => document.removeEventListener('ai:change', handler);
        },

        /** Ringkasan statistik. period: '1d' | '1w' | '1m' | '3m' | '1y' | '5y' | 'all'. */
        stats(period) {
            const key = PERIODS[period] ? period : '1d';
            if (statsCache.has(key)) return statsCache.get(key);

            const cfg = PERIODS[key];
            const cameras = nodes.map(n => ({ ...n }));
            const activeCameras = cameras.filter(c => c.aktif);
            /* Firebase satu-satunya sumber angka. Tanpa sampel -> semua nol. */
            const countedCameras = activeCameras;
            const today = startOfDay(new Date());
            const buckets = [];
            const perNodeMap = new Map(cameras.map(cam => [cam.id, {
                id: cam.id, nama: cam.nama, zona: cam.zona || '-', aktif: !!cam.aktif,
                mobil: 0, motor: 0, truk: 0, bus: 0, total: 0
            }]));

            let rangeStart = today;

            if (cfg.unit === 'hour') {
                const todayKey = dateKey(today);

                for (let hour = 0; hour < 24; hour += 1) {
                    const bucket = {
                        key: String(hour).padStart(2, '0'),
                        label: `${String(hour).padStart(2, '0')}:00`,
                        mobil: 0, motor: 0, truk: 0, bus: 0, total: 0
                    };

                    countedCameras.forEach(cam => {
                        const value = firebaseHour(cam.id, todayKey, hour);
                        bucket.mobil += value.mobil;
                        bucket.motor += value.motor;
                        bucket.truk += value.truk;
                        bucket.bus += value.bus;
                        bucket.total += value.total;

                        const acc = perNodeMap.get(cam.id);
                        acc.mobil += value.mobil;
                        acc.motor += value.motor;
                        acc.truk += value.truk;
                        acc.bus += value.bus;
                        acc.total += value.total;
                    });

                    buckets.push(bucket);
                }
            } else {
                rangeStart = cfg.days ? addDays(today, -(cfg.days - 1)) : earliestTelemetryDay(today);
                const withWeekday = cfg.days === 7;
                const byKey = new Map();

                for (let day = rangeStart; day <= today; day = addDays(day, 1)) {
                    const spot = bucketOf(day, cfg.unit, withWeekday);
                    let bucket = byKey.get(spot.key);
                    if (!bucket) {
                        bucket = { key: spot.key, label: spot.label, mobil: 0, motor: 0, truk: 0, bus: 0, total: 0 };
                        byKey.set(spot.key, bucket);
                    }

                    const dayKey = dateKey(day);
                    for (let i = 0; i < countedCameras.length; i += 1) {
                        const cam = countedCameras[i];
                        const totals = firebaseDay(cam.id, dayKey);

                        bucket.mobil += totals.mobil;
                        bucket.motor += totals.motor;
                        bucket.truk += totals.truk;
                        bucket.bus += totals.bus;
                        bucket.total += totals.total;

                        const acc = perNodeMap.get(cam.id);
                        acc.mobil += totals.mobil;
                        acc.motor += totals.motor;
                        acc.truk += totals.truk;
                        acc.bus += totals.bus;
                        acc.total += totals.total;
                    }
                }

                buckets.push(...byKey.values());
            }

            const perNode = [...perNodeMap.values()].sort((a, b) => b.total - a.total);
            const total = buckets.reduce((sum, b) => sum + b.total, 0);
            const peak = buckets.reduce((best, b) => (b.total > best.total ? b : best), buckets[0] || { label: '-', total: 0 });

            const result = {
                period: key,
                periodLabel: cfg.label,
                bucketName: cfg.bucketName,
                avgLabel: cfg.avgLabel,
                peakLabel: cfg.peakLabel,
                generatedAt: new Date(),
                dataSource: 'firebase',
                hasData: !!statsTelemetry,
                rangeLabel: key === '1d'
                    ? `Hari ini, ${shortDate(today)}`
                    : key === 'all'
                        ? `Seluruh data (${shortDate(rangeStart)} - ${shortDate(today)})`
                        : `${cfg.label} terakhir (${shortDate(rangeStart)} - ${shortDate(today)})`,
                buckets,
                perNode,
                summary: {
                    total,
                    mobil: buckets.reduce((sum, b) => sum + b.mobil, 0),
                    motor: buckets.reduce((sum, b) => sum + b.motor, 0),
                    truk: buckets.reduce((sum, b) => sum + b.truk, 0),
                    bus: buckets.reduce((sum, b) => sum + b.bus, 0),
                    avgPerBucket: buckets.length ? Math.round(total / buckets.length) : 0,
                    peakLabel: peak.label,
                    peakTotal: peak.total,
                    nodes: cameras.length,
                    online: activeCameras.length
                }
            };

            statsCache.set(key, result);
            return result;
        },

        /**
         * Muat agregat statistik dari Firebase lewat backend.
         * Tidak ada fallback simulasi: bila RTDB belum punya sampel, halaman
         * menampilkan nol dan penanda "belum ada data".
         */
        async loadStats(force) {
            if (statsLoading && !force) return statsLoading;

            statsLoading = (async () => {
                try {
                    const data = await apiRead('stats/telemetry');
                    const hasDaily = data && data.daily && Object.keys(data.daily).length;
                    statsTelemetry = (data && data.has_data && hasDaily) ? data : null;
                    statsLoadedAt = new Date();
                } catch (err) {
                    statsTelemetry = null;
                    statsLoadedAt = new Date();
                    console.warn('[Store] Statistik Firebase tidak tersedia:', err.message || err);
                }
                statsCache.clear();
                emit('stats:change', { source: 'firebase', hasData: !!statsTelemetry });
                return Store.statsInfo();
            })();

            try {
                return await statsLoading;
            } finally {
                statsLoading = null;
            }
        },

        /** Status sumber angka untuk label halaman dan ekspor. */
        statsInfo() {
            return {
                source: 'firebase',
                hasData: !!statsTelemetry,
                loadedAt: statsLoadedAt,
                generatedAt: statsTelemetry ? statsTelemetry.generated_at : null,
                days: statsTelemetry ? statsTelemetry.days : null
            };
        },

        /** Kembalikan node ke seed backend (akun Firebase tidak disentuh). */
        async resetDemo() {
            const data = await apiRequest('nodes/reset', { method: 'POST' });
            nodes = Array.isArray(data.nodes) ? data.nodes : [];
            aiState = {};
            statsCache.clear();
            statsTelemetry = null;
            writeJson(NODES_CACHE_KEY, nodes);
            writeJson(AI_KEY, aiState);
            emit('store:change', { type: 'reset' });
            return nodes;
        }
    };

    global.Store = Store;
})(window);
