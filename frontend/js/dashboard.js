/* ==========================================================================
   DASHBOARD.JS — Panel manajemen node CCTV
   --------------------------------------------------------------------------
   Halaman ini hanya untuk Administrator dan Teknisi. Data diambil dari Store
   (nanti: Firebase RTDB). Semua aksi tulis melewati Store agar titik integrasi
   tetap satu.
   ========================================================================== */

(async function () {
    'use strict';

    App.init({ active: 'dashboard' });

    const user = await Auth.requireOperator();
    if (!user) return; // requireOperator sudah mengalihkan ke login.html

    const el = {
        initial: document.getElementById('profile-initial'),
        name: document.getElementById('profile-name'),
        role: document.getElementById('profile-role'),
        sumTotal: document.getElementById('sum-total'),
        sumOnline: document.getElementById('sum-online'),
        sumOffline: document.getElementById('sum-offline'),
        sumZones: document.getElementById('sum-zones'),
        filterZona: document.getElementById('filter-zona'),
        filterStatus: document.getElementById('filter-status'),
        statusText: document.getElementById('status-text-body'),
        tableBody: document.getElementById('node-table-body'),
        cards: document.getElementById('node-cards'),
        resetDemo: document.getElementById('btn-reset-demo'),
        logoutBtn: document.getElementById('btn-logout-dash')
    };

    /* --- Profil ---------------------------------------------------------- */
    function paintProfile() {
        el.name.textContent = user.nama || 'Petugas';
        el.role.textContent = Auth.roleLabel(user.role);
        el.initial.textContent = (user.nama || '?').charAt(0).toUpperCase();
    }

    /* --- Ringkasan ------------------------------------------------------- */
    function paintSummary() {
        const cameras = Store.list();
        const online = cameras.filter(c => c.aktif).length;
        const zones = new Set(cameras.map(c => c.zona).filter(Boolean));

        el.sumTotal.textContent = cameras.length;
        el.sumOnline.textContent = online;
        el.sumOffline.textContent = cameras.length - online;
        el.sumZones.textContent = zones.size;
    }

    /* --- Filter ---------------------------------------------------------- */
    function paintZoneOptions() {
        const current = el.filterZona.value;
        const zones = Store.zones();
        el.filterZona.innerHTML = '<option value="">Semua Zona</option>' +
            zones.map(z => `<option value="${z}">${z}</option>`).join('');
        if (zones.includes(current)) el.filterZona.value = current;
    }

    function filtered() {
        const zona = el.filterZona.value;
        const status = el.filterStatus.value;
        return Store.list().filter(cam => {
            if (zona && cam.zona !== zona) return false;
            if (status === 'online' && !cam.aktif) return false;
            if (status === 'offline' && cam.aktif) return false;
            return true;
        });
    }

    /* --- Tabel ----------------------------------------------------------- */
    function aiBadges(cam) {
        const ai = Store.getAi(cam.id);
        const badges = [];
        badges.push(ai.yolo
            ? `<span class="px-2 py-0.5 rounded bg-yellow-500/15 text-yellow-700 dark:text-yellow-300 border border-yellow-500/30 text-[10px] font-bold">YOLO ${ai.yolo_model}</span>`
            : '<span class="px-2 py-0.5 rounded bg-slate-500/10 text-slate-600 dark:bg-slate-700/40 dark:text-slate-400 border border-slate-400/40 dark:border-slate-600/40 text-[10px] font-bold">YOLO OFF</span>');
        badges.push(ai.lowlight
            ? `<span class="px-2 py-0.5 rounded bg-blue-500/15 text-blue-700 dark:text-blue-300 border border-blue-500/30 text-[10px] font-bold">${ai.lowlight_model}</span>`
            : '<span class="px-2 py-0.5 rounded bg-slate-500/10 text-slate-600 dark:bg-slate-700/40 dark:text-slate-400 border border-slate-400/40 dark:border-slate-600/40 text-[10px] font-bold">LOWLIGHT OFF</span>');
        return `<div class="flex flex-wrap gap-1">${badges.join('')}</div>`;
    }

    function statusBadge(cam) {
        return cam.aktif
            ? '<span class="shrink-0 px-2 py-1 rounded-lg bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border border-emerald-500/30 text-[10px] font-black uppercase tracking-wider">Online</span>'
            : '<span class="shrink-0 px-2 py-1 rounded-lg bg-red-500/15 text-red-700 dark:text-red-300 border border-red-500/30 text-[10px] font-black uppercase tracking-wider">Offline</span>';
    }

    function editLink(cam, extra, label) {
        return `<a href="add-data.html?id=${encodeURIComponent(cam.id)}" title="Perbarui konfigurasi" class="${extra}">
                    <i class="fa-solid fa-pen-to-square"></i>${label ? `<span>${label}</span>` : ''}
                </a>`;
    }

    function deleteButton(cam, extra, label) {
        return `<button type="button" data-delete="${cam.id}" title="Hapus node" class="${extra}">
                    <i class="fa-solid fa-trash-can"></i>${label ? `<span>${label}</span>` : ''}
                </button>`;
    }

    /* Ukuran dipisah dari gaya: tabel memakai tombol ikon 36 px, kartu memakai tombol lebar 40 px. */
    const BASE = 'flex items-center justify-center rounded-lg text-xs transition';
    const EDIT_STYLE = 'bg-yellow-600/15 text-yellow-400 border border-yellow-500/30 hover:bg-yellow-500 hover:text-[#050a1f]';
    const DEL_STYLE = 'bg-red-900/40 text-red-400 border border-red-500/30 hover:bg-red-600 hover:text-white';
    const CARD_BTN = `${BASE} flex-1 h-10 gap-2 font-bold text-[11px] uppercase tracking-wider`;

    /* Kartu untuk ponsel: kolom AI dan aksi tidak lagi tersembunyi di balik gulir. */
    function cardOf(cam) {
        return `
            <div class="rounded-2xl border border-blue-900/50 sk-panel p-4">
                <div class="flex items-start justify-between gap-3">
                    <div class="min-w-0">
                        <div class="font-bold text-white text-sm leading-snug break-words">${cam.nama}</div>
                        <div class="text-[11px] text-slate-500 font-mono mt-0.5">${cam.id}${cam.channel && cam.channel !== '—' ? ' · CH ' + cam.channel : ''}</div>
                    </div>
                    ${statusBadge(cam)}
                </div>
                <div class="mt-3 text-xs text-slate-300 font-semibold">${cam.zona || '—'}</div>
                <div class="text-[11px] text-slate-500">${cam.jalan || '—'}</div>
                <div class="mt-3">${aiBadges(cam)}</div>
                <div class="mt-4 flex items-center gap-2">
                    ${editLink(cam, `${CARD_BTN} ${EDIT_STYLE}`, 'Edit')}
                    ${deleteButton(cam, `${CARD_BTN} ${DEL_STYLE}`, 'Hapus')}
                </div>
            </div>`;
    }

    function paintTable() {
        const rows = filtered();

        if (rows.length === 0) {
            el.tableBody.innerHTML = `
                <tr><td colspan="5" class="px-4 py-12 text-center text-slate-500 text-sm">
                    <i class="fa-solid fa-folder-open text-3xl mb-3 block opacity-50"></i>
                    Tidak ada node yang cocok dengan filter.
                </td></tr>`;
            el.cards.innerHTML = `
                <div class="rounded-2xl border border-blue-900/50 sk-panel px-4 py-12 text-center text-slate-500 text-sm">
                    <i class="fa-solid fa-folder-open text-3xl mb-3 block opacity-50"></i>
                    Tidak ada node yang cocok dengan filter.
                </div>`;
            el.statusText.textContent = 'Tidak ada node yang cocok dengan filter.';
            return;
        }

        el.tableBody.innerHTML = rows.map(cam => `
            <tr class="hover:bg-white/5 transition">
                <td class="px-4 py-4">
                    <div class="font-bold text-white">${cam.nama}</div>
                    <div class="text-[11px] text-slate-500 font-mono">${cam.id}${cam.channel && cam.channel !== '—' ? ' · CH ' + cam.channel : ''}</div>
                </td>
                <td class="px-4 py-4">
                    <div class="text-xs text-slate-300 font-semibold">${cam.zona || '—'}</div>
                    <div class="text-[11px] text-slate-500">${cam.jalan || '—'}</div>
                </td>
                <td class="px-4 py-4">${statusBadge(cam)}</td>
                <td class="px-4 py-4">${aiBadges(cam)}</td>
                <td class="px-4 py-4">
                    <div class="flex justify-end gap-2">
                        ${editLink(cam, `${BASE} w-9 h-9 ${EDIT_STYLE}`)}
                        ${deleteButton(cam, `${BASE} w-9 h-9 ${DEL_STYLE}`)}
                    </div>
                </td>
            </tr>`).join('');

        el.cards.innerHTML = rows.map(cardOf).join('');
        el.statusText.textContent = `Menampilkan ${rows.length} dari ${Store.list().length} node.`;
    }

    /* --- Render ulang ---------------------------------------------------- */
    function refresh() {
        paintSummary();
        paintZoneOptions();
        paintTable();
    }

    /* --- Event ----------------------------------------------------------- */
    el.filterZona.addEventListener('change', paintTable);
    el.filterStatus.addEventListener('change', paintTable);

    async function onDeleteClick(event) {
        const btn = event.target.closest('[data-delete]');
        if (!btn) return;

        const cam = Store.get(btn.dataset.delete);
        if (!cam) return;

        if (!confirm(`Hapus node "${cam.nama}" (${cam.id}) dari direktori?`)) return;

        btn.disabled = true;
        try {
            if (await Store.remove(cam.id)) {
                App.toast(`Node ${cam.id} dihapus.`, 'success');
            } else {
                App.toast('Node gagal dihapus.', 'error');
            }
        } catch (err) {
            App.toast(err.message || 'Node gagal dihapus.', 'error');
        } finally {
            btn.disabled = false;
        }
    }

    el.tableBody.addEventListener('click', onDeleteClick);
    el.cards.addEventListener('click', onDeleteClick);

    el.resetDemo.addEventListener('click', async () => {
        if (!confirm('Kembalikan seluruh data node dan akun ke kondisi demo awal?')) return;
        try {
            await Store.resetDemo();
            Auth.resetDemo();
            App.toast('Data demo dikembalikan. Mengalihkan ke login...', 'info');
            setTimeout(() => { location.href = 'login.html'; }, 1200);
        } catch (err) {
            App.toast(err.message || 'Gagal mereset data demo.', 'error');
        }
    });

    el.logoutBtn.addEventListener('click', () => {
        Auth.logout();
        location.href = 'index.html';
    });

    Store.onChange(refresh);
    Store.onAiChange(paintTable);
    document.addEventListener('auth:change', (event) => {
        if (!event.detail.user) location.replace('login.html');
    });

    paintProfile();
    Store.ready().then(refresh);

    document.addEventListener('store:offline', () => {
        App.toast('Backend tidak dapat dihubungi. Data yang tampil berasal dari cache.', 'error', 5000);
    });
})();
