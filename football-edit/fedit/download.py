"""Téléchargement des sources (YouTube, TikTok, …) avec yt-dlp. Les chemins locaux sont gardés tels quels."""

import os
import re


def is_url(s: str) -> bool:
    return bool(re.match(r"^https?://", s))


def _section_name(a: float, b: float) -> str:
    return f"{int(a * 10):06d}-{int(b * 10):06d}"


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
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
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
            "format": fmt,
            "outtmpl": base + ".%(ext)s",
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
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
