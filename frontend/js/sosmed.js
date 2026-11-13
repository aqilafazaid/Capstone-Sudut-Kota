/* ==========================================================================
   SOSMED.JS — ringkasan kiriman Instagram resmi (bukan data contoh)

   Sumber: frontend/data/instagram.json, diisi dari halaman embed resmi
   Instagram (caption, tanggal, permalink asli). Tidak ada teks atau gambar
   karangan; bila file gagal dimuat, halaman hanya menampilkan tautan akun.

   Memperbarui: ganti isi data/instagram.json (caption + permalink dari post
   terbaru) lalu ubah field "updated".
   ========================================================================== */

(function (global) {
    'use strict';

    var DATA_URL = 'data/instagram.json';

    var ICONS = {
        dishub_kotapekalongan: 'fa-solid fa-tower-broadcast',
        pjukotapekalongan: 'fa-solid fa-lightbulb'
    };

    function esc(text) {
        return String(text == null ? '' : text)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function formatDate(value) {
        if (!value) return '';
        var date = new Date(value);
        if (isNaN(date.getTime())) return esc(value);
        return date.toLocaleDateString('id-ID', { day: 'numeric', month: 'long', year: 'numeric' });
    }

    function accountOf(data, handle) {
        var list = (data && data.accounts) || [];
        for (var i = 0; i < list.length; i += 1) {
            if (list[i].handle === handle) return list[i];
        }
        return { handle: handle, label: handle, url: 'https://www.instagram.com/' + handle, icon: 'fa-brands fa-instagram' };
    }

    function card(data, post) {
        var account = accountOf(data, post.handle);
        var icon = account.icon || ICONS[post.handle] || 'fa-brands fa-instagram';
        var date = formatDate(post.date);
        var kindLabel = post.kind === 'reel' ? 'Reel' : 'Kiriman';

        return '' +
            '<article class="bg-white dark:bg-[#0a143c] rounded-[1.5rem] border border-slate-200 dark:border-white/5 shadow-sm p-5 flex flex-col gap-3">' +
                '<header class="flex items-center justify-between gap-3">' +
                    '<a href="' + esc(account.url) + '" target="_blank" rel="noopener" class="flex items-center gap-3 min-w-0 group">' +
                        '<span class="w-9 h-9 rounded-full bg-gradient-to-tr from-yellow-400 via-red-500 to-purple-500 text-white flex items-center justify-center shrink-0">' +
                            '<i class="' + esc(icon) + ' text-sm"></i>' +
                        '</span>' +
                        '<span class="min-w-0">' +
                            '<span class="block text-xs font-bold text-slate-800 dark:text-white truncate group-hover:text-blue-500 transition-colors">' + esc(account.handle) + '</span>' +
                            '<span class="block text-[10px] text-slate-500 truncate">' + esc(account.label) + '</span>' +
                        '</span>' +
                    '</a>' +
                    '<span class="text-[9px] font-bold uppercase tracking-widest text-slate-400 shrink-0">' + kindLabel + '</span>' +
                '</header>' +
                '<p class="text-sm text-slate-700 dark:text-slate-200 leading-relaxed line-clamp-5 whitespace-pre-line">' + esc(post.caption) + '</p>' +
                '<footer class="mt-auto flex items-center justify-between gap-3 pt-2 border-t border-slate-100 dark:border-white/5">' +
                    '<span class="text-[10px] text-slate-400 uppercase font-medium">' + (date || 'Instagram') + '</span>' +
                    '<a href="' + esc(post.permalink) + '" target="_blank" rel="noopener" class="text-[11px] font-bold text-blue-600 dark:text-blue-400 hover:underline flex items-center gap-1.5">' +
                        'Lihat di Instagram <i class="fa-solid fa-arrow-up-right-from-square text-[9px]"></i>' +
                    '</a>' +
                '</footer>' +
            '</article>';
    }

    function render(data) {
        var host = document.getElementById('instagram-feed');
        if (!host) return;

        var posts = (data && data.posts) || [];
        if (!posts.length) {
            showFallback(host, data);
            return;
        }

        host.innerHTML = posts.map(function (post) { return card(data, post); }).join('') +
            '<p class="md:col-span-2 text-center text-[10px] sk-muted">' +
                'Ringkasan kiriman resmi' + (data.updated ? ' · diperbarui ' + formatDate(data.updated) : '') +
                ' · foto dan video lengkap dibuka di Instagram.' +
            '</p>';
    }

    function showFallback(host, data) {
        var accounts = (data && data.accounts) || [
            { handle: 'dishub_kotapekalongan', label: 'Dishub Kota Pekalongan', url: 'https://www.instagram.com/dishub_kotapekalongan' },
            { handle: 'pjukotapekalongan', label: 'PJU Dishub Pekalongan', url: 'https://www.instagram.com/pjukotapekalongan' }
        ];
        host.innerHTML = '<div class="sk-panel p-6 md:col-span-2 rounded-2xl text-center text-sm sk-muted leading-relaxed">' +
            '<i class="fa-brands fa-instagram mr-2"></i>' +
            'Ringkasan kiriman belum tersedia. Buka langsung: ' +
            accounts.map(function (a) {
                return '<a class="sk-accent underline" target="_blank" rel="noopener" href="' + esc(a.url) + '">@' + esc(a.handle) + '</a>';
            }).join(' · ') +
            '</div>';
    }

    function load() {
        var host = document.getElementById('instagram-feed');
        if (!host) return;

        fetch(DATA_URL, { cache: 'no-store' })
            .then(function (response) {
                if (!response.ok) throw new Error('HTTP ' + response.status);
                return response.json();
            })
            .then(render)
            .catch(function (err) {
                console.warn('[Sosmed] gagal memuat ringkasan Instagram:', err.message || err);
                showFallback(host, null);
            });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', load);
    } else {
        load();
    }

    global.SudutKotaSosmed = { reload: load };
})(window);
