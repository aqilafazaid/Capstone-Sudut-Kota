/* ==========================================================================
   ADD-DATA.JS — Form registrasi / pembaruan node CCTV
   --------------------------------------------------------------------------
   Satu formulir dipakai untuk dua mode:
     add-data.html            → node baru
     add-data.html?id=cam_XX  → perbarui node yang sudah ada

   Hanya ada satu URL: RTSP. Backend yang mengubahnya menjadi HLS dan
   menurunkan hls_url; frontend tidak pernah menyimpan RTSP di cache.
   ========================================================================== */

(async function () {
    'use strict';

    App.init({ active: 'dashboard' });

    const user = await Auth.requireOperator();
    if (!user) return;

    await Store.ready();

    const params = new URLSearchParams(location.search);
    const editId = params.get('id');
    const editing = !!editId;

    const fields = {
        nama: document.getElementById('f-nama'),
        zona: document.getElementById('f-zona'),
        jalan: document.getElementById('f-jalan'),
        channel: document.getElementById('f-channel'),
        rtsp: document.getElementById('f-rtsp'),
        aktif: document.getElementById('f-aktif')
    };
    const form = document.getElementById('node-form');
    const errorBox = document.getElementById('form-error');
    const submitBtn = form ? form.querySelector('button[type="submit"]') : null;

    /* --- Zona yang sudah ada sebagai saran ------------------------------- */
    const zonaList = document.getElementById('zona-list');
    if (zonaList) {
        zonaList.innerHTML = Store.zones().map(z => `<option value="${z}"></option>`).join('');
    }

    /* --- Mode edit ------------------------------------------------------- */
    if (editing) {
        const cam = Store.get(editId);
        if (!cam) {
            App.toast('Node tidak ditemukan. Kembali ke dashboard.', 'error');
            setTimeout(() => { location.href = 'dashboard.html'; }, 1400);
            return;
        }

        document.getElementById('form-title').textContent = 'Perbarui Konfigurasi Node';
        document.getElementById('form-subtitle').textContent = `Modifikasi data titik ${cam.id}.`;
        document.getElementById('form-icon').className = 'fa-solid fa-pen-ruler';

        fields.nama.value = cam.nama || '';
        fields.zona.value = cam.zona || '';
        fields.jalan.value = cam.jalan || '';
        fields.channel.value = cam.channel && cam.channel !== '—' ? cam.channel : '';
        fields.aktif.checked = !!cam.aktif;

        /* RTSP hanya dikembalikan endpoint detail yang butuh token. Bila token
           belum diisi/dibatalkan, form tetap bisa menyimpan field lain tanpa
           menimpa RTSP lama. */
        try {
            const detail = await Store.fetchDetail(editId);
            fields.rtsp.value = detail.rtsp || '';
        } catch (err) {
            fields.rtsp.placeholder = 'Kosongkan untuk mempertahankan URL lama';
            showError('URL RTSP lama tidak dimuat (' + err.message + '). Isi ulang hanya bila ingin menggantinya.');
        }
    }

    /* --- Validasi -------------------------------------------------------- */
    function showError(message) {
        if (!errorBox) return;
        errorBox.innerHTML = `<i class="fa-solid fa-triangle-exclamation mt-0.5"></i><span>${message}</span>`;
        errorBox.classList.remove('hidden');
    }

    function clearError() {
        if (errorBox) errorBox.classList.add('hidden');
    }

    function validate() {
        if (!fields.nama.value.trim()) return 'Nama titik wajib diisi.';
        if (!fields.zona.value.trim()) return 'Zona wilayah wajib diisi.';

        const rtsp = fields.rtsp.value.trim();
        /* Saat edit, kosong = pertahankan RTSP lama (endpoint PUT parsial). */
        if (!rtsp && editing) return null;

        if (!rtsp) return 'URL RTSP wajib diisi.';

        const allowTest = !!(Store.config() && Store.config().allow_test_sources);
        const pattern = allowTest
            ? /^(rtsps?|https?):\/\//i
            : /^rtsps?:\/\//i;

        if (!pattern.test(rtsp)) {
            return allowTest
                ? 'URL harus diawali rtsp://, rtsps://, http://, atau https://.'
                : 'URL harus diawali rtsp:// atau rtsps://.';
        }

        return null;
    }

    /* --- Simpan ---------------------------------------------------------- */
    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        clearError();

        const problem = validate();
        if (problem) {
            showError(problem);
            return;
        }

        const payload = {
            nama: fields.nama.value.trim(),
            zona: fields.zona.value.trim(),
            jalan: fields.jalan.value.trim(),
            channel: fields.channel.value.trim(),
            kota: fields.zona.value.trim().toUpperCase(),
            aktif: fields.aktif.checked
        };

        const rtsp = fields.rtsp.value.trim();
        if (rtsp) payload.rtsp = rtsp;

        if (editing) {
            payload.id = editId;
            payload.status = payload.aktif ? 'ONLINE' : 'OFFLINE';
        }

        if (submitBtn) submitBtn.disabled = true;
        try {
            const id = await Store.upsert(payload);
            App.toast(editing ? `Node ${id} diperbarui.` : `Node ${id} ditambahkan.`, 'success');
            setTimeout(() => { location.href = 'dashboard.html'; }, 900);
        } catch (err) {
            showError(err.message || 'Gagal menyimpan konfigurasi.');
        } finally {
            if (submitBtn) submitBtn.disabled = false;
        }
    });

    /* --- Petunjuk URL HLS otomatis ---------------------------------------- */
    const autoUrl = document.getElementById('hls-auto-url');

    function refreshAutoUrl() {
        if (!autoUrl) return;
        const digits = (fields.channel.value || '').replace(/\D/g, '');
        const camId = editing ? editId : (digits ? 'cam_' + digits : 'cam_<id>');
        autoUrl.textContent = SK_CONFIG.hlsUrl({ id: camId });
    }

    if (fields.channel) fields.channel.addEventListener('input', refreshAutoUrl);
    refreshAutoUrl();
})();
