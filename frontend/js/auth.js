/* ==========================================================================
   AUTH.JS — Autentikasi (versi demo, tanpa Firebase)
   --------------------------------------------------------------------------
   Antarmuka modul ini disengaja sama dengan rencana Firebase Auth:
       Auth.login(identifier, password)
       Auth.register({ nama, nip, username, password })
       Auth.logout()
       Auth.user()            → { uid, nama, username, role } | null
       Auth.isOperator()      → role admin/teknisi
       Auth.requireOperator() → tendang ke login.html bila bukan operator

   Saat Firebase diaktifkan: ganti isi fungsi-fungsi ini dengan
   signInWithEmailAndPassword / createUserWithEmailAndPassword / onAuthStateChanged,
   lalu ambil role dari /roles/{uid}. Pemanggilnya tidak perlu diubah.

   PERINGATAN: sesi disimpan di localStorage dan kata sandi tidak di-hash.
   Ini HANYA untuk demo frontend. Jangan dipakai sebagai otorisasi produksi —
   penjaga halaman di sini bisa dilewati dari konsol peramban.
   ========================================================================== */

(function (global) {
    'use strict';

    const SESSION_KEY = 'sudutkota.session.v1';
    const USERS_KEY = 'sudutkota.users.v1';

    /* Tiga peran saja: Administrator, Teknisi, Visitor. */
    const ROLE_LABEL = {
        admin: 'Administrator',
        teknisi: 'Teknisi',
        visitor: 'Visitor'
    };

    /* Akun demo bawaan. Role tidak pernah dipilih sendiri oleh pengguna. */
    const SEED_USERS = [
        { uid: 'demo-admin', nama: 'Admin Dishub', nip: 'ADM-001', username: 'admin', password: 'admin123', role: 'admin' },
        { uid: 'demo-teknisi', nama: 'Teknisi Lapangan', nip: 'TKN-001', username: 'teknisi', password: 'teknisi123', role: 'teknisi' }
    ];

    const ROLES = ['admin', 'teknisi', 'visitor'];

    /** Tulis daftar akun lalu beri tahu seluruh halaman (navbar ikut segar). */
    function persist(users) {
        localStorage.setItem(USERS_KEY, JSON.stringify(users));
        const session = readSession();
        document.dispatchEvent(new CustomEvent('auth:change', {
            detail: { user: session ? publicUser(session) : null }
        }));
    }

    function readUsers() {
        try {
            const raw = localStorage.getItem(USERS_KEY);
            const parsed = raw ? JSON.parse(raw) : null;
            if (Array.isArray(parsed) && parsed.length) {
                // Dua migrasi data lama: peran 'pending' -> 'visitor',
                // dan kolom 'email' -> 'username' (akun tidak lagi memakai email).
                let changed = false;
                const migrated = parsed.map(u => {
                    const next = { ...u };
                    if (next.role === 'pending') { next.role = 'visitor'; changed = true; }
                    if (!next.username && next.email) next.username = String(next.email).toLowerCase();
                    if ('email' in next) { delete next.email; changed = true; }
                    return next;
                });
                if (changed) localStorage.setItem(USERS_KEY, JSON.stringify(migrated));
                return migrated;
            }
        } catch (err) {
            console.warn('[Auth] Data pengguna rusak, memakai akun demo.', err);
        }
        localStorage.setItem(USERS_KEY, JSON.stringify(SEED_USERS));
        return SEED_USERS.slice();
    }

    function readSession() {
        try {
            const raw = localStorage.getItem(SESSION_KEY);
            return raw ? JSON.parse(raw) : null;
        } catch (err) {
            return null;
        }
    }

    function writeSession(session) {
        if (session) localStorage.setItem(SESSION_KEY, JSON.stringify(session));
        else localStorage.removeItem(SESSION_KEY);
    }

    function publicUser(account) {
        if (!account) return null;
        return {
            uid: account.uid,
            nama: account.nama,
            nip: account.nip,
            username: account.username,
            role: account.role
        };
    }

    const Auth = {
        roles: ROLE_LABEL,

        user() {
            return publicUser(readSession());
        },

        isLoggedIn() {
            return !!readSession();
        },

        isOperator() {
            const user = readSession();
            return !!user && (user.role === 'admin' || user.role === 'teknisi');
        },

        isAdmin() {
            const user = readSession();
            return !!user && user.role === 'admin';
        },

        roleLabel(role) {
            return ROLE_LABEL[role] || 'Visitor';
        },

        /**
         * Login memakai username atau NIP.
         * @returns {{ok: boolean, user?: object, error?: string}}
         */
        login(identifier, password) {
            const key = String(identifier || '').trim().toLowerCase();
            if (!key || !password) return { ok: false, error: 'Isi username dan kata sandi.' };

            const account = readUsers().find(u =>
                String(u.username).toLowerCase() === key ||
                String(u.nip).toLowerCase() === key
            );

            if (!account || account.password !== password) {
                return { ok: false, error: 'Username atau kata sandi salah.' };
            }

            writeSession(publicUser(account));
            document.dispatchEvent(new CustomEvent('auth:change', { detail: { user: publicUser(account) } }));
            return { ok: true, user: publicUser(account) };
        },

        register({ nama, nip, username, password }) {
            const users = readUsers();
            const key = String(username || '').trim().toLowerCase();
            if (!nama || !key || !password) return { ok: false, error: 'Nama, username, dan kata sandi wajib diisi.' };
            if (password.length < 6) return { ok: false, error: 'Kata sandi minimal 6 karakter.' };
            if (users.some(u => String(u.username).toLowerCase() === key || String(u.nip).toLowerCase() === String(nip || '').toLowerCase())) {
                return { ok: false, error: 'Username atau NIP sudah terdaftar.' };
            }

            /* Akun baru tidak mendapat akses operator sampai dipromosikan. */
            const account = {
                uid: 'u-' + Date.now().toString(36),
                nama: nama.trim(),
                nip: (nip || '').trim(),
                username: key,
                password,
                role: 'visitor'
            };
            users.push(account);
            localStorage.setItem(USERS_KEY, JSON.stringify(users));
            return { ok: true, user: publicUser(account), visitor: true };
        },

        logout() {
            writeSession(null);
            document.dispatchEvent(new CustomEvent('auth:change', { detail: { user: null } }));
        },

        /** Pagar halaman operator. Mengembalikan user bila lolos. */
        requireOperator() {
            const user = readSession();
            if (user && (user.role === 'admin' || user.role === 'teknisi')) return user;

            const next = encodeURIComponent(location.pathname + location.search);
            const reason = user ? 'visitor' : 'login';
            location.replace(`login.html?next=${next}&reason=${reason}`);
            return null;
        },

        /* --- CRUD akun, khusus Administrator ----------------------------- */

        /** Daftar akun tanpa kata sandi, diurutkan peran lalu nama. */
        list() {
            const rank = { admin: 0, teknisi: 1, visitor: 2 };
            return readUsers()
                .map(publicUser)
                .sort((a, b) => (rank[a.role] - rank[b.role]) || String(a.nama).localeCompare(String(b.nama), 'id'));
        },

        count() {
            const users = readUsers();
            return {
                total: users.length,
                admin: users.filter(u => u.role === 'admin').length,
                teknisi: users.filter(u => u.role === 'teknisi').length,
                visitor: users.filter(u => u.role === 'visitor').length
            };
        },

        create({ nama, nip, username, password, role }) {
            const users = readUsers();
            const namaBersih = String(nama || '').trim();
            const kunci = String(username || '').trim().toLowerCase();
            const nipBersih = String(nip || '').trim();
            const sandi = String(password || '');
            const peran = ROLES.includes(role) ? role : 'visitor';

            if (!namaBersih || !kunci || !sandi) {
                return { ok: false, error: 'Nama, username, dan kata sandi wajib diisi.' };
            }
            if (kunci.length < 3) return { ok: false, error: 'Username minimal 3 karakter.' };
            if (sandi.length < 6) return { ok: false, error: 'Kata sandi minimal 6 karakter.' };
            if (users.some(u => String(u.username).toLowerCase() === kunci)) {
                return { ok: false, error: 'Username sudah dipakai akun lain.' };
            }
            if (nipBersih && users.some(u => String(u.nip).toLowerCase() === nipBersih.toLowerCase())) {
                return { ok: false, error: 'NIP sudah dipakai akun lain.' };
            }

            const account = {
                uid: 'u-' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6),
                nama: namaBersih,
                nip: nipBersih,
                username: kunci,
                password: sandi,
                role: peran
            };

            users.push(account);
            persist(users);
            return { ok: true, user: publicUser(account) };
        },

        update(uid, patch) {
            const users = readUsers();
            const index = users.findIndex(u => u.uid === uid);
            if (index === -1) return { ok: false, error: 'Akun tidak ditemukan.' };

            const current = users[index];
            const namaBersih = patch.nama !== undefined ? String(patch.nama).trim() : current.nama;
            const kunci = patch.username !== undefined ? String(patch.username).trim().toLowerCase() : current.username;
            const nipBersih = patch.nip !== undefined ? String(patch.nip).trim() : current.nip;
            const peran = patch.role && ROLES.includes(patch.role) ? patch.role : current.role;
            const sandi = patch.password === undefined || patch.password === null ? '' : String(patch.password);

            if (!namaBersih || !kunci) return { ok: false, error: 'Nama dan username wajib diisi.' };
            if (kunci.length < 3) return { ok: false, error: 'Username minimal 3 karakter.' };
            if (users.some((u, i) => i !== index && String(u.username).toLowerCase() === kunci)) {
                return { ok: false, error: 'Username sudah dipakai akun lain.' };
            }
            if (nipBersih && users.some((u, i) => i !== index && String(u.nip).toLowerCase() === nipBersih.toLowerCase())) {
                return { ok: false, error: 'NIP sudah dipakai akun lain.' };
            }
            if (sandi && sandi.length < 6) return { ok: false, error: 'Kata sandi minimal 6 karakter.' };

            const admins = users.filter(u => u.role === 'admin').length;
            if (current.role === 'admin' && peran !== 'admin' && admins <= 1) {
                return { ok: false, error: 'Minimal harus ada satu Administrator.' };
            }

            const updated = { ...current, nama: namaBersih, nip: nipBersih, username: kunci, role: peran };
            if (sandi) updated.password = sandi;
            users[index] = updated;

            persist(users);

            // Bila akun yang diubah adalah sesi yang sedang aktif, segarkan sesinya.
            const session = readSession();
            if (session && session.uid === uid) writeSession(publicUser(updated));

            return { ok: true, user: publicUser(updated) };
        },

        remove(uid) {
            const users = readUsers();
            const index = users.findIndex(u => u.uid === uid);
            if (index === -1) return { ok: false, error: 'Akun tidak ditemukan.' };

            const session = readSession();
            if (session && session.uid === uid) {
                return { ok: false, error: 'Tidak bisa menghapus akun yang sedang dipakai.' };
            }
            if (users[index].role === 'admin' && users.filter(u => u.role === 'admin').length <= 1) {
                return { ok: false, error: 'Minimal harus ada satu Administrator.' };
            }

            users.splice(index, 1);
            persist(users);
            return { ok: true };
        },

        /** Pulihkan akun demo tanpa memaksa keluar bila sesi masih ada di seed. */
        resetAccounts() {
            localStorage.setItem(USERS_KEY, JSON.stringify(SEED_USERS));
            const session = readSession();
            const stillThere = session ? SEED_USERS.find(u => u.uid === session.uid) : null;
            writeSession(stillThere ? publicUser(stillThere) : null);

            document.dispatchEvent(new CustomEvent('auth:change', {
                detail: { user: stillThere ? publicUser(stillThere) : null }
            }));
            return { ok: true };
        },

        /** Pagar halaman Administrator. */
        requireAdmin() {
            const user = readSession();
            if (user && user.role === 'admin') return user;

            const next = encodeURIComponent(location.pathname + location.search);
            const reason = user ? 'forbidden' : 'login';
            location.replace(`login.html?next=${next}&reason=${reason}`);
            return null;
        },

        onChange(callback) {
            const handler = (event) => callback(event.detail.user);
            document.addEventListener('auth:change', handler);
            window.addEventListener('storage', (event) => {
                if (event.key === SESSION_KEY) callback(readSession());
            });
            return () => document.removeEventListener('auth:change', handler);
        },

        /** Kembalikan akun demo ke kondisi awal (dipakai saat reset data). */
        resetDemo() {
            localStorage.setItem(USERS_KEY, JSON.stringify(SEED_USERS));
            writeSession(null);
        }
    };

    global.Auth = Auth;
})(window);
