"""Test de bout en bout sur des médias synthétiques : python3 tests/test_sync.py

Vérifie que le tempo et le drop sont bien détectés, que chaque coupe tombe sur un beat
à moins d'une demi-image près, et que la vidéo rendue a la bonne durée et le bon format.
"""

import json
import os
import subprocess
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import make_test_media  # noqa: E402
from fedit import audio  # noqa: E402
from fedit.__main__ import main  # noqa: E402


def check(cond, msg):
    print(("  ✓ " if cond else "  ✗ ") + msg)
    if not cond:
        sys.exit(1)


def run():
    with tempfile.TemporaryDirectory() as d:
        make_test_media.main(d)
        m = audio.analyze(os.path.join(d, "musique.wav"), os.path.join(d, "cache"))
        truth = np.arange(0, m.duration, make_test_media.BEAT)
        err = np.array([np.min(np.abs(truth - b)) for b in m.beats])
        check(abs(m.tempo - make_test_media.BPM) < 0.5, f"tempo {m.tempo:.2f} BPM")
        check(abs(m.drop - make_test_media.DROP) < 0.03, f"drop {m.drop:.3f} s")
        check(err.max() < 0.025, f"erreur max sur les beats {err.max() * 1000:.0f} ms")

        with open(os.path.join(d, "projet.yaml"), "w") as f:
            f.write("titre: Test\nstyle: hype\nduree: 16\nmusique: musique.wav\nclips:\n  - match1.mp4\n  - match2.mp4\n")
        out = os.path.join(d, "rendu.mp4")
        main(["render", os.path.join(d, "projet.yaml"), "--apercu", "-o", out])

        plan = json.load(open(out.replace(".mp4", ".plan.json")))
        start = plan["debut_musique"]
        fps = 30
        for p in plan["plans"][1:]:
            nearest = np.min(np.abs(m.beats - start - p["debut"]))
            if nearest > 0.5 / fps:
                check(False, f"plan {p['plan']} à {p['debut']} s hors beat ({nearest * 1000:.0f} ms)")
        check(True, f"{len(plan['plans'])} plans, toutes les coupes sur un beat")
        check(any(p["type"] == "drop" for p in plan["plans"]), "un plan démarre pile sur le drop")

        info = json.loads(subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration",
             "-of", "json", out], capture_output=True, text=True, check=True).stdout)
        v = next(s for s in info["streams"] if s["codec_type"] == "video")
        dur = float(info["format"]["duration"])
        expected = plan["plans"][-1]["fin"]
        check((v["width"], v["height"]) == (540, 960), "format vertical 9:16")
        check(any(s["codec_type"] == "audio" for s in info["streams"]), "piste audio présente")
        check(abs(dur - expected) < 0.1, f"durée {dur:.2f} s (attendu {expected:.2f} s)")
    print("Tout est bon.")


if __name__ == "__main__":
    run()
