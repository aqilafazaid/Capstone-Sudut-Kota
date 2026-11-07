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

    global.SK_CONFIG = {
        backendBase: backendBase,

        /** Basis folder HLS: <backend>/hls */
        hlsBase: join('hls').replace(/\/$/, ''),

        /** Endpoint REST backend. */
        api: function (path) {
            return join('api/' + String(path || '').replace(/^\/+/, ''));
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
