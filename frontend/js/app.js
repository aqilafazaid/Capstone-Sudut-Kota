/* ==========================================================================
   APP.JS — Kerangka halaman bersama
   --------------------------------------------------------------------------
   Menyuntikkan navbar, footer, bottom bar, dan loader ke setiap halaman
   statis supaya markup tidak disalin 7 kali. Juga menangani tema gelap,
   jam, ticker, dan notifikasi toast.
   ========================================================================== */

(function (global) {
    'use strict';

    const THEME_KEY = 'color-theme';

    const TICKER_TEXT = [
        'SELAMAT DATANG DI COMMAND CENTER SUDUT KOTA',
        'SISTEM INI MENGGUNAKAN DETEKSI OBJEK YOLOv8 UNTUK MENGKLASIFIKASIKAN KENDARAAN',
        'DILENGKAPI DEEP LEARNING MIRNET DAN ZERO-DCE UNTUK MENJERNIHKAN GAMBAR MALAM',
        'DILARANG MELAKUKAN TANGKAPAN LAYAR UNTUK KEPENTINGAN YANG MELANGGAR UU PRIVASI DAN ITE',
        'PASTIKAN KONEKSI INTERNET STABIL AGAR STREAMING HLS BERJALAN LANCAR'
    ].join('   //   ');

    const LOGO = 'asset/logo-suko.png';

    /* Beranda tidak lagi jadi item menu: logo + tulisan SUDUT KOTA yang
       mengarah ke index.html (lihat navbarMarkup). */
    const NAV_LINKS = [
        { key: 'dashboard', href: 'dashboard.html', label: 'Dashboard', icon: 'fa-chart-pie' },
        { key: 'cctv', href: 'cctv.html', label: 'Stream', icon: 'fa-video' },
        { key: 'statistik', href: 'statistik.html', label: 'Statistik', icon: 'fa-chart-column' },
        { key: 'akun', href: 'akun.html', label: 'Akun', icon: 'fa-user-shield' }
    ];

    /* --- Tema ------------------------------------------------------------ */
    function applyTheme(mode) {
        const dark = mode === 'dark';
        document.documentElement.classList.toggle('dark', dark);
        document.documentElement.style.colorScheme = dark ? 'dark' : 'light';
        document.querySelectorAll('#theme-toggle-dark-icon').forEach(el => el.classList.toggle('hidden', !dark));
        document.querySelectorAll('#theme-toggle-light-icon').forEach(el => el.classList.toggle('hidden', dark));
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
    function userChipMarkup() {
        const user = global.Auth ? global.Auth.user() : null;

        if (!user) {
            return `<a href="login.html" title="Masuk" class="flex items-center gap-2 px-3 sm:px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-black uppercase tracking-wider transition shadow-[0_0_15px_rgba(37,99,235,0.35)]">
                        <i class="fa-solid fa-right-to-bracket"></i><span class="hidden sm:inline">Masuk</span>
                    </a>`;
        }

        const roleLabel = global.Auth.roleLabel(user.role);
        const isOperator = user.role === 'admin' || user.role === 'teknisi';
        return `
            <div class="flex items-center gap-2">
                <div class="hidden sm:flex flex-col items-end leading-tight">
                    <span class="text-[11px] font-black text-slate-800 dark:text-white truncate max-w-[140px]">${user.nama}</span>
                    <span class="text-[10px] font-bold ${isOperator ? 'text-blue-500' : 'text-amber-500'} uppercase tracking-wider">${roleLabel}</span>
                </div>
                <div class="w-9 h-9 rounded-full bg-gradient-to-br from-blue-600 to-blue-800 text-white flex items-center justify-center font-black text-sm border border-blue-400/40">
                    ${(user.nama || '?').charAt(0).toUpperCase()}
                </div>
                <button type="button" id="btn-logout" title="Keluar"
                    class="hidden sm:flex w-9 h-9 rounded-full bg-slate-200 dark:bg-white/10 text-slate-600 dark:text-white hover:bg-red-600 hover:text-white transition items-center justify-center">
                    <i class="fa-solid fa-door-open text-xs"></i>
                </button>
            </div>`;
    }

    /** Dashboard: admin + teknisi. Akun: hanya Administrator. */
    function canSee(link) {
        if (!global.Auth) return link.key !== 'dashboard' && link.key !== 'akun';
        if (link.key === 'dashboard') return global.Auth.isOperator();
        if (link.key === 'akun') return global.Auth.isAdmin();
        return true;
    }

    function desktopLinksMarkup(active) {
        return NAV_LINKS.filter(canSee).map(link => {
            const isActive = link.key === active;
            const cls = isActive
                ? 'text-blue-600 dark:text-white bg-blue-50 dark:bg-white/10'
                : 'text-slate-600 dark:text-slate-300 hover:text-blue-600 dark:hover:text-white';
            return `<a href="${link.href}" class="font-semibold px-3 py-2 rounded-xl transition ${cls}">${link.label}</a>`;
        }).join('');
    }

    function mobileLinksMarkup(active) {
        const links = NAV_LINKS.filter(canSee).map(link => `
            <a href="${link.href}" class="p-3 rounded-xl hover:bg-slate-100 dark:hover:bg-blue-900/30 font-bold text-slate-700 dark:text-slate-200 flex items-center gap-3 ${
                link.key === active ? 'bg-blue-50 dark:bg-blue-900/40 text-blue-600 dark:text-white' : ''
            }">
                <i class="fa-solid ${link.icon} w-5 text-blue-500"></i> ${link.label}
            </a>`).join('');

        const user = global.Auth ? global.Auth.user() : null;
        const logout = user ? `
            <button type="button" data-logout class="p-3 rounded-xl hover:bg-red-50 dark:hover:bg-red-900/30 font-bold text-red-600 dark:text-red-400 flex items-center gap-3">
                <i class="fa-solid fa-door-open w-5"></i> Keluar
            </button>` : '';

        return links + logout;
    }

    function searchMarkup() {
        return `
                    <div class="order-3 md:order-2 basis-full md:basis-0 md:flex-1 md:min-w-0 md:max-w-md md:mx-3 mt-3 md:mt-0">
                        <div class="relative group">
                            <i class="fa-solid fa-magnifying-glass absolute left-4 top-1/2 -translate-y-1/2 text-slate-400 group-focus-within:text-blue-500 text-sm"></i>
                            <input id="search-input" type="text" autocomplete="off"
                                   placeholder="Cari lokasi simpang / tiang..."
                                   class="w-full bg-slate-100 dark:bg-[#050a1f] border border-slate-300 dark:border-blue-900/60 text-slate-800 dark:text-white text-sm rounded-full py-2.5 pl-11 pr-4 font-semibold focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500 transition placeholder:text-slate-500">
                        </div>
                    </div>`;
    }

    function navbarMarkup(active, withSearch) {
        return `
        <nav class="fixed top-4 left-0 right-0 w-full z-50 px-3 lg:px-6">
            <div class="max-w-[1400px] mx-auto bg-white/80 dark:bg-[#0a143c]/90 backdrop-blur-md shadow-xl rounded-2xl lg:rounded-[2rem] border border-slate-200 dark:border-blue-400/20 transition-colors duration-300 relative">
                <div class="flex flex-wrap md:flex-nowrap justify-between items-center gap-x-3 py-3 md:py-0 md:min-h-[80px] px-4 md:px-6 lg:px-8 w-full">
                    <a href="index.html" title="Beranda" aria-label="Beranda — Sudut Kota"
                       class="order-1 shrink-0 flex items-center gap-2 md:gap-3 border-r border-slate-300 dark:border-white/10 pr-2.5 md:pr-5">
                        <img src="asset/logo-suko.png"
                             srcset="asset/logo-suko-96.png 96w, asset/logo-suko.png 256w"
                             sizes="40px" width="40" height="40" alt=""
                             class="h-8 w-8 sm:h-9 sm:w-9 lg:h-10 lg:w-10 rounded-full object-contain shrink-0 ${active === 'home' ? 'ring-2 ring-blue-500/60' : ''}">
                        <span class="hidden min-[360px]:inline font-black text-sm sm:text-base md:text-xl lg:text-2xl text-slate-900 dark:text-white">SUDUT <span class="text-blue-600 dark:text-blue-500">KOTA</span></span>
                    </a>
                    ${withSearch ? searchMarkup() : ''}
                    <div class="order-2 md:order-3 shrink-0 flex items-center gap-1 sm:gap-1.5 lg:gap-3 justify-end">
                        <div class="hidden lg:flex items-center space-x-1 mr-2" id="nav-links">${desktopLinksMarkup(active)}</div>
                        <button id="theme-toggle" type="button" class="w-9 h-9 lg:w-10 lg:h-10 rounded-full bg-slate-200 dark:bg-white/10 text-slate-600 dark:text-white flex items-center justify-center transition border border-slate-300 dark:border-white/10 hover:bg-slate-300 dark:hover:bg-white/20">
                            <i id="theme-toggle-dark-icon" class="hidden fa-solid fa-moon"></i>
                            <i id="theme-toggle-light-icon" class="hidden fa-solid fa-sun"></i>
                        </button>
                        <div id="nav-user" class="flex items-center">${userChipMarkup()}</div>
                        <button type="button" id="btn-mobile-menu" class="lg:hidden w-9 h-9 lg:w-10 lg:h-10 rounded-full bg-slate-200 dark:bg-white/10 text-slate-700 dark:text-white flex items-center justify-center transition">
                            <i class="fa-solid fa-bars"></i>
                        </button>
                    </div>
                </div>

                <div id="mobile-menu" class="lg:hidden absolute top-full left-0 right-0 mt-2 bg-white/95 dark:bg-[#0a143c]/95 backdrop-blur-xl border border-slate-200 dark:border-blue-400/20 rounded-2xl shadow-2xl p-4 flex-col gap-2" style="display:none;">
                    ${mobileLinksMarkup(active)}
                </div>
            </div>
        </nav>`;
    }

    function footerMarkup() {
        return `
        <footer class="bg-slate-900 dark:bg-[#0a143c] text-slate-400 dark:text-slate-300 pt-16 pb-24 border-t border-slate-800 dark:border-blue-900 transition-colors duration-300">
            <div class="text-center"><p class="text-xs">&copy; ${new Date().getFullYear()} Tim Capstone TA — Universitas Diponegoro.</p></div>
        </footer>`;
    }

    function bottomBarMarkup() {
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

    function loaderMarkup() {
        return `
        <div id="initial-loader" class="fixed inset-0 z-[9999] bg-white dark:bg-[#0a143c] flex flex-col justify-center items-center transition-opacity duration-400">
            <div class="relative z-10 font-black text-4xl text-slate-900 dark:text-white animate-bounce mb-8">
                SUDUT <span class="text-blue-600 dark:text-blue-500 text-5xl">KOTA</span>
            </div>
            <p class="text-blue-600 dark:text-blue-200 font-bold tracking-[0.2em] text-xs">MEMUAT SISTEM...</p>
        </div>`;
    }

    function backgroundMarkup() {
        return `
        <div class="bg-base fixed inset-0 z-[-2] bg-gradient-to-br from-blue-100 to-slate-50 dark:from-[#0a143c] dark:to-[#1e3a8a]"></div>
        <div class="fixed inset-0 z-[-1] opacity-10 dark:opacity-30 mix-blend-multiply dark:mix-blend-screen bg-[url('https://images.unsplash.com/photo-1518605368461-1e122b10287b?auto=format&fit=crop&q=80')] bg-cover bg-center"></div>`;
    }

    /* --- Jam & ticker ---------------------------------------------------- */
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

    function startClock() {
        const tick = () => {
            const now = new Date();
            const text = now.toLocaleTimeString('id-ID', { hour12: false }) + ' WIB';
            document.querySelectorAll('#clock-desktop, #digital-clock').forEach(el => { el.textContent = text; });

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
    /* Navbar memakai position:fixed, jadi padding atas <main> tidak boleh
       di-hardcode: pada rasio tertentu barisnya melipat dua. Tinggi nyata
       dipublikasikan ke CSS sebagai --sk-nav-h dan dipakai halaman mana pun. */
    var navObserver = null;

    function syncNavHeight() {
        const nav = document.querySelector('#site-nav nav');
        const box = nav && nav.firstElementChild;
        if (!box) return;

        const bottom = Math.ceil(box.getBoundingClientRect().bottom);
        document.documentElement.style.setProperty('--sk-nav-h', bottom + 'px');
    }

    function watchNavHeight() {
        const nav = document.querySelector('#site-nav nav');
        const box = nav && nav.firstElementChild;
        if (!box) return;

        syncNavHeight();

        if (navObserver) navObserver.disconnect();
        if (window.ResizeObserver) {
            navObserver = new ResizeObserver(syncNavHeight);
            navObserver.observe(box);
        }
        if (document.fonts && document.fonts.ready) document.fonts.ready.then(syncNavHeight);
    }

    /* --- Inisialisasi ---------------------------------------------------- */
    function mount(options) {
        const opts = Object.assign({ active: 'home', chrome: true }, options || {});

        if (opts.chrome) {
            const navHost = document.getElementById('site-nav');
            if (navHost) navHost.innerHTML = navbarMarkup(opts.active, !!opts.search);

            const footerHost = document.getElementById('site-footer');
            if (footerHost) footerHost.innerHTML = footerMarkup();

            const barHost = document.getElementById('site-bottombar');
            if (barHost) barHost.innerHTML = bottomBarMarkup();

            if (!document.getElementById('initial-loader')) {
                document.body.insertAdjacentHTML('afterbegin', backgroundMarkup() + loaderMarkup());
            }
        }

        if (opts.chrome) {
            watchNavHeight();
            requestAnimationFrame(startTicker);
            if (document.fonts && document.fonts.ready) document.fonts.ready.then(startTicker);
            window.addEventListener('resize', startTicker);
        }
        window.addEventListener('resize', syncNavHeight);
        window.addEventListener('orientationchange', syncNavHeight);

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
            if (menu) menu.innerHTML = mobileLinksMarkup(opts.active);
            if (user) user.innerHTML = userChipMarkup();
            syncNavHeight();
        });

        document.addEventListener('click', (event) => {
            if (event.target.closest('#theme-toggle')) toggleTheme();
            if (event.target.closest('#btn-logout') || event.target.closest('[data-logout]')) {
                global.Auth && global.Auth.logout();
                toast('Sesi diakhiri.', 'info');
                setTimeout(() => { location.href = 'index.html'; }, 600);
            }
            if (event.target.closest('#btn-mobile-menu')) {
                const menu = document.getElementById('mobile-menu');
                if (menu) menu.style.display = menu.style.display === 'flex' ? 'none' : 'flex';
            }
        });

        window.addEventListener('load', () => {
            const loader = document.getElementById('initial-loader');
            if (!loader) return;
            setTimeout(() => {
                loader.style.opacity = '0';
                setTimeout(() => loader.remove(), 400);
            }, 350);
        });

        document.dispatchEvent(new CustomEvent('app:mounted', { detail: opts }));
    }

    /** Isi area pengguna pada header kustom (dipakai halaman CCTV). */
    function renderUserChip(selector) {
        const host = document.querySelector(selector);
        if (host) host.innerHTML = userChipMarkup();
    }

    global.App = {
        init: mount,
        mount: mount,
        toast: toast,
        applyTheme: applyTheme,
        toggleTheme: toggleTheme,
        renderUserChip: renderUserChip,
        logoUrl: LOGO
    };
})(window);
