"""Ambil kiriman Instagram publik lewat browser sungguhan (Playwright).

Instagram menutup seluruh endpoint anonim (web_profile_info/`__a=1` menjawab
429, mirror pihak ketiga 403) dan halaman post tidak membawa metadata
server-side (tanpa og:image). Satu-satunya sumber yang stabil adalah DOM yang
sudah dirender, jadi modul ini menjalankan Chromium headless sekali per
kedaluwarsa cache:

1. buka profil, kumpulkan tautan /p/ dan /reel/ terbaru;
2. buka halaman embed resmi tiap post, ambil caption, tanggal, jumlah suka,
   dan URL gambarnya;
3. unduh gambarnya ke ``media/instagram/<code>.jpg`` supaya tidak bergantung
   pada URL CDN bertanda tangan yang kedaluwarsa;
4. simpan hasilnya di ``data/instagram-cache.json``.

Halaman lalu memanggil :func:`page` dan tidak pernah memicu scrape sendiri.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
CACHE_FILE = BASE_DIR / "data" / "instagram-cache.json"
IMAGE_DIR = BASE_DIR / "media" / "instagram"
AVATAR_DIR = IMAGE_DIR / "avatars"

DEFAULT_HANDLES = ("dishub_kotapekalongan", "pjukotapekalongan")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# Batas aman supaya satu scrape tidak menghajar Instagram.
MAX_POSTS = 16
POSTS_PER_HANDLE = 8
PAUSE_SECONDS = 1.0

_lock = threading.Lock()


def handles() -> list[str]:
    raw = os.environ.get("IG_HANDLES", "").strip()
    if not raw:
        return list(DEFAULT_HANDLES)
    return [part.strip().lstrip("@") for part in raw.split(",") if part.strip()]


def cache_seconds() -> int:
    try:
        return max(60, int(os.environ.get("IG_CACHE_SECONDS", "900")))
    except ValueError:
        return 900


def _read_cache() -> dict[str, Any]:
    if not CACHE_FILE.exists():
        return {}
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_cache(payload: dict[str, Any]) -> None:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(CACHE_FILE)


_CAPTION_JS = r"""() => {
  const txt = document.body.innerText.replace(/\s+/g, ' ').trim();
  const capEl = document.querySelector('div.Caption');
  let caption = capEl ? capEl.innerText : '';
  // Baris pertama caption adalah handle pemilik post.
  caption = caption.replace(/^[^\n]*\n+/, '').trim();
  if (!caption) {
    // Cadangan: teks setelah "… suka/likes <handle>".
    const m = txt.match(/(?:suka|likes)\s+@?[\w.]+\s+(.+?)(?:Tambahkan komentar|Add a comment|$)/i);
    if (m) caption = m[1].trim();
  }
  const dateMatch = caption.match(/^(\d{1,2}\s+[A-Za-z]+\s+\d{4})\s+/);
  const date = dateMatch ? dateMatch[1] : '';
  if (dateMatch) caption = caption.slice(dateMatch[0].length).trim();
  const likeMatch = txt.match(/([\d.,]+)\s+(?:suka|likes)/i);

  // Media post berukuran besar; avatar/thumb hanya 150 px.
  const imgs = [...document.querySelectorAll('img')].filter(i => /cdninstagram|fbcdn/.test(i.src));
  imgs.sort((a, b) => (b.naturalWidth || 0) - (a.naturalWidth || 0));
  let image = imgs.length ? imgs[0].src : '';
  if (image) image = image.replace(/s150x150/, 's640x640').replace(/p150x150/, 'p640x640');

  return {
    caption: caption,
    date: date,
    likes: likeMatch ? likeMatch[1] : '',
    image: image
  };
}"""

_LINKS_JS = r"""() => [...document.querySelectorAll('a[href*="/p/"], a[href*="/reel/"]')]
    .map(a => a.getAttribute('href'))
    .filter(Boolean)"""

_AVATAR_JS = r"""() => {
  const img = [...document.querySelectorAll('img')]
    .find(i => /^(foto profil|profile picture)/i.test((i.alt || '').trim()));
  // URL-nya bertanda tangan: mengubah ukuran di string membuatnya 403.
  return img ? img.src : '';
}"""


def _collect_links(page, handle: str) -> list[dict[str, Any]]:
    page.goto(f"https://www.instagram.com/{handle}/", wait_until="domcontentloaded", timeout=45000)
    page.wait_for_selector('a[href*="/p/"], a[href*="/reel/"]', timeout=20000)
    raw = page.evaluate(_LINKS_JS) or []

    found: list[dict[str, str]] = []
    seen: set[str] = set()
    for href in raw:
        parts = [p for p in href.split("?")[0].split("/") if p]
        if len(parts) < 3:
            continue
        kind, code = parts[-2], parts[-1]
        if kind not in {"p", "reel"} or code in seen:
            continue
        seen.add(code)
        label, iso = _date_label(code)
        found.append({
            "handle": handle,
            "kind": kind,
            "code": code,
            "permalink": f"https://www.instagram.com/{kind}/{code}/",
            "date": label,
            "taken_at": iso,
        })
        if len(found) >= POSTS_PER_HANDLE:
            break
    return found


_CAPTION_NOISE = re.compile(
    r"(\bLihat\s+(?:semua\s+)?(?:\d+\s+)?komentar\b|\bView\s+(?:all\s+)?(?:\d+\s+)?comments?\b"
    r"|\bTambahkan\s+komentar\b|\bAdd\s+a\s+comment\b|\bBalas\b|\bReply\b)",
    re.IGNORECASE,
)

# Shortcode Instagram adalah base64 dari media id; 41 bit pertamanya adalah
# milidetik sejak epoch yang digeser 1.314.220.021.721 ms. Dipakai untuk
# mendapatkan tanggal unggah tanpa API.
_SHORTCODE_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
_MONTHS_ID = ("Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli",
              "Agustus", "September", "Oktober", "November", "Desember")
_MEDIA_EPOCH_MS = 1314220021721
_WIB = timezone(timedelta(hours=7))


def _taken_at(code: str):
    """Waktu unggah dari shortcode; None bila kode tidak valid."""
    try:
        value = 0
        for char in code:
            value = value * 64 + _SHORTCODE_ALPHABET.index(char)
        ms = (value >> 23) + _MEDIA_EPOCH_MS
        return datetime.fromtimestamp(ms / 1000, tz=_WIB)
    except (ValueError, OverflowError, OSError):
        return None


def _date_label(code: str):
    """(label Indonesia, ISO) untuk tanggal unggah."""
    moment = _taken_at(code)
    if not moment:
        return "", ""
    return f"{moment.day} {_MONTHS_ID[moment.month - 1]} {moment.year}", moment.isoformat(timespec="seconds")


def _clean_caption(text: str) -> str:
    """Buang teks antarmuka Instagram yang ikut terbaca dari DOM."""
    cleaned = _CAPTION_NOISE.sub(" ", text or "")
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _normalize_image(path: Path, max_width: int = 720, quality: int = 82) -> None:
    """Kecilkan gambar agar halaman tidak mengunduh file 0,5–1 MB per kartu."""
    try:
        from PIL import Image
    except ImportError:
        return
    resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS", 1)
    try:
        with Image.open(path) as img:
            if img.width > max_width:
                ratio = max_width / img.width
                img = img.resize((max_width, max(1, int(img.height * ratio))), resample)
            img.convert("RGB").save(path, "JPEG", quality=quality, optimize=True)
    except Exception:
        pass


def _download_image(context, url: str, code: str, directory: Path | None = None,
                    max_width: int = 720) -> bool:
    if not url:
        return False
    directory = directory or IMAGE_DIR
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{code}.jpg"
    if target.exists() and target.stat().st_size > 1000:
        return True
    try:
        response = context.request.get(url, timeout=20000)
        if not response.ok:
            return False
        body = response.body()
        if len(body) < 1000:
            return False
        target.write_bytes(body)
        _normalize_image(target, max_width=max_width)
        return True
    except Exception:
        return False


def _download_avatar(context, url: str, handle: str) -> bool:
    """Foto profil akun; disimpan terpisah dari gambar post agar tidak ikut dipangkas."""
    return _download_image(context, url, handle, directory=AVATAR_DIR, max_width=320)


def scrape() -> dict[str, Any]:
    """Buka Instagram dengan Chromium headless dan kembalikan daftar post."""
    from playwright.sync_api import sync_playwright

    posts: list[dict[str, Any]] = []
    errors: list[str] = []
    avatars: dict[str, bool] = {}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        context = browser.new_context(
            user_agent=UA,
            locale="id-ID",
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()
        try:
            for handle in handles():
                try:
                    links = _collect_links(page, handle)
                except Exception as exc:
                    errors.append(f"{handle}: {type(exc).__name__}")
                    continue

                try:
                    avatar_url = page.evaluate(_AVATAR_JS) or ""
                    avatars[handle] = _download_avatar(context, avatar_url, handle)
                except Exception:
                    avatars[handle] = False

                for item in links:
                    if len(posts) >= MAX_POSTS:
                        break
                    embed = f"https://www.instagram.com/{item['kind']}/{item['code']}/embed/captioned/"
                    try:
                        page.goto(embed, wait_until="domcontentloaded", timeout=40000)
                        page.wait_for_selector('img[src*="cdninstagram"], img[src*="fbcdn"]', timeout=15000)
                        # Caption dirender setelah media; tunggu elemennya.
                        page.wait_for_selector('div.Caption', timeout=15000)
                        info = page.evaluate(_CAPTION_JS) or {}
                        label, iso = _date_label(item["code"])
                        item.update({
                            "caption": _clean_caption(info.get("caption") or ""),
                            "date": label or (info.get("date") or "").strip(),
                            "taken_at": iso,
                            "likes": (info.get("likes") or "").strip(),
                            "image_ok": _download_image(context, info.get("image") or "", item["code"]),
                        })
                        posts.append(item)
                    except Exception as exc:
                        errors.append(f"{item['code']}: {type(exc).__name__}")
                    time.sleep(PAUSE_SECONDS)

                # Simpan per akun: scrape yang lambat tetap menyisakan hasil.
                if posts:
                    _write_cache({
                        "fetched_at": datetime.now().isoformat(timespec="seconds"),
                        "handles": handles(),
                        "posts": posts,
                        "avatars": avatars,
                        "errors": errors,
                        "partial": True,
                    })
        finally:
            context.close()
            browser.close()

    payload = {
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "handles": handles(),
        "posts": posts,
        "avatars": avatars,
        "errors": errors,
    }
    if posts:
        _write_cache(payload)
        _purge_old_images({post["code"] for post in posts})
    return payload


def _purge_old_images(keep: set[str]) -> None:
    if not IMAGE_DIR.exists():
        return
    for path in IMAGE_DIR.glob("*.jpg"):
        if path.stem not in keep:
            try:
                path.unlink()
            except OSError:
                pass


def refresh(force: bool = False) -> dict[str, Any]:
    """Kembalikan cache; scrape ulang bila kedaluwarsa atau ``force``."""
    cached = _read_cache()
    fresh_enough = False
    if cached.get("fetched_at") and cached.get("posts"):
        try:
            age = datetime.now() - datetime.fromisoformat(cached["fetched_at"])
            fresh_enough = age.total_seconds() < cache_seconds()
        except ValueError:
            fresh_enough = False

    if fresh_enough and not force:
        return cached

    if not _lock.acquire(blocking=False):
        # Scrape lain sedang jalan: pakai cache lama bila ada.
        return cached or {"fetched_at": None, "posts": [], "errors": ["scrape berjalan"]}
    try:
        try:
            return scrape()
        except Exception as exc:  # Playwright/browser tidak siap
            if cached.get("posts"):
                cached["errors"] = [f"{type(exc).__name__}: {exc}"]
                return cached
            return {"fetched_at": None, "posts": [], "errors": [f"{type(exc).__name__}: {exc}"]}
    finally:
        _lock.release()


def page(page_no: int = 1, per_page: int = 6, force: bool = False) -> dict[str, Any]:
    data = refresh(force=force)
    posts = data.get("posts") or []
    per_page = max(1, min(12, int(per_page)))
    total = len(posts)
    pages = max(1, (total + per_page - 1) // per_page)
    current = max(1, min(int(page_no), pages))
    start = (current - 1) * per_page
    visible = []
    for post in posts[start:start + per_page]:
        item = dict(post)
        item["avatar"] = avatar_file(item.get("handle", "")) is not None
        visible.append(item)
    return {
        "ok": bool(posts),
        "fetched_at": data.get("fetched_at"),
        "cache_seconds": cache_seconds(),
        "page": current,
        "pages": pages,
        "per_page": per_page,
        "total": total,
        "has_prev": current > 1,
        "has_next": current < pages,
        "posts": visible,
        "errors": data.get("errors") or [],
    }


_HANDLE_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")


def avatar_file(handle: str) -> Path | None:
    """Foto profil akun yang tersimpan; None bila belum pernah diunduh."""
    if not handle or not _HANDLE_RE.match(handle):
        return None
    path = AVATAR_DIR / f"{handle}.jpg"
    return path if path.exists() else None


def image_file(code: str) -> Path | None:
    if not code or not code.replace("-", "").replace("_", "").isalnum():
        return None
    path = IMAGE_DIR / f"{code}.jpg"
    return path if path.exists() else None
