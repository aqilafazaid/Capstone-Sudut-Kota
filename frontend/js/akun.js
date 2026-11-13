/* ==========================================================================
   AKUN.JS — Manajemen akun petugas (khusus Administrator)
   --------------------------------------------------------------------------
   CRUD berjalan lewat Auth (auth.js) dan backend /api/akun, yang memakai
   Firebase Authentication + RTDB.
   Saat Firebase Auth dipakai, cukup ganti isi Auth.list/create/update/remove;
   halaman ini tidak perlu diubah.
   ========================================================================== */

(async function () {
    'use strict';

    App.init({ active: 'akun' });

    /* Akses "akun" kini bisa diberikan ke peran mana pun oleh Administrator,
       jadi pagar memakai fitur — bukan requireAdmin(). */
    const gate = await Auth.guard('akun');
    if (!gate.ok) { if (!gate.redirected) App.blocked('akun'); return; }
    const admin = gate.user;

    /** Cache daftar akun dari /api/akun; halaman ini tidak menulis RTDB. */
    let accounts = [];

    const el = {
        total: document.getElementById('sum-total'),
        admin: document.getElementById('sum-admin'),
        teknisi: document.getElementById('sum-teknisi'),
        visitor: document.getElementById('sum-visitor'),
        search: document.getElementById('filter-search'),
        role: document.getElementById('filter-role'),
        status: document.getElementById('status-text-body'),
        cards: document.getElementById('user-cards'),
        tableBody: document.getElementById('user-table-body'),
        addBtn: document.getElementById('btn-add-user'),
        resetBtn: document.getElementById('btn-reset-accounts'),

        modal: document.getElementById('user-modal'),
        modalTitle: document.getElementById('modal-title'),
        modalSubtitle: document.getElementById('modal-subtitle'),
        modalIcon: document.getElementById('modal-icon'),
        form: document.getElementById('user-form'),
        uid: document.getElementById('field-uid'),
        nama: document.getElementById('field-nama'),
        email: document.getElementById('field-email'),
        roleField: document.getElementById('field-role'),
        password: document.getElementById('field-password'),
        passwordHint: document.getElementById('password-hint'),
        togglePassword: document.getElementById('btn-toggle-password'),
        modalAkses: document.getElementById('modal-akses'),
        error: document.getElementById('form-error'),
        save: document.getElementById('btn-save-user'),
        close: document.getElementById('btn-close-modal'),
        cancel: document.getElementById('btn-cancel-modal')
    };

    /* --- Gaya ------------------------------------------------------------ */
    const ROLE_STYLE = {
        admin: 'bg-sky-500/15 text-sky-700 dark:text-sky-300 border-sky-500/30',
        teknisi: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/30',
        visitor: 'bg-slate-500/15 text-slate-700 dark:text-slate-300 border-slate-500/30'
    };

    function roleBadge(role) {
        const cls = ROLE_STYLE[role] || ROLE_STYLE.visitor;
        return `<span class="shrink-0 px-2 py-1 rounded-lg border text-[10px] font-black uppercase tracking-wider ${cls}">${Auth.roleLabel(role)}</span>`;
    }

    const BASE = 'flex items-center justify-center rounded-lg text-xs transition';
    const EDIT_STYLE = 'bg-amber-500/15 text-amber-700 dark:text-amber-300 border border-amber-500/40 hover:bg-amber-500 hover:text-white';

    /* --- Akses fitur ------------------------------------------------------
       Semua sakelar berfungsi untuk akun mana pun: Administrator yang berhak
       mengaturnya, jadi peran tidak lagi mengunci pilihan. Peran hanya menjadi
       nilai bawaan. Satu-satunya sakelar terkunci: akses "Akun" milik akun
       yang sedang dipakai (mencegah Administrator mengunci dirinya sendiri). */
    const FEATURES = Auth.features();
    const SHORT_LABEL = { cctv: 'CCTV', statistik: 'Statistik', dashboard: 'Dashboard', ai: 'Modul AI', akun: 'Akun' };
    const FEATURE_DESC = {
        cctv: 'Menonton kamera live.',
        statistik: 'Grafik volume lalu lintas, tabel, ekspor PDF/CSV.',
        dashboard: 'Command Center dan registrasi titik kamera.',
        ai: 'Panel kontrol modul AI di halaman CCTV (YOLOv8, MirNet/Zero-DCE, pilihan model).',
        akun: 'Kelola akun petugas dan akses fiturnya.'
    };

    function roleAllows(role, feature) {
        return Auth.roleFeatures(role).indexOf(feature) >= 0;
    }

    function defaultHint(role, feature) {
        return 'Bawaan peran: ' + (roleAllows(role, feature) ? 'aktif' : 'nonaktif');
    }

    /** Sakelar; `size` 'sm' untuk tabel/kartu, 'md' untuk modal. */
    function aksesSwitch(user, feature, size) {
        const on = user.akses[feature] === true;
        const locked = user.uid === admin.uid && feature === 'akun';
        const md = size === 'md';
        const track = md ? 'h-6 w-11' : 'h-5 w-9';
        const knob = md ? 'h-5 w-5' : 'h-4 w-4';
        const shift = on ? (md ? 'translate-x-[22px]' : 'translate-x-4') : 'translate-x-0.5';

        return `<button type="button" role="switch" aria-checked="${on}"
                    data-akses="${user.uid}" data-feature="${feature}"
                    aria-label="${Auth.featureLabel(feature)} untuk ${user.nama}"
                    title="${locked ? 'Tidak bisa dicabut dari akun sendiri' : (on ? 'Nonaktifkan akses' : 'Aktifkan akses') + ' · ' + defaultHint(user.role, feature)}"
                    ${locked ? 'disabled aria-disabled="true"' : ''}
                    class="relative inline-flex ${track} shrink-0 items-center rounded-full transition-colors ${
                        on ? 'bg-blue-600' : 'bg-slate-300 dark:bg-slate-600'
                    } ${locked ? 'opacity-60 cursor-not-allowed' : 'cursor-pointer'}">
                    <span class="inline-block ${knob} rounded-full bg-white shadow transform transition-transform ${shift}"></span>
                </button>`;
    }

    /** Empat sakelar ringkas (2 kolom) untuk tabel dan kartu ponsel. */
    function aksesGrid(user, size) {
        return `<div class="grid grid-cols-2 gap-x-4 gap-y-2">${FEATURES.map(feature => `
            <div class="flex items-center gap-2">
                ${aksesSwitch(user, feature, size)}
                <span class="text-[10px] font-bold uppercase tracking-wide ${
                    user.akses[feature] === true ? 'sk-ink' : 'sk-faint'
                }">${SHORT_LABEL[feature] || feature}</span>
            </div>`).join('')}</div>`;
    }
    const DEL_STYLE = 'sk-btn-soft-danger';

    function editButton(user, extra, label) {
        return `<button type="button" data-edit="${user.uid}" title="Ubah akun" class="${extra}">
                    <i class="fa-solid fa-pen-to-square"></i>${label ? `<span>${label}</span>` : ''}
                </button>`;
    }

    function deleteButton(user, extra, label) {
        return `<button type="button" data-delete="${user.uid}" title="Hapus akun" class="${extra}">
                    <i class="fa-solid fa-trash-can"></i>${label ? `<span>${label}</span>` : ''}
                </button>`;
    }

    /* --- Data & filter --------------------------------------------------- */
    function filtered() {
        const q = el.search.value.trim().toLowerCase();
        const role = el.role.value;

        return accounts.filter(user => {
            if (role && user.role !== role) return false;
            if (!q) return true;
            return [user.nama, user.nip, user.username, user.email].some(v => String(v || '').toLowerCase().includes(q));
        });
    }

    function paintSummary() {
        const c = {
            total: accounts.length,
            admin: accounts.filter(u => u.role === 'admin').length,
            teknisi: accounts.filter(u => u.role === 'teknisi').length,
            visitor: accounts.filter(u => u.role === 'visitor').length
        };
        el.total.textContent = c.total;
        el.admin.textContent = c.admin;
        el.teknisi.textContent = c.teknisi;
        el.visitor.textContent = c.visitor;
    }

    /* --- Render ---------------------------------------------------------- */
    function cardOf(user) {
        const isSelf = user.uid === admin.uid;
        return `
            <div class="rounded-2xl border sk-line sk-panel p-4">
                <div class="flex items-start justify-between gap-3">
                    <div class="min-w-0">
                        <div class="font-bold sk-ink text-sm leading-snug break-words">${user.nama}</div>
                        <div class="text-[11px] sk-muted font-mono mt-0.5">${user.nip || 'tanpa NIP'}</div>
                    </div>
                    ${roleBadge(user.role)}
                </div>
                <div class="mt-3 text-[11px] sk-muted font-mono break-all">${user.username}</div>
                <div class="mt-3 pt-3 border-t sk-line-soft">
                    <div class="text-[9px] font-bold sk-faint uppercase tracking-widest mb-2">Akses Fitur</div>
                    ${aksesGrid(user, 'md')}
                </div>
                <div class="mt-4 flex items-center gap-2">
                    ${editButton(user, `${BASE} flex-1 h-10 gap-2 font-bold text-[11px] uppercase tracking-wider ${EDIT_STYLE}`, 'Ubah')}
                    ${deleteButton(user, `${BASE} flex-1 h-10 gap-2 font-bold text-[11px] uppercase tracking-wider ${DEL_STYLE}`, isSelf ? 'Dipakai' : 'Hapus')}
                </div>
            </div>`;
    }

    function paintList() {
        const rows = filtered();
        const total = accounts.length;

        if (rows.length === 0) {
            el.tableBody.innerHTML = `
                <tr><td colspan="5" class="px-4 py-12 text-center sk-muted text-sm">
                    <i class="fa-solid fa-user-slash text-3xl mb-3 block opacity-50"></i>
                    Tidak ada akun yang cocok dengan filter.
                </td></tr>`;
            el.cards.innerHTML = `
                <div class="rounded-2xl border sk-line sk-panel px-4 py-12 text-center sk-muted text-sm">
                    <i class="fa-solid fa-user-slash text-3xl mb-3 block opacity-50"></i>
                    Tidak ada akun yang cocok dengan filter.
                </div>`;
            el.status.textContent = 'Tidak ada akun yang cocok dengan filter.';
            return;
        }

        el.tableBody.innerHTML = rows.map(user => {
            const isSelf = user.uid === admin.uid;
            return `
            <tr class="sk-row-hover">
                <td class="px-4 py-4">
                    <div class="font-bold sk-ink">${user.nama}${isSelf ? ' <span class="text-[10px] font-black sk-accent uppercase tracking-wider">(Anda)</span>' : ''}</div>
                    <div class="text-[11px] sk-muted font-mono">${user.nip || '—'}</div>
                </td>
                <td class="px-4 py-4">
                    <span class="text-xs sk-muted font-mono">${user.username}</span>
                </td>
                <td class="px-4 py-4">${roleBadge(user.role)}</td>
                <td class="px-4 py-4">${aksesGrid(user, 'sm')}</td>
                <td class="px-4 py-4">
                    <div class="flex justify-end gap-2">
                        ${editButton(user, `${BASE} w-9 h-9 ${EDIT_STYLE}`)}
                        ${deleteButton(user, `${BASE} w-9 h-9 ${DEL_STYLE}`)}
                    </div>
                </td>
            </tr>`;
        }).join('');

        el.cards.innerHTML = rows.map(cardOf).join('');
        el.status.textContent = rows.length === total
            ? `Menampilkan seluruh ${total} akun.`
            : `Menampilkan ${rows.length} dari ${total} akun.`;
    }

    async function refresh() {
        try {
            accounts = await Auth.list();
        } catch (err) {
            accounts = [];
            App.toast('Gagal memuat akun: ' + err.message, 'error');
        }
        paintSummary();
        paintList();
    }

    /* --- Akses di modal --------------------------------------------------
       Modal memakai sakelar yang sama; nilainya dikirim bersama Simpan,
       sedangkan sakelar di tabel/kartu langsung tersimpan saat diklik. */
    let modalAksesState = {};

    function modalAksesRow(feature, role, on) {
        const locked = el.uid.value === admin.uid && feature === 'akun';
        const shift = on ? 'translate-x-[22px]' : 'translate-x-0.5';

        return `
            <div class="flex items-center justify-between gap-3 px-3 py-2.5 rounded-xl border sk-line">
                <div class="min-w-0">
                    <div class="text-xs font-bold sk-ink">${Auth.featureLabel(feature)}</div>
                    <div class="text-[10px] sk-muted leading-snug">${FEATURE_DESC[feature]}</div>
                </div>
                <button type="button" role="switch" aria-checked="${on}" data-modal-akses="${feature}"
                        aria-label="${Auth.featureLabel(feature)}"
                        ${locked ? 'disabled aria-disabled="true" title="Tidak bisa dicabut dari akun sendiri"' : 'title="' + defaultHint(role, feature) + '"'}
                        class="relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors ${
                            on ? 'bg-blue-600' : 'bg-slate-300 dark:bg-slate-600'
                        } ${locked ? 'opacity-60 cursor-not-allowed' : 'cursor-pointer'}">
                    <span class="inline-block h-5 w-5 rounded-full bg-white shadow transform transition-transform ${shift}"></span>
                </button>
            </div>`;
    }

    function renderModalAkses() {
        const role = el.roleField.value;
        el.modalAkses.innerHTML = FEATURES.map(feature =>
            modalAksesRow(feature, role, modalAksesState[feature] === true)).join('');
    }

    function setModalAkses(role, akses) {
        modalAksesState = Auth.aksesOf(role, akses);
        renderModalAkses();
    }

    /* --- Modal ----------------------------------------------------------- */
    function showError(message) {
        if (!message) {
            el.error.classList.add('hidden');
            el.error.textContent = '';
            return;
        }
        el.error.textContent = message;
        el.error.classList.remove('hidden');
    }

    function openModal(user) {
        el.form.reset();
        showError('');
        el.password.type = 'password';

        if (user) {
            el.modalTitle.textContent = 'Ubah Akun';
            el.modalSubtitle.textContent = `Perbarui data ${user.nama}.`;
            el.modalIcon.className = 'fa-solid fa-user-pen text-lg';
            el.uid.value = user.uid;
            el.nama.value = user.nama;
            el.email.value = user.email || '';
            el.roleField.value = user.role;
            el.passwordHint.textContent = '(kosongkan bila tidak diubah)';
            el.save.innerHTML = '<i class="fa-solid fa-floppy-disk mr-1"></i> Simpan Perubahan';
        } else {
            el.modalTitle.textContent = 'Tambah Akun';
            el.modalSubtitle.textContent = 'Lengkapi data petugas.';
            el.modalIcon.className = 'fa-solid fa-user-plus text-lg';
            el.uid.value = '';
            el.passwordHint.textContent = '(minimal 6 karakter)';
            el.save.innerHTML = '<i class="fa-solid fa-floppy-disk mr-1"></i> Simpan';
        }

        /* `el.uid` sudah terisi, jadi sakelar "Akun" tahu apakah ini akun sendiri. */
        setModalAkses(el.roleField.value, user ? user.akses : null);

        el.modal.classList.remove('hidden');
        el.modal.classList.add('flex');
        document.body.classList.add('modal-open');
        setTimeout(() => el.nama.focus(), 30);
    }

    function closeModal() {
        el.modal.classList.add('hidden');
        el.modal.classList.remove('flex');
        document.body.classList.remove('modal-open');
        showError('');
    }

    function isOpen() {
        return !el.modal.classList.contains('hidden');
    }

    /* --- Aksi ------------------------------------------------------------ */
    async function submitForm(event) {
        event.preventDefault();

        const payload = {
            nama: el.nama.value,
            email: el.email.value,
            peran: el.roleField.value,
            password: el.password.value,
            akses: Object.assign({}, modalAksesState)
        };

        const uid = el.uid.value;
        let result;

        if (uid) {
            const patch = { ...payload };
            if (!patch.password) delete patch.password; // biarkan kata sandi lama
            result = await Auth.update(uid, patch);
        } else {
            result = await Auth.create(payload);
        }

        if (!result.ok) {
            showError(result.error);
            return;
        }

        // Administrator yang mengubah aksesnya sendiri harus melihat menu ikut berubah.
        if (uid && uid === admin.uid) await Auth.refreshProfile();

        closeModal();
        refresh();
        App.toast(uid ? 'Akun diperbarui.' : 'Akun baru ditambahkan.', 'success');
    }

    function findUser(uid) {
        return accounts.find(u => u.uid === uid) || null;
    }

    async function handleAction(event) {
        const editBtn = event.target.closest('[data-edit]');
        if (editBtn) {
            const user = findUser(editBtn.dataset.edit);
            if (user) openModal(user);
            return;
        }

        const delBtn = event.target.closest('[data-delete]');
        if (!delBtn) return;

        const user = findUser(delBtn.dataset.delete);
        if (!user) return;

        if (!confirm(`Hapus akun "${user.nama}" (${user.username})? Tindakan ini tidak bisa dibatalkan.`)) return;

        const result = await Auth.remove(user.uid);
        if (!result.ok) {
            App.toast(result.error, 'error');
            return;
        }
        refresh();
        App.toast(`Akun ${user.username} dihapus.`, 'success');
    }

    /* --- Sakelar akses di tabel/kartu (langsung tersimpan) ---------------- */
    async function handleAksesToggle(event) {
        const btn = event.target.closest('[data-akses]');
        if (!btn || btn.disabled) return;

        const user = findUser(btn.dataset.akses);
        const feature = btn.dataset.feature;
        if (!user || FEATURES.indexOf(feature) < 0) return;

        const next = user.akses[feature] === false;   // false → nyalakan
        const previous = Object.assign({}, user.akses);

        user.akses[feature] = next;                   // optimistis
        paintList();

        const result = await Auth.update(user.uid, { akses: { [feature]: next } });
        if (!result.ok) {
            user.akses = previous;                    // kembalikan bila ditolak server
            paintList();
            App.toast(result.error, 'error');
            return;
        }

        Object.assign(user, result.user);
        if (user.uid === admin.uid) await Auth.refreshProfile();

        paintSummary();
        paintList();
        App.toast(
            `${Auth.featureLabel(feature)} ${next ? 'diaktifkan' : 'dinonaktifkan'} untuk ${user.nama}.`,
            next ? 'success' : 'info'
        );
    }

    /* --- Event ----------------------------------------------------------- */
    el.addBtn.addEventListener('click', () => openModal(null));
    el.close.addEventListener('click', closeModal);
    el.cancel.addEventListener('click', closeModal);
    el.form.addEventListener('submit', submitForm);

    el.modal.addEventListener('click', (event) => {
        if (event.target === el.modal) closeModal();
    });

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && isOpen()) closeModal();
    });

    el.togglePassword.addEventListener('click', () => {
        const show = el.password.type === 'password';
        el.password.type = show ? 'text' : 'password';
        el.togglePassword.innerHTML = `<i class="fa-solid ${show ? 'fa-eye-slash' : 'fa-eye'} text-xs"></i>`;
    });

    el.search.addEventListener('input', paintList);
    el.role.addEventListener('change', paintList);

    /* Sakelar akses di modal: ubah peran = kembalikan ke bawaan peran itu. */
    el.roleField.addEventListener('change', () => {
        modalAksesState = Auth.aksesOf(el.roleField.value, null);
        renderModalAkses();
    });

    el.modalAkses.addEventListener('click', (event) => {
        const btn = event.target.closest('[data-modal-akses]');
        if (!btn || btn.disabled) return;
        const feature = btn.dataset.modalAkses;
        modalAksesState[feature] = modalAksesState[feature] !== true;
        renderModalAkses();
    });

    el.tableBody.addEventListener('click', handleAksesToggle);
    el.cards.addEventListener('click', handleAksesToggle);

    el.tableBody.addEventListener('click', handleAction);
    el.cards.addEventListener('click', handleAction);

    el.resetBtn && el.resetBtn.addEventListener('click', async () => {
        App.toast('Akun dikelola Firebase Auth; tidak ada reset demo.', 'info');
    });

    document.addEventListener('auth:change', refresh);

    refresh();
})();
