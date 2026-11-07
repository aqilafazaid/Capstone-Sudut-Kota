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

    const NODES_CACHE_KEY = 'sudutkota.nodes.cache.v2';
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
        const response = await fetch(SK_CONFIG.api(path), {
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

        const response = await fetch(SK_CONFIG.api(path), opts);
        if (response.status === 401 && global.Auth) {
            const fresh = await global.Auth.idToken(true);
            if (fresh) {
                opts.headers['Authorization'] = 'Bearer ' + fresh;
                return readResponse(await fetch(SK_CONFIG.api(path), opts));
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

    let aiState = readJson(AI_KEY, {});
    if (typeof aiState !== 'object' || aiState === null) aiState = {};

    /* ---------------------------------------------------------------------
       Event bus sederhana
       --------------------------------------------------------------------- */
    function emit(type, detail) {
        document.dispatchEvent(new CustomEvent(type, { detail: detail }));
    }

    /* ---------------------------------------------------------------------
       Telemetri demo
       Nilai bergerak acak di sekitar angka yang masuk akal untuk satu simpang.
       --------------------------------------------------------------------- */
    const telemetry = {};

    function seedTelemetry(cam) {
        return {
            timestamp: Date.now() / 1000,
            jumlah_mobil: 8 + Math.floor(Math.random() * 12),
            jumlah_motor: 20 + Math.floor(Math.random() * 30),
            jumlah_truk: 1 + Math.floor(Math.random() * 4),
            jumlah_bus: Math.floor(Math.random() * 3),
            total_kendaraan: 0,
            server_fps: 22 + Math.random() * 6,
            night_vision_status: !!aiState[cam.id]?.lowlight,
            status: cam.aktif ? 'ONLINE' : 'OFFLINE',
            engine: cam.aktif ? 'demo' : 'offline'
        };
    }

    function stepTelemetry(cam) {
        const prev = telemetry[cam.id] || seedTelemetry(cam);
        if (!cam.aktif) {
            return { ...prev, timestamp: Date.now() / 1000, status: 'OFFLINE', engine: 'offline' };
        }
        const drift = (value, min, max, delta) => {
            const next = value + (Math.random() * 2 - 1) * delta;
            return Math.max(min, Math.min(max, Math.round(next)));
        };
        const mobil = drift(prev.jumlah_mobil, 0, 45, 2);
        const motor = drift(prev.jumlah_motor, 0, 90, 3);
        const truk = drift(prev.jumlah_truk, 0, 9, 1);
        const bus = drift(prev.jumlah_bus, 0, 5, 1);
        return {
            timestamp: Date.now() / 1000,
            jumlah_mobil: mobil,
            jumlah_motor: motor,
            jumlah_truk: truk,
            jumlah_bus: bus,
            total_kendaraan: mobil + motor + truk + bus,
            server_fps: Math.round((18 + Math.random() * 10) * 10) / 10,
            night_vision_status: !!aiState[cam.id]?.lowlight,
            status: 'ONLINE',
            engine: 'demo'
        };
    }

    /* ---------------------------------------------------------------------
       Statistik
       Data dibangkitkan secara deterministik dari (id node + tanggal + jam),
       sehingga angka tetap sama ketika halaman dimuat ulang. Ini data
       simulasi sampai telemetri Firebase tersambung.
       --------------------------------------------------------------------- */
    const HOUR_WEIGHT = [3, 2, 2, 2, 3, 5, 9, 16, 22, 18, 13, 12, 14, 13, 13, 16, 22, 24, 19, 14, 10, 8, 6, 4];
    const DAY_LABEL = ['Min', 'Sen', 'Sel', 'Rab', 'Kam', 'Jum', 'Sab'];
    const MONTH_LABEL = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des'];

    /** Awal arsip simulasi. Dipakai oleh periode "Seluruhnya". */
    const DATA_START = new Date(2019, 0, 1);

    /**
     * Definisi periode. `unit` menentukan lebar bucket, `days` panjang rentang
     * (null = sejak DATA_START). Rata-rata & puncak selalu per bucket.
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

    function hash32(text) {
        let h = 2166136261;
        for (let i = 0; i < text.length; i += 1) {
            h ^= text.charCodeAt(i);
            h = Math.imul(h, 16777619);
        }
        return h >>> 0;
    }

    function mulberry32(seed) {
        let a = seed;
        return function () {
            a |= 0; a = (a + 0x6D2B79F5) | 0;
            let t = Math.imul(a ^ (a >>> 15), 1 | a);
            t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
            return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
        };
    }

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

    /**
     * Dua puluh empat nilai dasar satu node pada satu hari.
     * Deterministik per (node, tanggal) sehingga angka hari ini sama dengan
     * hari itu di dalam periode mana pun.
     */
    function daySeries(cam, dayKey) {
        const series = new Array(24).fill(0);
        if (!cam.aktif) return series;

        const rng = mulberry32(hash32(`${cam.id}|${dayKey}`));
        for (let hour = 0; hour < 24; hour += 1) {
            series[hour] = HOUR_WEIGHT[hour] * (0.7 + rng() * 0.7);
        }
        return series;
    }

    /** Sebaran 0..1 deterministik dari sebuah angka (tanpa RNG tambahan). */
    function hashUnit(x) {
        const s = Math.sin(x * 12.9898) * 43758.5453;
        return s - Math.floor(s);
    }

    function hourCompose(base) {
        const mobil = Math.round(base * 0.35);
        const motor = Math.round(base * 0.55);
        /* Faktor 0,4..1,6 pada porsi 6% dan 4% supaya truk/bus tidak selalu
           jatuh ke angka yang sama di jam yang berbeda. */
        const noise = hashUnit(base);
        const truk = Math.round(base * 0.06 * (0.4 + noise * 1.2));
        const bus = Math.round(base * 0.04 * (0.4 + (1 - noise) * 1.2));
        return { mobil, motor, truk, bus, total: mobil + motor + truk + bus };
    }

    function composeSeries(series) {
        const acc = { mobil: 0, motor: 0, truk: 0, bus: 0, total: 0 };
        for (let hour = 0; hour < series.length; hour += 1) {
            const value = hourCompose(series[hour]);
            acc.mobil += value.mobil;
            acc.motor += value.motor;
            acc.truk += value.truk;
            acc.bus += value.bus;
            acc.total += value.total;
        }
        return acc;
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
            delete telemetry[id];
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

        /* --- Telemetri --- */
        getTelemetry(id) {
            const cam = this.get(id);
            if (!cam) return null;
            telemetry[id] = stepTelemetry(cam);
            return { ...telemetry[id] };
        },

        /** Polling 2 detik; mengembalikan fungsi untuk berhenti. */
        subscribeTelemetry(id, callback) {
            const tick = () => {
                const cam = this.get(id);
                if (!cam) return;
                telemetry[id] = stepTelemetry(cam);
                callback({ ...telemetry[id] });
            };
            tick();
            const timer = setInterval(tick, 2000);
            return () => clearInterval(timer);
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
            const today = startOfDay(new Date());
            const buckets = [];
            const perNodeMap = new Map(cameras.map(cam => [cam.id, {
                id: cam.id, nama: cam.nama, zona: cam.zona || '-', aktif: !!cam.aktif,
                mobil: 0, motor: 0, truk: 0, bus: 0, total: 0
            }]));

            let rangeStart = today;

            if (cfg.unit === 'hour') {
                const seriesByNode = activeCameras.map(cam => ({ cam, series: daySeries(cam, dateKey(today)) }));

                for (let hour = 0; hour < 24; hour += 1) {
                    const bucket = {
                        key: String(hour).padStart(2, '0'),
                        label: `${String(hour).padStart(2, '0')}:00`,
                        mobil: 0, motor: 0, truk: 0, bus: 0, total: 0
                    };

                    seriesByNode.forEach(({ cam, series }) => {
                        const value = hourCompose(series[hour]);
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
                rangeStart = cfg.days ? addDays(today, -(cfg.days - 1)) : new Date(DATA_START);
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
                    for (let i = 0; i < activeCameras.length; i += 1) {
                        const cam = activeCameras[i];
                        const totals = composeSeries(daySeries(cam, dayKey));

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

        /** Kembalikan data demo di backend. */
        async resetDemo() {
            const data = await apiRequest('nodes/reset', { method: 'POST' });
            nodes = Array.isArray(data.nodes) ? data.nodes : [];
            aiState = {};
            statsCache.clear();
            writeJson(NODES_CACHE_KEY, nodes);
            writeJson(AI_KEY, aiState);
            emit('store:change', { type: 'reset' });
            return nodes;
        }
    };

    global.Store = Store;
})(window);
