/* ==========================================================================
   STATISTIK.JS — Halaman statistik + ekspor PDF dan CSV
   --------------------------------------------------------------------------
   Sumber angka: Store.stats(period). Saat Firebase tersambung, cukup ganti
   implementasi Store.stats(); halaman ini tidak perlu disentuh.
   ========================================================================== */

(async function () {
    'use strict';

    App.init({ active: 'statistik' });

    /* Fitur bisa dicabut Administrator; tamu tetap boleh melihat statistik. */
    const viewer = await Auth.ready();
    if (viewer && !Auth.can('statistik')) { App.blocked('statistik'); return; }

    const state = { period: '1d', data: null, volumeChart: null, compositionChart: null };

    const el = {
        rangeLabel: document.getElementById('range-label'),
        source: document.getElementById('stats-source'),
        kpiTotal: document.getElementById('kpi-total'),
        kpiMobil: document.getElementById('kpi-mobil'),
        kpiMotor: document.getElementById('kpi-motor'),
        kpiTruk: document.getElementById('kpi-truk'),
        kpiBus: document.getElementById('kpi-bus'),
        kpiAvg: document.getElementById('kpi-avg'),
        kpiAvgLabel: document.getElementById('kpi-avg-label'),
        kpiPeak: document.getElementById('kpi-peak'),
        kpiPeakLabel: document.getElementById('kpi-peak-label'),
        tableBody: document.getElementById('stats-table-body'),
        tableFoot: document.getElementById('stats-table-foot'),
        tableCount: document.getElementById('table-count'),
        btnPdf: document.getElementById('btn-export-pdf'),
        btnCsv: document.getElementById('btn-export-csv')
    };

    const COLORS = { mobil: '#38bdf8', motor: '#22d3ee', truk: '#fbbf24', bus: '#f97316' };

    /* Kanvas tidak ikut berubah lewat CSS. Warna sumbu, grid, dan tooltip
       dibaca dari token tema setiap kali grafik digambar, lalu grafik
       digambar ulang saat event `theme:change` (lihat App.applyTheme). */
    function themeColors() {
        const css = getComputedStyle(document.documentElement);
        const dark = document.documentElement.classList.contains('dark');
        const pick = (name, fallback) => (css.getPropertyValue(name) || '').trim() || fallback;
        return {
            tick: pick('--sk-text-faint', dark ? '#94a3b8' : '#64748b'),
            legend: pick('--sk-text-muted', dark ? '#94a3b8' : '#475569'),
            grid: dark ? 'rgba(30,58,138,.35)' : 'rgba(148,163,184,.35)',
            tooltipBg: dark ? 'rgba(3,7,24,.95)' : 'rgba(255,255,255,.97)',
            tooltipBorder: dark ? '#1e3a8a' : '#cbd5e1',
            tooltipTitle: dark ? '#ffffff' : '#0f172a',
            tooltipBody: dark ? '#cbd5e1' : '#334155',
            donutBorder: dark ? '#020617' : '#ffffff'
        };
    }

    /* --- Bantu ----------------------------------------------------------- */
    const nf = new Intl.NumberFormat('id-ID');

    function fmt(value) {
        return nf.format(value || 0);
    }

    /** jsPDF memakai font Latin-1: buang karakter di luar itu. */
    function ascii(text) {
        return String(text == null ? '' : text)
            .replace(/[—–]/g, '-')
            .replace(/[^\x20-\x7E]/g, '')
            .trim() || '-';
    }

    /** Jalan diambil dari node; sebagian node tidak punya kolom jalan. */
    function jalanOf(node) {
        const cam = Store.get(node.id);
        return (cam && cam.jalan) || '-';
    }

    function filename(ext) {
        const now = new Date();
        const stamp = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}-${String(now.getHours()).padStart(2, '0')}${String(now.getMinutes()).padStart(2, '0')}`;
        // "Seluruhnya" memuat semua interval; periode lain hanya dirinya sendiri.
        const kunci = state.period === 'all' ? 'lengkap' : state.period;
        return `statistik-sudut-kota-${kunci}-${stamp}.${ext}`;
    }

    function download(blob, name) {
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = name;
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 4000);
    }

    /** Keterangan sumber di kop PDF/CSV mengikuti data yang benar-benar dipakai. */
    function sourceLabel() {
        const info = Store.statsInfo ? Store.statsInfo() : { source: 'simulasi' };
        return info.source === 'firebase'
            ? 'Firebase RTDB (agregat telemetri AI)'
            : 'Simulasi frontend (belum tersambung Firebase)';
    }

    /* --- Render ---------------------------------------------------------- */
    function paintKpi() {
        const s = state.data.summary;
        el.rangeLabel.textContent = state.data.rangeLabel;
        if (el.source) {
            const firebase = state.data.dataSource === 'firebase';
            el.source.textContent = firebase ? 'sumber: Firebase RTDB' : 'data simulasi';
            el.source.className = firebase
                ? 'text-emerald-700 dark:text-emerald-400/90'
                : 'text-amber-700 dark:text-amber-400/80';
        }
        el.kpiTotal.textContent = fmt(s.total);
        el.kpiMobil.textContent = fmt(s.mobil);
        el.kpiMotor.textContent = fmt(s.motor);
        el.kpiTruk.textContent = fmt(s.truk);
        el.kpiBus.textContent = fmt(s.bus);
        el.kpiAvg.textContent = fmt(s.avgPerBucket);
        el.kpiAvgLabel.textContent = state.data.avgLabel;
        el.kpiPeak.textContent = s.peakLabel;
        el.kpiPeakLabel.textContent = state.data.peakLabel;
    }

    function paintTable() {
        const rows = state.data.perNode;

        el.tableCount.textContent = `${rows.length} node`;
        el.tableBody.innerHTML = rows.map(node => `
            <tr class="sk-row-hover">
                <td class="px-4 py-3">
                    <div class="font-bold sk-ink">${node.nama}</div>
                    <div class="text-[11px] sk-muted font-mono">${node.id}</div>
                </td>
                <td class="px-4 py-3 text-xs sk-muted">${node.zona}</td>
                <td class="px-4 py-3 text-right text-sm text-sky-700 dark:text-sky-300 font-semibold">${fmt(node.mobil)}</td>
                <td class="px-4 py-3 text-right text-sm text-cyan-700 dark:text-cyan-300 font-semibold">${fmt(node.motor)}</td>
                <td class="px-4 py-3 text-right text-sm text-amber-700 dark:text-amber-300 font-semibold">${fmt(node.truk)}</td>
                <td class="px-4 py-3 text-right text-sm text-orange-700 dark:text-orange-300 font-semibold">${fmt(node.bus)}</td>
                <td class="px-4 py-3 text-right text-sm text-slate-900 dark:text-white font-black">${fmt(node.total)}</td>
                <td class="px-4 py-3 text-center">
                    ${node.aktif
                        ? '<span class="px-2 py-1 rounded-lg bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border border-emerald-500/30 text-[10px] font-black uppercase tracking-wider">Online</span>'
                        : '<span class="px-2 py-1 rounded-lg bg-red-500/15 text-red-700 dark:text-red-300 border border-red-500/30 text-[10px] font-black uppercase tracking-wider">Offline</span>'}
                </td>
            </tr>`).join('');

        const s = state.data.summary;
        el.tableFoot.innerHTML = `
            <tr>
                <td class="px-4 py-4" colspan="2">Total ${rows.length} node</td>
                <td class="px-4 py-4 text-right">${fmt(s.mobil)}</td>
                <td class="px-4 py-4 text-right">${fmt(s.motor)}</td>
                <td class="px-4 py-4 text-right">${fmt(s.truk)}</td>
                <td class="px-4 py-4 text-right">${fmt(s.bus)}</td>
                <td class="px-4 py-4 text-right text-blue-300">${fmt(s.total)}</td>
                <td></td>
            </tr>`;
    }

    function paintCharts() {
        if (typeof Chart === 'undefined') {
            console.warn('[Statistik] Chart.js tidak tersedia, grafik dilewati.');
            return;
        }

        const buckets = state.data.buckets;
        const theme = themeColors();

        if (state.volumeChart) state.volumeChart.destroy();
        if (state.compositionChart) state.compositionChart.destroy();

        state.volumeChart = new Chart(document.getElementById('chart-volume'), {
            type: 'bar',
            data: {
                labels: buckets.map(b => b.label),
                datasets: [
                    { label: 'Mobil', data: buckets.map(b => b.mobil), backgroundColor: COLORS.mobil, borderRadius: 3, stack: 'v' },
                    { label: 'Motor', data: buckets.map(b => b.motor), backgroundColor: COLORS.motor, borderRadius: 3, stack: 'v' },
                    { label: 'Truk', data: buckets.map(b => b.truk), backgroundColor: COLORS.truk, borderRadius: 3, stack: 'v' },
                    { label: 'Bus', data: buckets.map(b => b.bus), backgroundColor: COLORS.bus, borderRadius: 3, stack: 'v' }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: { duration: 300 },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: theme.tooltipBg,
                        borderColor: theme.tooltipBorder,
                        borderWidth: 1,
                        titleColor: theme.tooltipTitle,
                        bodyColor: theme.tooltipBody
                    }
                },
                scales: {
                    x: {
                        stacked: true,
                        grid: { display: false },
                        ticks: { color: theme.tick, font: { size: 10, weight: '700' }, maxRotation: 0, autoSkip: true }
                    },
                    y: {
                        stacked: true,
                        beginAtZero: true,
                        grid: { color: theme.grid },
                        ticks: { color: theme.tick, font: { size: 10 } }
                    }
                }
            }
        });

        state.compositionChart = new Chart(document.getElementById('chart-composition'), {
            type: 'doughnut',
            data: {
                labels: ['Mobil', 'Motor', 'Truk', 'Bus'],
                datasets: [{
                    data: [
                        state.data.summary.mobil,
                        state.data.summary.motor,
                        state.data.summary.truk,
                        state.data.summary.bus
                    ],
                    backgroundColor: [COLORS.mobil, COLORS.motor, COLORS.truk, COLORS.bus],
                    borderColor: theme.donutBorder,
                    borderWidth: 3
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: '62%',
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: { color: theme.legend, font: { size: 11, weight: '700' }, boxWidth: 10, usePointStyle: true }
                    },
                    tooltip: {
                        backgroundColor: theme.tooltipBg,
                        borderColor: theme.tooltipBorder,
                        borderWidth: 1,
                        callbacks: {
                            label: (ctx) => ` ${ctx.label}: ${fmt(ctx.parsed)}`
                        }
                    }
                }
            }
        });
    }

    function paint() {
        paintKpi();
        paintTable();
        paintCharts();
    }

    function load(period) {
        state.period = period;
        state.data = Store.stats(period);

        document.querySelectorAll('[data-period]').forEach(btn => {
            btn.classList.toggle('is-active', btn.dataset.period === period);
        });

        paint();
    }

    /* --- Ekspor: seluruh interval ---------------------------------------- */

    const PERIOD_KEYS = ['1d', '1w', '1m', '3m', '1y', '5y', 'all'];

    /** Semua interval (dipakai saat periode terpilih = Seluruhnya). */
    function allPeriods() {
        return PERIOD_KEYS.map(key => Store.stats(key));
    }

    /** Isi unduhan mengikuti interval yang sedang dipilih; khusus "Seluruhnya"
        (kunci `all`) tetap memuat semua interval seperti sebelumnya. */
    function exportPeriods() {
        return state.period === 'all' ? allPeriods() : [Store.stats(state.period)];
    }

    /* --- Ekspor CSV ------------------------------------------------------ */
    /* Satu berkas, dipisah baris kosong: ringkasan semua interval lalu satu
       blok per interval (ringkasan, per node, per bucket). Pemisah titik koma
       karena Excel berlokal Indonesia memakai itu; angka ditulis polos supaya
       bisa dihitung ulang. */
    const CSV_SEP = ';';
    const CSV_BOM = '\uFEFF';

    function csvCell(value) {
        const text = value === null || value === undefined ? '' : String(value);
        return /[";\r\n]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text;
    }

    function csvRow(cells) {
        return cells.map(csvCell).join(CSV_SEP);
    }

    function buildCsv() {
        const periods = exportPeriods();
        const out = [];

        out.push(csvRow(['Laporan Statistik Lalu Lintas - Sudut Kota']));
        out.push(csvRow(['Command Center Dishub Kota Pekalongan']));
        out.push(csvRow(['Dibuat', new Date().toLocaleString('id-ID')]));
        out.push(csvRow(['Sumber', sourceLabel()]));
        out.push(csvRow(['Isi', periods.length > 1
            ? 'Semua interval: ' + periods.map(p => p.periodLabel).join(', ')
            : periods[0].periodLabel + ' (' + periods[0].rangeLabel + ')']));
        out.push('');

        /* Ringkasan lintas interval hanya bila berkas memuat lebih dari satu */
        if (periods.length > 1) {
            out.push(csvRow(['RINGKASAN SEMUA INTERVAL']));
            out.push(csvRow(['Interval', 'Rentang', 'Satuan', 'Total', 'Mobil', 'Motor', 'Truk', 'Bus', 'Rata-rata', 'Puncak', 'Node', 'Online']));
            periods.forEach(p => {
                const s = p.summary;
                out.push(csvRow([
                    p.periodLabel, p.rangeLabel, p.bucketName,
                    s.total, s.mobil, s.motor, s.truk, s.bus,
                    s.avgPerBucket, `${s.peakLabel} (${s.peakTotal})`,
                    s.nodes, s.online
                ]));
            });
            out.push('');
        }

        /* Satu blok per interval */
        periods.forEach(p => {
            const s = p.summary;

            out.push(csvRow([`${p.periodLabel.toUpperCase()} - ${p.rangeLabel}`]));
            out.push(csvRow(['Ringkasan', 'Nilai']));
            out.push(csvRow(['Total kendaraan', s.total]));
            out.push(csvRow(['Mobil', s.mobil]));
            out.push(csvRow(['Motor', s.motor]));
            out.push(csvRow(['Truk', s.truk]));
            out.push(csvRow(['Bus', s.bus]));
            out.push(csvRow([p.avgLabel, s.avgPerBucket]));
            out.push(csvRow([p.peakLabel, `${s.peakLabel} (${s.peakTotal})`]));
            out.push(csvRow(['Total node', s.nodes]));
            out.push(csvRow(['Node online', s.online]));
            out.push(csvRow(['Node offline', s.nodes - s.online]));
            out.push('');

            out.push(csvRow(['PER NODE']));
            out.push(csvRow(['ID Node', 'Node', 'Zona', 'Jalan', 'Mobil', 'Motor', 'Truk', 'Bus', 'Total', 'Kontribusi (%)', 'Status']));
            p.perNode.forEach(n => {
                out.push(csvRow([
                    n.id, n.nama, n.zona, jalanOf(n),
                    n.mobil, n.motor, n.truk, n.bus, n.total,
                    s.total ? Math.round((n.total / s.total) * 1000) / 10 : 0,
                    n.aktif ? 'Online' : 'Offline'
                ]));
            });
            out.push(csvRow(['', 'TOTAL', '', '', s.mobil, s.motor, s.truk, s.bus, s.total, 100, '']));
            out.push('');

            out.push(csvRow([`PER ${String(p.bucketName).toUpperCase()}`]));
            out.push(csvRow([p.bucketName, 'Mobil', 'Motor', 'Truk', 'Bus', 'Total']));
            p.buckets.forEach(b => {
                out.push(csvRow([b.label, b.mobil, b.motor, b.truk, b.bus, b.total]));
            });
            out.push(csvRow(['TOTAL', s.mobil, s.motor, s.truk, s.bus, s.total]));
            out.push('');
        });

        return CSV_BOM + out.join('\r\n');
    }

    function exportCsv() {
        try {
            const csv = buildCsv();
            download(new Blob([csv], { type: 'text/csv;charset=utf-8' }), filename('csv'));
            App.toast('CSV dibuat: ringkasan + 7 blok interval.', 'success');
        } catch (err) {
            console.error('[Statistik] Ekspor CSV gagal', err);
            App.toast('Ekspor CSV gagal: ' + err.message, 'error');
        }
    }

    /* --- KOP laporan ------------------------------------------------------ */
    /* Ubah di sini bila identitas instansi berubah; seluruh kop mengikuti. */
    const KOP = {
        instansi: 'PEMERINTAH KOTA PEKALONGAN',
        dinas: 'DINAS PERHUBUNGAN',
        alamat: 'Jl. Seruni No. 66, Kota Pekalongan, Jawa Tengah',
        kontak: 'Email: dishub.pekalongankota@gmail.com   Instagram: @dishub_kotapekalongan   Telp. (0285) 421600',
        kota: 'Kota Pekalongan'
    };

    const LOGO_PEMKOT = 'asset/logo-pemkot.svg';
    const LOGO_DISHUB = 'asset/logo-dishub.svg';

    /**
     * jsPDF tidak bisa menanam SVG, jadi tiap logo digambar ke canvas dulu
     * (raster 512 px, latar transparan) lalu dikirim sebagai PNG.
     */
    /** Potong tepi transparan sebuah canvas; kembalikan canvas baru. */
    function trimTransparent(canvas) {
        const w = canvas.width;
        const h = canvas.height;
        const data = canvas.getContext('2d').getImageData(0, 0, w, h).data;

        let top = h, left = w, right = -1, bottom = -1;
        for (let y = 0; y < h; y += 1) {
            for (let x = 0; x < w; x += 1) {
                if (data[(y * w + x) * 4 + 3] > 8) {
                    if (y < top) top = y;
                    if (y > bottom) bottom = y;
                    if (x < left) left = x;
                    if (x > right) right = x;
                }
            }
        }
        if (right < left || bottom < top) return canvas; // kosong: biarkan apa adanya

        const cw = right - left + 1;
        const ch = bottom - top + 1;
        const out = document.createElement('canvas');
        out.width = cw;
        out.height = ch;
        out.getContext('2d').drawImage(canvas, left, top, cw, ch, 0, 0, cw, ch);
        return out;
    }

    function svgToPng(url, tinggiPx) {
        return new Promise((resolve) => {
            const img = new Image();
            img.onload = () => {
                const natW = img.naturalWidth || 1;
                const natH = img.naturalHeight || 1;

                // Canvas dibuat setinggi target dan selebar rasio asli SVG.
                // Kalau canvas dipaksa persegi, margin transparan ikut tertarik
                // saat ditempel di PDF dan logonya terlihat gepeng.
                const h = tinggiPx || 512;
                const w = Math.max(1, Math.round(h * (natW / natH)));

                const canvas = document.createElement('canvas');
                canvas.width = w;
                canvas.height = h;
                canvas.getContext('2d').drawImage(img, 0, 0, w, h);

                // Buang margin transparan: banyak SVG lambang punya ruang kosong
                // di dalam viewBox-nya, sehingga logo tampak kecil dan menjorok
                // dari tepi margin kop.
                const tight = trimTransparent(canvas);

                resolve({ dataUrl: tight.toDataURL('image/png'), ratio: tight.width / tight.height });
            };
            img.onerror = () => resolve(null);
            img.src = url;
        });
    }

    async function loadLogos() {
        const [pemkot, dishub] = await Promise.all([svgToPng(LOGO_PEMKOT), svgToPng(LOGO_DISHUB)]);
        if (!pemkot || !dishub) {
            console.warn('[Statistik] Logo kop gagal dimuat; kop dicetak tanpa logo.');
        }
        return { pemkot, dishub };
    }

    /* --- Ekspor PDF ------------------------------------------------------ */
    async function buildPdf() {
        if (!window.jspdf || !window.jspdf.jsPDF) throw new Error('Pustaka jsPDF belum termuat.');

        const periods = exportPeriods();
        const selected = state.data || periods[0];

        /* F4 / Folio Indonesia: 215 x 330 mm */
        const doc = new window.jspdf.jsPDF({ unit: 'mm', format: [215, 330], orientation: 'portrait' });
        const M = 15;
        const W = 185;
        const BOTTOM = 320;

        /* Kursor Y eksplisit: gambar tidak mengubah doc.lastAutoTable. */
        let cursor = 0;

        const heading = (text, y, size) => {
            doc.setFont('helvetica', 'bold');
            doc.setFontSize(size || 11);
            doc.setTextColor(20, 30, 60);
            doc.text(text, M, y);
        };

        const ensure = (space) => {
            if (cursor > 0 && cursor + space > BOTTOM) {
                doc.addPage();
                cursor = 20;
            }
        };

        /* ---------------- KOP ---------------- */
        const logos = await loadLogos();

        const LOGO_BOX = 20;
        const logoY = 13;
        const centre = M + W / 2;

        if (logos.pemkot) {
            const w = LOGO_BOX * (logos.pemkot.ratio || 1);
            const h = LOGO_BOX;
            doc.addImage(logos.pemkot.dataUrl, 'PNG', M, logoY, w, h, 'kop-pemkot', 'FAST');
        }
        if (logos.dishub) {
            const w = LOGO_BOX * (logos.dishub.ratio || 1);
            const h = LOGO_BOX;
            doc.addImage(logos.dishub.dataUrl, 'PNG', M + W - w, logoY, w, h, 'kop-dishub', 'FAST');
        }

        doc.setTextColor(17, 17, 17);
        doc.setFont('helvetica', 'normal');
        doc.setFontSize(12);
        doc.text(ascii(KOP.instansi), centre, 20.5, { align: 'center' });

        doc.setFont('helvetica', 'bold');
        doc.setFontSize(15);
        doc.text(ascii(KOP.dinas), centre, 27.5, { align: 'center' });

        doc.setFont('helvetica', 'normal');
        doc.setFontSize(7.5);
        doc.text(ascii(KOP.alamat), centre, 33, { align: 'center' });
        doc.text(ascii(KOP.kontak), centre, 37.5, { align: 'center' });

        /* Garis tebal pemisah kop */
        doc.setDrawColor(0, 0, 0);
        doc.setLineWidth(0.9);
        doc.line(M, 41.5, M + W, 41.5);

        /* Identitas laporan */
        doc.setFont('helvetica', 'bold');
        doc.setFontSize(13.5);
        doc.setTextColor(20, 30, 60);
        doc.text('Laporan Statistik Lalu Lintas', M, 50);

        doc.setFont('helvetica', 'normal');
        doc.setFontSize(8.5);
        doc.setTextColor(105, 115, 135);
        doc.text('Sudut Kota - Command Center Dinas Perhubungan ' + ascii(KOP.kota), M, 55.5);
        doc.text('Dibuat: ' + ascii(new Date().toLocaleString('id-ID')) + '   |   Sumber: ' + ascii(sourceLabel()), M, 60);
        doc.text('Isi: ' + (periods.length > 1
            ? 'seluruh interval - ' + ascii(periods.map(p => p.periodLabel).join(', '))
            : ascii(periods[0].periodLabel) + ' (' + ascii(periods[0].rangeLabel) + ')'), M, 64.5);

        /* ---------------- RINGKASAN LINTAS INTERVAL ---------------- */
        /* Hanya muncul saat berkas memuat semua interval ("Seluruhnya"). */
        if (periods.length > 1) {
            heading('Ringkasan Semua Interval', 73);

            doc.autoTable({
                startY: 77,
                head: [['Interval', 'Rentang', 'Total', 'Mobil', 'Motor', 'Truk', 'Bus', 'Rata-rata', 'Puncak']],
                body: periods.map(p => [
                    ascii(p.periodLabel), ascii(p.rangeLabel),
                    fmt(p.summary.total), fmt(p.summary.mobil), fmt(p.summary.motor),
                    fmt(p.summary.truk), fmt(p.summary.bus), fmt(p.summary.avgPerBucket),
                    ascii(p.summary.peakLabel) + ' (' + fmt(p.summary.peakTotal) + ')'
                ]),
                theme: 'grid',
                headStyles: { fillColor: [37, 99, 235], fontSize: 7.5, cellPadding: 1.8 },
                bodyStyles: { fontSize: 7.5, cellPadding: 1.6 },
                columnStyles: {
                    0: { cellWidth: 24 },
                    1: { cellWidth: 55 },
                    2: { halign: 'right' }, 3: { halign: 'right' }, 4: { halign: 'right' },
                    5: { halign: 'right' }, 6: { halign: 'right' }, 7: { halign: 'right' },
                    8: { halign: 'right' }
                },
                margin: { left: M, right: M },
                tableWidth: W
            });

            cursor = doc.lastAutoTable.finalY;
        } else {
            cursor = 72;
        }

        /* ---------------- GRAFIK periode terpilih ---------------- */
        const barCanvas = document.getElementById('chart-volume');
        const donutCanvas = document.getElementById('chart-composition');

        /* Canvas kosong terjadi bila tab sedang tidak aktif (animasi Chart.js
           memakai requestAnimationFrame yang dijeda). update('none') menggambar
           ulang tanpa animasi supaya ekspor tetap berisi grafik. */
        const hasPixels = (canvas) => {
            const data = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
            for (let i = 3; i < data.length; i += 4) {
                if (data[i]) return true;
            }
            return false;
        };

        const chartImage = (canvas) => {
            if (!canvas) return null;
            const inst = window.Chart ? window.Chart.getChart(canvas) : null;

            if (inst) {
                try { inst.update('none'); } catch (err) { /* diabaikan */ }
                // update('none') belum tentu menggambar bila tab tidak aktif;
                // draw() menulis langsung ke canvas tanpa requestAnimationFrame.
                if (!hasPixels(canvas)) {
                    try { inst.draw(); } catch (err) { /* diabaikan */ }
                }
            }

            if (!hasPixels(canvas)) {
                console.warn('[Statistik] Grafik kosong, dilewati saat ekspor PDF.');
                return null;
            }
            return canvas.toDataURL('image/png', 1.0);
        };

        if (barCanvas) {
            ensure(30);
            const chartY = cursor + 9;
            heading('Grafik periode terpilih: ' + ascii(selected.periodLabel) + ' (per ' + ascii(selected.bucketName) + ')', chartY, 9.5);

            const imgH = Math.min(W * (barCanvas.height / barCanvas.width), 92);
            const barImg = chartImage(barCanvas);
            if (barImg) {
                doc.addImage(barImg, 'PNG', M, chartY + 4, W, imgH);
                cursor = chartY + 4 + imgH;
            } else {
                cursor = chartY + 6;
            }

            if (donutCanvas) {
                const donutW = 62;
                const donutH = Math.min(donutW * (donutCanvas.height / donutCanvas.width), 58);
                const donutImg = chartImage(donutCanvas);
                if (donutImg && cursor + 14 + donutH <= BOTTOM) {
                    heading('Komposisi jenis kendaraan', cursor + 10, 9.5);
                    doc.addImage(donutImg, 'PNG', M, cursor + 14, donutW, donutH);
                    cursor = cursor + 14 + donutH;
                }
            }
        }

        /* ---------------- DETAIL PER INTERVAL ---------------- */
        periods.forEach(p => {
            const s = p.summary;

            ensure(80);
            const titleY = cursor + 9;
            heading(ascii(p.periodLabel) + '  -  ' + ascii(p.rangeLabel), titleY, 11);

            doc.setFont('helvetica', 'normal');
            doc.setFontSize(8);
            doc.setTextColor(90, 100, 120);
            doc.text(
                `Total ${fmt(s.total)} | Mobil ${fmt(s.mobil)} | Motor ${fmt(s.motor)} | Truk ${fmt(s.truk)} | Bus ${fmt(s.bus)} | ` +
                `${ascii(p.avgLabel)} ${fmt(s.avgPerBucket)} | ${ascii(p.peakLabel)} ${ascii(s.peakLabel)} (${fmt(s.peakTotal)})`,
                M, titleY + 5
            );

            doc.autoTable({
                startY: titleY + 8,
                head: [['Node', 'Zona', 'Mobil', 'Motor', 'Truk', 'Bus', 'Total', 'Status']],
                body: p.perNode.map(n => [
                    ascii(n.nama), ascii(n.zona),
                    fmt(n.mobil), fmt(n.motor), fmt(n.truk), fmt(n.bus), fmt(n.total),
                    n.aktif ? 'Online' : 'Offline'
                ]),
                foot: [['TOTAL', '', fmt(s.mobil), fmt(s.motor), fmt(s.truk), fmt(s.bus), fmt(s.total), '']],
                theme: 'striped',
                headStyles: { fillColor: [37, 99, 235], fontSize: 7, cellPadding: 1.5 },
                footStyles: { fillColor: [15, 23, 42], fontSize: 7, textColor: [255, 255, 255], cellPadding: 1.5 },
                bodyStyles: { fontSize: 7, cellPadding: 1.3 },
                columnStyles: {
                    0: { cellWidth: 50 }, 1: { cellWidth: 38 },
                    2: { halign: 'right' }, 3: { halign: 'right' }, 4: { halign: 'right' },
                    5: { halign: 'right' }, 6: { halign: 'right', fontStyle: 'bold' },
                    7: { cellWidth: 16, halign: 'center' }
                },
                margin: { left: M, right: M },
                tableWidth: W
            });

            cursor = doc.lastAutoTable.finalY;
            ensure(34);

            doc.autoTable({
                startY: cursor + 4,
                head: [[ascii(p.bucketName), 'Mobil', 'Motor', 'Truk', 'Bus', 'Total']],
                body: p.buckets.map(b => [ascii(b.label), fmt(b.mobil), fmt(b.motor), fmt(b.truk), fmt(b.bus), fmt(b.total)]),
                foot: [['TOTAL', fmt(s.mobil), fmt(s.motor), fmt(s.truk), fmt(s.bus), fmt(s.total)]],
                theme: 'grid',
                headStyles: { fillColor: [30, 58, 138], fontSize: 7.5, cellPadding: 1.5 },
                footStyles: { fillColor: [15, 23, 42], fontSize: 7.5, textColor: [255, 255, 255], cellPadding: 1.5 },
                bodyStyles: { fontSize: 7.5, cellPadding: 1.3 },
                columnStyles: {
                    0: { cellWidth: 45 },
                    1: { halign: 'right' }, 2: { halign: 'right' }, 3: { halign: 'right' },
                    4: { halign: 'right' }, 5: { halign: 'right', fontStyle: 'bold' }
                },
                margin: { left: M, right: M },
                tableWidth: W
            });

            cursor = doc.lastAutoTable.finalY;
        });

        /* ---------------- FOOTER ---------------- */
        const pages = doc.getNumberOfPages();
        for (let page = 1; page <= pages; page += 1) {
            doc.setPage(page);
            doc.setFont('helvetica', 'normal');
            doc.setFontSize(7.5);
            doc.setTextColor(140, 148, 165);
            doc.text('Sudut Kota - Laporan Statistik Lalu Lintas (semua interval)', M, BOTTOM + 4);
            doc.text(`Halaman ${page} dari ${pages}`, M + W, BOTTOM + 4, { align: 'right' });
        }

        return doc;
    }

    async function exportPdf() {
        try {
            App.toast('Menyiapkan PDF semua interval...', 'info', 1500);
            // buildPdf menunggu logo kop (SVG -> canvas) sebelum menggambar.
            const doc = await buildPdf();
            doc.save(filename('pdf'));
            App.toast('PDF F4 dibuat: semua interval.', 'success');
        } catch (err) {
            console.error('[Statistik] Ekspor PDF gagal', err);
            App.toast('Ekspor PDF gagal: ' + err.message, 'error');
        }
    }

    /* --- Event ----------------------------------------------------------- */
    document.querySelectorAll('[data-period]').forEach(btn => {
        btn.addEventListener('click', () => load(btn.dataset.period));
    });

    if (el.btnPdf) el.btnPdf.addEventListener('click', exportPdf);
    if (el.btnCsv) el.btnCsv.addEventListener('click', exportCsv);

    Store.onChange(() => {
        Store.loadStats(true).then(() => load(state.period));
    });

    /* Tema berubah → warna kanvas harus digambar ulang. */
    document.addEventListener('theme:change', () => {
        if (state.data) paintCharts();
    });

    /* Render simulasi dulu agar halaman tidak pernah kosong, lalu ganti dengan
       agregat Firebase bila tersedia. */
    Store.ready()
        .then(() => {
            load('1d');
            return Store.loadStats();
        })
        .then(() => load(state.period))
        .catch((err) => {
            console.warn('[Statistik] Gagal memuat data:', err);
            if (!state.data) load('1d');
        });

    /* Hook untuk pengujian otomatis dan pemakaian dari konsol. */
    window.Statistik = {
        reload: load,
        getData: () => state.data,
        buildPdf,
        buildCsv,
        exportPdf,
        exportCsv
    };
})();
