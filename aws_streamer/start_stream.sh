#!/bin/bash

# ==============================================================================
# SCRIPT STREAMING CCTV NON-AI - SUDUT KOTA DISHUB PEKALONGAN
# ==============================================================================

# 1. KONFIGURASI KREDENSIAL & NETWORK TAILSCALE
RTSP_USER="Undip"
RTSP_PASS="Pekalongan12345"
TAILSCALE_IP="10.28.110.253"
RTSP_PORT="554"

# 2. KONFIGURASI PATH OUTPUT HLS NGINX
HLS_BASE_DIR="/var/www/hls"

# Tangkap nomor channel dari argumen CLI (Default ke Channel 29 jika tidak diisi)
CHANNEL=${1:-"29"}

# Format URL RTSP Hikvision dan Direktori Output
RTSP_URL="rtsp://${RTSP_USER}:${RTSP_PASS}@${TAILSCALE_IP}:${RTSP_PORT}/Streaming/Channels/${CHANNEL}01"
TARGET_DIR="${HLS_BASE_DIR}/ch${CHANNEL}"
OUTPUT_M3U8="${TARGET_DIR}/index.m3u8"

# Buat folder penyimpanan HLS jika belum ada dan atur perizinannya untuk Nginx
mkdir -p "$TARGET_DIR"
chown -R www-data:www-data "$TARGET_DIR"
chmod -R 775 "$TARGET_DIR"

echo "=========================================================="
echo " [START] Memulai Streamer CCTV Non-AI Sudut Kota"
echo " Channel CCTV  : CH ${CHANNEL}"
echo " RTSP Source   : rtsp://${RTSP_USER}:***@${TAILSCALE_IP}:${RTSP_PORT}"
echo " HLS Output    : ${OUTPUT_M3U8}"
echo "=========================================================="

# 3. LOOPING UTAMA (AUTO-RECONNECT JIKA KONEKSI TERPUTUS)
while true; do
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [INFO] Menjalankan FFmpeg Stream untuk CH ${CHANNEL}..."
    
    ffmpeg -hide_banner -loglevel warning \
        -rtsp_transport tcp \
        -i "$RTSP_URL" \
        -c:v libx264 \
        -preset ultrafast \
        -tune zerolatency \
        -b:v 1500k \
        -maxrate 2000k \
        -bufsize 4000k \
        -g 50 \
        -an \
        -f hls \
        -hls_time 2 \
        -hls_list_size 5 \
        -hls_flags delete_segments \
        "$OUTPUT_M3U8"

    # Jika FFmpeg terhenti (koneksi putus/timeout), tunggu 5 detik lalu sambung kembali
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [WARNING] Koneksi RTSP CH ${CHANNEL} terputus. Mencoba reconnect dalam 5 detik..."
    sleep 5
done
