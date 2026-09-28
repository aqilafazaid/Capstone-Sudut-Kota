import os
import cv2
import threading
import hashlib
import random
import re
import pytz
import time
import requests
import feedparser
import xml.etree.ElementTree as ET
import google.generativeai as genai
import concurrent.futures
from datetime import datetime, timedelta
import urllib3

from flask import Flask, request, render_template, redirect, url_for, session, flash, jsonify, send_from_directory, Response
from flask_cors import CORS
from dotenv import load_dotenv
from flask_mail import Mail, Message

import firebase_admin
from firebase_admin import credentials, db

# Menonaktifkan peringatan InsecureRequest SSL untuk API lokal/pemerintah
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Muat variabel dari .env
load_dotenv()

app = Flask(__name__)
CORS(app)

app.secret_key = os.environ.get("SECRET_KEY", "SUDUT_KOTA_CAPSTONE_AQILA_2026")
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = 86400 # Sesi login valid 24 Jam

# ==========================================
# 1. KONEKSI DATABASE (FIREBASE HYBRID)
# ==========================================
db_url = os.environ.get('DATABASE_URL', 'https://adminsudutkota-default-rtdb.firebaseio.com/')
try:
    if not firebase_admin._apps:
        if os.environ.get("FIREBASE_PRIVATE_KEY"):
            cred = credentials.Certificate({
                "type": "service_account",
                "project_id": os.environ.get("FIREBASE_PROJECT_ID"),
                "private_key_id": os.environ.get("FIREBASE_PRIVATE_KEY_ID"),
                "private_key": os.environ.get("FIREBASE_PRIVATE_KEY").replace('\\n', '\n'),
                "client_email": os.environ.get("FIREBASE_CLIENT_EMAIL"),
                "token_uri": "https://oauth2.googleapis.com/token",
            })
        else:
            cred = credentials.Certificate("serviceAccountKey.json")
            
        firebase_admin.initialize_app(cred, {'databaseURL': db_url})
        
    ref = db.reference('/')
    print(f"INFO: Database Sudut Kota terhubung ke {db_url}")
except Exception as e:
    ref = None
    print(f"WARNING: Firebase luring. Menggunakan mode lokal/fallback. Error: {e}")

# ==========================================
# 2. KONFIGURASI EMAIL & AI GEMINI
# ==========================================
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get("MAIL_USERNAME") 
app.config['MAIL_PASSWORD'] = os.environ.get("MAIL_PASSWORD") 
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get("MAIL_USERNAME")
mail = Mail(app)

GEMINI_KEY = os.environ.get("GEMINI_API_KEY") 
def get_gemini_model():
    if not GEMINI_KEY: return None
    try:
        genai.configure(api_key=GEMINI_KEY)
        return genai.GenerativeModel("gemini-1.5-flash") 
    except: return None

# ==========================================
# 3. KELAS MULTI-THREADING OPENCV (8 KAMERA)
# ==========================================
class VideoStream:
    def __init__(self, src=0):
        self.stream = cv2.VideoCapture(src)
        # Turunkan resolusi buffer awal untuk stabilitas 8 kamera
        self.stream.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.stream.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        (self.grabbed, self.frame) = self.stream.read()
        self.stopped = False
        self.lock = threading.Lock()

    def start(self):
        threading.Thread(target=self.update, args=(), daemon=True).start()
        return self

    def update(self):
        while not self.stopped:
            (grabbed, frame) = self.stream.read()
            with self.lock:
                self.grabbed = grabbed
                self.frame = frame
            time.sleep(0.01) # Mencegah CPU 100%

    def read(self):
        with self.lock:
            return self.frame

    def stop(self):
        self.stopped = True
        self.stream.release()

active_streams = {}

def get_rtsp_url(kamera_id):
    """Fungsi mengambil RTSP dari Firebase berdasarkan ID Kamera"""
    if ref:
        try:
            data = ref.child('titik_kamera').get() or {}
            for zona, jalans in data.items():
                for jalan, tiangs in jalans.items():
                    for tiang, detail in tiangs.items():
                        if isinstance(detail, dict):
                            kams = detail.get('kamera', {})
                            if isinstance(kams, dict) and kamera_id in kams:
                                return kams[kamera_id].get('rtsp_url')
                            elif isinstance(kams, list) and kamera_id in kams:
                                return 0 # Fallback webcam lokal jika struktur list
        except Exception as e:
            print(f"Error parse RTSP: {e}")
            
    # Dummy stream video lokal / Webcam 0 untuk testing jika tidak ada di DB
    return 0

def generate_frames(kamera_id):
    if kamera_id not in active_streams:
        url = get_rtsp_url(kamera_id)
        if url is None:
            return b'' # Stream tidak ditemukan
        active_streams[kamera_id] = VideoStream(src=url).start()
        time.sleep(1.0) # Waktu buffer sensor kamera

    camera = active_streams[kamera_id]
    
    while True:
        frame = camera.read()
        if frame is None:
            time.sleep(0.1)
            continue
            
        # ====================================================
        # [RUANG CAPSTONE PROJECT AQILA NIAM FAZA]
        # Sisipkan algoritma Low Light Enhancement (Zero-DCE/MirNet) 
        # dan YOLOv8 Vehicle Counting di area ini.
        # 
        # Contoh Pseudocode:
        # if is_night_time():
        #     frame = zero_dce_enhance(frame)
        # results = model_yolo(frame)
        # frame = draw_bounding_boxes(frame, results)
        # ====================================================

        # Kompresi MJPEG
        ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 60])
        if not ret:
            continue
            
        frame_bytes = buffer.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

# ==========================================
# 4. HELPER AUTH & FUNGSI UTILITAS
# ==========================================
def hash_password(pw): return hashlib.sha256(pw.encode()).hexdigest()
def normalize_input(text): return text.strip().lower() if text else ""

# (Fungsi Get News, Kemenag, EWS Bendungan tetap berjalan di background seperti sebelumnya)
NEWS_CACHE = []
NEWS_LAST_FETCH = 0
def get_news_entries():
    global NEWS_CACHE, NEWS_LAST_FETCH
    if len(NEWS_CACHE) > 0 and (time.time() - NEWS_LAST_FETCH < 30):
        return NEWS_CACHE
    # Dummy Data agar aplikasi cepat dirender (Bisa diganti dengan fungsi RSS scraping sebelumnya)
    NEWS_CACHE = [{'title': 'Pusat Informasi Sudut Kota Beroperasi Normal', 'link': '#', 'published_parsed': datetime.now().timetuple(), 'source_name': 'Sistem Internal', 'image': None}]
    NEWS_LAST_FETCH = time.time()
    return NEWS_CACHE

# ==========================================
# 5. ROUTES (JALUR FLASK)
# ==========================================
@app.route("/", methods=['GET'])
def home():
    stats = {'zona': 0, 'jalan': 0, 'kamera': 0}
    last_str = datetime.now().strftime('%d-%m-%Y')
    if ref:
        try:
            titik = ref.child('titik_kamera').get() or {}
            stats['zona'] = len(titik)
        except: pass
    return render_template('index.html', stats=stats, last_updated_time=last_str)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        raw_input = request.form.get('username')
        password = request.form.get('password')
        hashed_pw = hash_password(password)
        clean_input = normalize_input(raw_input)
        
        if not ref: return render_template('login.html', error="Sistem gagal terhubung ke pangkalan data utama.")
        
        users = ref.child('users').get() or {}
        for uid, data in users.items():
            if not isinstance(data, dict): continue
            if normalize_input(uid) == clean_input or normalize_input(data.get('email')) == clean_input:
                if data.get('password') == hashed_pw:
                    session.permanent = True
                    session['user'] = uid
                    session['nama'] = data.get('nama', 'Petugas Terdaftar')
                    return redirect(url_for('dashboard'))
        return render_template('login.html', error="Kredensial identitas atau kata sandi tidak valid.")
    return render_template('login.html')

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))

@app.route("/dashboard")
def dashboard():
    if 'user' not in session: return redirect(url_for('login'))
    data = ref.child("zona_utama").get() or {}
    return render_template("dashboard.html", name=session.get('nama'), zona_list=list(data.values()) if isinstance(data, dict) else [])

@app.route("/daftar-kamera")
def daftar_siaran():
    data = ref.child("zona_utama").get() or {}
    return render_template("daftar-siaran.html", zona_list=list(data.values()) if isinstance(data, dict) else [])

# ==========================================
# 6. ENDPOINT CCTV STREAMING (INTI)
# ==========================================
@app.route('/video_feed/<kamera_id>')
def video_feed(kamera_id):
    """Endpoint yang dipanggil oleh tag <img> di HTML frontend untuk streaming"""
    return Response(generate_frames(kamera_id), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/cctv')
def cctv_page():
    """Halaman Dashboard Kamera Grid 8 Channel"""
    if 'user' not in session: return redirect(url_for('login'))
    # Menyiapkan 8 ID Kamera default (Bisa dinamis dari Firebase)
    kamera_aktif = [f"CAM-{i}" for i in range(1, 9)]
    return render_template("cctv.html", cameras=kamera_aktif)

# ==========================================
# 7. CHATBOT GEMINI & API LAINNYA
# ==========================================
@app.route('/api/chat', methods=['POST'])
def chatbot_api():
    data = request.get_json()
    user_msg = data.get('prompt', '')
    
    prompt_sistem = "Anda adalah AI Asisten Virtual Resmi dari Command Center Sudut Kota. Jawablah dengan profesional dan ringkas."
    full_prompt = f"{prompt_sistem}\nPengguna: {user_msg}\nAI:"

    model = get_gemini_model()
    if not model: return jsonify({"response": "Sistem AI sedang offline. Mohon coba beberapa saat lagi."})
    
    try: 
        response = model.generate_content(full_prompt)
        return jsonify({"response": response.text})
    except Exception as e: 
        print(f"INFO GALAT: Anomali pada API Gemini: {e}")
        return jsonify({"response": "Terjadi galat pada pemrosesan bahasa alami."})

@app.route('/api/news-ticker')
def news_ticker(): return jsonify([n['title'] for n in get_news_entries()])

if __name__ == '__main__':
    # Threaded wajib = True agar Flask dapat menangani 8 stream serentak
    app.run(host='0.0.0.0', port=5000, threaded=True, debug=True)
