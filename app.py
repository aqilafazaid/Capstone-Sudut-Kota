import os
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

from flask import Flask, request, render_template, redirect, url_for, session, flash, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
from flask_mail import Mail, Message

import firebase_admin
from firebase_admin import credentials, db

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
load_dotenv()

app = Flask(__name__)
CORS(app)

app.secret_key = os.environ.get("SECRET_KEY", "SUDUT_KOTA_OFFICIAL_SECRET_KEY")
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = 86400

# ==========================================
# KONEKSI FIREBASE
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
            if os.path.exists("serviceAccountKey.json"):
                cred = credentials.Certificate("serviceAccountKey.json")
            else:
                cred = None
        
        if cred:
            firebase_admin.initialize_app(cred, {'databaseURL': db_url})
            
    ref = db.reference('/') if firebase_admin._apps else None
except Exception as e:
    ref = None

# ==========================================
# KONFIGURASI EMAIL & GEMINI AI
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
# ROUTES UTAMA (VERCEL COMPATIBLE)
# ==========================================
@app.route("/", methods=['GET'])
def home():
    stats = {'zona': 4, 'jalan': 12, 'kamera': 8}
    last_str = datetime.now().strftime('%d-%m-%Y')
    if ref:
        try:
            titik_cctv = ref.child('titik_kamera').get() or {}
            stats['zona'] = len(titik_cctv)
        except: pass
    return render_template('index.html', stats=stats, last_updated_time=last_str)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        raw_input = request.form.get('username')
        password = request.form.get('password')
        hashed_pw = hashlib.sha256(password.encode()).hexdigest()
        clean_input = raw_input.strip().lower() if raw_input else ""
        
        if not ref: return render_template('login.html', error="Sistem database offline.")
        users = ref.child('users').get() or {}
        
        for uid, data in users.items():
            if isinstance(data, dict) and (uid.lower() == clean_input or data.get('email', '').lower() == clean_input):
                if data.get('password') == hashed_pw:
                    session.permanent = True
                    session['user'] = uid
                    session['nama'] = data.get('nama', 'Petugas')
                    return redirect(url_for('dashboard'))
        return render_template('login.html', error="Kredensial tidak valid.")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route("/dashboard")
def dashboard():
    if 'user' not in session: return redirect(url_for('login'))
    return render_template("dashboard.html", name=session.get('nama'))

@app.route("/daftar-kamera")
def daftar_siaran():
    return render_template("daftar-siaran.html", zona_list=[])

@app.route('/cctv')
def cctv_page():
    if 'user' not in session: return redirect(url_for('login'))
    # Di sini halaman CCTV frontend Vercel akan mengambil stream dari domain Cloudflare Tunnel PC Lokal Dishub
    return render_template("cctv.html", cameras=[f"CAM-{i}" for i in range(1, 9)])

@app.route('/api/chat', methods=['POST'])
def chatbot_api():
    data = request.get_json()
    user_msg = data.get('prompt', '')
    model = get_gemini_model()
    if not model: return jsonify({"response": "AI sedang tidak aktif."})
    try:
        response = model.generate_content(f"Jawab profesional sebagai AI Dishub Pekalongan: {user_msg}")
        return jsonify({"response": response.text})
    except:
        return jsonify({"response": "Terjadi galat pada sistem AI."})

@app.route('/about')
def about(): return render_template('about.html')

@app.route('/sitemap.xml')
def sitemap(): return send_from_directory('static', 'sitemap.xml')

# Jalankan lokal jika bukan di serverless Vercel
if __name__ == '__main__':
    app.run(debug=True)
