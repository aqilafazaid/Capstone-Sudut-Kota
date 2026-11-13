/* ==========================================================================
   CONFIG.JS — alamat backend untuk API + HLS
   --------------------------------------------------------------------------
   Alur: CCTV → RTSP → backend lokal (ffmpeg) → HLS (m3u8) → Vercel/nginx → client.

   Saat halaman disajikan nginx (http://localhost:8080), backendBase = ''
   sehingga /api dan /hls same-origin. Saat memakai `python -m http.server 8787`,
   default diarahkan ke http://127.0.0.1:5000. Di Vercel, isi
   localStorage['sudutkota.backend'] dengan URL publik nginx (HTTPS).
   ========================================================================== */

(function (global) {
    'use strict';

    var LOCAL = ['127.0.0.1', 'localhost', ''].indexOf(location.hostname) >= 0;
    var saved = '';
    try {
        saved = localStorage.getItem('sudutkota.backend') || '';
    } catch (err) {
        saved = '';
    }

    /* Server statis 8787 butuh alamat Flask eksplisit; nginx (:8080/:443)
       memakai origin yang sama supaya tidak ada CORS dan tidak ada mixed content. */
    /* Prioritas alamat backend:
       1) dev 8787 (python -m http.server)  -> Flask langsung, beda origin
       2) localhost/nginx :8080             -> same-origin (backendBase '')
       3) halaman lain (Vercel)             -> js/public-config.js hasil generator
       localStorage hanya dipakai sebagai override darurat di lingkungan non-lokal. */
    var devServer = LOCAL && location.port === '8787';
    var publicBase = (global.SK_PUBLIC && global.SK_PUBLIC.backendBase) || '';
    var backendBase;

    if (devServer) {
        backendBase = 'http://127.0.0.1:5000';
    } else if (LOCAL) {
        backendBase = '';
    } else {
        backendBase = publicBase || saved || '';
    }
    backendBase = backendBase.replace(/\/+$/, '');

    function join(path) {
        var clean = String(path || '').replace(/^\/+/, '');
        return backendBase ? backendBase + '/' + clean : '/' + clean;
    }

    /* Di mesin operator, nama *.ts.net sering diresolve ke IP tailnet (100.x).
       Chrome memblokir permintaan dari origin HTTPS publik ke alamat privat
       (Private Network Access), jadi halaman Vercel di mesin itu tidak bisa
       memanggil backend walau backend sehat. Flask tetap listen di loopback,
       sehingga 127.0.0.1:5000 jadi jalur cadangan untuk mesin yang sama. */
    var LOOPBACK_BASE = 'http://127.0.0.1:5000';
    var isPublicPage = !LOCAL;
    var resolvedBase = '';

    function apiPath(path) {
        return String(path || '').replace(/^\/+/, '');
    }

    /** Daftar { base, url } yang dicoba berurutan untuk satu path API. */
    function apiTargets(path) {
        var clean = 'api/' + apiPath(path);
        var targets = [{ base: resolvedBase || backendBase, url: join(clean) }];
        if (!resolvedBase && isPublicPage && backendBase) {
            targets.push({
                base: LOOPBACK_BASE,
                url: LOOPBACK_BASE + '/' + clean
            });
        }
        return targets;
    }

    global.SK_CONFIG = {
        backendBase: backendBase,
        loopbackBase: isPublicPage ? LOOPBACK_BASE : '',

        /** Basis folder HLS: <backend>/hls */
        hlsBase: join('hls').replace(/\/$/, ''),

        /** Endpoint REST backend. */
        api: function (path) {
            return join('api/' + apiPath(path));
        },

        apiTargets: apiTargets,

        /**
         * fetch ke backend dengan fallback loopback.
         * Kandidat pertama backendBase; bila gagal di level jaringan (bukan
         * HTTP 4xx/5xx), coba 127.0.0.1:5000 sekali dan ingat base yang berhasil.
         */
        apiFetch: function (path, options) {
            var targets = apiTargets(path);
            function attempt(index) {
                return fetch(targets[index].url, options).then(function (response) {
                    if (index > 0) resolvedBase = targets[index].base;
                    return response;
                }).catch(function (cause) {
                    if (index + 1 < targets.length) return attempt(index + 1);
                    var error = new Error('Tidak dapat menghubungi ' + targets[index].url);
                    error.url = targets[index].url;
                    error.candidates = targets.map(function (t) { return t.url; });
                    error.cause = cause;
                    throw error;
                });
            }
            return attempt(0);
        },

        /** Tambahkan backendBase ke path relatif; URL absolut dibiarkan. */
        withBackend: function (path) {
            if (!path) return '';
            if (/^https?:\/\//i.test(path)) return path;
            return join(path);
        },

        /** URL m3u8 sebuah node: hls_url dari API, atau turunan dari id. */
        hlsUrl: function (cam) {
            if (!cam) return '';
            if (cam.hls_url) return this.withBackend(cam.hls_url);
            return this.withBackend('/hls/' + encodeURIComponent(cam.id) + '/index.m3u8');
        },

        /** true bila halaman HTTPS memuat stream HTTP (akan diblokir peramban). */
        isMixedContent: function (url) {
            return location.protocol === 'https:' && /^http:\/\//i.test(url || '');
        }
    };
})(window);
