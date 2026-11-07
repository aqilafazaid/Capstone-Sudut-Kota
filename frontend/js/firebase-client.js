/* ==========================================================================
   FIREBASE-CLIENT.JS — inisialisasi Firebase App + Auth (SDK compat)
   --------------------------------------------------------------------------
   Membaca window.FIREBASE_CONFIG (dihasilkan backend/scripts/sync_public_config.py).
   Bila konfigurasi kosong, SK_FIREBASE = null dan aplikasi tetap berjalan pada
   mode publik: semua orang boleh menonton, tidak ada yang boleh menulis.
   ========================================================================== */

(function (global) {
    'use strict';

    global.SK_FIREBASE = null;

    if (!global.FIREBASE_READY || !global.firebase) {
        console.info('[Firebase] belum dikonfigurasi; mode publik.');
        return;
    }

    try {
        const app = global.firebase.apps && global.firebase.apps.length
            ? global.firebase.app()
            : global.firebase.initializeApp(global.FIREBASE_CONFIG);
        const auth = global.firebase.auth();
        auth.setPersistence(global.firebase.auth.Auth.Persistence.LOCAL).catch(function () {});
        global.SK_FIREBASE = { app: app, auth: auth };
    } catch (err) {
        console.error('[Firebase] gagal inisialisasi:', err);
        global.SK_FIREBASE = null;
    }
})(window);
