/**
 * Dihasilkan oleh backend/scripts/sync_public_config.py.
 * Jangan edit manual: ubah backend/.env lalu jalankan ulang skrip itu.
 *
 * Hanya berisi kunci PUBLIK Firebase Web SDK. Kunci Admin SDK / service
 * account tidak pernah masuk ke file ini.
 */
window.FIREBASE_CONFIG = {
  apiKey: "AIzaSyBnhEtKYel30QEz49w-Whn86ScmEQ8H3PM",
  authDomain: "adminsudutkota.firebaseapp.com",
  databaseURL: "https://adminsudutkota-default-rtdb.firebaseio.com",
  projectId: "adminsudutkota",
  storageBucket: "adminsudutkota.firebasestorage.app",
  messagingSenderId: "1014149981874",
  appId: "1:1014149981874:web:2e375ede649c5d47af0bab",
  measurementId: "G-KDJP5JLMDM"
};

window.FIREBASE_READY = (function (cfg) {
  var required = ['apiKey', 'authDomain', 'databaseURL', 'projectId', 'appId'];
  return required.every(function (key) {
    return String(cfg[key] || '').trim() !== '';
  });
})(window.FIREBASE_CONFIG);
