"""Préréglages de style. Chaque champ peut être surchargé dans le projet (clé `reglages`)."""

from dataclasses import dataclass, fields, replace


@dataclass
class Style:
    name: str
    # Rythme : nombre de beats par plan selon l'énergie de la musique (faible, moyenne, forte).
    beats_per_cut: tuple = (4, 2, 1)
    min_shot: float = 0.3  # durée minimale d'un plan (s)
    # Vitesse de lecture : avant le drop / après le drop (1 = normal, 0.5 = ralenti x2).
    speed_intro: float = 0.6
    speed_hype: float = 1.0
    # Effet "velocity" après le drop : (vitesse rapide, vitesse lente, part du plan en rapide).
    ramp: tuple | None = None
    ramp_min_shot: float = 0.45  # le velocity ne s'applique qu'aux plans assez longs
    motion_blur: bool = True  # flou de mouvement sur les passages accélérés
    # Effets au changement de plan, multipliés par l'accent du plan (drop = 1).
    zoom_cut: float = 0.1  # zoom "punch" qui se relâche
    zoom_beat: float = 0.03  # petite pulsation sur chaque beat
    shake: float = 10.0  # tremblement (pixels en 1080p)
    rotation: float = 1.0  # rotation du tremblement (degrés)
    flash: float = 0.6  # flash blanc
    flash_min_accent: float = 0.75  # accent minimum pour déclencher un flash
    rgb_split: float = 0.8  # aberration chromatique
    pre_drop_black: float = 0.1  # écran noir juste avant le drop (s), 0 = désactivé
    # Image.
    grade: str = "eq=contrast=1.12:saturation=1.3,unsharp=5:5:0.5"
    vignette: bool = True
    grain: float = 0.0
    bars: int = 0  # bandes noires haut/bas (pixels en 1080x1920)
    framing: str = "crop"  # "crop" (plein écran, recadré sur l'action) ou "fit" (fond flou)
    frame_zoom: float = 1.0  # zoom supplémentaire dans la source
    fade_in: float = 0.2
    fade_out: float = 0.6


PRESETS = {
    "hype": Style("hype"),
    "velocity": Style(
        "velocity",
        beats_per_cut=(4, 2, 2),
        min_shot=0.4,
        speed_intro=0.5,
        ramp=(2.4, 0.3, 0.35),
        zoom_cut=0.08,
        zoom_beat=0.05,
        shake=5.0,
        rotation=0.5,
        flash=0.35,
        flash_min_accent=0.9,
        rgb_split=0.6,
    ),
    "cinematique": Style(
        "cinematique",
        beats_per_cut=(8, 4, 2),
        min_shot=0.8,
        speed_intro=0.45,
        speed_hype=0.75,
        zoom_cut=0.03,
        zoom_beat=0.015,
        shake=0.0,
        rotation=0.0,
        flash=0.25,
        flash_min_accent=0.95,
        rgb_split=0.0,
        pre_drop_black=0.0,
        grade="eq=contrast=1.08:saturation=0.85:gamma=0.97,colorbalance=rs=0.04:bs=-0.04:rh=0.04:bh=-0.05",
        grain=0.06,
        fade_in=0.6,
        fade_out=1.2,
    ),
    "classique": Style(
        "classique",
        beats_per_cut=(4, 2, 2),
        min_shot=0.35,
        speed_intro=0.8,
        zoom_cut=0.06,
        zoom_beat=0.025,
        shake=0.0,
        rotation=0.0,
        flash=0.3,
        flash_min_accent=0.95,
        rgb_split=0.0,
        pre_drop_black=0.0,
    ),
}


def get_style(name: str, overrides: dict | None = None) -> Style:
    if name not in PRESETS:
        raise SystemExit(f"Style inconnu « {name} ». Choix : {', '.join(PRESETS)}")
    style = PRESETS[name]
    if overrides:
        known = {f.name for f in fields(Style)}
        unknown = set(overrides) - known
        if unknown:
            raise SystemExit(f"Réglages inconnus : {', '.join(sorted(unknown))}")
        style = replace(style, **{k: tuple(v) if isinstance(v, list) else v for k, v in overrides.items()})
    return style
