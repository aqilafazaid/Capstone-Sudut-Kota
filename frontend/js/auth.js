/* ==========================================================================
   AUTH.JS — Firebase Authentication + profil operator dari backend
   --------------------------------------------------------------------------
   Identitas  : Firebase Auth (email + kata sandi).
   Peran      : RTDB `<RTDB_ROOT>/akun/<uid>/peran`, dibaca backend dan
                dikirim lewat GET /api/akun/me. Peramban tidak pernah membaca
                atau menulis RTDB.
   Otorisasi  : ditegakkan backend pada setiap endpoint tulis. Fungsi di sini
                hanya mengatur tampilan; bypass di konsol tidak memberi akses.

   Semua pemanggil WAJIB menunggu Auth.ready() (atau memakai requireOperator/
   requireAdmin yang sudah menunggu sendiri) sebelum membaca Auth.user().
   ========================================================================== */

(function (global) {
    'use strict';

    const ROLE_LABEL = { admin: 'Administrator', teknisi: 'Teknisi', visitor: 'Visitor' };
    const VALID_ROLES = ['admin', 'teknisi', 'visitor'];
    const ROLE_RANK = { admin: 0, teknisi: 1, visitor: 2 };

    /* Peta halaman -> peran yang boleh membuka. Halaman yang tidak terdaftar
       (beranda publik, login, register, lupa sandi, stream, statistik) tidak
       dijaga di sini; stream & statistik memang terbuka untuk Visitor. */
    const PAGE_ROLES = {
        'dashboard.html': ['admin', 'teknisi'],
        'add-data.html': ['admin', 'teknisi'],
        'akun.html': ['admin']
    };

    let currentUser = null;
    let readyPromise = null;
    let firstResolve = null;
    let lastProfileError = null;
    /* idle → pending selama Firebase memulihkan sesi → done setelah hasil
       pertama keluar. Halaman memakai ini untuk membedakan "belum tahu"
       dari "memang belum login". */
    let status = 'idle';

    function firebaseAuth() {
        return global.SK_FIREBASE && global.SK_FIREBASE.auth ? global.SK_FIREBASE.auth : null;
    }

    function api(path) {
        return global.SK_CONFIG.api(path);
    }

    function friendly(err) {
        const code = String((err && (err.code || err.message)) || '');
        if (code.includes('invalid-credential') || code.includes('wrong-password') || code.includes('user-not-found')) {
            return 'Email atau kata sandi salah.';
        }
        if (code.includes('invalid-email')) return 'Format email tidak valid.';
        if (code.includes('too-many-requests')) return 'Terlalu banyak percobaan. Coba lagi nanti.';
        if (code.includes('email-already-in-use')) return 'Email sudah terdaftar.';
        if (code.includes('weak-password')) return 'Kata sandi minimal 6 karakter.';
        if (code.includes('network')) return 'Tidak dapat menghubungi Firebase. Periksa koneksi.';
        return (err && err.message) || 'Terjadi kesalahan.';
    }

    async function idToken(force) {
        const auth = firebaseAuth();
        if (!auth || !auth.currentUser) return '';
        try {
            return await auth.currentUser.getIdToken(!!force);
        } catch (err) {
            console.warn('[Auth] gagal mengambil ID token:', err);
            return '';
        }
    }

    async function request(path, options) {
        const opts = Object.assign({}, options || {});
        const headers = Object.assign({ Accept: 'application/json' }, opts.headers || {});
        if (opts.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json';

        const token = await idToken();
        if (token) headers.Authorization = 'Bearer ' + token;
        opts.headers = headers;

        const url = api(path);
        let response;
        try {
            response = await fetch(url, opts);
        } catch (cause) {
            const error = new Error('Tidak dapat menghubungi ' + url);
            error.url = url;
            error.cause = cause;
            throw error;
        }
        const data = await response.json().catch(function () { return {}; });
        if (!response.ok) {
            const error = new Error(data.error || ('HTTP ' + response.status));
            error.status = response.status;
            error.url = url;
            throw error;
        }
        return data;
    }

    function normalize(profile, fallback) {
        if (!profile) return null;
        const peran = VALID_ROLES.indexOf(profile.peran) >= 0 ? profile.peran : 'visitor';
        const email = profile.email || (fallback && fallback.email) || '';
        return {
            uid: profile.uid || (fallback && fallback.uid) || '',
            nama: profile.nama || (fallback && fallback.displayName) || email || 'Petugas',
            nip: profile.nip || '',
            username: profile.username || '',
            email: email,
            role: peran
        };
    }

    async function loadProfile() {
        const auth = firebaseAuth();
        if (!auth || !auth.currentUser) return null;
        lastProfileError = null;
        try {
            return normalize(await request('akun/me'), auth.currentUser);
        } catch (err) {
            lastProfileError = err;
            if (err.status === 404) {
                console.warn('[Auth] Profil belum dibuat untuk uid', auth.currentUser.uid);
            } else {
                console.warn('[Auth] Gagal memuat profil:', err.message);
            }
            return null;
        }
    }

    /* Pesan login gagal yang menyebut URL backend + status, supaya kasus
       "backend tidak terjangkau" tidak tertukar dengan "profil belum dibuat". */
    function profileErrorHint() {
        const err = lastProfileError;
        if (!err) return 'Login berhasil, tetapi profil akun belum dibuat. Hubungi Administrator.';
        const url = err.url || api('akun/me');
        if (err.status === 404) {
            return 'Login berhasil, tetapi endpoint profil tidak ditemukan di ' + url +
                ' (404). Periksa alamat backend (SK_CONFIG.backendBase) atau apakah profil akun ini ada.';
        }
        if (err.status === 401 || err.status === 403) {
            return 'Login berhasil, tetapi backend menolak token (' + err.status + ') di ' + url + '.';
        }
        return 'Login berhasil, tetapi backend ' + url + ' tidak bisa dihubungi (' + err.message + ').';
    }

    function emit() {
        document.dispatchEvent(new CustomEvent('auth:change', { detail: { user: currentUser } }));
    }

    /** Nama berkas halaman aktif, mis. ``akun.html``. */
    function currentPage() {
        var name = String(location.pathname || '').split('/').pop();
        return (name || 'index.html').toLowerCase();
    }

    /** Halaman awal menurut peran. */
    function homeFor(role) {
        return role === 'visitor' ? 'cctv.html' : 'dashboard.html';
    }

    function ready() {
        if (readyPromise) return readyPromise;
        status = 'pending';

        readyPromise = (async function () {
            const auth = firebaseAuth();
            if (!auth) {
                status = 'done';
                currentUser = null;
                emit();
                return null;
            }

            const first = new Promise(function (resolve) { firstResolve = resolve; });
            auth.onAuthStateChanged(async function (firebaseUser) {
                currentUser = firebaseUser ? await loadProfile() : null;
                status = 'done';
                emit();
                if (firstResolve) {
                    const done = firstResolve;
                    firstResolve = null;
                    done(currentUser);
                }
            });
            return first;
        })();

        return readyPromise;
    }

    const Auth = {
        roles: ROLE_LABEL,

        ready: ready,

        /** true setelah Firebase selesai memulihkan sesi (login atau tidak). */
        isReady() {
            return status === 'done';
        },

        user() {
            return currentUser ? Object.assign({}, currentUser) : null;
        },

        isLoggedIn() {
            return !!currentUser;
        },

        isOperator() {
            return !!currentUser && (currentUser.role === 'admin' || currentUser.role === 'teknisi');
        },

        isAdmin() {
            return !!currentUser && currentUser.role === 'admin';
        },

        roleLabel(role) {
            return ROLE_LABEL[role] || 'Visitor';
        },

        idToken: idToken,

        async login(identifier, password) {
            const auth = firebaseAuth();
            if (!auth) return { ok: false, error: 'Firebase belum dikonfigurasi di backend.' };

            const email = String(identifier || '').trim();
            if (!email || !password) return { ok: false, error: 'Isi email dan kata sandi.' };

            try {
                await auth.signInWithEmailAndPassword(email, password);
                const user = await loadProfile();
                currentUser = user;
                status = 'done';
                emit();
                if (!user) {
                    return { ok: false, error: profileErrorHint() };
                }
                return { ok: true, user: user };
            } catch (err) {
                return { ok: false, error: friendly(err) };
            }
        },

        async register(payload) {
            const auth = firebaseAuth();
            if (!auth) return { ok: false, error: 'Firebase belum dikonfigurasi di backend.' };

            const nama = String((payload && payload.nama) || '').trim();
            const email = String((payload && payload.email) || '').trim().toLowerCase();
            const password = String((payload && payload.password) || '');

            if (!nama || !email) return { ok: false, error: 'Nama dan email wajib diisi.' };
            if (password.length < 6) return { ok: false, error: 'Kata sandi minimal 6 karakter.' };

            try {
                const cred = await auth.createUserWithEmailAndPassword(email, password);
                if (cred.user && cred.user.updateProfile) {
                    await cred.user.updateProfile({ displayName: nama }).catch(function () {});
                }
                let profile;
                try {
                    profile = await request('akun/self', {
                        method: 'POST',
                        body: JSON.stringify({ nama: nama, email: email })
                    });
                } catch (profileError) {
                    // Jangan tinggalkan user Auth tanpa profil (akun yatim):
                    // hapus identitas yang baru dibuat lalu laporkan gagal.
                    try { await cred.user.delete(); } catch (cleanupError) { /* diabaikan */ }
                    throw profileError;
                }
                currentUser = normalize(profile, cred.user);
                status = 'done';
                emit();
                return { ok: true, user: currentUser, visitor: true };
            } catch (err) {
                return { ok: false, error: friendly(err) };
            }
        },

        async resetPassword(email) {
            const auth = firebaseAuth();
            if (!auth) return { ok: false, error: 'Firebase belum dikonfigurasi di backend.' };
            const address = String(email || '').trim();
            if (!address) return { ok: false, error: 'Isi email akun.' };
            try {
                await auth.sendPasswordResetEmail(address);
                return { ok: true };
            } catch (err) {
                return { ok: false, error: friendly(err) };
            }
        },

        async logout() {
            const auth = firebaseAuth();
            currentUser = null;
            status = 'done';
            emit();
            if (auth) {
                try { await auth.signOut(); } catch (err) { console.warn(err); }
            }
        },

        /** Pagar halaman operator. Sudah menunggu Auth.ready(). */
        async requireOperator() {
            const user = await ready();
            if (user && (user.role === 'admin' || user.role === 'teknisi')) return user;
            if (user) {
                location.replace('cctv.html?denied=' + encodeURIComponent(currentPage()));
                return null;
            }
            const next = encodeURIComponent(location.pathname + location.search);
            location.replace('login.html?next=' + next + '&reason=login');
            return null;
        },

        /** Pagar halaman Administrator. */
        async requireAdmin() {
            const user = await ready();
            if (user && user.role === 'admin') return user;
            if (user) {
                const target = user.role === 'teknisi' ? 'dashboard.html' : 'cctv.html';
                location.replace(target + '?denied=' + encodeURIComponent(currentPage()));
                return null;
            }
            const next = encodeURIComponent(location.pathname + location.search);
            location.replace('login.html?next=' + next + '&reason=login');
            return null;
        },

        /** Pagar berbasis peta PAGE_ROLES; halaman tak terdaftar lolos apa adanya. */
        async requirePage(page) {
            const user = await ready();
            const name = String(page || currentPage()).toLowerCase();
            const allowed = PAGE_ROLES[name];
            if (!allowed) return user;
            if (!user) {
                const next = encodeURIComponent(location.pathname + location.search);
                location.replace('login.html?next=' + next + '&reason=login');
                return null;
            }
            if (allowed.indexOf(user.role) >= 0) return user;
            const target = user.role === 'visitor' ? 'cctv.html' : 'dashboard.html';
            location.replace(target + '?denied=' + encodeURIComponent(name));
            return null;
        },

        /** true bila peran boleh membuka halaman (tanpa mengalihkan). */
        canAccess(page, role) {
            const allowed = PAGE_ROLES[String(page || '').toLowerCase()];
            return !allowed || allowed.indexOf(role || (currentUser && currentUser.role)) >= 0;
        },

        homeFor: homeFor,
        currentPage: currentPage,

        /* --- CRUD akun, khusus Administrator (lewat /api/akun) ----------- */

        async list() {
            const rows = await request('akun');
            return (Array.isArray(rows) ? rows : [])
                .map(function (row) { return normalize(row); })
                .filter(Boolean)
                .sort(function (a, b) {
                    const rank = (ROLE_RANK[a.role] || 9) - (ROLE_RANK[b.role] || 9);
                    return rank || String(a.nama).localeCompare(String(b.nama), 'id');
                });
        },

        async count() {
            const rows = await this.list();
            return {
                total: rows.length,
                admin: rows.filter(function (u) { return u.role === 'admin'; }).length,
                teknisi: rows.filter(function (u) { return u.role === 'teknisi'; }).length,
                visitor: rows.filter(function (u) { return u.role === 'visitor'; }).length
            };
        },

        async create(payload) {
            try {
                const profile = await request('akun', { method: 'POST', body: JSON.stringify(payload) });
                return { ok: true, user: normalize(profile) };
            } catch (err) {
                return { ok: false, error: err.message };
            }
        },

        async update(uid, patch) {
            try {
                const profile = await request('akun/' + encodeURIComponent(uid), {
                    method: 'PUT',
                    body: JSON.stringify(patch)
                });
                return { ok: true, user: normalize(profile) };
            } catch (err) {
                return { ok: false, error: err.message };
            }
        },

        async remove(uid) {
            try {
                await request('akun/' + encodeURIComponent(uid), { method: 'DELETE' });
                return { ok: true };
            } catch (err) {
                return { ok: false, error: err.message };
            }
        },

        onChange(callback) {
            const handler = function (event) { callback(event.detail.user); };
            document.addEventListener('auth:change', handler);
            return function () { document.removeEventListener('auth:change', handler); };
        }
    };

    global.Auth = Auth;
})(window);
