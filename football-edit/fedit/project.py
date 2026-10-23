"""Lecture du fichier projet (YAML ou JSON)."""

import json
import os
import re

from .clips import Clip
from .download import fetch, is_url


def parse_time(v) -> float:
    """'1:23' → 83 ; '1:02:03' → 3723 ; 45 → 45."""
    if isinstance(v, (int, float)):
        return float(v)
    parts = [float(p) for p in str(v).strip().split(":")]
    total = 0.0
    for p in parts:
        total = total * 60 + p
    return total


def parse_range(v) -> tuple[float, float]:
    a, b = re.split(r"\s*(?:-|→|à)\s*(?=\d)", str(v).strip(), maxsplit=1)
    a, b = parse_time(a), parse_time(b)
    if b <= a:
        raise SystemExit(f"Moment invalide « {v} » : la fin doit être après le début.")
    return a, b


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if path.endswith(".json"):
        data = json.loads(text)
    else:
        import yaml

        data = yaml.safe_load(text)
    data["_dir"] = os.path.dirname(os.path.abspath(path))
    return data


def _local(base: str, p: str) -> str:
    return p if is_url(p) or os.path.isabs(p) else os.path.join(base, p)


def resolve_music(project: dict, dest: str) -> str:
    music = project.get("musique")
    if isinstance(music, dict):
        music = music.get("source")
    if not music:
        raise SystemExit("Le projet doit indiquer une musique (clé `musique`).")
    return fetch(_local(project["_dir"], music), dest, audio_only=True)[0]


def resolve_clips(project: dict, dest: str) -> list[Clip]:
    clips = []
    for entry in project.get("clips") or []:
        if isinstance(entry, str):
            entry = {"source": entry}
        src = _local(project["_dir"], entry["source"])
        moments = []
        for mo in entry.get("moments") or []:
            star = False
            if isinstance(mo, dict):
                star = bool(mo.get("vedette"))
                mo = mo.get("t")
            moments.append((*parse_range(mo), star))
        if is_url(src) and moments:
            # On ne télécharge que les passages indiqués : chaque passage devient un clip.
            files = fetch(src, dest, sections=[(a, b) for a, b, _ in moments])
            clips += [Clip(f, star=star) for f, (_, _, star) in zip(files, moments)]
        else:
            path = fetch(src, dest)[0]
            if moments:
                for a, b, star in moments:
                    clips.append(Clip(path, ranges=[(a, b)], star=star))
            else:
                clips.append(Clip(path, star=bool(entry.get("vedette"))))
    if not clips:
        raise SystemExit("Le projet ne contient aucun clip (clé `clips`).")
    return clips
