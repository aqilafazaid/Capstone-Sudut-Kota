/* ==========================================================================
   MAIN.JS - SUDUT KOTA DISHUB PEKALONGAN
   Fungsi: HLS Player, Switcher AI / Non-AI, Firebase Realtime Sync, UI Control
   ========================================================================== */

// 1. DATA MASTER TITIK CCTV
const CCTV_CAMERAS = [
    {
        id: "29",
        name: "Simpang Ponolawen",
        city: "KOTA PEKALONGAN",
        urlNonAI: "http://16.16.121.70:8091/hls/ch29/index.m3u8",
        urlAI: "http://16.16.121.70:8091/hls/simpang_29_ai/index.m3u8",
        firebaseNode: "cam_29"
    },
    {
        id: "35",
        name: "Simpang Grogolan / Alun-Alun",
        city: "KOTA PEKALONGAN",
        urlNonAI: "http://16.16.121.70:8091/hls/ch35/index.m3u8",
        urlAI: "http://16.16.121.70:8091/hls/simpang_35_ai/index.m3u8",
        firebaseNode: "cam_35"
    },
    {
        id: "43",
        name: "Simpang THR / Pusri",
        city: "KOTA PEKALONGAN",
        urlNonAI: "http://16.16.121.70:8091/hls/ch43/index.m3u8",
        urlAI: "http://16.16.121.70:8091/hls/simpang_43_ai/index.m3u8",
        firebaseNode: "cam_43"
    }
];

// URL Firebase Realtime Database
const FIREBASE_BASE_URL = "https://sudut-kota-default-rtdb.firebaseio.com/cctv_data";

// 2. STATE GLOBAL APLIKASI
let currentHlsInstance = null;
let activeCamIndex = 0;
let isAiModeActive = false;
let firebaseIntervalTimer = null;

// DOM Elements Reference
let videoElement, loadingOverlay, errorOverlay, logTextElement, resDisplayElement;
let yoloToggle, mirnetToggle, badgeYolo, badgeMirnet;

// 3. INISIALISASI SAAT HALAMAN SELESAI DIMUAT
document.addEventListener("DOMContentLoaded", () => {
    // Tangkap elemen DOM jika ada di halaman
    videoElement = document.getElementById("video-element");
    loadingOverlay = document.getElementById("overlay-loading");
    errorOverlay = document.getElementById("overlay-error");
    logTextElement = document.getElementById("ai-log-text");
    resDisplayElement = document.getElementById("resolution-display");

    yoloToggle = document.getElementById("yolo-toggle");
    mirnetToggle = document.getElementById("mirnet-toggle");
    badgeYolo = document.getElementById("badge-yolo");
    badgeMirnet = document.getElementById("badge-mirnet");

    // Hanya jalankan logic player jika elemen video ditemukan di halaman (misal di cctv.html)
    if (videoElement) {
        initCctvPage();
    }
});

// 4. LOGIC PEMUTAR CCTV & HLS
function initCctvPage() {
    renderCameraList();

    // Event saat metadata video berhasil dibaca (Dapatkan resolusi asli)
    videoElement.addEventListener("loadedmetadata", () => {
        if (resDisplayElement) {
            resDisplayElement.innerText = `${videoElement.videoWidth}x${videoElement.videoHeight}`;
        }
    });

    videoElement.addEventListener("playing", () => {
        if (loadingOverlay) loadingOverlay.classList.add("hidden");
        if (errorOverlay) errorOverlay.classList.add("hidden");
    });

    // Muat kamera pertama secara default
    loadCameraStream(0);
}

function loadCameraStream(index) {
    if (index < 0 || index >= CCTV_CAMERAS.length) return;
    activeCamIndex = index;
    const cam = CCTV_CAMERAS[index];

    // Tentukan URL mana yang dipakai (AI vs Non-AI)
    const streamUrl = isAiModeActive ? cam.urlAI : cam.urlNonAI;

    // Update Text UI Header
    const cityEl = document.getElementById("active-cam-city");
    const nameEl = document.getElementById("active-cam-name");
    if (cityEl) cityEl.innerText = cam.city;
    if (nameEl) nameEl.innerText = `[CH ${cam.id}] ${cam.name}`;

    if (loadingOverlay) loadingOverlay.classList.remove("hidden");
    if (errorOverlay) errorOverlay.classList.add("hidden");
    if (resDisplayElement) resDisplayElement.innerText = "DETECTING...";

    // Update status highlight pada daftar sidebar
    document.querySelectorAll(".cam-item").forEach(el => el.classList.remove("active"));
    const activeItem = document.getElementById(`cam-item-${index}`);
    if (activeItem) {
        activeItem.classList.add("active");
    }

    // Putar menggunakan HLS.js
    if (Hls.isSupported()) {
        if (currentHlsInstance) {
            currentHlsInstance.destroy();
        }

        currentHlsInstance = new Hls({
            manifestLoadingTimeOut: 10000,
            manifestLoadingMaxRetry: 3,
            levelLoadingTimeOut: 10000
        });

        currentHlsInstance.loadSource(streamUrl);
        currentHlsInstance.attachMedia(videoElement);

        currentHlsInstance.on(Hls.Events.MANIFEST_PARSED, () => {
            videoElement.play().catch(() => {
                // Browser autoplays Blocked fallback (Mute first then play)
                videoElement.muted = true;
                videoElement.play();
            });
        });

        currentHlsInstance.on(Hls.Events.ERROR, (event, data) => {
            if (data.fatal) {
                switch (data.type) {
                    case Hls.ErrorTypes.NETWORK_ERROR:
                        console.warn("[HLS] Network error encountered, trying to recover...");
                        currentHlsInstance.startLoad();
                        break;
                    case Hls.ErrorTypes.MEDIA_ERROR:
                        console.warn("[HLS] Media error encountered, trying to recover...");
                        currentHlsInstance.recoverMediaError();
                        break;
                    default:
                        console.error("[HLS] Fatal error, destroying player.");
                        currentHlsInstance.destroy();
                        showPlayerErrorState();
                        break;
                }
            }
        });
    } else if (videoElement.canPlayType("application/vnd.apple.mpegurl")) {
        // Fallback untuk Safari / iOS Native HLS
        videoElement.src = streamUrl;
        videoElement.addEventListener("loadedmetadata", () => {
            videoElement.play();
        });
    }

    // Mulai/Ulangi polling data statistik kendaraan dari Firebase
    startFirebaseSync(cam.firebaseNode);
}

function showPlayerErrorState() {
    if (loadingOverlay) loadingOverlay.classList.add("hidden");
    if (errorOverlay) errorOverlay.classList.remove("hidden");
    if (resDisplayElement) resDisplayElement.innerText = "OFFLINE";
}

function retryStream() {
    loadCameraStream(activeCamIndex);
}

// 5. TOGGLE AI ENGINE (YOLO & MIRNET)
function toggleAI(type) {
    const cam = CCTV_CAMERAS[activeCamIndex];
    const isYoloChecked = yoloToggle ? yoloToggle.checked : false;
    const isMirnetChecked = mirnetToggle ? mirnetToggle.checked : false;

    // Jika salah satu sakelar menyala, aktifkan mode AI Stream
    isAiModeActive = isYoloChecked || isMirnetChecked;

    // Update indikator visual badge di video
    if (type === "yolo" && badgeYolo) {
        if (isYoloChecked) {
            badgeYolo.classList.add("active");
            badgeYolo.innerHTML = `<i class="fa-solid fa-object-group"></i> YOLOv8: ACTIVE`;
        } else {
            badgeYolo.classList.remove("active");
            badgeYolo.innerHTML = `<i class="fa-solid fa-object-group text-slate-400"></i> YOLOv8: OFF`;
        }
    }

    if (type === "mirnet" && badgeMirnet) {
        if (isMirnetChecked) {
            badgeMirnet.classList.add("active-green");
            badgeMirnet.innerHTML = `<i class="fa-solid fa-moon"></i> MirNet: ACTIVE`;
        } else {
            badgeMirnet.classList.remove("active-green");
            badgeMirnet.innerHTML = `<i class="fa-solid fa-moon text-slate-400"></i> MirNet/Zero-DCE: OFF`;
        }
    }

    // Log terminal simulasi
    if (logTextElement) {
        if (isAiModeActive) {
            logTextElement.innerText = `> [SYSTEM] Mengalihkan aliran video ke AI Stream AWS (${cam.urlAI})...`;
        } else {
            logTextElement.innerText = `> [SYSTEM] Mengalihkan ke Raw CCTV Stream (${cam.urlNonAI}). Mode hemat daya.`;
        }
    }

    // Muat ulang stream video sesuai mode yang dipilih
    loadCameraStream(activeCamIndex);
}

// 6. SINKRONISASI FIREBASE REALTIME STATS (REST POLLING)
function startFirebaseSync(nodeName) {
    if (firebaseIntervalTimer) {
        clearInterval(firebaseIntervalTimer);
    }

    async function fetchStats() {
        try {
            const response = await fetch(`${FIREBASE_BASE_URL}/${nodeName}.json`);
            if (!response.ok) return;

            const data = await response.json();
            if (data) {
                updateStatCards(data);
            }
        } catch (err) {
            console.debug("[FIREBASE] Syncing...", err);
        }
    }

    // Ambil langsung saat ini & ulangi setiap 2 detik
    fetchStats();
    firebaseIntervalTimer = setInterval(fetchStats, 2000);
}

function updateStatCards(data) {
    const mobilEl = document.getElementById("stat-mobil");
    const motorEl = document.getElementById("stat-motor");
    const beratEl = document.getElementById("stat-berat");
    const totalEl = document.getElementById("stat-total");
    const fpsEl = document.getElementById("stat-fps");

    if (mobilEl) mobilEl.innerText = data.jumlah_mobil ?? 0;
    if (motorEl) motorEl.innerText = data.jumlah_motor ?? 0;
    if (beratEl) beratEl.innerText = data.jumlah_berat ?? 0;
    if (totalEl) totalEl.innerText = data.total_kendaraan ?? 0;

    if (fpsEl && data.server_fps) {
        fpsEl.innerText = `${data.server_fps} FPS`;
    }

    if (logTextElement && data.timestamp) {
        const timeStr = new Date(data.timestamp * 1000).toLocaleTimeString("id-ID");
        logTextElement.innerText = `> [FIREBASE_SYNC ${timeStr}] Status: ${data.status || 'ONLINE'} | FPS GPU: ${data.server_fps || 0}`;
    }
}

// 7. KONTROL PLAYER (VOLUME & FULLSCREEN)
function toggleMute() {
    if (!videoElement) return;
    videoElement.muted = !videoElement.muted;

    const btnVolumeIcon = document.querySelector("#btn-volume i");
    if (btnVolumeIcon) {
        btnVolumeIcon.className = videoElement.muted
            ? "fa-solid fa-volume-xmark text-lg"
            : "fa-solid fa-volume-high text-lg text-sky-400";
    }
}

function toggleFullscreen() {
    const wrapper = document.querySelector(".video-wrapper");
    if (!wrapper) return;

    if (!document.fullscreenElement) {
        if (wrapper.requestFullscreen) wrapper.requestFullscreen();
        else if (wrapper.webkitRequestFullscreen) wrapper.webkitRequestFullscreen();
    } else {
        if (document.exitFullscreen) document.exitFullscreen();
    }
}

// 8. SIDEBAR DAFTAR KAMERA & PENCARIAN
function renderCameraList() {
    const container = document.getElementById("camera-list-container");
    if (!container) return;

    container.innerHTML = "";

    const groupDiv = document.createElement("div");
    groupDiv.className = "accordion-group shadow-md";
    groupDiv.innerHTML = `
        <div class="group-header active" onclick="this.classList.toggle('active'); this.nextElementSibling.classList.toggle('open');">
            <div class="group-title font-bold text-sm text-slate-200">
                <i class="fa-solid fa-map-location-dot text-sky-400 mr-2"></i> KOTA PEKALONGAN
            </div>
            <i class="fa-solid fa-chevron-down text-slate-500"></i>
        </div>
        <div class="group-body open" id="cam-list-wrapper"></div>
    `;
    container.appendChild(groupDiv);

    const wrapper = document.getElementById("cam-list-wrapper");
    CCTV_CAMERAS.forEach((item, i) => {
        const row = document.createElement("div");
        row.className = `cam-item ${i === activeCamIndex ? "active" : ""}`;
        row.id = `cam-item-${i}`;
        row.onclick = () => loadCameraStream(i);
        row.innerHTML = `
            <i class="fa-solid fa-camera text-slate-500 text-base"></i>
            <span class="cam-name flex-1">[CH ${item.id}] ${item.name}</span>
            <span class="text-[10px] bg-sky-900/40 text-sky-400 px-2 py-0.5 rounded border border-sky-500/20">LIVE</span>
        `;
        wrapper.appendChild(row);
    });

    const totalEl = document.getElementById("total-cams");
    if (totalEl) totalEl.innerText = `${CCTV_CAMERAS.length} Titik`;
}

function handleSearch() {
    const searchInput = document.getElementById("search-input");
    if (!searchInput) return;

    const term = searchInput.value.toLowerCase();
    const items = document.querySelectorAll(".cam-item");

    items.forEach(item => {
        if (item.innerText.toLowerCase().includes(term)) {
            item.style.display = "flex";
        } else {
            item.style.display = "none";
        }
    });
}
