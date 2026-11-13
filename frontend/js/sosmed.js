/* ==========================================================================
   SOSMED.JS — feed Instagram asli (backend scrape + cache), berhalaman.

   Data: GET /api/sosmed/instagram?page=N&per_page=6
         { posts:[{handle, kind, code, permalink, caption, date, likes, image_ok}],
           page, pages, total, fetched_at, errors }

   Gambar: /api/sosmed/instagram/image/<code>.jpg (diunduh backend, bukan
   hotlink CDN yang kedaluwarsa).

   Tidak ada kartu contoh: bila backend belum bisa mengambil data, yang tampil
   hanya tautan akun.
   ========================================================================== */

(function (global) {
    'use strict';

    var PER_PAGE = 6;
    /* Selaras IG_CACHE_SECONDS=300 di backend; permintaan lebih sering dari ini
       tetap dilayani dari cache, jadi tidak menambah beban ke Instagram. */
    var REFRESH_MS = 5 * 60 * 1000;
    var pollId = null;
    var state = { page: 1, pages: 1, loading: false, data: null, expanded: {}, polls: 0 };

    function esc(text) {
        return String(text == null ? '' : text)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function assetBase() {
        var cfg = global.SK_CONFIG;
        if (!cfg) return '';
        return cfg.backendBase || '';
    }

    function imageUrl(code) {
        return assetBase() + '/api/sosmed/instagram/image/' + encodeURIComponent(code) + '.jpg';
    }

    function avatarUrl(handle) {
        return assetBase() + '/api/sosmed/instagram/avatar/' + encodeURIComponent(handle) + '.jpg';
    }

    function timeLabel(iso) {
        if (!iso) return '';
        var date = new Date(iso);
        if (isNaN(date.getTime())) return '';
        return date.toLocaleString('id-ID', {
            day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit'
        });
    }

    function accountLabel(handle) {
        return handle === 'pjukotapekalongan' ? 'PJU Dishub Pekalongan' : 'Dishub Kota Pekalongan';
    }

    function card(post) {
        var caption = String(post.caption || '').trim();
        var long = caption.length > 240;
        var open = !!state.expanded[post.code];
        var date = post.date || '';
        var likes = String(post.likes || '').trim();
        var meta = [];
        if (likes) meta.push(likes + ' suka');
        if (date) meta.push(date);
        var metaText = meta.join(' \u00b7 ') || 'Instagram';

        return '' +
            '<article data-code="' + esc(post.code) + '" class="bg-white dark:bg-[#0a143c] rounded-[1.5rem] border border-slate-200 dark:border-white/5 shadow-sm overflow-hidden flex flex-col">' +
                (post.image_ok
                    ? '<a href="' + esc(post.permalink) + '" target="_blank" rel="noopener" class="block bg-slate-100 dark:bg-slate-800">' +
                        '<img src="' + esc(imageUrl(post.code)) + '" alt="Kiriman @' + esc(post.handle) + '" loading="lazy" ' +
                             'class="w-full aspect-square object-cover" ' +
                             'onerror="this.parentElement.classList.add(\'hidden\')">' +
                      '</a>'
                    : '') +
                '<div class="p-5 flex flex-col gap-3 flex-grow">' +
                    '<header class="flex items-center justify-between gap-3">' +
                        '<span class="flex items-center gap-2 min-w-0">' +
                            '<span class="relative w-7 h-7 rounded-full overflow-hidden bg-gradient-to-tr from-yellow-400 via-red-500 to-purple-500 text-white grid place-items-center shrink-0">' +
                                '<i class="fa-brands fa-instagram text-[11px]"></i>' +
                                (post.avatar
                                    ? '<img src="' + esc(avatarUrl(post.handle)) + '" alt="Foto profil @' + esc(post.handle) + '" loading="lazy" ' +
                                       'class="absolute inset-0 w-full h-full object-cover" onerror="this.remove()">'
                                    : '') +
                            '</span>' +
                            '<span class="min-w-0">' +
                                '<a href="https://www.instagram.com/' + esc(post.handle) + '" target="_blank" rel="noopener" ' +
                                   'class="block text-[11px] font-bold text-slate-800 dark:text-white truncate hover:text-blue-500">@' + esc(post.handle) + '</a>' +
                                '<span class="block text-[9px] text-slate-500 truncate">' + esc(accountLabel(post.handle)) + '</span>' +
                            '</span>' +
                        '</span>' +
                        '<span class="text-[9px] font-bold uppercase tracking-widest text-slate-400 shrink-0">' +
                            (post.kind === 'reel' ? 'Reel' : 'Kiriman') +
                        '</span>' +
                    '</header>' +
                    '<p class="text-sm text-slate-700 dark:text-slate-200 leading-relaxed whitespace-pre-line ' +
                        (long && !open ? 'line-clamp-4' : '') + '" data-caption>' + esc(caption || '(tanpa teks)') + '</p>' +
                    (long ? '<button type="button" data-more class="self-start text-[11px] font-bold text-blue-600 dark:text-blue-400 hover:underline">' + (open ? 'Ringkas' : 'Selengkapnya') + '</button>' : '') +
                    '<footer class="mt-auto flex items-center justify-between gap-3 pt-2 border-t border-slate-100 dark:border-white/5">' +
                        '<span class="text-[10px] text-slate-400 font-semibold">' + esc(metaText) + '</span>' +
                        '<a href="' + esc(post.permalink) + '" target="_blank" rel="noopener" ' +
                           'class="text-[11px] font-bold text-blue-600 dark:text-blue-400 hover:underline flex items-center gap-1.5">' +
                            'Lihat di Instagram <i class="fa-solid fa-arrow-up-right-from-square text-[9px]"></i>' +
                        '</a>' +
                    '</footer>' +
                '</div>' +
            '</article>';
    }

    function skeleton() {
        var cells = '';
        for (var i = 0; i < 3; i += 1) {
            cells += '<div class="bg-white dark:bg-[#0a143c] rounded-[1.5rem] border border-slate-200 dark:border-white/5 overflow-hidden">' +
                '<div class="aspect-square skeleton"></div>' +
                '<div class="p-5 space-y-2"><div class="h-3 w-1/3 skeleton rounded"></div><div class="h-3 w-full skeleton rounded"></div><div class="h-3 w-4/5 skeleton rounded"></div></div>' +
            '</div>';
        }
        return cells;
    }

    function fallback(message) {
        return '<div class="md:col-span-2 sk-panel p-6 rounded-2xl text-center text-sm sk-muted leading-relaxed">' +
            '<i class="fa-brands fa-instagram mr-2"></i>' + message + '<br>' +
            '<a class="sk-accent underline" target="_blank" rel="noopener" href="https://www.instagram.com/dishub_kotapekalongan">@dishub_kotapekalongan</a> · ' +
            '<a class="sk-accent underline" target="_blank" rel="noopener" href="https://www.instagram.com/pjukotapekalongan">@pjukotapekalongan</a>' +
            '</div>';
    }

    function renderPager(host, data) {
        var pager = document.getElementById('instagram-pager');
        if (!pager) return;
        if (!data || data.pages <= 1) {
            pager.innerHTML = '';
            return;
        }
        pager.innerHTML =
            '<button type="button" data-page="prev" class="sk-btn text-xs px-4 py-2 rounded-full border border-slate-200 dark:border-white/10 ' +
                (data.has_prev ? '' : 'opacity-40 cursor-not-allowed') + '" ' + (data.has_prev ? '' : 'disabled') + '>' +
                '<i class="fa-solid fa-chevron-left mr-1"></i> Sebelumnya</button>' +
            '<span class="text-[11px] font-bold uppercase tracking-widest sk-muted">Halaman ' + data.page + ' / ' + data.pages + '</span>' +
            '<button type="button" data-page="next" class="sk-btn text-xs px-4 py-2 rounded-full border border-slate-200 dark:border-white/10 ' +
                (data.has_next ? '' : 'opacity-40 cursor-not-allowed') + '" ' + (data.has_next ? '' : 'disabled') + '>' +
                'Berikutnya <i class="fa-solid fa-chevron-right ml-1"></i></button>';
    }

    function bindCards(host) {
        host.querySelectorAll('[data-more]').forEach(function (button) {
            button.addEventListener('click', function () {
                var card = button.closest('[data-code]');
                var caption = button.parentElement.querySelector('[data-caption]');
                if (!caption) return;
                var expanded = caption.classList.toggle('line-clamp-none');
                caption.classList.toggle('line-clamp-4', !expanded);
                button.textContent = expanded ? 'Ringkas' : 'Selengkapnya';
                /* Ingat status buka/tutup supaya refresh senyap tidak melipatnya. */
                if (card) {
                    if (expanded) state.expanded[card.dataset.code] = true;
                    else delete state.expanded[card.dataset.code];
                }
            });
        });
    }

    function load(page, opts) {
        var silent = !!(opts && opts.silent);
        var host = document.getElementById('instagram-feed');
        if (!host || state.loading) return;
        state.loading = true;
        if (!silent) {
            host.innerHTML = skeleton();
            var pager = document.getElementById('instagram-pager');
            if (pager) pager.innerHTML = '';
        }

        var url = assetBase() + '/api/sosmed/instagram?page=' + page + '&per_page=' + PER_PAGE;
        fetch(url, { cache: 'no-store' })
            .then(function (response) {
                if (!response.ok) throw new Error('HTTP ' + response.status);
                return response.json();
            })
            .then(function (data) {
                state.data = data;
                state.page = data.page || page;
                state.pages = data.pages || 1;
                if (!data.posts || !data.posts.length) {
                    if (silent) return;  /* biarkan kartu lama tetap tampil */
                    host.innerHTML = fallback('Kiriman belum bisa dimuat dari Instagram.');
                    renderPager(host, null);
                    return;
                }
                host.innerHTML = data.posts.map(card).join('');
                bindCards(host);
                renderPager(host, data);
                var note = document.getElementById('instagram-updated');
                if (note) {
                    note.textContent = data.fetched_at
                        ? 'Diperbarui ' + timeLabel(data.fetched_at) + ' · ' + data.total + ' kiriman'
                        : data.total + ' kiriman';
                }
            })
            .catch(function (err) {
                console.warn('[Sosmed] gagal memuat feed:', err.message || err);
                if (silent) return;  /* refresh latar gagal: jangan rusak tampilan */
                host.innerHTML = fallback('Feed Instagram tidak dapat dihubungi.');
                renderPager(host, null);
            })
            .finally(function () { state.loading = false; });
    }

    /* Refresh senyap: hanya area feed, tanpa skeleton, status buka/tutup dan
       halaman aktif dipertahankan. Otomatis berhenti saat tab tidak aktif. */
    function refreshSilently() {
        if (document.visibilityState !== 'visible' || state.loading) return;
        load(state.page, { silent: true });
    }

    function startPolling() {
        if (pollId) return;
        pollId = setInterval(function () {
            state.polls += 1;
            refreshSilently();
        }, REFRESH_MS);
        document.addEventListener('visibilitychange', function () {
            if (document.visibilityState !== 'visible') return;
            var stamp = state.data && state.data.fetched_at
                ? new Date(state.data.fetched_at).getTime() : 0;
            if (Date.now() - stamp > REFRESH_MS) refreshSilently();
        });
    }

    function init() {
        var host = document.getElementById('instagram-feed');
        if (!host) return;
        load(1);
        startPolling();
        var pager = document.getElementById('instagram-pager');
        if (pager) {
            pager.addEventListener('click', function (event) {
                var button = event.target.closest('[data-page]');
                if (!button || button.disabled) return;
                var next = button.dataset.page === 'next' ? state.page + 1 : state.page - 1;
                load(Math.max(1, Math.min(next, state.pages)));
                host.scrollIntoView({ behavior: 'smooth', block: 'start' });
            });
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    global.SudutKotaSosmed = {
        reload: init,
        refresh: refreshSilently,
        state: state,
        refreshMs: REFRESH_MS
    };
})(window);
