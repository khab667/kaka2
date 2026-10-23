"""Ligne de commande : python -m fedit <commande> …"""

import argparse
import json
import os
import sys
import time

from . import audio, clips as clipmod, project as projmod, reference, timeline
from .download import fetch
from .render import Output, render
from .styles import PRESETS, get_style


def fmt(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:05.2f}"


def cmd_beats(args):
    path = fetch(args.musique, args.sources, audio_only=True)[0]
    m = audio.analyze(path, args.cache)
    start, end = audio.choose_window(m, args.duree)
    print(f"Durée      : {fmt(m.duration)}")
    print(f"Tempo      : {m.tempo:.1f} BPM ({len(m.beats)} beats)")
    print(f"Drop       : {fmt(m.drop)}")
    print(f"Extrait conseillé pour {args.duree:.0f} s : {fmt(start)} → {fmt(end)}")


def cmd_reference(args):
    path = fetch(args.video, args.sources)[0]
    d = reference.describe(path, args.cache)
    cuts = d.pop("temps_des_coupes")
    for k, v in d.items():
        print(f"{k:28s}: {v}")
    print(f"{'coupes (s)':28s}: {', '.join(f'{c:.2f}' for c in cuts[:40])}{' …' if len(cuts) > 40 else ''}")
    print(f"\nStyle le plus proche : {reference.suggest_style(d)}")


def cmd_download(args):
    for p in fetch(args.url, args.sources, audio_only=args.audio):
        print(p)


def cmd_render(args):
    proj = projmod.load(args.projet)
    base = proj["_dir"]
    cache = args.cache or os.path.join(base, ".fedit-cache")
    sources = args.sources or os.path.join(base, "sources")
    style = get_style(args.style or proj.get("style", "hype"), proj.get("reglages"))
    duration = float(args.duree or proj.get("duree", 20))
    music_cfg = proj.get("musique") if isinstance(proj.get("musique"), dict) else {}
    debut = music_cfg.get("debut", "auto")

    print("♪ Musique…")
    music = projmod.resolve_music(proj, sources)
    m = audio.analyze(music, cache)
    if music_cfg.get("drop") is not None:
        m.drop_index = m.nearest_downbeat(projmod.parse_time(music_cfg["drop"]))
    start, end = audio.choose_window(m, duration, None if debut in (None, "auto") else projmod.parse_time(debut))
    print(f"  {m.tempo:.1f} BPM · drop à {fmt(m.drop)} · extrait {fmt(start)} → {fmt(end)}")

    segments, beats, downbeat, drop = timeline.plan(m, style, start, end)
    print(f"  {len(segments)} plans · style {style.name}")

    print("▶ Vidéos…")
    clip_list = projmod.resolve_clips(proj, sources)
    for c in clip_list:
        clipmod.analyze(c, cache)
        print(f"  {os.path.basename(c.path)} · {c.duration:.0f} s · {c.width}x{c.height} @ {c.fps:.0f} i/s")

    out_cfg = Output(fps=args.fps or int(proj.get("fps", 30)))
    if args.apercu:
        out_cfg = Output(540, 960, out_cfg.fps, "veryfast", 23)

    output = args.sortie or os.path.join(base, "rendus", f"{os.path.splitext(os.path.basename(args.projet))[0]}.mp4")
    seeds = [args.seed + i for i in range(args.variantes)]
    for v, seed in enumerate(seeds):
        path = output if len(seeds) == 1 else output.replace(".mp4", f"_v{v + 1}.mp4")
        shots = clipmod.select(segments, clip_list, seed)
        plan = [
            {"plan": k + 1, "debut": round(s.start, 3), "fin": round(s.end, 3), "type": s.kind,
             "energie": round(s.energy, 2), "vitesse": list(s.speeds), "source": os.path.basename(sh.clip.path),
             "source_debut": fmt(sh.src_start)}
            for k, (s, sh) in enumerate(zip(segments, shots))
        ]
        print(f"■ Rendu {path}")
        t0 = time.time()
        render(segments, shots, style, out_cfg, music, start, beats, downbeat, drop, path,
               title=proj.get("titre", ""), subtitle=proj.get("sous_titre", ""),
               caption=proj.get("legende", ""), seed=seed)
        with open(path.replace(".mp4", ".plan.json"), "w", encoding="utf-8") as f:
            json.dump({"musique": os.path.basename(music), "debut_musique": round(start, 3), "bpm": round(m.tempo, 1),
                       "drop": round(drop, 3), "plans": plan}, f, ensure_ascii=False, indent=1)
        print(f"  terminé en {time.time() - t0:.0f} s → {path}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="fedit", description="Montages foot automatiques calés sur la musique.")
    p.add_argument("--cache", default=None, help="dossier de cache des analyses")
    p.add_argument("--sources", default=None, help="dossier des téléchargements")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("render", help="fabrique le montage à partir d'un projet YAML")
    r.add_argument("projet")
    r.add_argument("-o", "--sortie")
    r.add_argument("--style", choices=list(PRESETS))
    r.add_argument("--duree", type=float, help="durée du montage en secondes")
    r.add_argument("--fps", type=int, choices=[24, 25, 30, 50, 60])
    r.add_argument("--apercu", action="store_true", help="rendu rapide en 540x960")
    r.add_argument("--variantes", type=int, default=1, help="nombre de versions différentes à générer")
    r.add_argument("--seed", type=int, default=0)
    r.set_defaults(func=cmd_render)

    b = sub.add_parser("beats", help="analyse une musique (BPM, drop, extrait conseillé)")
    b.add_argument("musique")
    b.add_argument("--duree", type=float, default=20)
    b.set_defaults(func=cmd_beats)

    ref = sub.add_parser("reference", help="analyse un montage existant (fichier ou lien TikTok/YouTube)")
    ref.add_argument("video")
    ref.set_defaults(func=cmd_reference)

    d = sub.add_parser("download", help="télécharge une vidéo ou une musique")
    d.add_argument("url")
    d.add_argument("--audio", action="store_true")
    d.set_defaults(func=cmd_download)

    args = p.parse_args(argv)
    if args.cmd != "render":
        args.cache = args.cache or ".fedit-cache"
        args.sources = args.sources or "sources"
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
