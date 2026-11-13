/* ==========================================================================
   APP.JS — Kerangka halaman bersama
   --------------------------------------------------------------------------
   Menyuntikkan navbar, footer, bottom bar, dan loader ke setiap halaman
   statis supaya markup tidak disalin 7 kali. Juga menangani tema gelap,
   sapaan + jam, ticker, dan notifikasi toast.

   Navbar memakai tinggi tetap (h-16 / h-20). app.js mengukur tinggi
   sebenarnya dan mempublikasikannya sebagai --sk-nav-h supaya <main> tidak
   pernah tertutup, berapa pun rasionya.
   ========================================================================== */

(function (global) {
    'use strict';

    const THEME_KEY = 'color-theme';

    const TICKER_TEXT = [
        'SELAMAT DATANG DI COMMAND CENTER SUDUT KOTA',
        'SISTEM INI MENGGUNAKAN DETEKSI OBJEK YOLOv8 UNTUK MENGKLASIFIKASI KENDARAAN',
        'DILENGKAPI DEEP LEARNING MIRNET DAN ZERO-DCE UNTUK MENJERNIHKAN GAMBAR MALAM',
        'DILARANG MELAKUKAN TANGKAPAN LAYAR UNTUK KEPENTINGAN YANG MELANGGAR UU PRIVASI DAN ITE',
        'PASTIKAN KONEKSI INTERNET STABIL AGAR STREAMING HLS BERJALAN LANCAR'
    ].join('   //   ');

    const LOGO = 'asset/logo-suko.png';
    const LOGO_96 = 'asset/logo-suko-96.png';

    /* Urutan `mobile` menentukan posisi pada bottom bar ponsel; CCTV sengaja
       di tengah (slot ke-3) seperti tombol utama di aplikasi media sosial.
       `feature` dihubungkan ke izin per akun (lihat Auth.can). */
    const NAV_LINKS = [
        { key: 'home', href: 'index.html', label: 'Beranda', icon: 'fa-house', short: 'Home', mobile: 1, feature: null },
        { key: 'cctv', href: 'cctv.html', label: 'CCTV Live', icon: 'fa-video', short: 'CCTV', mobile: 3, center: true, feature: 'cctv' },
        { key: 'statistik', href: 'statistik.html', label: 'Statistik', icon: 'fa-chart-column', short: 'Statistik', mobile: 2, feature: 'statistik' },
        { key: 'dashboard', href: 'dashboard.html', label: 'Dashboard', icon: 'fa-chart-pie', short: 'Dashboard', mobile: 4, feature: 'dashboard' },
        { key: 'akun', href: 'akun.html', label: 'Akun', icon: 'fa-user-shield', short: 'Akun', mobile: 5, feature: 'akun' }
    ];

    /* Fitur yang juga terbuka untuk tamu (belum login). */
    const PUBLIC_FEATURES = ['cctv', 'statistik'];

    /* --- Tema ------------------------------------------------------------ */
    function applyTheme(mode) {
        const dark = mode === 'dark';
        document.documentElement.classList.toggle('dark', dark);
        document.documentElement.style.colorScheme = dark ? 'dark' : 'light';
        document.querySelectorAll('#theme-toggle-dark-icon').forEach(el => el.classList.toggle('hidden', !dark));
        document.querySelectorAll('#theme-toggle-light-icon').forEach(el => el.classList.toggle('hidden', dark));
        /* Kanvas grafik dan elemen yang digambar lewat JS tidak ikut berubah
           lewat CSS; mereka mendengarkan event ini untuk menggambar ulang. */
        document.dispatchEvent(new CustomEvent('theme:change', { detail: { theme: dark ? 'dark' : 'light' } }));
    }

    function currentTheme() {
        // Bawaan gelap; terang hanya bila pengguna memilihnya.
        return localStorage.getItem(THEME_KEY) === 'light' ? 'light' : 'dark';
    }

    function toggleTheme() {
        const next = document.documentElement.classList.contains('dark') ? 'light' : 'dark';
        localStorage.setItem(THEME_KEY, next);
        applyTheme(next);
    }

    /* --- Toast ----------------------------------------------------------- */
    function ensureToastStack() {
        let stack = document.getElementById('toast-stack');
        if (!stack) {
            stack = document.createElement('div');
            stack.id = 'toast-stack';
            document.body.appendChild(stack);
        }
        return stack;
    }

    function toast(message, type, timeout) {
        const stack = ensureToastStack();
        const palette = { success: 'fa-circle-check', error: 'fa-triangle-exclamation', info: 'fa-circle-info' };
        const kind = palette[type] ? type : 'info';

        const el = document.createElement('div');
        el.className = `toast ${kind}`;
        el.innerHTML = `<i class="fa-solid ${palette[kind]} mt-0.5"></i><span class="flex-1">${message}</span>`;
        stack.appendChild(el);

        setTimeout(() => {
            el.style.transition = 'opacity .25s, transform .25s';
            el.style.opacity = '0';
            el.style.transform = 'translateX(30px)';
            setTimeout(() => el.remove(), 260);
        }, timeout || 3800);
    }

    /* --- Navigasi -------------------------------------------------------- */
    /* Sebelum Firebase selesai memulihkan sesi, jangan tampilkan tombol
       "Masuk": pengguna yang sudah login akan melihat seolah sesinya hilang.
       Placeholder netral lebih jujur daripada status yang salah. */
    function userChipMarkup() {
        const auth = global.Auth;
        if (auth && !auth.isReady()) {
            return '<span aria-hidden="true" class="block w-9 h-9 rounded-full bg-slate-200 dark:bg-white/10 animate-pulse"></span>';
        }
        const user = auth ? auth.user() : null;

        if (!user) {
            return `<a href="login.html" title="Masuk" aria-label="Masuk"
                       class="flex items-center gap-2 px-2.5 sm:px-4 h-9 rounded-full bg-blue-600 hover:bg-blue-500 text-white text-[11px] font-display font-bold uppercase tracking-wider transition shadow-[0_0_15px_rgba(37,99,235,0.35)]">
                        <i class="fa-solid fa-right-to-bracket"></i><span class="hidden sm:inline">Masuk</span>
                    </a>`;
        }

        const roleLabel = global.Auth.roleLabel(user.role);
        const isOperator = user.role === 'admin' || user.role === 'teknisi';
        return `
            <div class="flex items-center gap-2">
                <div class="hidden xl:flex flex-col items-end leading-tight">
                    <span class="text-[11px] font-black text-slate-800 dark:text-white truncate max-w-[140px]">${user.nama}</span>
                    <span class="text-[10px] font-bold ${isOperator ? 'text-blue-600 dark:text-blue-400' : 'text-amber-600 dark:text-amber-400'} uppercase tracking-wider">${roleLabel}</span>
                </div>
                <div class="w-9 h-9 rounded-full bg-gradient-to-br from-blue-600 to-blue-800 text-white flex items-center justify-center font-black text-sm border border-blue-400/40" title="${user.nama}">
                    ${(user.nama || '?').charAt(0).toUpperCase()}
                </div>
                <button type="button" id="btn-logout" title="Keluar" aria-label="Keluar"
                    class="hidden lg:flex w-9 h-9 rounded-full bg-slate-100 dark:bg-white/10 text-slate-600 dark:text-white hover:bg-red-600 hover:text-white transition items-center justify-center">
                    <i class="fa-solid fa-door-open text-xs"></i>
                </button>
            </div>`;
    }

    /** Dashboard: admin + teknisi. Akun: hanya Administrator — lalu `akses`. */
    function canSee(link) {
        if (!link.feature) return true;

        const auth = global.Auth;
        const isPublic = PUBLIC_FEATURES.indexOf(link.feature) >= 0;

        if (!auth) return isPublic;
        /* Sebelum sesi diketahui, sembunyikan hanya yang memang butuh peran. */
        if (!auth.isReady()) return isPublic;
        /* Tamu tidak punya `akses`; fitur publik tetap terbuka untuknya. */
        if (!auth.user()) return isPublic;

        return auth.can(link.feature);
    }

    function desktopLinksMarkup(active) {
        return NAV_LINKS.filter(canSee).map(link => {
            const isActive = link.key === active;
            const cls = isActive
                ? 'text-blue-600 dark:text-white bg-blue-50 dark:bg-white/10'
                : 'text-slate-600 dark:text-slate-300 hover:text-blue-600 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-white/10';
            return `<a href="${link.href}" class="font-display font-bold text-[11px] uppercase tracking-wider px-2.5 xl:px-4 py-2 rounded-full transition-all ${cls}">${link.label}</a>`;
        }).join('');
    }

    function mobileLinksMarkup(active) {
        const links = NAV_LINKS.filter(canSee).map(link => `
            <a href="${link.href}" class="px-3 py-2.5 rounded-xl hover:bg-slate-100 dark:hover:bg-blue-900/30 font-bold text-slate-700 dark:text-slate-200 flex items-center gap-3 ${
                link.key === active ? 'bg-blue-50 dark:bg-blue-900/40 text-blue-600 dark:text-white' : ''
            }">
                <i class="fa-solid ${link.icon} w-5 text-blue-500"></i> ${link.label}
            </a>`).join('');

        const user = global.Auth ? global.Auth.user() : null;
        const account = user ? `
            <button type="button" data-logout class="px-3 py-2.5 rounded-xl hover:bg-red-50 dark:hover:bg-red-900/30 font-bold text-red-600 dark:text-red-400 flex items-center gap-3">
                <i class="fa-solid fa-door-open w-5"></i> Keluar
            </button>` : `
            <a href="login.html" class="px-3 py-2.5 rounded-xl bg-blue-600 text-white font-bold flex items-center gap-3">
                <i class="fa-solid fa-right-to-bracket w-5"></i> Masuk
            </a>`;

        return links + account;
    }

    /* Pencarian hanya dirender sekali per halaman. Di layar kecil kolom
       navbar tidak cukup, jadi input dipindah ke panel menu; nilai yang
       diketik disalin ke input desktop supaya main.js tetap punya satu
       sumber (id search-input) untuk didengarkan. */
    function searchMarkup(variant) {
        if (variant === 'mobile') {
            return `
                <div class="relative mb-1">
                    <i class="fa-solid fa-magnifying-glass absolute left-4 top-1/2 -translate-y-1/2 text-slate-400 text-sm"></i>
                    <input id="search-input-mobile" type="text" autocomplete="off" placeholder="Cari lokasi simpang / tiang..."
                           class="w-full bg-slate-100 dark:bg-[#050a1f] border border-slate-300 dark:border-blue-900/60 text-slate-800 dark:text-white text-sm rounded-xl py-3 pl-11 pr-4 font-semibold focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500 transition placeholder:text-slate-500">
                </div>`;
        }
        return `
            <div class="hidden md:block flex-1 min-w-0 max-w-md mx-2 lg:mx-4">
                <div class="relative group">
                    <i class="fa-solid fa-magnifying-glass absolute left-4 top-1/2 -translate-y-1/2 text-slate-400 group-focus-within:text-blue-500 text-sm"></i>
                    <input id="search-input" type="text" autocomplete="off"
                           placeholder="Cari lokasi simpang / tiang..."
                           class="w-full bg-slate-100 dark:bg-[#050a1f] border border-slate-300 dark:border-blue-900/60 text-slate-800 dark:text-white text-sm rounded-full py-2.5 pl-11 pr-4 font-semibold focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500 transition placeholder:text-slate-500">
                </div>
            </div>`;
    }

    /* Panel menu dirender ulang setiap kali status auth berubah; input
       pencariannya ikut dirender ulang, jadi pendengar harus dipasang lagi. */
    function bindMobileSearch() {
        const mobileSearch = document.getElementById('search-input-mobile');
        const mainSearch = document.getElementById('search-input');
        if (!mobileSearch || !mainSearch) return;

        mobileSearch.addEventListener('input', () => {
            mainSearch.value = mobileSearch.value;
            mainSearch.dispatchEvent(new Event('input', { bubbles: true }));
        });
    }

    function clockMarkup() {
        return `
            <div class="hidden min-[430px]:flex glass-pill px-2.5 sm:px-3 py-1.5 rounded-full items-center gap-2 shrink-0">
                <i class="greeting-icon fa-solid fa-sun text-yellow-500 text-[10px]"></i>
                <span class="greeting-text hidden xl:inline font-display font-bold text-[10px] text-slate-600 dark:text-slate-300 uppercase tracking-wider">Memuat...</span>
                <span class="hidden xl:block h-3.5 w-px bg-slate-300 dark:bg-slate-600"></span>
                <span class="flex items-center gap-1.5">
                    <i class="fa-regular fa-clock text-blue-600 dark:text-blue-400 text-[10px]"></i>
                    <span data-clock="full" class="hidden md:inline realtime-clock font-mono font-bold text-[10px] text-[#0a143c] dark:text-white tracking-widest">00:00:00 WIB</span>
                    <span data-clock="short" class="md:hidden realtime-clock font-mono font-bold text-[10px] text-[#0a143c] dark:text-white tracking-widest">00:00 WIB</span>
                </span>
            </div>`;
    }

    function navbarMarkup(active, withSearch) {
        return `
        <nav class="fixed top-0 inset-x-0 z-50 bg-white/85 dark:bg-[#0a143c]/90 backdrop-blur-xl border-b border-slate-200 dark:border-white/5 shadow-[0_4px_30px_rgba(0,0,0,0.04)] transition-colors duration-300">
            <div class="sk-shell h-16 md:h-20 flex items-center justify-between gap-2 md:gap-3">
                <a href="index.html" title="Beranda" aria-label="Beranda — Sudut Kota"
                   class="group flex items-center gap-2 md:gap-3 min-w-0 shrink">
                    <img src="${LOGO}"
                         srcset="${LOGO_96} 96w, ${LOGO} 256w"
                         sizes="44px" width="44" height="44" alt=""
                         class="h-8 w-8 sm:h-9 sm:w-9 md:h-11 md:w-11 rounded-full object-contain shrink-0 ${active === 'home' ? 'ring-2 ring-blue-500/60' : ''}">
                    <span class="hidden sm:block h-7 md:h-9 w-px bg-slate-200 dark:bg-slate-700 shrink-0"></span>
                    <span class="flex flex-col justify-center min-w-0">
                        <span class="font-display font-black text-sm sm:text-base md:text-xl text-[#0a143c] dark:text-white leading-none tracking-tight whitespace-nowrap">SUDUT<span class="hidden min-[380px]:inline"> KOTA</span></span>
                        <span class="hidden sm:block text-[7px] md:text-[9px] font-bold text-slate-500 dark:text-slate-400 uppercase tracking-[0.14em] md:tracking-[0.18em] mt-1 truncate">Dinas Perhubungan Kota Pekalongan</span>
                    </span>
                </a>

                ${withSearch ? searchMarkup() : ''}

                <div class="flex items-center gap-1.5 md:gap-2 shrink-0">
                    <div id="nav-links" class="hidden lg:flex items-center gap-0.5 xl:gap-1">${desktopLinksMarkup(active)}</div>
                    <span class="hidden lg:block h-6 w-px bg-slate-200 dark:bg-slate-700"></span>
                    ${clockMarkup()}
                    <button id="theme-toggle" type="button" aria-label="Ganti tema"
                            class="w-9 h-9 rounded-full bg-slate-100 dark:bg-white/10 text-slate-600 dark:text-white flex items-center justify-center transition-all hover:bg-slate-200 dark:hover:bg-white/20 active:scale-95 shrink-0">
                        <i id="theme-toggle-dark-icon" class="hidden fa-solid fa-moon text-[13px]"></i>
                        <i id="theme-toggle-light-icon" class="hidden fa-solid fa-sun text-[13px] text-yellow-400"></i>
                    </button>
                    <div id="nav-user" class="flex items-center">${userChipMarkup()}</div>
                    <button type="button" id="btn-mobile-menu" aria-label="Menu" aria-expanded="false"
                            class="lg:hidden w-9 h-9 rounded-full bg-slate-100 dark:bg-white/10 text-slate-700 dark:text-white flex items-center justify-center transition hover:bg-slate-200 dark:hover:bg-white/20 shrink-0">
                        <i class="fa-solid fa-bars text-[13px]"></i>
                    </button>
                </div>
            </div>

            <div id="mobile-menu"
                 class="lg:hidden absolute inset-x-0 top-full bg-white/95 dark:bg-[#0a143c]/95 backdrop-blur-xl border-b border-slate-200 dark:border-white/10 shadow-2xl px-4 pb-5 pt-4 flex-col gap-1 max-h-[calc(100vh-4rem)] overflow-y-auto"
                 style="display:none;">
                ${withSearch ? searchMarkup('mobile') : ''}
                ${mobileLinksMarkup(active)}
            </div>
        </nav>`;
    }

    function footerMarkup() {
        const year = new Date().getFullYear();
        return `
        <footer class="bg-white dark:bg-[#050b14] border-t border-slate-200 dark:border-white/5 pt-14 md:pt-16 pb-28 lg:pb-24 transition-colors duration-300">
            <div class="sk-shell">
                <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-10 md:gap-12 mb-10 md:mb-12">

                    <div class="space-y-4">
                        <a href="index.html" class="flex items-center gap-3">
                            <img src="${LOGO}" alt="Logo Dishub Pekalongan" class="h-10 w-auto">
                            <span class="h-6 w-px bg-slate-300 dark:bg-slate-700"></span>
                            <span class="font-display font-black text-xl text-[#0a143c] dark:text-white tracking-tight">SUDUT KOTA</span>
                        </a>
                        <p class="text-slate-500 dark:text-slate-400 text-sm font-medium italic">"Pantau Kotamu, Kenali Sekitarmu."</p>
                    </div>

                    <div>
                        <h3 class="font-display font-bold text-[#0a143c] dark:text-white text-sm uppercase tracking-widest mb-5">Navigasi</h3>
                        <ul class="space-y-3 text-sm text-slate-500 dark:text-slate-400">
                            <li><a href="index.html" class="hover:text-blue-600 dark:hover:text-blue-400 transition-colors">Beranda</a></li>
                            <li><a href="cctv.html" class="hover:text-blue-600 dark:hover:text-blue-400 transition-colors">CCTV Live</a></li>
                            <li><a href="statistik.html" class="hover:text-blue-600 dark:hover:text-blue-400 transition-colors">Statistik</a></li>
                            <li><a href="index.html#pusat-pengaduan" class="hover:text-blue-600 dark:hover:text-blue-400 transition-colors">Lapor &amp; Aduan</a></li>
                        </ul>
                    </div>

                    <div>
                        <h3 class="font-display font-bold text-[#0a143c] dark:text-white text-sm uppercase tracking-widest mb-5">Instansi</h3>
                        <ul class="space-y-3 text-sm text-slate-500 dark:text-slate-400">
                            <li class="font-semibold text-slate-700 dark:text-slate-300">Dinas Perhubungan Kota Pekalongan</li>
                            <li>Pemerintah Kota Pekalongan</li>
                            <li>
                                <a href="https://dishub.pekalongankota.go.id/" target="_blank" rel="noopener"
                                   class="text-blue-600 dark:text-blue-400 hover:underline inline-flex items-center gap-2">
                                    <i class="fa-solid fa-globe"></i> Website Resmi Dishub
                                </a>
                            </li>
                        </ul>
                    </div>

                    <div>
                        <h3 class="font-display font-bold text-[#0a143c] dark:text-white text-sm uppercase tracking-widest mb-5">Kontak</h3>
                        <ul class="space-y-3 text-sm text-slate-500 dark:text-slate-400 leading-relaxed">
                            <li class="flex gap-2">
                                <i class="fa-solid fa-location-dot w-4 mt-1 text-slate-400 shrink-0"></i>
                                <span>Jl. Seruni No. 66, Kel. Poncol<br>Kec. Pekalongan Timur, Kota Pekalongan<br>Jawa Tengah 51122</span>
                            </li>
                            <li class="flex gap-2"><i class="fa-solid fa-phone w-4 mt-1 text-slate-400 shrink-0"></i><span>(0285) 421600</span></li>
                            <li class="flex gap-2 min-w-0"><i class="fa-solid fa-envelope w-4 mt-1 text-slate-400 shrink-0"></i><span class="break-all">dishub.pekalongankota@gmail.com</span></li>
                        </ul>
                    </div>
                </div>

                <div class="border-t border-slate-200 dark:border-white/10 pt-6 md:pt-8 flex flex-col lg:flex-row justify-between items-center gap-4 text-center lg:text-left">
                    <p class="text-[10px] md:text-xs text-slate-400 dark:text-slate-500 max-w-3xl leading-relaxed">
                        <strong>Disclaimer:</strong> Informasi tayangan CCTV merupakan relay dari berbagai sumber pengelola, termasuk instansi pemerintah, vendor, dan masyarakat. Ketersediaan serta kualitas tayangan bergantung pada kondisi perangkat dan jaringan sumber.
                    </p>
                    <p class="text-[11px] font-bold text-slate-500 dark:text-slate-400 lg:whitespace-nowrap uppercase tracking-wider">
                        &copy; ${year} Sudut Kota.<br class="lg:hidden"> Dinas Perhubungan Kota Pekalongan.
                    </p>
                </div>
            </div>
        </footer>`;
    }

    function desktopBarMarkup() {
        return `
        <div class="hidden lg:flex desktop-bottom-bar bg-white/90 dark:bg-[#0a143c]/95 backdrop-blur-xl border border-slate-200 dark:border-white/15 h-[52px] w-[calc(100%-40px)] max-w-[1600px] fixed bottom-6 left-1/2 -translate-x-1/2 z-[60] rounded-full shadow-2xl items-center px-4">
            <div class="bg-blue-600 h-8 flex items-center px-4 rounded-full z-20 shrink-0 text-white text-[10px] font-black uppercase tracking-widest gap-2 mr-4">
                <span class="w-2 h-2 bg-yellow-400 rounded-full animate-pulse"></span> INFO
            </div>
            <div class="ticker-wrap relative flex-1 min-w-0 text-slate-800 dark:text-white overflow-hidden">
                <div id="unified-ticker-desktop" class="ticker-track">
                    <span class="ticker-item text-xs font-semibold uppercase">${TICKER_TEXT}</span>
                    <span class="ticker-item text-xs font-semibold uppercase" aria-hidden="true">${TICKER_TEXT}</span>
                </div>
            </div>
            <div class="bg-slate-100 dark:bg-black/40 h-8 px-3 rounded-full border border-slate-200 dark:border-white/20 z-20 flex items-center gap-2 ml-4 text-slate-700 dark:text-white text-[11px] font-bold">
                <i class="fa-solid fa-gauge-high text-green-600 dark:text-green-400"></i>
                <span id="speedometer">—</span>
            </div>
            <div class="bg-slate-100 dark:bg-white/10 h-8 px-4 rounded-full border border-slate-200 dark:border-white/20 z-20 flex items-center ml-2 text-slate-800 dark:text-white font-mono text-xs font-bold">
                <span id="clock-desktop">00:00:00 WIB</span>
            </div>
        </div>`;
    }

    function bottomItemMarkup(link, active) {
        const isActive = link.key === active;

        if (link.center) {
            return `
            <a href="${link.href}" aria-label="${link.label}" class="flex flex-col items-center justify-center w-full h-full -translate-y-3 group">
                <span class="w-12 h-12 rounded-full bg-gradient-to-tr from-blue-600 to-cyan-400 flex items-center justify-center text-white shadow-lg shadow-blue-500/30 border-4 border-white dark:border-[#0a143c] active:scale-95 transition-transform group-hover:scale-105">
                    <i class="fa-solid ${link.icon} text-lg"></i>
                </span>
                <span class="text-[10px] font-display font-bold uppercase tracking-widest mt-1 ${isActive ? 'text-blue-600 dark:text-blue-400' : 'text-slate-500 dark:text-slate-400'}">${link.short}</span>
            </a>`;
        }

        return `
            <a href="${link.href}" class="flex flex-col items-center justify-center w-full h-full gap-1 ${isActive ? 'text-blue-600 dark:text-blue-400' : 'text-slate-400 dark:text-slate-500'} hover:text-blue-600 dark:hover:text-blue-400 transition-colors">
                <i class="fa-solid ${link.icon} text-lg"></i>
                <span class="text-[10px] font-display font-bold uppercase tracking-widest">${link.short}</span>
            </a>`;
    }

    /* Instagram-style: hanya di bawah lg, karena di atas itu tautan teks
       navbar sudah memuat semua tujuan. Pintu masuk akun sudah ada di navbar
       (ikon "Masuk"), jadi bilah ini tidak mengulanginya. */
    function mobileNavMarkup(active) {
        const center = NAV_LINKS.find(link => link.center && canSee(link));
        const items = NAV_LINKS
            .filter(link => canSee(link) && !link.center)
            .sort((a, b) => a.mobile - b.mobile);

        /* Tombol utama selalu di tengah, berapa pun jumlah item yang tersisa
           setelah filter peran (tamu hanya melihat tiga tujuan). */
        if (center) items.splice(Math.ceil(items.length / 2), 0, center);

        return `
        <div id="site-bottom-nav" class="lg:hidden fixed bottom-0 inset-x-0 z-[100] bg-white/95 dark:bg-[#0a143c]/95 backdrop-blur-xl border-t border-slate-200 dark:border-white/10 shadow-[0_-5px_20px_rgba(0,0,0,0.06)] sk-safe-bottom">
            <div class="flex justify-around items-stretch h-16 px-1">
                ${items.map(link => bottomItemMarkup(link, active)).join('')}
            </div>
        </div>`;
    }

    function loaderMarkup() {
        return `
        <div id="initial-loader" class="fixed inset-0 z-[9999] bg-slate-50 dark:bg-[#0a143c] flex flex-col justify-center items-center transition-opacity duration-500 overflow-hidden">
            <div class="absolute inset-0 opacity-[0.05] dark:opacity-[0.08]" style="background-image: radial-gradient(#1e3a8a 1px, transparent 1px); background-size: 22px 22px;"></div>
            <div class="relative w-52 h-52 sm:w-64 sm:h-64 flex flex-col items-center justify-center">
                <div class="absolute inset-0 border-2 border-blue-500/20 rounded-full animate-ping" style="animation-duration:3s;"></div>
                <div class="absolute inset-4 border border-blue-500/30 rounded-full"></div>
                <div class="radar-scanner"></div>
                <img src="${LOGO}" alt="Logo Sudut Kota" class="h-14 sm:h-16 w-auto relative z-10 drop-shadow-2xl rounded-full">
                <h1 class="font-display font-black text-lg sm:text-xl text-[#0a143c] dark:text-white tracking-[0.2em] mt-4 relative z-10">SUDUT KOTA</h1>
                <p class="text-[10px] font-bold tracking-[0.3em] text-blue-600 dark:text-blue-400 uppercase mt-2 relative z-10">Memuat Sistem ATCS...</p>
            </div>
        </div>`;
    }

    /* --- Jam, sapaan & ticker -------------------------------------------- */
    /* Marquee butuh dua salinan teks dan durasi yang sebanding dengan lebarnya,
       supaya kecepatannya sama di semua lebar layar. */
    function startTicker() {
        // Kecepatan tetap berapa pun panjang teksnya. Pengguna yang memilih
        // `prefers-reduced-motion` tetap mendapat teks berjalan, hanya lebih lambat.
        const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        const speed = reduce ? 40 : 55;

        document.querySelectorAll('.ticker-track').forEach((track) => {
            const half = track.scrollWidth / 2;
            if (!half) return;

            track.style.animationDuration = Math.max(14, Math.round(half / speed)) + 's';
            track.style.animationName = 'ticker-scroll';
            track.style.animationTimingFunction = 'linear';
            track.style.animationIterationCount = 'infinite';
        });
    }

    function greetingOf(hours) {
        if (hours >= 4 && hours < 11) return { text: 'Selamat Pagi', icon: 'fa-sun text-yellow-500' };
        if (hours >= 11 && hours < 15) return { text: 'Selamat Siang', icon: 'fa-sun text-yellow-600 dark:text-yellow-400' };
        if (hours >= 15 && hours < 18) return { text: 'Selamat Sore', icon: 'fa-cloud-sun text-orange-500' };
        return { text: 'Selamat Malam', icon: 'fa-moon text-blue-500 dark:text-blue-400' };
    }

    function startClock() {
        const tick = () => {
            const now = new Date();
            const pad = (value) => String(value).padStart(2, '0');
            const full = `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
            const short = `${pad(now.getHours())}:${pad(now.getMinutes())}`;

            /* Zona waktu mengikuti perangkat: WIB (7), WITA (8), WIT (9). */
            const offset = -now.getTimezoneOffset() / 60;
            const tz = offset === 8 ? 'WITA' : offset === 9 ? 'WIT' : 'WIB';

            document.querySelectorAll('[data-clock="full"]').forEach(el => { el.textContent = `${full} ${tz}`; });
            document.querySelectorAll('[data-clock="short"]').forEach(el => { el.textContent = `${short} ${tz}`; });
            document.querySelectorAll('#clock-desktop, #digital-clock').forEach(el => { el.textContent = `${full} ${tz}`; });

            const greeting = greetingOf(now.getHours());
            document.querySelectorAll('.greeting-text').forEach(el => { el.textContent = greeting.text + ','; });
            document.querySelectorAll('.greeting-icon').forEach(el => { el.className = `greeting-icon fa-solid ${greeting.icon} text-[10px]`; });

            document.querySelectorAll('#date-display').forEach(el => {
                el.textContent = now.toLocaleDateString('id-ID', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
            });
        };
        tick();
        setInterval(tick, 1000);
    }

    function describeConnection() {
        const conn = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
        const el = document.getElementById('speedometer');
        if (!el) return;
        if (conn && typeof conn.downlink === 'number') el.textContent = `${conn.downlink} Mbps`;
        else el.textContent = 'LIVE';
    }

    /* --- Tinggi navbar ---------------------------------------------------- */
    /* Navbar bertinggi tetap dan nilainya ditetapkan di css/style.css
       (--sk-nav-h). Tidak ada pengukuran runtime di sini: nilai hasil ukur
       bisa tertinggal satu bingkai saat rasio layar berubah, dan <main> lalu
       tertutup navbar. */

    /* --- Inisialisasi ---------------------------------------------------- */
    function mount(options) {
        const opts = Object.assign({ active: 'home', chrome: true }, options || {});

        if (opts.chrome) {
            const navHost = document.getElementById('site-nav');
            if (navHost) navHost.innerHTML = navbarMarkup(opts.active, !!opts.search);

            const footerHost = document.getElementById('site-footer');
            if (footerHost) footerHost.innerHTML = footerMarkup();

            /* Dua bilah berbagi satu host: ticker desktop dan bottom nav ponsel.
               Keduanya fixed, jadi urutan markup tidak memengaruhi tata letak. */
            const barHost = document.getElementById('site-bottombar');
            if (barHost) barHost.innerHTML = desktopBarMarkup() + mobileNavMarkup(opts.active);

            if (!document.getElementById('initial-loader')) {
                document.body.insertAdjacentHTML('afterbegin', loaderMarkup());
            }

            bindMobileSearch();
        }

        if (opts.chrome) {
            requestAnimationFrame(startTicker);
            if (document.fonts && document.fonts.ready) document.fonts.ready.then(startTicker);
            window.addEventListener('resize', startTicker);
        }

        // Setelah markup disuntikkan, ikon tema baru ada — terapkan ulang.
        applyTheme(currentTheme());

        ensureToastStack();
        startClock();
        describeConnection();

        // Tautan Dashboard muncul/hilang mengikuti peran tanpa memuat ulang halaman.
        document.addEventListener('auth:change', () => {
            if (!opts.chrome) return;
            const links = document.getElementById('nav-links');
            const menu = document.getElementById('mobile-menu');
            const user = document.getElementById('nav-user');
            if (links) links.innerHTML = desktopLinksMarkup(opts.active);
            if (menu) {
                menu.innerHTML = (opts.search ? searchMarkup('mobile') : '') + mobileLinksMarkup(opts.active);
                bindMobileSearch();
            }
            if (user) user.innerHTML = userChipMarkup();

            const barHost = document.getElementById('site-bottombar');
            if (barHost) {
                barHost.innerHTML = desktopBarMarkup() + mobileNavMarkup(opts.active);
                requestAnimationFrame(startTicker);
                describeConnection();
            }
        });

        /* Firebase memulihkan sesi secara asinkron. Tanpa panggilan ini,
           halaman yang tidak memakai requireOperator/requireAdmin (stream,
           statistik, beranda) tidak pernah tahu pengguna sudah login dan
           menampilkan tombol "Masuk" seolah sesinya berakhir. */
        if (global.Auth) {
            global.Auth.ready().catch(function (err) {
                console.warn('[App] Gagal memulihkan sesi:', err);
            });

            /* Visitor yang sudah login diarahkan ke fitur pertama yang boleh
               ia buka — bukan selalu Stream, karena akses per akun bisa
               berbeda (mis. Statistik dicabut, atau Panel diberikan). */
            if (opts.active === 'home') {
                global.Auth.ready().then(function (user) {
                    if (!user || user.role !== 'visitor') return;
                    const order = ['cctv', 'statistik', 'dashboard', 'akun'];
                    const page = { cctv: 'cctv.html', statistik: 'statistik.html', dashboard: 'dashboard.html', akun: 'akun.html' };
                    const next = order.find(function (feature) { return global.Auth.can(feature); });
                    if (next) location.replace(page[next]);
                }).catch(function () {});
            }
        }

        /* Pesan saat halaman dialihkan karena peran tidak mencukupi. */
        try {
            const denied = new URLSearchParams(location.search).get('denied');
            if (denied) {
                const only = denied === 'akun.html' ? 'Administrator' : 'Teknisi atau Administrator';
                setTimeout(function () {
                    toast('Halaman ' + denied + ' hanya untuk ' + only + '.', 'error', 5200);
                }, 500);
            }
        } catch (err) { /* URLSearchParams tidak tersedia: abaikan */ }

        document.addEventListener('click', (event) => {
            if (event.target.closest('#theme-toggle')) toggleTheme();
            if (event.target.closest('#btn-logout') || event.target.closest('[data-logout]')) {
                global.Auth && global.Auth.logout();
                toast('Sesi diakhiri.', 'info');
                setTimeout(() => { location.href = 'index.html'; }, 600);
            }
            if (event.target.closest('#btn-mobile-menu')) {
                const menu = document.getElementById('mobile-menu');
                const btn = document.getElementById('btn-mobile-menu');
                if (menu) {
                    const open = menu.style.display !== 'flex';
                    menu.style.display = open ? 'flex' : 'none';
                    if (btn) btn.setAttribute('aria-expanded', open ? 'true' : 'false');
                }
            }
        });

        /* Loader tidak boleh bergantung pada `load`: satu gambar eksternal yang
           menggantung akan menahannya selamanya. */
        const hideLoader = () => {
            const loader = document.getElementById('initial-loader');
            if (!loader) return;
            loader.style.opacity = '0';
            setTimeout(() => loader.remove(), 500);
        };
        window.addEventListener('load', () => setTimeout(hideLoader, 350));
        setTimeout(hideLoader, 2200);

        document.dispatchEvent(new CustomEvent('app:mounted', { detail: opts }));
    }

    /** Isi area pengguna pada header kustom (dipakai halaman CCTV). */
    function renderUserChip(selector) {
        const host = document.querySelector(selector);
        if (host) host.innerHTML = userChipMarkup();
    }

    /**
     * Tutup isi halaman dengan panel "akses dinonaktifkan".
     * Dipakai halaman yang fiturnya dicabut Administrator. Sengaja TIDAK
     * mengalihkan: pengalihan ke beranda bisa memantul balik ke halaman ini
     * untuk peran Visitor dan membuat lingkaran navigasi.
     */
    function blocked(feature) {
        const main = document.querySelector('main');
        if (!main) return;
        const label = global.Auth ? global.Auth.featureLabel(feature) : feature;

        main.innerHTML = `
        <div class="sk-shell py-16 md:py-24">
            <div class="glass-card max-w-xl mx-auto p-8 md:p-10 text-center">
                <div class="w-16 h-16 mx-auto rounded-full sk-soft flex items-center justify-center text-2xl mb-5">
                    <i class="fa-solid fa-lock"></i>
                </div>
                <h1 class="font-display font-black text-xl md:text-2xl sk-ink">Akses Fitur Dinonaktifkan</h1>
                <p class="text-sm sk-muted mt-3 leading-relaxed">
                    Akun Anda tidak memiliki akses ke fitur <strong class="sk-ink">${label}</strong>.
                    Hubungi Administrator untuk membukanya kembali.
                </p>
                <a href="index.html" class="inline-flex items-center gap-2 mt-6 px-5 py-3 bg-blue-600 hover:bg-blue-500 text-white text-xs font-black uppercase tracking-wider rounded-xl transition">
                    <i class="fa-solid fa-house"></i> Kembali ke Beranda
                </a>
            </div>
        </div>`;
        window.scrollTo(0, 0);
    }

    global.App = {
        init: mount,
        mount: mount,
        toast: toast,
        applyTheme: applyTheme,
        toggleTheme: toggleTheme,
        renderUserChip: renderUserChip,
        blocked: blocked,
        logoUrl: LOGO
    };
})(window);
