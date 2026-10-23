"""Téléchargement des sources (YouTube, TikTok, …) avec yt-dlp. Les chemins locaux sont gardés tels quels."""

import hashlib
import json
import os
import re
import shutil
import subprocess
import urllib.request
from http.cookiejar import CookieJar

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0 Safari/537.36")


def is_url(s: str) -> bool:
    return bool(re.match(r"^https?://", s))


def _section_name(a: float, b: float) -> str:
    return f"{int(a * 10):06d}-{int(b * 10):06d}"


def _ydl_base() -> dict:
    """Options communes : runtime JavaScript (node) pour YouTube, cookies facultatifs
    (variable d'environnement FEDIT_COOKIES = chemin d'un cookies.txt)."""
    opts = {"quiet": True, "no_warnings": True, "noplaylist": True}
    if shutil.which("node") and not shutil.which("deno"):
        opts["js_runtimes"] = {"node": {}}
    cookies = os.environ.get("FEDIT_COOKIES")
    if cookies:
        opts["cookiefile"] = cookies
    return opts


def _tiktok_direct(url: str, base: str) -> str:
    """Secours pour TikTok : lit l'adresse de la vidéo dans la page, avec les cookies de la page."""
    jar = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = [("User-Agent", UA), ("Referer", "https://www.tiktok.com/")]
    html = opener.open(url, timeout=30).read().decode("utf-8", "replace")
    m = re.search(r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        raise SystemExit(f"TikTok : page illisible ({url})")
    item = json.loads(m.group(1))["__DEFAULT_SCOPE__"]["webapp.video-detail"]["itemInfo"]["itemStruct"]
    path = base + ".mp4"
    with opener.open(item["video"]["playAddr"], timeout=120) as r, open(path, "wb") as f:
        shutil.copyfileobj(r, f)
    return path


def _cut(path: str, a: float, b: float, out: str) -> str:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(a), "-i", path, "-t", str(b - a),
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-c:a", "aac", out], check=True)
    return out


def fetch(source: str, dest: str, audio_only: bool = False, sections: list | None = None) -> list[str]:
    """Retourne la liste des fichiers locaux. Avec `sections` [(début, fin)], ne télécharge que
    ces passages (un fichier par passage) : beaucoup plus rapide qu'une vidéo entière."""
    if not is_url(source):
        if not os.path.exists(source):
            raise SystemExit(f"Fichier introuvable : {source}")
        return [source]

    import yt_dlp
    from yt_dlp.utils import download_range_func

    os.makedirs(dest, exist_ok=True)
    if "tiktok.com" in source:
        return _fetch_tiktok(source, dest, sections)
    with yt_dlp.YoutubeDL(_ydl_base()) as ydl:
        info = ydl.extract_info(source, download=False)
    vid = f"{info.get('extractor_key', 'web').lower()}_{info['id']}"

    if audio_only:
        fmt = "bestaudio/best"
    else:
        # 1080p max, 50/60 i/s en priorité (ralentis plus fluides), mp4 si possible.
        fmt = ("bv*[height<=1080][fps>=50][ext=mp4]+ba[ext=m4a]/bv*[height<=1080][fps>=50]+ba/"
               "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/bv*[height<=1080]+ba/b[height<=1080]/b")

    targets = [(None, os.path.join(dest, vid))] if not sections else [
        ((a, b), os.path.join(dest, f"{vid}_{_section_name(a, b)}")) for a, b in sections
    ]
    paths = []
    for rng, base in targets:
        existing = [f for f in os.listdir(dest) if f.startswith(os.path.basename(base) + ".")]
        if existing:
            paths.append(os.path.join(dest, existing[0]))
            continue
        opts = {
            **_ydl_base(),
            "format": fmt,
            "outtmpl": base + ".%(ext)s",
            "merge_output_format": None if audio_only else "mp4",
        }
        if rng:
            opts["download_ranges"] = download_range_func(None, [rng])
            opts["force_keyframes_at_cuts"] = True
        print(f"  ↓ {info.get('title', source)}" + (f" [{rng[0]:.0f}s → {rng[1]:.0f}s]" if rng else ""))
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([source])
        produced = [f for f in os.listdir(dest) if f.startswith(os.path.basename(base) + ".") and not f.endswith(".part")]
        if not produced:
            raise SystemExit(f"Téléchargement échoué : {source}")
        paths.append(os.path.join(dest, produced[0]))
    return paths


def _fetch_tiktok(source: str, dest: str, sections: list | None) -> list[str]:
    jar = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = [("User-Agent", UA)]
    final = opener.open(source, timeout=30).geturl()  # résout les liens courts vm.tiktok.com
    m = re.search(r"/video/(\d+)", final)
    vid = f"tiktok_{m.group(1) if m else hashlib.md5(final.encode()).hexdigest()[:12]}"
    base = os.path.join(dest, vid)
    path = base + ".mp4"
    if not os.path.exists(path):
        print(f"  ↓ TikTok {vid}")
        _tiktok_direct(final.split("?")[0], base)
    if not sections:
        return [path]
    return [p if os.path.exists(p) else _cut(path, a, b, p)
            for (a, b), p in ((r, f"{base}_{_section_name(*r)}.mp4") for r in sections)]
