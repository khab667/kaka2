"""Génère des médias synthétiques dont on connaît le tempo et le drop, pour tester la synchro.

Musique : 128 BPM, intro calme 15 s (8 mesures) puis drop avec grosse caisse sur chaque temps.
Vidéos : 1080p 60 i/s, avec du mouvement et des changements de plan francs.
"""

import os
import subprocess
import sys

import numpy as np
import soundfile as sf

BPM = 128
BEAT = 60 / BPM
DROP = 32 * BEAT  # 15.0 s
SR = 44100


def music(path: str, duration: float = 40.0):
    t = np.arange(int(duration * SR)) / SR
    y = np.zeros_like(t)
    rng = np.random.default_rng(1)
    # Nappe d'accords (intro et suite).
    for f in (220.0, 277.18, 329.63):
        y += 0.05 * np.sin(2 * np.pi * f * t)
    n_beats = int(duration / BEAT)
    for k in range(n_beats):
        s = int(k * BEAT * SR)
        # Charleston léger partout (donne les temps pendant l'intro).
        hat = rng.normal(0, 1, int(0.03 * SR)) * np.exp(-np.arange(int(0.03 * SR)) / (0.006 * SR))
        y[s : s + len(hat)] += 0.08 * hat
        if k * BEAT >= DROP - 1e-6:
            n = int(0.25 * SR)
            tt = np.arange(n) / SR
            kick = np.sin(2 * np.pi * (50 + 120 * np.exp(-tt * 30)) * tt) * np.exp(-tt * 12)
            y[s : s + n] += 0.9 * kick[: len(y) - s]
            if k % 2 == 1:
                n2 = int(0.12 * SR)
                snare = rng.normal(0, 1, n2) * np.exp(-np.arange(n2) / (0.03 * SR))
                y[s : s + n2] += 0.35 * snare[: len(y) - s]
    post = t >= DROP
    y[post] += 0.25 * np.sign(np.sin(2 * np.pi * 55 * t[post])) * 0.5
    y /= np.abs(y).max() * 1.05
    sf.write(path, y.astype(np.float32), SR)


def video(path: str, parts: list[str], seconds: float):
    inputs, filters = [], []
    for i, src in enumerate(parts):
        inputs += ["-f", "lavfi", "-t", str(seconds), "-i", src]
        filters.append(f"[{i}:v]scale=1920:1080,fps=60,format=yuv420p,setsar=1[v{i}]")
    filters.append("".join(f"[v{i}]" for i in range(len(parts))) + f"concat=n={len(parts)}:v=1:a=0[out]")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(filters), "-map", "[out]",
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", path],
        check=True,
    )


def main(out_dir: str):
    os.makedirs(out_dir, exist_ok=True)
    music(os.path.join(out_dir, "musique.wav"))
    ball = ("color=c=0x2e7d32:s=1920x1080:r=60,drawbox=x='960+700*sin(t*1.7)':y='540+300*sin(t*2.3)'"
            ":w=60:h=60:c=white:t=fill,drawbox=x='300+200*sin(t)':y=600:w=80:h=200:c=red:t=fill")
    video(os.path.join(out_dir, "match1.mp4"), ["testsrc2=s=1920x1080:r=60", ball], 12)
    video(os.path.join(out_dir, "match2.mp4"), [ball, "life=s=480x270:r=60:mold=10:ratio=0.3:death_color=#202020", "testsrc2=s=1920x1080:r=60"], 10)
    print("médias de test dans", out_dir)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "test-media")
