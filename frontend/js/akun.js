/* ==========================================================================
   AKUN.JS — Manajemen akun petugas (khusus Administrator)
   --------------------------------------------------------------------------
   CRUD berjalan lewat Auth (auth.js), yang kini menyimpan akun di localStorage.
   Saat Firebase Auth dipakai, cukup ganti isi Auth.list/create/update/remove;
   halaman ini tidak perlu diubah.
   ========================================================================== */

(async function () {
    'use strict';

    App.init({ active: 'akun' });

    const admin = await Auth.requireAdmin();
    if (!admin) return; // requireAdmin sudah mengalihkan ke login.html

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
        error: document.getElementById('form-error'),
        save: document.getElementById('btn-save-user'),
        close: document.getElementById('btn-close-modal'),
        cancel: document.getElementById('btn-cancel-modal')
    };

    /* --- Gaya ------------------------------------------------------------ */
    const ROLE_STYLE = {
        admin: 'bg-sky-500/15 text-sky-300 border-sky-500/30',
        teknisi: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
        visitor: 'bg-slate-500/15 text-slate-300 border-slate-500/30'
    };

    function roleBadge(role) {
        const cls = ROLE_STYLE[role] || ROLE_STYLE.visitor;
        return `<span class="shrink-0 px-2 py-1 rounded-lg border text-[10px] font-black uppercase tracking-wider ${cls}">${Auth.roleLabel(role)}</span>`;
    }

    const BASE = 'flex items-center justify-center rounded-lg text-xs transition';
    const EDIT_STYLE = 'bg-yellow-600/15 text-yellow-400 border border-yellow-500/30 hover:bg-yellow-500 hover:text-[#050a1f]';
    const DEL_STYLE = 'bg-red-900/40 text-red-400 border border-red-500/30 hover:bg-red-600 hover:text-white';

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
            <div class="rounded-2xl border border-blue-900/50 sk-panel p-4">
                <div class="flex items-start justify-between gap-3">
                    <div class="min-w-0">
                        <div class="font-bold text-white text-sm leading-snug break-words">${user.nama}</div>
                        <div class="text-[11px] text-slate-500 font-mono mt-0.5">${user.nip || 'tanpa NIP'}</div>
                    </div>
                    ${roleBadge(user.role)}
                </div>
                <div class="mt-3 text-[11px] text-slate-400 font-mono break-all">${user.username}</div>
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
                <tr><td colspan="4" class="px-4 py-12 text-center text-slate-500 text-sm">
                    <i class="fa-solid fa-user-slash text-3xl mb-3 block opacity-50"></i>
                    Tidak ada akun yang cocok dengan filter.
                </td></tr>`;
            el.cards.innerHTML = `
                <div class="rounded-2xl border border-blue-900/50 sk-panel px-4 py-12 text-center text-slate-500 text-sm">
                    <i class="fa-solid fa-user-slash text-3xl mb-3 block opacity-50"></i>
                    Tidak ada akun yang cocok dengan filter.
                </div>`;
            el.status.textContent = 'Tidak ada akun yang cocok dengan filter.';
            return;
        }

        el.tableBody.innerHTML = rows.map(user => {
            const isSelf = user.uid === admin.uid;
            return `
            <tr class="hover:bg-white/5 transition">
                <td class="px-4 py-4">
                    <div class="font-bold text-white">${user.nama}${isSelf ? ' <span class="text-[10px] font-black text-blue-400 uppercase tracking-wider">(Anda)</span>' : ''}</div>
                    <div class="text-[11px] text-slate-500 font-mono">${user.nip || '—'}</div>
                </td>
                <td class="px-4 py-4">
                    <span class="text-xs text-slate-300 font-mono">${user.username}</span>
                </td>
                <td class="px-4 py-4">${roleBadge(user.role)}</td>
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
            password: el.password.value
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

    el.tableBody.addEventListener('click', handleAction);
    el.cards.addEventListener('click', handleAction);

    el.resetBtn.addEventListener('click', async () => {
        if (!confirm('Kembalikan daftar akun ke kondisi demo awal? Akun tambahan akan hilang.')) return;
        const result = await Auth.resetAccounts();
        if (!result.ok) { App.toast(result.error, 'error'); return; }
        await refresh();
        App.toast('Akun demo dipulihkan.', 'info');
    });

    document.addEventListener('auth:change', refresh);

    refresh();
})();
