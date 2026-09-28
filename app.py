import os
import hashlib
import random
import time
from datetime import datetime
import requests
import feedparser
import google.generativeai as genai
import urllib3

from flask import Flask, request, render_template, redirect, url_for, session, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
from flask_mail import Mail

import firebase_admin
from firebase_admin import credentials, db

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
load_dotenv()

app = Flask(__name__)
CORS(app)

app.secret_key = os.environ.get("SECRET_KEY", "SUDUT_KOTA_OFFICIAL_SECRET_KEY")
app.config['SESSION_PERMANENT'] = True

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
            firebase_admin.initialize_app(cred, {'databaseURL': db_url})
        elif os.path.exists("serviceAccountKey.json"):
            cred = credentials.Certificate("serviceAccountKey.json")
            firebase_admin.initialize_app(cred, {'databaseURL': db_url})
            
    ref = db.reference('/') if firebase_admin._apps else None
except Exception as e:
    ref = None

# ==========================================
# ROUTES UTAMA
# ==========================================
@app.route("/", methods=['GET'])
def home():
    stats = {'zona': 0, 'jalan': 0, 'kamera': 0}
    last_str = datetime.now().strftime('%d-%m-%Y')
    if ref:
        try:
            titik_cctv = ref.child('titik_kamera').get() or {}
            stats['zona'] = len(titik_cctv)
            for zona, jalan in titik_cctv.items():
                if isinstance(jalan, dict):
                    stats['jalan'] += len(jalan)
                    for j, tiang in jalan.items():
                        if isinstance(tiang, dict):
                            for t, detail in tiang.items():
                                if 'kamera' in detail:
                                    stats['kamera'] += len(detail['kamera'])
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
    return render_template("cctv.html", cameras=[f"CAM-{i}" for i in range(1, 9)])

if __name__ == '__main__':
    app.run(debug=True)
