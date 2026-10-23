"""Analyse des vidéos sources (mouvement, changements de plan, centre de l'action)
et choix du meilleur passage pour chaque plan du montage."""

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass, field
from fractions import Fraction

import cv2
import numpy as np

from .timeline import Segment

SAMPLE_FPS = 8
SAMPLE_W = 192


@dataclass
class Clip:
    path: str
    ranges: list = field(default_factory=list)  # [(début, fin)] autorisés ; vide = toute la vidéo
    star: bool = False  # passage "vedette" : réservé aux moments forts (drop)
    mask: tuple | None = None  # (x, y, largeur, hauteur) d'un logo à effacer, en pixels de la source
    # Rempli par analyze() :
    duration: float = 0.0
    fps: float = 30.0
    width: int = 1920
    height: int = 1080
    times: np.ndarray = None
    motion: np.ndarray = None  # mouvement par échantillon (nan = image inutilisable)
    center_x: np.ndarray = None  # position horizontale de l'action 0..1
    cuts: np.ndarray = None  # changements de plan dans la source (s)


def probe(path: str) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height,r_frame_rate:format=duration", "-of", "json", path],
        check=True, capture_output=True, text=True,
    ).stdout
    info = json.loads(out)
    st = info["streams"][0]
    return {
        "width": int(st["width"]),
        "height": int(st["height"]),
        "fps": float(Fraction(st["r_frame_rate"])),
        "duration": float(info["format"]["duration"]),
    }


def analyze(clip: Clip, cache_dir: str = ".fedit-cache") -> Clip:
    info = probe(clip.path)
    clip.width, clip.height, clip.fps, clip.duration = info["width"], info["height"], info["fps"], info["duration"]

    st = os.stat(clip.path)
    key = hashlib.md5(f"{os.path.abspath(clip.path)}:{st.st_size}:{st.st_mtime}:v3".encode()).hexdigest()[:12]
    cache = os.path.join(cache_dir, f"motion_{key}.npz")
    if os.path.exists(cache):
        d = np.load(cache)
        clip.times, clip.motion, clip.center_x, clip.cuts = d["times"], d["motion"], d["center_x"], d["cuts"]
        return clip

    h = int(round(SAMPLE_W * clip.height / clip.width / 2) * 2)
    proc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", clip.path, "-vf", f"fps={SAMPLE_FPS},scale={SAMPLE_W}:{h}",
         "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        stdout=subprocess.PIPE,
    )
    size = SAMPLE_W * h
    motion, centers, cuts, prev, prev_hist = [], [], [], None, None
    cols = np.arange(SAMPLE_W, dtype=np.float32)
    j = 0
    while True:
        buf = proc.stdout.read(size)
        if len(buf) < size:
            break
        f = np.frombuffer(buf, np.uint8).reshape(h, SAMPLE_W)
        hist = cv2.calcHist([f], [0], None, [32], [0, 256])
        cv2.normalize(hist, hist)
        m, cx = np.nan, 0.5
        if prev is not None:
            diff = cv2.absdiff(f, prev)
            d = float(diff.mean())
            corr = cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CORREL)
            if (d > 22 and corr < 0.75) or corr < 0.45:
                cuts.append(j / SAMPLE_FPS)
            elif f.std() > 6:  # écarte les images noires / unies (transitions, logos)
                m = d
                weights = (diff > 18).sum(axis=0).astype(np.float32)
                if weights.sum() > 0.01 * diff.size:
                    cx = float((weights * cols).sum() / weights.sum() / SAMPLE_W)
        motion.append(m)
        centers.append(cx)
        prev, prev_hist = f, hist
        j += 1
    proc.wait()

    clip.times = np.arange(len(motion)) / SAMPLE_FPS
    clip.motion = np.array(motion, dtype=np.float32)
    # Lissage du centre de l'action sur ~1 s pour éviter un recadrage nerveux.
    c = np.array(centers, dtype=np.float32)
    clip.center_x = np.convolve(np.pad(c, 4, mode="edge"), np.ones(9) / 9, mode="valid") if len(c) else c
    clip.cuts = np.array(cuts, dtype=np.float32)
    os.makedirs(cache_dir, exist_ok=True)
    np.savez(cache, times=clip.times, motion=clip.motion, center_x=clip.center_x, cuts=clip.cuts)
    return clip


@dataclass
class Shot:
    clip: Clip
    src_start: float
    center_x: float
    score: float


def select(segments: list[Segment], clips: list[Clip], seed: int = 0) -> list[Shot]:
    """Attribue à chaque plan un passage source, sans réutiliser deux fois la même image.
    Les plans les plus intenses (drop d'abord) choisissent en premier."""
    rng = np.random.default_rng(seed)
    all_m = np.concatenate([c.motion[~np.isnan(c.motion)] for c in clips if len(c.motion)])
    scale = float(np.percentile(all_m, 95)) if len(all_m) else 1.0
    used: dict[int, list] = {i: [] for i in range(len(clips))}
    shots: list[Shot | None] = [None] * len(segments)

    warned = False
    order = sorted(range(len(segments)), key=lambda k: (segments[k].kind != "drop", -segments[k].energy))
    for k in order:
        seg = segments[k]
        span = seg.source_span + 0.05
        desired = 0.35 + 0.6 * seg.energy
        neighbours = {id(s.clip) for s in (shots[k - 1] if k else None, shots[k + 1] if k + 1 < len(shots) else None) if s}
        best = None
        for relax in (0, 1, 2):  # 0 = strict ; 1 = réutilisation permise ; 2 = traverse un changement de plan
            for ci, clip in enumerate(clips):
                valid = ~np.isnan(clip.motion)
                csum = np.concatenate([[0], np.cumsum(np.where(valid, clip.motion, 0))])
                cvalid = np.concatenate([[0], np.cumsum(valid)])
                ccx = np.concatenate([[0], np.cumsum(clip.center_x)])
                for a, b in clip.ranges or [(0.0, clip.duration)]:
                    a = max(0.0, a)
                    hi = min(max(a, b - span), clip.duration - span - 0.1)
                    starts = np.arange(a, hi + 1e-6, 0.2)
                    if len(starts) == 0:
                        continue
                    ends = starts + span
                    lo_i = np.searchsorted(clip.times, starts)
                    hi_i = np.searchsorted(clip.times, ends, side="right")
                    n = np.maximum(hi_i - lo_i, 1)
                    nvalid = cvalid[hi_i] - cvalid[lo_i]
                    ok = (hi_i > lo_i) & (nvalid >= 0.7 * n)
                    if relax < 2:
                        crossing = np.searchsorted(clip.cuts, ends - 0.05) - np.searchsorted(clip.cuts, starts + 0.05, side="right")
                        ok &= crossing <= 0
                    near_used = np.zeros(len(starts), bool)
                    overlaps = np.zeros(len(starts))
                    for us, ue in used[ci]:
                        overlaps += (starts < ue + 0.3) & (ends > us - 0.3)
                        near_used |= np.abs(starts - us) < 3
                    if relax < 1:
                        ok &= overlaps == 0
                    if not ok.any():
                        continue
                    m = np.minimum((csum[hi_i] - csum[lo_i]) / np.maximum(nvalid, 1) / scale, 1.5)
                    score = 1 - np.abs(m - desired) + 0.25 * np.minimum(m, 1) - 0.1 * near_used - 0.6 * overlaps
                    if clip.star:
                        score += 0.8 * seg.energy + (0.6 if seg.kind == "drop" else 0)
                    if id(clip) in neighbours:
                        score -= 0.15
                    if seed:
                        score += rng.uniform(0, 0.08, len(score))
                    score[~ok] = -np.inf
                    i = int(np.argmax(score))
                    if best is None or score[i] > best.score:
                        cx = float((ccx[hi_i[i]] - ccx[lo_i[i]]) / n[i])
                        best = Shot(clip, float(starts[i]), cx, float(score[i]))
            if best:
                if relax and not warned:
                    print("  ⚠ pas assez de vidéo source : certains passages sont réutilisés (ajoute des clips ou des moments)")
                    warned = True
                break
        if best is None:
            raise SystemExit(
                f"Pas assez de vidéo source pour le plan {k + 1} ({span:.1f} s de source). Ajoute des clips."
            )
        shots[k] = best
        used[clips.index(best.clip)].append((best.src_start, best.src_start + span))
    return shots
