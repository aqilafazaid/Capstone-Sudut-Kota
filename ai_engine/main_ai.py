import cv2
import numpy as np
import torch
import time
import subprocess
import argparse
import firebase_admin
from firebase_admin import credentials, db
from ultralytics import YOLO
import sys

# ==========================================
# 1. PARSING ARGUMEN (UNTUK MULTI-KAMERA)
# ==========================================
parser = argparse.ArgumentParser(description="AI Engine Sudut Kota - Dishub Pekalongan")
parser.add_argument('--channel', type=str, required=True, help="Nomor channel CCTV (Contoh: 29, 35, 43)")
parser.add_argument('--rtmp_name', type=str, required=True, help="Nama endpoint RTMP di AWS (Contoh: simpang_29_ai)")
args = parser.parse_args()

print(f"==================================================")
print(f"[START] Memulai AI Engine untuk Channel : {args.channel}")
print(f"[START] Target RTMP Stream AWS        : {args.rtmp_name}")
print(f"==================================================")

# ==========================================
# 2. KONFIGURASI FIREBASE REALTIME DB
# ==========================================
# Ganti dengan nama file JSON dari Firebase Anda
FIREBASE_CREDENTIALS = "firebase_credentials.json"
FIREBASE_DB_URL = "https://sudut-kota-default-rtdb.firebaseio.com/" # Ganti dengan URL DB Anda

try:
    # Cek agar tidak error jika firebase sudah diinisialisasi (saat running ulang)
    if not firebase_admin._apps:
        cred = credentials.Certificate(FIREBASE_CREDENTIALS)
        firebase_admin.initialize_app(cred, {'databaseURL': FIREBASE_DB_URL})
    
    # Path database dinamis sesuai nomor channel
    db_ref = db.reference(f'cctv_data/cam_{args.channel}')
    print("[INFO] Berhasil terhubung ke Firebase.")
except Exception as e:
    print(f"[ERROR] Gagal terhubung ke Firebase. Pastikan file JSON ada! Error: {e}")
    sys.exit(1)

# ==========================================
# 3. INISIALISASI MODEL AI (YOLOv8 & NIGHT VISION)
# ==========================================
print("[INFO] Memuat model YOLOv8 (Kendaraan)...")
# Gunakan yolov8n.pt (Nano) untuk kecepatan real-time di PC lokal
yolo_model = YOLO('yolov8n.pt') 
TARGET_CLASSES = [2, 3, 5, 7] # 2:Mobil, 3:Motor, 5:Bus, 7:Truk pada COCO Dataset

def apply_night_vision(frame):
    """
    Fungsi Restorasi Visual Malam Hari (MirNet/Zero-DCE).
    [PLACEHOLDER] - M. Adnan bisa memasukkan model PyTorch-nya di dalam blok ini.
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    brightness = np.mean(gray)
    
    if brightness < 60: # Jika kondisi gelap
        # Simulasi pencerahan sementara
        enhanced_frame = cv2.convertScaleAbs(frame, alpha=1.3, beta=40)
        cv2.putText(enhanced_frame, "MIRNET & ZERO-DCE: ACTIVE", (20, 30), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        return enhanced_frame, True
    return frame, False

# ==========================================
# 4. KONFIGURASI VIDEO & KONEKSI TAILSCALE
# ==========================================
# Format URL RTSP Hikvision via Tailscale IP
RTSP_URL = f"rtsp://Undip:Pekalongan12345@10.28.110.253:554/Streaming/Channels/{args.channel}01"
# Ganti dengan IP Publik AWS Ubuntu Anda
AWS_RTMP_URL = f"rtmp://IP_AWS_UBUNTU_ANDA/live/{args.rtmp_name}"

def connect_camera():
    print(f"[INFO] Menghubungkan ke RTSP Tailscale Channel {args.channel}...")
    cap = cv2.VideoCapture(RTSP_URL)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 2) # Kurangi buffer agar tidak delay
    return cap

cap = connect_camera()
if not cap.isOpened():
    print(f"[ERROR] Tidak dapat membuka RTSP stream CCTV Channel {args.channel}!")
    sys.exit(1)

width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
fps = int(cap.get(cv2.CAP_PROP_FPS))
if fps == 0 or fps > 30: fps = 25 # Normalisasi FPS

print(f"[INFO] Resolusi CCTV: {width}x{height} | FPS: {fps}")

# ==========================================
# 5. KONFIGURASI FFMPEG STREAMING (KE AWS)
# ==========================================
ffmpeg_cmd = [
    'ffmpeg',
    '-y',
    '-f', 'rawvideo',
    '-vcodec', 'rawvideo',
    '-pix_fmt', 'bgr24', # Input dari OpenCV BGR
    '-s', f"{width}x{height}",
    '-r', str(fps),
    '-i', '-', # Input dari stdin pipe
    '-c:v', 'libx264',
    '-pix_fmt', 'yuv420p', # Output standar untuk HLS AWS
    '-preset', 'ultrafast',
    '-tune', 'zerolatency',
    '-b:v', '1500k',       # Batasi Bitrate (Biar kuota internet lokal aman)
    '-maxrate', '2000k',
    '-bufsize', '4000k',
    '-g', str(fps * 2),    # Keyframe setiap 2 detik (Standar HLS)
    '-f', 'flv',           # Format FLV untuk protokol RTMP
    AWS_RTMP_URL
]

# Start FFmpeg Subprocess
ffmpeg_process = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)

# ==========================================
# 6. LOOPING UTAMA (INFERENSI AI & PUSH DATA)
# ==========================================
print("[INFO] AI Engine berjalan... Tekan CTRL+C untuk berhenti.")

frame_count = 0
start_time = time.time()
last_firebase_update = time.time()

try:
    while True:
        ret, frame = cap.read()
        
        # Skenario jika Tailscale/Internet putus (Auto-Reconnect)
        if not ret:
            print("[WARNING] Frame kosong. Coba menyambung kembali (Auto-Reconnect)...")
            # Update status Firebase menjadi Error sementara
            try: db_ref.update({'status': 'OFFLINE/RECONNECTING'})
            except: pass
            
            cap.release()
            time.sleep(3)
            cap = connect_camera()
            continue

        # A. Restorasi Visual AI Malam Hari
        frame, is_night = apply_night_vision(frame)

        # B. Deteksi YOLOv8
        results = yolo_model(frame, classes=TARGET_CLASSES, verbose=False)
        counts = {'mobil': 0, 'motor': 0, 'berat': 0}
        
        for result in results:
            for box in result.boxes:
                cls_id = int(box.cls[0])
                conf = float(box.conf[0])
                
                if conf > 0.4: # Minimal kepercayaan AI 40%
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    
                    if cls_id == 2:
                        counts['mobil'] += 1
                        color, label = ((255, 100, 0), "Mobil")
                    elif cls_id == 3:
                        counts['motor'] += 1
                        color, label = ((0, 255, 255), "Motor")
                    elif cls_id in [5, 7]:
                        counts['berat'] += 1
                        color, label = ((0, 0, 255), "Truk/Bus")
                    
                    # Gambar kotak (Bounding Box)
                    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                    cv2.putText(frame, f"{label} {conf:.2f}", (x1, y1-5), 
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

        # C. Kalkulasi FPS Peladen (GPU/CPU lokal)
        frame_count += 1
        elapsed_time = time.time() - start_time
        current_fps = frame_count / elapsed_time
        
        # D. Tulis frame hasil AI ke pipa FFmpeg (Push ke AWS)
        try:
            ffmpeg_process.stdin.write(frame.tobytes())
        except Exception as e:
            print(f"[ERROR] Pipa FFmpeg terputus. Pastikan server AWS RTMP aktif! Error: {e}")
            break

        # E. Sinkronisasi Data ke Firebase (Setiap 2.0 Detik)
        if time.time() - last_firebase_update > 2.0:
            payload = {
                'timestamp': time.time(),
                'jumlah_mobil': counts['mobil'],
                'jumlah_motor': counts['motor'],
                'jumlah_berat': counts['berat'],
                'total_kendaraan': sum(counts.values()),
                'server_fps': round(current_fps, 1),
                'night_vision_status': is_night,
                'status': 'ONLINE'
            }
            try:
                # Update ke Firebase tanpa memblokir thread
                db_ref.update(payload)
            except Exception as e:
                print(f"[WARNING] Gagal update Firebase: {e}")
                
            last_firebase_update = time.time()
            
            # Reset perhitungan FPS setiap 10 detik agar tetap akurat
            if elapsed_time > 10:
                start_time = time.time()
                frame_count = 0

except KeyboardInterrupt:
    print("\n[INFO] AI Engine dihentikan secara manual (CTRL+C).")
except Exception as e:
    print(f"\n[CRITICAL ERROR] Terjadi kesalahan sistem: {e}")
finally:
    # Pembersihan Resource (Clean-up)
    print("[INFO] Membersihkan resource memori dan jaringan...")
    if cap.isOpened():
        cap.release()
    if ffmpeg_process:
        ffmpeg_process.stdin.close()
        ffmpeg_process.wait()
    try: db_ref.update({'status': 'OFFLINE'})
    except: pass
    print("[INFO] Selesai.")
