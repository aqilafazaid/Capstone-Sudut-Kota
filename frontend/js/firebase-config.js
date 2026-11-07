/**
 * Dihasilkan oleh backend/scripts/sync_firebase_config.py.
 * Jangan edit manual: ubah backend/.env lalu jalankan ulang skrip itu.
 *
 * Hanya berisi kunci PUBLIK Firebase Web SDK. Kunci Admin SDK / service
 * account tidak pernah masuk ke file ini.
 */
window.FIREBASE_CONFIG = {
  apiKey: "",
  authDomain: "",
  databaseURL: "",
  projectId: "",
  storageBucket: "",
  messagingSenderId: "",
  appId: "",
  measurementId: ""
};

window.FIREBASE_READY = (function (cfg) {
  var required = ['apiKey', 'authDomain', 'databaseURL', 'projectId', 'appId'];
  return required.every(function (key) {
    return String(cfg[key] || '').trim() !== '';
  });
})(window.FIREBASE_CONFIG);
