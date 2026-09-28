import os
import cv2
import threading
import time
from flask import Flask, render_template, Response, jsonify
import firebase_admin
from firebase_admin import credentials, db

app = Flask(__name__)

# ==========================================
# 1. KONEKSI FIREBASE (HYBRID FALLBACK)
# ==========================================
try:
    if not firebase_admin._apps:
        cred = credentials.Certificate("serviceAccountKey.json")
        firebase_admin.initialize_app(cred, {'databaseURL': 'https://adminsudutkota-default-rtdb.firebaseio.com/'})
    ref = db.reference('/')
    print("INFO: Terhubung ke Firebase.")
except Exception as e:
    ref = None
    print(f"WARNING: Firebase luring. Menggunakan mode lokal. Error: {e}")

# ==========================================
# 2. KELAS PEMBACA STREAM (ASINKRON)
# ==========================================
class VideoStream:
    def __init__(self, src=0):
        self.stream = cv2.VideoCapture(src)
        # Turunkan resolusi buffer untuk menghemat CPU pada 8 kamera
        self.stream.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.stream.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        (self.grabbed, self.frame) = self.stream.read()
        self.stopped = False
        self.lock = threading.Lock()

    def start(self):
        # Jalankan thread terpisah untuk membaca frame
        threading.Thread(target=self.update, args=(), daemon=True).start()
        return self

    def update(self):
        while not self.stopped:
            (grabbed, frame) = self.stream.read()
            with self.lock:
                self.grabbed = grabbed
                self.frame = frame
            time.sleep(0.01) # Mencegah bottleneck CPU

    def read(self):
        with self.lock:
            return self.frame

    def stop(self):
        self.stopped = True
        self.stream.release()

# Dictionary untuk menyimpan instance stream yang aktif
active_streams = {}

def get_rtsp_url(kamera_id):
    """Mengambil URL RTSP dari Firebase, atau gunakan dummy/webcam lokal jika gagal"""
    if ref:
        try:
            # Query pencarian di seluruh titik (disesuaikan dengan path Firebase Anda)
            data = ref.child('titik_kamera').get()
            for zona, jalans in data.items():
                for jalan, tiangs in jalans.items():
                    for tiang, detail in tiangs.items():
                        kamera_dict = detail.get('kamera', {})
                        if kamera_id in kamera_dict:
                            return kamera_dict[kamera_id].get('rtsp_url')
        except:
            pass
    # Fallback untuk testing lokal
    return 0 if kamera_id == "CAM-TEST" else None

# ==========================================
# 3. GENERATOR MJPEG & ROUTES
# ==========================================
def generate_frames(kamera_id):
    if kamera_id not in active_streams:
        url = get_rtsp_url(kamera_id)
        if url is None:
            return b'' # Kamera tidak ditemukan
        active_streams[kamera_id] = VideoStream(src=url).start()
        time.sleep(1.0) # Waktu pemanasan sensor/buffer

    camera = active_streams[kamera_id]
    
    while True:
        frame = camera.read()
        if frame is None:
            continue
            
        # Optional: Sisipkan logika YOLOv8 Object Detection di sini
        
        ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if not ret:
            continue
            
        frame_bytes = buffer.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

@app.route('/video_feed/<kamera_id>')
def video_feed(kamera_id):
    """Endpoint untuk tag <img> di sisi frontend"""
    return Response(generate_frames(kamera_id), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/cctv_dashboard')
def cctv_dashboard():
    # Render dashboard yang menampilkan 8 tag image sekaligus
    return render_template('cctv_grid.html', cameras=[f"CAM-{i}" for i in range(1, 9)])

if __name__ == '__main__':
    # Threaded wajib True agar Flask bisa melayani banyak request gambar bersamaan
    app.run(host='0.0.0.0', port=5000, threaded=True, debug=True)
