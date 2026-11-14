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

    /* Pagar berbasis fitur: peran hanya bawaan, jadi Administrator bisa
       membuka Command Center untuk peran apa pun. */
    const gate = await Auth.guard('dashboard');
    if (!gate.ok) { if (!gate.redirected) App.blocked('dashboard'); return; }
    const user = gate.user;

    const el = {
        initial: document.getElementById('profile-initial'),
        name: document.getElementById('profile-name'),
        role: document.getElementById('profile-role'),
        sumTotal: document.getElementById('sum-total'),
        sumOnline: document.getElementById('sum-online'),
        sumOffline: document.getElementById('sum-offline'),
        sumZones: document.getElementById('sum-zones'),
        filterZona: document.getElementById('filter-zona'),
        filterJalan: document.getElementById('filter-jalan'),
        filterStatus: document.getElementById('filter-status'),
        search: document.getElementById('search-node'),
        bulk: document.getElementById('node-bulk'),
        bulkCount: document.getElementById('node-bulk-count'),
        bulkDelete: document.getElementById('btn-node-bulk-delete'),
        bulkClear: document.getElementById('btn-node-bulk-clear'),
        selectAll: document.getElementById('select-all-nodes'),
        statusText: document.getElementById('status-text-body'),
        tableBody: document.getElementById('node-table-body'),
        cards: document.getElementById('node-cards'),
        trashToggle: document.getElementById('btn-trash-toggle'),
        trashClose: document.getElementById('btn-trash-close'),
        trashPanel: document.getElementById('trash-panel'),
        trashList: document.getElementById('trash-list'),
        trashCount: document.getElementById('trash-count'),
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

    /* Jalan mengikuti zona terpilih (cascade), tetapi tetap bisa dipakai tanpa
       memilih zona lebih dulu: daftarnya lalu memuat semua ruas jalan. */
    function paintRoadOptions() {
        const zona = el.filterZona.value;
        const current = el.filterJalan.value;
        const roads = [...new Set(Store.list()
            .filter(cam => !zona || cam.zona === zona)
            .map(cam => cam.jalan)
            .filter(Boolean))].sort();

        el.filterJalan.innerHTML = '<option value="">Semua Jalan</option>' +
            roads.map(r => `<option value="${r}">${r}</option>`).join('');
        if (roads.includes(current)) el.filterJalan.value = current;
    }

    function filtered() {
        const zona = el.filterZona.value;
        const jalan = el.filterJalan.value;
        const status = el.filterStatus.value;
        const q = el.search.value.trim().toLowerCase();

        return Store.list().filter(cam => {
            if (zona && cam.zona !== zona) return false;
            if (jalan && cam.jalan !== jalan) return false;
            if (status === 'online' && !cam.aktif) return false;
            if (status === 'offline' && cam.aktif) return false;
            if (!q) return true;
            return [cam.nama, cam.id, cam.channel, cam.jalan, cam.zona]
                .some(v => String(v || '').toLowerCase().includes(q));
        });
    }

    /* --- Pilihan baris (sebagian / semua) -------------------------------- */
    const selected = new Set();

    function visibleIds() {
        return filtered().map(cam => cam.id);
    }

    function syncSelection() {
        const ids = visibleIds();
        const jumlah = selected.size;

        el.bulk.classList.toggle('hidden', jumlah === 0);
        el.bulkCount.textContent = jumlah;
        el.bulkDelete.disabled = jumlah === 0;

        const semua = ids.length > 0 && ids.every(id => selected.has(id));
        el.selectAll.checked = semua;
        el.selectAll.indeterminate = !semua && ids.some(id => selected.has(id));

        document.querySelectorAll('[data-select]').forEach(box => {
            box.checked = selected.has(box.dataset.select);
        });
    }

    function clearSelection() {
        selected.clear();
        syncSelection();
    }

    /* --- Tabel ----------------------------------------------------------- */
    function aiBadges(cam) {
        const ai = Store.getAi(cam.id);
        const badges = [];
        badges.push(ai.yolo
            ? `<span class="px-2 py-0.5 rounded bg-yellow-500/15 text-yellow-800 dark:text-yellow-300 border border-yellow-500/30 text-[10px] font-bold">YOLO ${ai.yolo_model}</span>`
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
    const EDIT_STYLE = 'bg-amber-500/15 text-amber-700 dark:text-amber-300 border border-amber-500/40 hover:bg-amber-500 hover:text-white';
    const DEL_STYLE = 'sk-btn-soft-danger';
    const CARD_BTN = `${BASE} flex-1 h-10 gap-2 font-bold text-[11px] uppercase tracking-wider`;

    /* Kartu untuk ponsel: kolom AI dan aksi tidak lagi tersembunyi di balik gulir. */
    function cardOf(cam) {
        return `
            <div class="rounded-2xl border sk-line sk-panel p-4">
                <div class="flex items-start justify-between gap-3">
                    <div class="flex items-start gap-3 min-w-0">
                        <input type="checkbox" data-select="${cam.id}" aria-label="Pilih ${cam.nama}"
                               class="mt-1 h-4 w-4 shrink-0 rounded border-slate-400 text-blue-600 focus:ring-blue-500 cursor-pointer">
                        <div class="min-w-0">
                            <div class="font-bold sk-ink text-sm leading-snug break-words">${cam.nama}</div>
                            <div class="text-[11px] sk-muted font-mono mt-0.5">${cam.id}${cam.channel && cam.channel !== '—' ? ' · CH ' + cam.channel : ''}</div>
                        </div>
                    </div>
                    ${statusBadge(cam)}
                </div>
                <div class="mt-3 text-xs sk-muted font-semibold">${cam.zona || '—'}</div>
                <div class="text-[11px] sk-muted">${cam.jalan || '—'}</div>
                <div class="mt-3">${aiBadges(cam)}</div>
                <div class="mt-4 flex items-center gap-2">
                    ${editLink(cam, `${CARD_BTN} ${EDIT_STYLE}`, 'Edit')}
                    ${deleteButton(cam, `${CARD_BTN} ${DEL_STYLE}`, 'Hapus')}
                </div>
            </div>`;
    }

    function paintTable() {
        const rows = filtered();

        /* Pilihan mengikuti direktori: node yang sudah dihapus/berpindah tidak
           boleh tertinggal di Set dan ikut terkirim saat aksi massal. */
        const ada = new Set(Store.list().map(cam => cam.id));
        [...selected].forEach(id => { if (!ada.has(id)) selected.delete(id); });

        if (rows.length === 0) {
            el.tableBody.innerHTML = `
                <tr><td colspan="6" class="px-4 py-12 text-center sk-muted text-sm">
                    <i class="fa-solid fa-folder-open text-3xl mb-3 block opacity-50"></i>
                    Tidak ada node yang cocok dengan filter.
                </td></tr>`;
            el.cards.innerHTML = `
                <div class="rounded-2xl border sk-line sk-panel px-4 py-12 text-center sk-muted text-sm">
                    <i class="fa-solid fa-folder-open text-3xl mb-3 block opacity-50"></i>
                    Tidak ada node yang cocok dengan filter.
                </div>`;
            el.statusText.textContent = 'Tidak ada node yang cocok dengan filter.';
            syncSelection();
            return;
        }

        el.tableBody.innerHTML = rows.map(cam => `
            <tr class="sk-row-hover">
                <td class="px-4 py-4">
                    <input type="checkbox" data-select="${cam.id}" aria-label="Pilih ${cam.nama}"
                           class="h-4 w-4 rounded border-slate-400 text-blue-600 focus:ring-blue-500 cursor-pointer">
                </td>
                <td class="px-4 py-4">
                    <div class="font-bold sk-ink">${cam.nama}</div>
                    <div class="text-[11px] sk-muted font-mono">${cam.id}${cam.channel && cam.channel !== '—' ? ' · CH ' + cam.channel : ''}</div>
                </td>
                <td class="px-4 py-4">
                    <div class="text-xs sk-muted font-semibold">${cam.zona || '—'}</div>
                    <div class="text-[11px] sk-muted">${cam.jalan || '—'}</div>
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
        syncSelection();
    }

    /* --- Tempat sampah (soft delete) -------------------------------------- */
    let trashItems = [];

    function fmtDeleted(value) {
        if (!value) return '—';
        const date = new Date(value);
        return Number.isNaN(date.getTime())
            ? value
            : date.toLocaleString('id-ID', { dateStyle: 'medium', timeStyle: 'short' });
    }

    function paintTrash() {
        el.trashCount.textContent = trashItems.length;

        if (trashItems.length === 0) {
            el.trashList.innerHTML = `
                <div class="px-4 py-8 text-center sk-muted text-xs">
                    <i class="fa-solid fa-trash-can text-2xl mb-2 block opacity-40"></i>
                    Tempat sampah kosong.
                </div>`;
            return;
        }

        el.trashList.innerHTML = trashItems.map(cam => `
            <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 px-4 py-3">
                <div class="min-w-0">
                    <div class="font-bold sk-ink truncate">${cam.nama}</div>
                    <div class="text-[11px] sk-muted font-mono">${cam.id}${cam.channel ? ' · CH ' + cam.channel : ''}</div>
                    <div class="text-[10px] sk-muted">Dihapus ${fmtDeleted(cam.deleted_at)}</div>
                </div>
                <div class="flex items-center gap-2 shrink-0">
                    <button type="button" data-restore="${cam.id}"
                            class="px-3 h-9 rounded-lg text-[10px] font-black uppercase tracking-wider bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border border-emerald-500/40 hover:bg-emerald-500 hover:text-white transition">
                        <i class="fa-solid fa-rotate-left"></i> Pulihkan
                    </button>
                    <button type="button" data-purge="${cam.id}"
                            class="px-3 h-9 rounded-lg text-[10px] font-black uppercase tracking-wider bg-red-500/15 text-red-700 dark:text-red-300 border border-red-500/40 hover:bg-red-600 hover:text-white transition">
                        <i class="fa-solid fa-trash-can"></i> Hapus permanen
                    </button>
                </div>
            </div>`).join('');
    }

    async function loadTrash() {
        try {
            trashItems = await Store.trash();
        } catch (err) {
            trashItems = [];
            App.toast(err.message || 'Gagal memuat tempat sampah.', 'error');
        }
        paintTrash();
    }

    /* --- Render ulang ---------------------------------------------------- */
    function refresh() {
        paintSummary();
        paintZoneOptions();
        paintRoadOptions();
        paintTable();
        /* Isi tempat sampah berubah setiap kali node dihapus/dipulihkan; tanpa
           ini hitungannya tetap angka lama sampai panel ditutup-buka. */
        loadTrash();
    }

    /* --- Event ----------------------------------------------------------- */
    el.filterZona.addEventListener('change', () => {
        paintRoadOptions();
        paintTable();
    });
    el.filterJalan.addEventListener('change', paintTable);
    el.filterStatus.addEventListener('change', paintTable);
    el.search.addEventListener('input', paintTable);

    function onSelectChange(event) {
        const box = event.target.closest('[data-select]');
        if (!box) return;
        if (box.checked) selected.add(box.dataset.select);
        else selected.delete(box.dataset.select);
        paintTable();
    }

    el.tableBody.addEventListener('change', onSelectChange);
    el.cards.addEventListener('change', onSelectChange);

    el.selectAll.addEventListener('change', () => {
        const ids = visibleIds();
        if (el.selectAll.checked) ids.forEach(id => selected.add(id));
        else ids.forEach(id => selected.delete(id));
        paintTable();
    });

    el.bulkClear.addEventListener('click', clearSelection);

    el.bulkDelete.addEventListener('click', async () => {
        const ids = [...selected];
        if (ids.length === 0) return;
        if (!confirm(`Pindahkan ${ids.length} node terpilih ke tempat sampah?\n\nNode berhenti mengudara dan hilang dari CCTV/statistik. Bisa dipulihkan lewat Tempat sampah.`)) return;

        el.bulkDelete.disabled = true;
        let berhasil = 0;
        const gagal = [];
        for (const id of ids) {
            try {
                const hasil = await Store.remove(id);
                if (hasil) berhasil += 1;
                else gagal.push(id);
            } catch (err) {
                gagal.push(`${id}: ${err.message}`);
            }
        }
        clearSelection();
        refresh();
        App.toast(
            `${berhasil} node dipindah ke tempat sampah` +
            (gagal.length ? `, ${gagal.length} gagal (${gagal[0]})` : '.'),
            gagal.length ? 'error' : 'success',
            gagal.length ? 7000 : undefined
        );
    });

    async function onDeleteClick(event) {
        const btn = event.target.closest('[data-delete]');
        if (!btn) return;

        const cam = Store.get(btn.dataset.delete);
        if (!cam) return;

        if (!confirm(`Pindahkan node "${cam.nama}" (${cam.id}) ke tempat sampah?\n\nNode berhenti mengudara dan hilang dari CCTV/statistik. Bisa dipulihkan lewat tombol Tempat sampah.`)) return;

        btn.disabled = true;
        try {
            const hasil = await Store.remove(cam.id);
            if (hasil) {
                App.toast(`Node ${cam.id} dipindah ke tempat sampah.`, 'success');
                /* Pembersihan RTDB bersifat best-effort (koneksi Firebase bisa
                   putus); kalau ada yang gagal, jangan diam. */
                const sisa = hasil.cleanup && hasil.cleanup.errors ? hasil.cleanup.errors : [];
                if (sisa.length) {
                    App.toast(`Sebagian data Firebase node ini gagal dihapus: ${sisa[0]}`, 'error', 7000);
                }
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

    /* --- Aksi tempat sampah ---------------------------------------------- */
    el.trashToggle.addEventListener('click', async () => {
        const dibuka = el.trashPanel.classList.toggle('hidden') === false;
        if (dibuka) await loadTrash();
    });
    el.trashClose.addEventListener('click', () => el.trashPanel.classList.add('hidden'));

    el.trashList.addEventListener('click', async (event) => {
        const pulih = event.target.closest('[data-restore]');
        const hapus = event.target.closest('[data-purge]');
        if (!pulih && !hapus) return;

        const id = (pulih || hapus).dataset.restore || (pulih || hapus).dataset.purge;
        const cam = trashItems.find(item => item.id === id);
        const nama = cam ? cam.nama : id;

        if (pulih) {
            pulih.disabled = true;
            try {
                const hasil = await Store.restore(id);
                App.toast(`Node ${id} dipulihkan${hasil && hasil.started ? ' dan dinyalakan lagi' : ''}.`, 'success');
                await loadTrash();
            } catch (err) {
                App.toast(err.message || 'Node gagal dipulihkan.', 'error');
            } finally {
                pulih.disabled = false;
            }
            return;
        }

        if (!confirm(`Hapus permanen node "${nama}" (${id})?\n\nKonfigurasi, telemetri, dan SELURUH statistik historis node ini dihapus. Tindakan ini tidak dapat dibatalkan.`)) return;
        hapus.disabled = true;
        try {
            const hasil = await Store.purge(id);
            App.toast(`Node ${id} dihapus permanen.`, 'success');
            const sisa = hasil && hasil.cleanup && hasil.cleanup.errors ? hasil.cleanup.errors : [];
            if (sisa.length) {
                App.toast(`Sebagian data Firebase gagal dihapus: ${sisa[0]}`, 'error', 7000);
            }
            await loadTrash();
        } catch (err) {
            App.toast(err.message || 'Node gagal dihapus permanen.', 'error');
        } finally {
            hapus.disabled = false;
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
    Store.ready().then(() => {
        refresh();
        loadTrash();
    });

    document.addEventListener('store:offline', () => {
        App.toast('Backend tidak dapat dihubungi. Data yang tampil berasal dari cache.', 'error', 5000);
    });
})();
