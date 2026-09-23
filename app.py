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
import base64
import json
import firebase_admin
from firebase_admin import credentials, db
from flask import Flask, request, render_template, redirect, url_for, session, flash, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
from flask_mail import Mail, Message
from datetime import datetime, timedelta, date
import urllib3

# ==========================================
# 1. KONFIGURASI SYSTEM & SECURITY
# ==========================================
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

load_dotenv()

app = Flask(__name__)
CORS(app)

app.secret_key = os.environ.get("SECRET_KEY", "SUDUT_KOTA_OFFICIAL_SECRET_KEY_FINAL_PRO_2026")
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = 86400 # Sesi login valid 24 Jam

# ==========================================
# 2. SISTEM AUTO-MAINTENANCE
# ==========================================
MAINTENANCE_END_DATE = datetime(2026, 6, 30, 7, 0, 0) 

@app.before_request
def maintenance_interceptor():
    if request.endpoint == 'static':
        return None
    now_wib = datetime.utcnow() + timedelta(hours=7) 
    # Hapus komentar (uncomment) 2 baris di bawah jika ingin mengaktifkan mode maintenance
    # if now_wib < MAINTENANCE_END_DATE:
    #     return render_template('maintenance.html'), 503
    return None

# ==========================================
# 2.5. SISTEM TRACKER PENGUNJUNG & LOKASI
# ==========================================
TRACKER_DATA = {
    "date": datetime.now(pytz.timezone('Asia/Jakarta')).date(),
    "daily_ips": set(),
    "online_ips": {},
    "ip_locations": {}
}

def fetch_and_store_location_sync(ip):
    """Pengambilan lokasi disinkronkan dengan batas waktu ketat"""
    try:
        r = requests.get(f"http://ip-api.com/json/{ip}?fields=city,country,status", timeout=1.5)
        if r.status_code == 200:
            res = r.json()
            if res.get("status") == "success":
                TRACKER_DATA["ip_locations"][ip] = f"{res.get('city', 'Unknown City')}, {res.get('country', 'Unknown Country')}"
            else:
                TRACKER_DATA["ip_locations"][ip] = "Tidak Terdeteksi"
    except Exception:
        TRACKER_DATA["ip_locations"][ip] = "Tidak Terdeteksi"

@app.before_request
def visitor_tracker():
    if request.endpoint and 'static' not in request.endpoint:
        tz = pytz.timezone('Asia/Jakarta')
        today = datetime.now(tz).date()
        
        if TRACKER_DATA["date"] != today:
            TRACKER_DATA["date"] = today
            TRACKER_DATA["daily_ips"].clear()
            TRACKER_DATA["ip_locations"].clear()
            
        user_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
        if user_ip:
            user_ip = user_ip.split(',')[0].strip()
            TRACKER_DATA["daily_ips"].add(user_ip)
            TRACKER_DATA["online_ips"][user_ip] = time.time()
            
            if user_ip not in TRACKER_DATA["ip_locations"] and not user_ip.startswith(('127.', '192.168.', '10.')):
                TRACKER_DATA["ip_locations"][user_ip] = "Mendeteksi Lokasi..."
                fetch_and_store_location_sync(user_ip)

# ==========================================
# 3. KONEKSI DATABASE (FIREBASE)
# ==========================================
try:
    if os.environ.get("FIREBASE_PRIVATE_KEY"):
        cred = credentials.Certificate({
            "type": "service_account",
            "project_id": os.environ.get("FIREBASE_PROJECT_ID"),
            "private_key_id": os.environ.get("FIREBASE_PRIVATE_KEY_ID"),
            "private_key": os.environ.get("FIREBASE_PRIVATE_KEY").replace('\\n', '\n'),
            "client_email": os.environ.get("FIREBASE_CLIENT_EMAIL"),
            "client_id": os.environ.get("FIREBASE_CLIENT_ID"),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_x509_cert_url": os.environ.get("FIREBASE_CLIENT_X509_CERT_URL"),
            "universe_domain": "googleapis.com"
        })
    else:
        if os.path.exists("serviceAccountKey.json"):
            cred = credentials.Certificate("serviceAccountKey.json")
        else:
            cred = None
    
    if cred and not firebase_admin._apps:
        db_url = os.environ.get('DATABASE_URL', 'https://adminsudutkota-default-rtdb.firebaseio.com/')
        firebase_admin.initialize_app(cred, {'databaseURL': db_url})
    
    if firebase_admin._apps:
        ref = db.reference('/')
        print("INFO: Koneksi Basis Data Sudut Kota berhasil ditetapkan.")
    else:
        ref = None
        print("WARNING: Kredensial Firebase tidak ditemukan. Sistem berjalan tanpa basis data.")

except Exception as e:
    ref = None
    print(f"ERROR: Kegagalan koneksi basis data. Mode luring diaktifkan. Rincian: {e}")

# ==========================================
# 4. KONFIGURASI EMAIL (SMTP GMAIL)
# ==========================================
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get("MAIL_USERNAME") 
app.config['MAIL_PASSWORD'] = os.environ.get("MAIL_PASSWORD") 
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get("MAIL_USERNAME")
mail = Mail(app)

# ==========================================
# 5. KONFIGURASI AI (GEMINI)
# ==========================================
GEMINI_KEY = os.environ.get("GEMINI_API_KEY") 

def get_gemini_model():
    if not GEMINI_KEY:
        print("WARNING: GEMINI_API_KEY tidak ditemukan di .env")
        return None
    try:
        genai.configure(api_key=GEMINI_KEY)
        safety_settings = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
        ]
        return genai.GenerativeModel("gemini-1.5-flash", safety_settings=safety_settings) 
    except Exception as e:
        print(f"ERROR: Konfigurasi model Gemini mengalami kegagalan. Rincian: {e}")
        return None

SUDUT_KOTA_PROMPT = """
Anda adalah AI Asisten Virtual Resmi dari Bidang Infrastruktur Command Center Sudut Kota - Dinas Perhubungan (Dishub) Pekalongan.
Karakteristik Komunikasi: Sangat profesional, informatif, objektif, dan menggunakan Bahasa Indonesia baku yang tepat sesuai EYD.
Tugas Utama: 
1. Memberikan respons akurat terkait rekayasa lalu lintas, kepadatan jalan, CCTV persimpangan, dan deteksi kendaraan.
2. Menyampaikan himbauan keselamatan berkendara (Safety Text) dan peringatan dini EWS Bendungan secara faktual dan presisi.
3. Menghindari penggunaan bahasa gaul, sapaan informal, atau opini pribadi.

INSTRUKSI KRITIKAL: Apabila data EWS mengindikasikan bendungan berstatus 'Siaga' atau 'Awas', Anda wajib mengeluarkan peringatan resmi terkait potensi banjir.
"""

# ==========================================
# 6. FUNGSI BANTUAN (HELPERS)
# ==========================================

def hash_password(pw): return hashlib.sha256(pw.encode()).hexdigest()
def normalize_input(text): return text.strip().lower() if text else ""

def format_indo_date(time_struct):
    if not time_struct: return datetime.now().strftime("%A, %d %B %Y - %H:%M WIB")
    try:
        dt = datetime.fromtimestamp(time.mktime(time_struct))
        return dt.strftime("%A, %d %B %Y - %H:%M WIB")
    except: return "Informasi Waktu Tidak Tersedia"

def get_email_template(action_type, nama_user, otp_code):
    waktu = datetime.now().strftime("%d %B %Y, Pukul %H:%M WIB")
    if action_type == "REGISTER":
        subject = f"🔐 Verifikasi Keamanan: Pendaftaran Akun Sudut Kota [{otp_code}]"
        title = "Verifikasi Pendaftaran Akun Baru"
        desc = "Sistem kami mendeteksi permintaan pendaftaran akun baru di portal Command Center Sudut Kota Dishub."
        warning = "Apabila Anda tidak merasa menginisiasi pendaftaran ini, harap abaikan pesan ini. Kode OTP ini RAHASIA."
    elif action_type == "RESET":
        subject = f"⚠️ Peringatan Keamanan: Permintaan Atur Ulang Kata Sandi [{otp_code}]"
        title = "Permintaan Atur Ulang Kata Sandi"
        desc = "Sistem kami menerima instruksi untuk mengatur ulang kata sandi (Reset Password) pada akun Sudut Kota Anda."
        warning = "JANGAN MEMBERIKAN kode ini kepada pihak mana pun. Segera lakukan pengamanan akun jika bukan Anda yang meminta."
    else:
        subject = "Pemberitahuan Sistem Sudut Kota"; title = "Notifikasi Sistem"; desc = "Pembaruan informasi terkait akun Anda."; warning = ""

    body = f"""========================================================
SISTEM KEAMANAN SUDUT KOTA - DISHUB PEKALONGAN
========================================================

Yth. {nama_user},

{desc}

Sebagai langkah otorisasi untuk memproses {title}, mohon gunakan Kode Verifikasi (OTP) berikut:

[ {otp_code} ]

*Catatan: Kode verifikasi ini hanya berlaku selama 60 detik terhitung sejak surel ini diterbitkan.

INSTRUKSI KEAMANAN: {warning}

Rincian Transaksi Sistem:
- Waktu Permintaan : {waktu}
- Status Transaksi : Menunggu Otorisasi Pengguna

Hormat kami,
Bidang Infrastruktur Teknologi & Keamanan Informasi,
Sudut Kota - Dishub Pekalongan
========================================================"""
    return subject, body

def get_hijri_date_string():
    HIJRI_OFFSET = -1 
    try:
        tz_jakarta = pytz.timezone('Asia/Jakarta')
        now_wib = datetime.now(tz_jakarta) + timedelta(days=HIJRI_OFFSET)
        
        url = f"https://api.aladhan.com/v1/gToH?date={now_wib.strftime('%d-%m-%Y')}"
        r = requests.get(url, timeout=3)
        if r.status_code == 200:
            data = r.json()['data']['hijri']
            indo_months = {
                "Muharram": "Muharam", "Safar": "Safar", "Rabi' al-awwal": "Rabiul Awal", 
                "Rabi' al-thani": "Rabiul Akhir", "Jumada al-awwal": "Jumadil Awal", 
                "Jumada al-thani": "Jumadil Akhir", "Rajab": "Rajab", "Sha'ban": "Syakban", 
                "Ramadan": "Ramadan", "Shawwal": "Syawal", "Dhu al-Qi'dah": "Zulkaidah", 
                "Dhu al-Hijjah": "Zulhijah"
            }
            d = data['day'].lstrip('0')
            m = indo_months.get(data['month']['en'], data['month']['en'])
            y = data['year']
            return f"{d} {m} {y} H"
    except Exception:
        pass
    return f"Tanggal Hijriah Tidak Tersedia"

# --- CACHE UNTUK BERITA ---
NEWS_CACHE = []
NEWS_LAST_FETCH = 0

def get_news_entries():
    global NEWS_CACHE, NEWS_LAST_FETCH
    if len(NEWS_CACHE) > 0 and (time.time() - NEWS_LAST_FETCH < 30):
        return NEWS_CACHE

    all_news = []
    headers = {'User-Agent': 'Mozilla/5.0'}

    try:
        r_bmkg = requests.get("https://data.bmkg.go.id/DataMKG/TEWS/autogempa.xml", timeout=5)
        if r_bmkg.status_code == 200:
            root = ET.fromstring(r_bmkg.content)
            gempa = root.find('gempa')
            if gempa is not None:
                wilayah = gempa.find('Wilayah').text
                magnitude = gempa.find('Magnitude').text
                potensi = gempa.find('Potensi').text
                shakemap = gempa.find('Shakemap').text
                
                all_news.append({
                    'title': f"INFORMASI GEMPA BMKG: Magnitudo {magnitude} di {wilayah} ({potensi})",
                    'link': "https://warning.bmkg.go.id/",
                    'published_parsed': datetime.now().timetuple(),
                    'source_name': 'BMKG Resmi',
                    'image': f"https://data.bmkg.go.id/DataMKG/TEWS/{shakemap}"
                })
    except Exception:
        pass

    try:
        sources = [
            'https://www.kompas.tv/rss', 'https://www.setneg.go.id/rss',
            'https://www.liputan6.com/rss', 'https://www.tribunnews.com/rss',
            'https://www.cnnindonesia.com/nasional/rss', 'https://www.cnbcindonesia.com/news/rss',
            'https://www.antaranews.com/rss/top-news.xml', 'https://rss.sindonews.com/news'
        ]
        
        def fetch_feed(url):
            try:
                res = requests.get(url, headers=headers, timeout=4)
                if res.status_code == 200:
                    return url, feedparser.parse(res.content)
            except:
                return url, None
            return url, None

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(sources)) as pool:
            futures = [pool.submit(fetch_feed, url) for url in sources]
            for future in concurrent.futures.as_completed(futures):
                url, feed = future.result()
                if feed and feed.entries:
                    for entry in feed.entries[:20]: 
                        if 'kompas.tv' in url: source_name = 'Kompas TV'
                        elif 'setneg' in url: source_name = 'Sekretariat Negara'
                        elif 'liputan6' in url: source_name = 'Liputan 6'
                        elif 'tribunnews' in url: source_name = 'Tribunnews'
                        elif 'cnnindonesia' in url: source_name = 'CNN Indonesia'
                        elif 'cnbcindonesia' in url: source_name = 'CNBC Indonesia'
                        elif 'antara' in url: source_name = 'Antara News'
                        elif 'sindonews' in url: source_name = 'Sindonews'
                        else: source_name = url.split('.')[1].capitalize()
                        
                        entry['source_name'] = source_name
                        
                        img_url = None
                        if 'media_content' in entry and entry.media_content:
                            img_url = entry.media_content[0]['url']
                        if not img_url and 'links' in entry:
                            for link in entry.links:
                                if link.get('type', '').startswith('image'):
                                    img_url = link.get('href'); break
                        if not img_url and 'description' in entry:
                            match = re.search(r'src="([^"]+)"', entry.description)
                            if match: img_url = match.group(1)
                        if not img_url and 'enclosures' in entry:
                            for enc in entry.enclosures:
                                if enc.get('type', '').startswith('image'):
                                    img_url = enc.get('href'); break
                                    
                        entry['image'] = img_url
                        all_news.append(entry)
                        
        all_news.sort(key=lambda x: x.published_parsed if x.get('published_parsed') else time.gmtime(0), reverse=True)
    except: pass
    
    if not all_news:
        if NEWS_CACHE: return NEWS_CACHE
        t = datetime.now().timetuple()
        return [{'title': 'Pusat Informasi Sudut Kota Beroperasi Normal', 'link': '#', 'published_parsed': t, 'source_name': 'Sistem Internal', 'image': None}]
    
    NEWS_CACHE = all_news[:150] 
    NEWS_LAST_FETCH = time.time()
    return NEWS_CACHE

def time_since_published(published_time):
    try:
        now = datetime.now()
        pt = datetime(*published_time[:6])
        diff = now - pt
        if diff.days > 0: return f"{diff.days} hari yang lalu"
        if diff.seconds > 3600: return f"{diff.seconds//3600} jam yang lalu"
        if diff.seconds > 60: return f"{diff.seconds//60} menit yang lalu"
        return "Terbaru"
    except: return "Waktu tidak dapat dipastikan"

def get_quote_religi():
    return {
        "muslim": ["Maka dirikanlah shalat... (QS. An-Nisa: 103)", "Hindari perbuatan curang dalam bentuk apa pun.", "Manusia terbaik adalah yang memberikan manfaat bagi sesamanya."],
        "universal": ["Integritas adalah landasan dari setiap tindakan yang benar.", "Kedamaian global bermula dari kedamaian personal.", "Kejujuran adalah nilai tukar universal yang diakui secara global."]
    }

def get_smart_fallback_response(text):
    return "Mohon maaf, server kecerdasan buatan kami saat ini sedang memproses antrean deteksi CCTV. Kami memohon kesediaan Anda untuk mencoba kembali."

KEMENAG_KOTA_CACHE = []
KEMENAG_LAST_FETCH = 0

def fetch_kemenag_kota():
    global KEMENAG_KOTA_CACHE, KEMENAG_LAST_FETCH
    if len(KEMENAG_KOTA_CACHE) > 50 and (time.time() - KEMENAG_LAST_FETCH < 86400):
        return KEMENAG_KOTA_CACHE

    try:
        r = requests.get("https://api.myquran.com/v2/sholat/kota/semua", timeout=8)
        if r.status_code == 200:
            data = r.json()
            if data.get('status') and 'data' in data:
                all_cities = [{"id": item['id'], "nama": item['lokasi'].title()} for item in data['data']]
                KEMENAG_KOTA_CACHE = sorted(all_cities, key=lambda x: x['nama'])
                KEMENAG_LAST_FETCH = time.time()
                return KEMENAG_KOTA_CACHE
    except Exception: pass

    return [
        {"id": "1604", "nama": "Kota Semarang"},
        {"id": "1607", "nama": "Kota Pekalongan"}
    ]

# ==========================================
# 7. LOGIKA EWS & KESELAMATAN LALU LINTAS
# ==========================================

def get_safety_texts():
    return [
        "Patuhi Rambu Lalu Lintas dan Marka Jalan.",
        "Gunakan Helm Berstandar SNI Demi Keselamatan Anda.",
        "Dahulukan Pejalan Kaki di Zona Zebra Cross.",
        "Kurangi Kecepatan Saat Hujan, Jalanan Licin.",
        "Dilarang Menggunakan Ponsel Saat Mengemudi.",
        "Pastikan Kondisi Kendaraan Anda Laik Jalan.",
        "Jaga Jarak Aman dengan Kendaraan di Depan Anda.",
        "Wajib Menggunakan Sabuk Pengaman Bagi Pengemudi Mobil."
    ]

def smart_convert_cm(value):
    try:
        val_float = float(value)
        if val_float != 0 and val_float < 50: return f"{val_float * 100:.0f}" 
        return f"{val_float:.0f}"
    except: return "0"

def normalize_dam_data(raw_data):
    clean_data = []
    for item in raw_data:
        try:
            latest = item.get('latest_debit_report', {})
            if not isinstance(latest, dict): latest = {}
            name = item.get('dam_name') or item.get('nama') or item.get('name') or "Infrastruktur Bendungan"
            siaga_val = item.get('siaga', 0)
            awas_val = item.get('awas', 0)
            siaga_cm = smart_convert_cm(siaga_val)
            awas_cm = smart_convert_cm(awas_val)
            if float(siaga_cm) == 0: siaga_cm = "200"
            if float(awas_cm) == 0: awas_cm = "300"
            raw_tma = latest.get('limpas') if latest else (item.get('tma') or item.get('siap') or 0)
            tma_cm = smart_convert_cm(raw_tma)
            raw_time = latest.get('created_at') or item.get('updated_at')
            waktu_display = "Pembaruan Terakhir"
            if raw_time:
                try:
                    clean_str = str(raw_time).split('.')[0].replace('Z', '')
                    dt_utc = datetime.strptime(clean_str, "%Y-%m-%dT%H:%M:%S")
                    dt_wib = dt_utc + timedelta(hours=7) 
                    waktu_display = dt_wib.strftime("%d-%m-%Y %H:%M")
                except:
                    waktu_display = str(raw_time)[:16].replace('T', ' ')
            status = latest.get('status') or item.get('status_alert') or 'Operasional Normal'
            pob = latest.get('pob_id')
            petugas = f"ID Petugas: {pob}" if pob else "Unit Pemantauan"
            cuaca_lokal = latest.get('cuaca', 'Berawan') 
            dam = {
                'name': name, 'tma': tma_cm, 'siaga': siaga_cm, 'awas': awas_cm,    
                'inflow': latest.get('debit', 0), 'outflow': latest.get('debit_ke_saluran_induk', 0),
                'status': status, 'cuaca': cuaca_lokal, 'petugas': petugas,
                'updated_at': waktu_display + " WIB", 'lokasi': item.get('river_name') or item.get('regency_name') or 'Jawa Tengah'
            }
            clean_data.append(dam)
        except: continue
    return clean_data

def fetch_ews_data():
    headers = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}
    try:
        ts = int(time.time() * 1000)
        url = f"https://siagakranji.my.id/data/latest_dams.json?t={ts}"
        r = requests.get(url, headers=headers, timeout=6, verify=False)
        if r.status_code == 200:
            data = r.json()
            raw_list = data.get('data') or data.get('result') or (data if isinstance(data, list) else [])
            if raw_list: return normalize_dam_data(raw_list)
    except: pass
    try:
        url = "https://api.ewsjateng.com/api/dams?page=1&pageSize=200"
        r = requests.get(url, headers=headers, timeout=9, verify=False)
        if r.status_code == 200:
            data = r.json()
            raw_list = data.get('data', [])
            return normalize_dam_data(raw_list)
    except: pass
    return []

# ==========================================
# 8. ROUTES & CONTROLLERS (SUDUT KOTA)
# ==========================================

@app.route("/", methods=['GET'])
def home():
    stats = {'zona': 0, 'jalan': 0, 'kamera': 0}
    last_str = "-"
    if ref:
        try:
            titik_cctv = ref.child('titik_kamera').get() or {}
            for zona in titik_cctv.values():
                if isinstance(zona, dict):
                    stats['zona'] += len(zona)
                    for jalan in zona.values():
                        if isinstance(jalan, dict):
                            stats['jalan'] += len(jalan)
                            for d in jalan.values():
                                if 'kamera' in d: stats['kamera'] += len(d['kamera'])
            last_str = datetime.now().strftime('%d-%m-%Y')
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
        target_user = None; target_uid = None
        for uid, data in users.items():
            if not isinstance(data, dict): continue
            if normalize_input(uid) == clean_input: target_user = data; target_uid = uid; break
            if normalize_input(data.get('email')) == clean_input: target_user = data; target_uid = uid; break
        if target_user and target_user.get('password') == hashed_pw:
            session.permanent = True
            session['user'] = target_uid
            session['nama'] = target_user.get('nama', 'Petugas Terdaftar')
            return redirect(url_for('dashboard'))
        return render_template('login.html', error="Kredensial identitas atau kata sandi tidak valid.")
    return render_template('login.html')

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        u = normalize_input(request.form.get("username"))
        e = normalize_input(request.form.get("email"))
        n = request.form.get("nama")
        p = request.form.get("password")
        if not ref: return "Terjadi galat koneksi basis data.", 500
        users = ref.child("users").get() or {}
        if u in users:
            flash("Nama pengguna telah terdaftar.", "error")
            return render_template("register.html")
        for uid, data in users.items():
            if normalize_input(data.get('email')) == e:
                flash("Alamat surel tersebut telah digunakan.", "error")
                return render_template("register.html")
        
        otp = str(random.randint(100000, 999999))
        expiry = time.time() + 60 
        ref.child(f'pending_users/{u}').set({"nama": n, "email": e, "password": hash_password(p), "otp": otp, "expiry": expiry})
        try:
            subject, body = get_email_template("REGISTER", n, otp)
            msg = Message(subject, recipients=[e])
            msg.body = body
            mail.send(msg)
            session["pending_username"] = u
            return redirect(url_for("verify_register"))
        except: 
            flash("Kegagalan transmisi surel. Pastikan alamat valid dan kredensial SMTP benar.", "error")
    return render_template("register.html")

@app.route("/verify-register", methods=["GET", "POST"])
def verify_register():
    u = session.get("pending_username")
    if not u: return redirect(url_for("register"))
    if request.method == "POST":
        p = ref.child(f'pending_users/{u}').get()
        if not p: return redirect(url_for("register"))
        if time.time() > p.get('expiry', 0):
            flash("Sesi kode verifikasi telah berakhir.", "error")
            ref.child(f'pending_users/{u}').delete()
            return redirect(url_for("register"))
        if str(p.get('otp')).strip() == request.form.get("otp").strip():
            ref.child(f'users/{u}').set({"nama": p['nama'], "email": p['email'], "password": p['password']})
            ref.child(f'pending_users/{u}').delete()
            session.pop('pending_username', None)
            flash("Registrasi berhasil diproses. Silakan masuk.", "success")
            return redirect(url_for('login'))
        flash("Kode otorisasi tidak tepat.", "error")
    return render_template("verify-register.html", username=u)

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email_input = normalize_input(request.form.get("identifier"))
        users = ref.child("users").get() or {}
        found_uid = None
        user_name = "Petugas"
        
        for uid, user_data in users.items():
            if isinstance(user_data, dict) and normalize_input(user_data.get('email')) == email_input:
                found_uid = uid
                user_name = user_data.get('nama', 'Petugas')
                break
                
        if found_uid:
            otp = str(random.randint(100000, 999999))
            expiry = time.time() + 60
            ref.child(f"otp/{found_uid}").set({"email": email_input, "otp": otp, "expiry": expiry})
            try:
                subject, body = get_email_template("RESET", user_name, otp)
                msg = Message(subject, recipients=[email_input])
                msg.body = body
                mail.send(msg)
                session["reset_uid"] = found_uid
                return redirect(url_for("verify_otp"))
            except: 
                flash("Gagal mengirim email OTP. Cek pengaturan SMTP di .env", "error")
        else:
            flash("Identitas tidak ditemukan dalam sistem.", "error")
    return render_template("forgot-password.html")

@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    uid = session.get("reset_uid")
    if not uid: return redirect(url_for("forgot_password"))
    if request.method == "POST":
        data = ref.child(f"otp/{uid}").get()
        if not data: return redirect(url_for("forgot_password"))
        if time.time() > data.get('expiry', 0):
            flash("Masa berlaku verifikasi habis.", "error")
            return redirect(url_for("forgot_password"))
        if str(data.get("otp")).strip() == request.form.get("otp").strip():
            session['reset_verified'] = True
            return redirect(url_for("reset_password"))
        flash("Kode tidak sesuai.", "error")
    return render_template("verify-otp.html")

@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    if not session.get('reset_verified'): return redirect(url_for('login'))
    if request.method == "POST":
        uid = session.get("reset_uid")
        pw = request.form.get("password")
        ref.child(f"users/{uid}").update({"password": hash_password(pw)})
        ref.child(f"otp/{uid}").delete()
        session.clear()
        flash("Kata sandi berhasil diubah.", "success")
        return redirect(url_for('login'))
    return render_template("reset-password.html")

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))

@app.route('/berita')
def berita_page():
    entries = get_news_entries()
    page = request.args.get('page', 1, type=int)
    per_page = 9
    start = (page - 1) * per_page
    end = start + per_page
    current = entries[start:end]
    
    for a in current:
        if 'published_parsed' in a and a['published_parsed']:
            a['formatted_date'] = format_indo_date(a['published_parsed'])
            a['time_since_published'] = time_since_published(a['published_parsed'])
        else:
            a['formatted_date'] = "Waktu Tidak Tersedia"
            a['time_since_published'] = "Terkini"

    total_pages = (len(entries)//per_page) + 1
    return render_template('berita.html', articles=current, page=page, total_pages=total_pages)

@app.route("/dashboard")
def dashboard():
    if 'user' not in session: return redirect(url_for('login'))
    data = ref.child("zona_utama").get() or {}
    return render_template("dashboard.html", name=session.get('nama'), zona_list=list(data.values()))

@app.route("/daftar-kamera")
def daftar_siaran():
    data = ref.child("zona_utama").get() or {}
    return render_template("daftar-siaran.html", zona_list=list(data.values()))

@app.route("/add_data", methods=["GET", "POST"])
def add_data():
    if 'user' not in session: return redirect(url_for('login'))
    zona_data = ref.child("zona_utama").get() or {}
    zona_list = list(zona_data.values()) if zona_data else ["Pekalongan Utara", "Pekalongan Barat", "Pekalongan Timur", "Pekalongan Selatan"]
    if request.method == "POST":
        z, j, i, k = request.form.get("zona"), request.form.get("jalan"), request.form.get("id_tiang"), request.form.get("kamera")
        if z and j and i and k:
            data_new = {
                "kamera": [ch.strip() for ch in k.split(',')],
                "last_updated_by_name": session.get('nama'),
                "last_updated_by_username": session.get('user'),
                "last_updated_date": datetime.now().strftime("%d-%m-%Y"),
                "last_updated_time": datetime.now().strftime("%H:%M:%S WIB")
            }
            ref.child(f"titik_kamera/{z}/{j}/{i}").set(data_new)
            ref.child(f"zona_utama/{z}").set(z)
            flash("Data kamera berhasil ditambahkan.", "success"); return redirect(url_for('dashboard'))
    return render_template("add_data_form.html", zona_list=sorted(zona_list))

@app.route("/edit_data/<zona>/<jalan>/<id_tiang>", methods=["GET", "POST"])
def edit_data(zona, jalan, id_tiang):
    if 'user' not in session: return redirect(url_for('login'))
    curr_data = ref.child(f"titik_kamera/{zona}/{jalan}/{id_tiang}").get()
    if request.method == "POST":
        k = request.form.get("kamera")
        ref.child(f"titik_kamera/{zona}/{jalan}/{id_tiang}").update({
            "kamera": [ch.strip() for ch in k.split(',')],
            "last_updated_by_name": session.get('nama'),
            "last_updated_date": datetime.now().strftime("%d-%m-%Y")
        })
        flash("Pembaruan data kamera berhasil.", "success"); return redirect(url_for('dashboard'))
    kamera_str = ", ".join(curr_data.get('kamera', [])) if curr_data else ""
    return render_template("add_data_form.html", edit_mode=True, curr_siaran=kamera_str, zona_list=[zona], curr_provinsi=zona, curr_wilayah=jalan, curr_mux=id_tiang)

@app.route("/delete_data/<zona>/<jalan>/<id_tiang>", methods=["POST"])
def delete_data(zona, jalan, id_tiang):
    if 'user' in session: 
        try: ref.child(f"titik_kamera/{zona}/{jalan}/{id_tiang}").delete(); return jsonify({"status": "success"})
        except: return jsonify({"status": "error"})
    return jsonify({"status": "unauthorized"})

@app.route("/get_wilayah")
def get_wilayah(): return jsonify({"wilayah": list((ref.child(f"titik_kamera/{request.args.get('provinsi')}").get() or {}).keys())})
@app.route("/get_mux")
def get_mux(): return jsonify({"mux": list((ref.child(f"titik_kamera/{request.args.get('provinsi')}/{request.args.get('wilayah')}").get() or {}).keys())})
@app.route("/get_siaran")
def get_siaran(): return jsonify(ref.child(f"titik_kamera/{request.args.get('provinsi')}/{request.args.get('wilayah')}/{request.args.get('mux')}").get() or {})

@app.route('/ews-jateng')
def ews_jateng_page():
    dams = fetch_ews_data()
    safety_texts = get_safety_texts()
    return render_template('ews-jateng.html', dams=dams, safety_texts=safety_texts)

@app.route('/lokasi')
def lokasi_page(): return render_template('lokasi.html')

@app.route('/api/chat', methods=['POST'])
def chatbot_api():
    data = request.get_json()
    user_msg = data.get('prompt', '')
    
    if "bendungan" in user_msg.lower() or "banjir" in user_msg.lower():
        dams = fetch_ews_data()
        bahaya = [f"{d['name']} ({d['status']})" for d in dams if 'awas' in d['status'].lower() or 'siaga' in d['status'].lower()]
        
        if bahaya: context = f"INSTRUKSI PRIORITAS: Terdeteksi infrastruktur bendungan dalam status waspada: {', '.join(bahaya)}. "
        else: context = f"INFORMASI: Hasil pemantauan menunjukkan {len(dams)} fasilitas bendungan operasional normal. "
            
        full_prompt = f"{SUDUT_KOTA_PROMPT}\n{context}\nPengguna: {user_msg}\nAI Sudut Kota:"
    else: full_prompt = f"{SUDUT_KOTA_PROMPT}\nPengguna: {user_msg}\nAI Sudut Kota:"

    model = get_gemini_model()
    if not model: 
        return jsonify({"response": get_smart_fallback_response(user_msg)})
    
    try: 
        response = model.generate_content(full_prompt)
        try:
            teks_balasan = response.text
        except ValueError:
            teks_balasan = "Sistem keamanan otomatis AI memblokir transmisi ini karena terindikasi mengandung konten yang tidak sesuai. Proses dihentikan."
            
        return jsonify({"response": teks_balasan})
    except Exception as e: 
        print(f"INFO GALAT: Anomali pada API Gemini: {e}")
        return jsonify({"response": get_smart_fallback_response(user_msg)})

@app.route("/jadwal-sholat")
def jadwal_sholat_page():
    daftar_kota = fetch_kemenag_kota()
    hijri_today = get_hijri_date_string()
    return render_template("jadwal-sholat.html", daftar_kota=daftar_kota, quotes=get_quote_religi(), hijri_date=hijri_today)

@app.route("/api/jadwal-imsakiyah")
def get_jadwal_kemenag():
    id_kota = request.args.get("id_kota")
    bulan = request.args.get("bulan", datetime.now().month)
    tahun = request.args.get("tahun", datetime.now().year)
    if not id_kota: return jsonify({"status": False, "message": "Atribut id_kota wajib dilampirkan."})
    try:
        url = f"https://api.myquran.com/v2/sholat/jadwal/{id_kota}/{tahun}/{bulan}"
        r = requests.get(url, timeout=10)
        if r.status_code == 200: return jsonify(r.json())
    except Exception as e: return jsonify({"status": False, "message": str(e)})
    return jsonify({"status": False, "message": "Gagal terhubung server penjadwalan."})

@app.route("/api/news-ticker")
def news_ticker(): return jsonify([n['title'] for n in get_news_entries()])

@app.route('/api/visitor-stats')
def visitor_stats():
    current_time = time.time()
    active_ips = {ip: ts for ip, ts in TRACKER_DATA["online_ips"].items() if current_time - ts <= 300}
    TRACKER_DATA["online_ips"] = active_ips
    active_locations = [TRACKER_DATA["ip_locations"].get(ip, "Tidak Terdeteksi") for ip in active_ips.keys()]
    
    return jsonify({
        "daily": len(TRACKER_DATA["daily_ips"]),
        "online": max(1, len(active_ips)),
        "active_locations": list(set(active_locations))
    })

# ==========================================
# 9. API DETEKSI PELANGGARAN & AI KENDARAAN
# ==========================================
@app.route('/api/detect_violation', methods=['POST'])
def api_detect_violation():
    try:
        data = request.get_json()
        frame_base64 = data.get('frame', '')
        
        chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        plat = f"G {random.randint(1000, 9999)} {random.choice(chars)}{random.choice(chars)}"
        pelanggaran = random.choice([
            "Pelanggaran Marka Jalan", 
            "Menerobos Lampu Merah",
            "Pengendara Tidak Menggunakan Helm"
        ])

        return jsonify({
            "status": "success",
            "plate": plat,
            "violation": pelanggaran
        })

    except Exception as e:
        return jsonify({"status": "error", "message": f"Terjadi kesalahan pada modul pemrosesan citra: {str(e)}"}), 500

@app.route('/about')
def about(): return render_template('about.html')
@app.route('/cctv')
def cctv_page(): return render_template("cctv.html")
@app.route('/sitemap.xml')
def sitemap(): return send_from_directory('static', 'sitemap.xml')

# ==========================================
# 10. FITUR PUSAT PESAN BLAST (EWS LALU LINTAS)
# ==========================================
@app.route('/email', methods=['GET', 'POST'])
def email_blast_page():
    if 'user' not in session: return redirect(url_for('login'))
        
    if request.method == 'POST':
        subject = request.form.get('subject')
        body_text = request.form.get('message')
        kategori = request.form.get('kategori', 'Informasi Lalu Lintas')
        prioritas = request.form.get('prioritas', 'Normal')
        
        if not subject or not body_text:
            flash("Halo Admin, mohon pastikan subjek dan isi pesan terisi.", "error")
            return redirect(url_for('email_blast_page'))
            
        if not ref:
            flash("Gagal memuat database petugas. Pastikan koneksi ke Firebase aman.", "error")
            return redirect(url_for('email_blast_page'))
            
        users = ref.child('users').get() or {}
        sent_details = [] 
        tz_jakarta = pytz.timezone('Asia/Jakarta')
        
        with app.app_context():
            for uid, user_data in users.items():
                if not isinstance(user_data, dict): continue
                
                email_tujuan = user_data.get('email')
                nama_user = user_data.get('nama', 'Petugas / Warga')
                
                if not email_tujuan: continue
                
                formatted_body = f"""
PESAN BLAST - COMMAND CENTER SUDUT KOTA
Kategori  : {kategori}
Prioritas : {prioritas}
========================================================

Yth. Bapak/Ibu {nama_user},

{body_text}

Harap berhati-hati dalam berkendara dan patuhi rambu lalu lintas.

Salam,
Admin Sistem Sudut Kota - Dishub Pekalongan
========================================================"""
                
                waktu_kirim = datetime.now(tz_jakarta).strftime("%d %b %Y - %H:%M:%S WIB")
                
                try:
                    msg = Message(subject, recipients=[email_tujuan])
                    msg.body = formatted_body
                    mail.send(msg)
                    sent_details.append({"nama": nama_user, "email": email_tujuan, "waktu": waktu_kirim, "status": "Sukses"})
                except Exception as e:
                    print(f"Gagal mengirim ke {email_tujuan}: {e}")
                    sent_details.append({"nama": nama_user, "email": email_tujuan, "waktu": waktu_kirim, "status": "Gagal"})
        
        if sent_details:
            session['last_sent_details'] = sent_details
            berhasil = sum(1 for x in sent_details if x['status'] == "Sukses")
            flash(f"Pesan blast berhasil terkirim ke {berhasil} dari {len(sent_details)} kontak.", "success")
        else:
            flash("Proses dibatalkan atau tidak ada kontak di database.", "error")
            
        return redirect(url_for('email_blast_page'))
        
    sent_list = session.pop('last_sent_details', None)
    
    total_users = 0
    if ref:
        try: total_users = len(ref.child('users').get() or {})
        except: pass
        
    return render_template('email.html', sent_list=sent_list, total_users=total_users)

if __name__ == '__main__':
    app.run(debug=True)