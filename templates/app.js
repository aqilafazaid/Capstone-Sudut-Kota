/**
 * SUDUT KOTA - COMMAND CENTER SCRIPT
 * Mengatur UI, Geolocation, Jam, API Kemenag, Anti-Inspect, dan Tema Gelap/Terang
 */

document.addEventListener('DOMContentLoaded', () => {
    
    /* =========================================
       1. SISTEM TEMA GELAP / TERANG (DARK MODE)
       ========================================= */
    const themeToggleBtn = document.getElementById('theme-toggle');
    const darkIcon = document.getElementById('theme-toggle-dark-icon');
    const lightIcon = document.getElementById('theme-toggle-light-icon');

    // Menyesuaikan Icon awal
    if (document.documentElement.classList.contains('dark')) {
        lightIcon.classList.remove('hidden');
    } else {
        darkIcon.classList.remove('hidden');
    }

    themeToggleBtn.addEventListener('click', function() {
        // Toggle icon
        darkIcon.classList.toggle('hidden');
        lightIcon.classList.toggle('hidden');

        // Toggle tema di HTML & Simpan ke localStorage
        if (document.documentElement.classList.contains('dark')) {
            document.documentElement.classList.remove('dark');
            localStorage.setItem('color-theme', 'light');
        } else {
            document.documentElement.classList.add('dark');
            localStorage.setItem('color-theme', 'dark');
        }
    });

    /* =========================================
       2. UI & LOADER MANAGEMENT
       ========================================= */
    function forceHideLoader() {
        const loader = document.getElementById('initial-loader');
        if(loader && loader.style.display !== 'none') {
            loader.style.opacity = '0';
            setTimeout(() => { 
                loader.style.visibility = 'hidden'; 
                loader.style.display = 'none'; 
            }, 400);
        }
    }
    setTimeout(forceHideLoader, 2000); // Waktu maksimal loader (dikurangi untuk optimasi)

    // Global Dropdown Handler
    window.toggleDropdown = function(id) {
        const el = document.getElementById(id);
        document.querySelectorAll('[id$="-dropdown"], .dropdown-menu-mobile').forEach(d => { 
            if(d.id !== id) d.classList.add('hidden'); 
        });
        el.classList.toggle('hidden');
    }

    // Klik di luar untuk menutup dropdown
    window.addEventListener('click', function(e){   
        if (!e.target.closest('.relative.group') && !e.target.closest('button')){
            document.querySelectorAll('.dropdown-menu-mobile, [id$="-dropdown"]').forEach(d => d.classList.add('hidden'));
        }
    });

    /* =========================================
       3. CLOCK & TICKER DATA
       ========================================= */
    function updateClock() {
        const now = new Date();
        const timeString = now.toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).replace(/\./g, ':');
        const fullString = `${timeString} WIB`;
        
        const deskClock = document.getElementById('clock-desktop');
        const mobClock = document.getElementById('clock-mobile');
        
        if(deskClock) deskClock.innerText = fullString;
        if(mobClock) mobClock.innerText = fullString;
    }
    setInterval(updateClock, 1000);
    updateClock();

    // Data Ticker Berita & Jadwal Sholat
    let prayerTimingsCache = {};
    async function updateTickerAndPrayer() {
        try { 
            // Ambil data Sholat
            const date = new Date();
            const dd = String(date.getDate()).padStart(2, '0');
            const mm = String(date.getMonth() + 1).padStart(2, '0');
            const resPrayer = await fetch(`https://api.aladhan.com/v1/timingsByCity/${dd}-${mm}-${date.getFullYear()}?city=Semarang&country=Indonesia`);
            const prayerData = await resPrayer.json();
            prayerTimingsCache = prayerData.data.timings;
            
            const prayerStr = `JADWAL SHOLAT HARI INI: Subuh ${prayerTimingsCache.Fajr} | Dzuhur ${prayerTimingsCache.Dhuhr} | Ashar ${prayerTimingsCache.Asr} | Maghrib ${prayerTimingsCache.Maghrib} | Isya ${prayerTimingsCache.Isha}`;

            // Ambil Berita (Contoh statis jika gagal fetch)
            let data = ['Sistem Infrastruktur Aktif - Pantauan Kamera CCTV Normal', prayerStr];
            
            if (data.length > 0) {
                // Formatting Ticker
                const items = data.map(n => `<span class="px-6 flex items-center">${n}</span><span class="text-blue-500 mx-2">//</span>`).join('');
                const fillHtml = items.repeat(5); // Repeat agar cukup mengisi layar
                
                const deskTicker = document.getElementById('unified-ticker-desktop');
                const mobTicker = document.getElementById('unified-ticker-mobile');
                
                if(deskTicker) deskTicker.innerHTML = fillHtml;
                if(mobTicker) mobTicker.innerHTML = fillHtml;
            }
        } catch (e) {
            console.warn("Gagal memuat ticker", e);
        }
    }
    updateTickerAndPrayer();

    /* =========================================
       4. GPS, SPEEDOMETER & GEOLOCATION
       ========================================= */
    let lastLat = null, lastLon = null;
    window.userIP = "Mendeteksi...";

    function initAdvancedTracking() {
        if ("geolocation" in navigator) {
            navigator.geolocation.watchPosition(async (position) => {
                // Kecepatan
                const speedMps = position.coords.speed || 0;
                const speedKmh = Math.round(speedMps * 3.6);
                
                ['speedometer', 'speedometer-mobile'].forEach(id => {
                    const speedEl = document.getElementById(id);
                    if (speedEl) {
                        speedEl.innerText = id === 'speedometer' ? `${speedKmh} km/h` : speedKmh;
                        if(speedKmh > 80) speedEl.parentElement.classList.add('text-red-500', 'animate-pulse');
                        else speedEl.parentElement.classList.remove('text-red-500', 'animate-pulse');
                    }
                });

                // Lokasi OpenStreetMap (Update jika jarak cukup jauh untuk efisiensi API)
                const lat = position.coords.latitude;
                const lon = position.coords.longitude;
                if(!lastLat || Math.abs(lat - lastLat) > 0.005 || Math.abs(lon - lastLon) > 0.005) {
                    lastLat = lat; lastLon = lon;
                    try {
                        const res = await fetch(`https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lon}&zoom=14`);
                        const data = await res.json();
                        let locName = data.address.city || data.address.town || data.address.village || 'Lokasi Terdeteksi';
                        
                        ['desktop-user-location', 'mobile-user-location'].forEach(id => {
                            const el = document.getElementById(id); 
                            if(el) el.innerText = locName;
                        });
                    } catch (e) {}
                }
            }, (err) => {
                fetchIPLocation();
            }, { enableHighAccuracy: true, maximumAge: 10000, timeout: 5000 });
        } else {
            fetchIPLocation();
        }
    }

    async function fetchIPLocation() {
        try {
            const res = await fetch('https://ipapi.co/json/'); 
            const data = await res.json();
            window.userIP = data.ip || 'Tidak Terdeteksi';
            const locString = `${data.city}, ${data.region}`;
            ['desktop-user-location', 'mobile-user-location'].forEach(id => {
                const el = document.getElementById(id); 
                if(el) el.innerText = locString;
            });
        } catch (e) { 
            console.error("Gagal lokasi IP", e); 
        }
    }
    initAdvancedTracking();

    /* =========================================
       5. SECURITY & ANTI-INSPECT KEAMANAN
       ========================================= */
    document.addEventListener('contextmenu', e => e.preventDefault());
    document.onkeydown = function(e) {
        let isBlocked = false;
        if(e.keyCode == 123) isBlocked = true; // F12
        if(e.ctrlKey && e.shiftKey && (e.keyCode == 73 || e.keyCode == 67 || e.keyCode == 74)) isBlocked = true; // Ctrl+Shift+I/C/J
        if(e.ctrlKey && (e.keyCode == 85 || e.keyCode == 83)) isBlocked = true; // Ctrl+U / Ctrl+S
        if(isBlocked) { 
            e.preventDefault(); 
            return false; 
        }
    }
    // Efek Blur saat user pindah tab (Keamanan CCTV)
    window.addEventListener('blur', () => document.body.classList.add('privacy-blur'));
    window.addEventListener('focus', () => document.body.classList.remove('privacy-blur'));
});
