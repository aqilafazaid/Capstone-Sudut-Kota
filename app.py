import os
from datetime import datetime
from flask import Flask, render_template, jsonify, request, make_response

# ==============================================================================
# APLIKASI WEB FLASK - SUDUT KOTA DISHUB PEKALONGAN (KTVDI ENGINE V2)
# ==============================================================================

app = Flask(__name__)

# Konfigurasi Keamanan (Session, Enkripsi, dan Cookie)
# Menggunakan environment variable untuk keamanan tingkat produksi di Vercel
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'ktvdi-sudutkota-super-secret-key-2026')
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True

# ------------------------------------------------------------------------------
# 1. MIDDLEWARE & SECURITY HEADERS (STANDAR KTVDI)
# ------------------------------------------------------------------------------
@app.after_request
def add_security_headers(response):
    """
    Menambahkan header keamanan pada setiap respon server untuk mencegah 
    serangan XSS, Clickjacking, dan Sniffing (Standar Produksi).
    """
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    # Memaksa browser mengecek versi terbaru halaman (mencegah cache tersangkut)
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return response

@app.context_processor
def inject_now():
    """
    Mengirimkan variabel global ke semua file HTML. 
    (Bisa dipanggil di footer dengan {{ year }} )
    """
    return {'year': datetime.now().year, 'app_version': '1.0.0 (KTVDI Engine)'}

# ------------------------------------------------------------------------------
# 2. ROUTING HALAMAN UTAMA (FRONTEND PUBLIC)
# ------------------------------------------------------------------------------

@app.route('/')
def index():
    """Halaman Beranda (Landing Page) Publik"""
    return render_template('index.html')

@app.route('/cctv')
def cctv():
    """Halaman Ruang Kendali CCTV (AI, MirNet, YOLOv8)"""
    return render_template('cctv.html')

@app.route('/dashboard')
def dashboard():
    """Halaman Dasbor Analitik untuk Operator Dishub"""
    return render_template('dashboard.html')

# ------------------------------------------------------------------------------
# 3. ROUTING AUTENTIKASI & MANAJEMEN PENGGUNA
# ------------------------------------------------------------------------------

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Halaman Autentikasi Masuk"""
    # Jika nanti ada form submit, logic pemeriksaannya bisa ditaruh di sini
    if request.method == 'POST':
        # Logic validasi login (simulasi)
        pass
    return render_template('login.html')

@app.route('/register')
def register():
    """Halaman Pendaftaran Akun"""
    return render_template('register.html')

# ------------------------------------------------------------------------------
# 4. API ENDPOINTS (KOMUNIKASI BACKEND)
# ------------------------------------------------------------------------------

@app.route('/api/status', methods=['GET'])
def system_status():
    """
    Endpoint API untuk mengecek apakah server Vercel aktif.
    Bisa digunakan untuk fitur monitoring di Dashboard.
    """
    return jsonify({
        "status": "online",
        "service": "Sudut Kota Web Engine",
        "timestamp": datetime.now().isoformat(),
        "developer": "Aqila Niam Faza (KTVDI)"
    }), 200

# ------------------------------------------------------------------------------
# 5. PENANGANAN KESALAHAN (ERROR HANDLING)
# ------------------------------------------------------------------------------

@app.errorhandler(404)
def page_not_found(e):
    """Menangani Error 404 (Halaman Tidak Ditemukan)"""
    return render_template('index.html'), 404

@app.errorhandler(500)
def internal_server_error(e):
    """Menangani Error 500 (Kesalahan Fatal Server)"""
    return jsonify({
        "error": "Internal Server Error",
        "message": "Terjadi kesalahan pada sistem Sudut Kota. Tim Teknisi sedang menanganinya."
    }), 500

# ------------------------------------------------------------------------------
# 6. ENTRY POINT EKSEKUSI (LOKAL ONLY)
# ------------------------------------------------------------------------------
if __name__ == '__main__':
    # Menjalankan server lokal di port 5000 (http://localhost:5000)
    app.run(debug=True, host='0.0.0.0', port=5000)
