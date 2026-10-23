"""Analyse d'un montage existant (ex. un TikTok qui t'inspire) : rythme des coupes et synchro sur les beats."""

import re
import subprocess

import numpy as np

from . import audio


def scene_cuts(path: str, threshold: float = 0.3) -> np.ndarray:
    res = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", path, "-an", "-vf", f"select='gt(scene,{threshold})',showinfo",
         "-f", "null", "-"],
        capture_output=True, text=True,
    )
    return np.array([float(x) for x in re.findall(r"pts_time:([\d.]+)", res.stderr)])


def describe(path: str, cache_dir: str) -> dict:
    cuts = scene_cuts(path)
    m = audio.analyze(path, cache_dir)
    shots = np.diff(np.concatenate([[0], cuts, [m.duration]]))
    if len(cuts):
        dist = np.min(np.abs(cuts[:, None] - m.beats[None, :]), axis=1)
        on_beat = float((dist < 0.07).mean())
    else:
        on_beat = 0.0
    beat = 60 / m.tempo
    pre = cuts[cuts < m.drop]
    post = cuts[cuts >= m.drop]
    pre_len = np.diff(np.concatenate([[0], pre, [m.drop]])).mean() if len(pre) else m.drop
    post_len = np.diff(np.concatenate([[m.drop], post, [m.duration]])).mean() if len(post) else m.duration - m.drop
    return {
        "durée": round(m.duration, 2),
        "bpm": round(m.tempo, 1),
        "drop": round(m.drop, 2),
        "coupes": len(cuts),
        "plan_moyen_s": round(float(shots.mean()), 2),
        "coupes_sur_beat": f"{on_beat:.0%}",
        "beats_par_plan_avant_drop": round(pre_len / beat, 1),
        "beats_par_plan_après_drop": round(post_len / beat, 1),
        "temps_des_coupes": [round(float(c), 2) for c in cuts],
    }


def suggest_style(d: dict) -> str:
    after = d["beats_par_plan_après_drop"]
    if after <= 1.3:
        return "hype"
    if after <= 2.5:
        return "velocity"
    if after <= 4.5:
        return "classique"
    return "cinematique"
