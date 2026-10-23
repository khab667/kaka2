"""Découpage du montage en plans calés sur les beats."""

from dataclasses import dataclass

import numpy as np

from .audio import MusicAnalysis
from .styles import Style


@dataclass
class Segment:
    start: float  # temps dans le montage (s), 0 = début de l'extrait musical
    end: float
    energy: float  # énergie de la musique 0..1
    kind: str  # "intro", "drop" ou "hype"
    accent: float  # force des effets au changement de plan
    speeds: tuple  # (vitesse début, vitesse fin, part en vitesse début) ; constante si égales

    @property
    def duration(self) -> float:
        return self.end - self.start

    def source_offset(self, t: np.ndarray) -> np.ndarray:
        """Position dans la source (s, depuis le début du passage choisi) pour un temps t du plan."""
        v1, v2, r = self.speeds
        if v1 == v2:
            return v1 * t
        # Passage progressif de v1 à v2 autour de r (smoothstep), intégré numériquement.
        grid = np.linspace(0, self.duration, 400)
        u = np.clip((grid / self.duration - (r - 0.12)) / 0.24, 0, 1)
        speed = v1 + (v2 - v1) * u * u * (3 - 2 * u)
        pos = np.concatenate([[0], np.cumsum((speed[1:] + speed[:-1]) / 2 * np.diff(grid))])
        return np.interp(t, grid, pos)

    @property
    def source_span(self) -> float:
        return float(self.source_offset(np.array([self.duration]))[0])


def plan(m: MusicAnalysis, style: Style, start: float, end: float):
    """Retourne (plans, beats relatifs au début, masque des premiers temps, drop relatif ou -1)."""
    rel = m.beats - start
    inside = np.where((rel > -1e-3) & (rel < end - start - 1e-3))[0]
    first, last = int(inside[0]), int(inside[-1])
    drop_i = m.drop_index if first < m.drop_index <= last else None

    def beats_per_cut(e: float) -> int:
        low, mid, high = style.beats_per_cut
        return low if e < 0.35 else mid if e < 0.68 else high

    cuts = [first]
    i = first
    while True:
        n = beats_per_cut(float(m.intensity[i]))
        j = i + 1
        # Plans longs alignés sur la mesure ; jamais plus courts que min_shot.
        while j <= last and ((j - m.downbeat_phase) % n != 0 or m.beats[j] - m.beats[i] < style.min_shot):
            j += 1
        if drop_i is not None and i < drop_i < j:
            j = drop_i  # on coupe toujours pile sur le drop
        if j > last:
            break
        cuts.append(j)
        i = j

    total = end - start
    times = [max(0.0, float(rel[c])) for c in cuts] + [total]
    times[0] = 0.0
    if times[-1] - times[-2] < style.min_shot and len(times) > 2:
        del times[-2]
        cuts.pop()

    segments = []
    for k, c in enumerate(cuts):
        s, e = times[k], times[k + 1]
        if drop_i is None:
            kind = "hype" if m.intensity[c] > 0.5 else "intro"
        else:
            kind = "intro" if c < drop_i else "drop" if c == drop_i else "hype"
        if kind == "drop":
            accent = 1.0
        elif m.is_downbeat(c):
            accent = 0.85 if kind == "hype" else 0.6
        else:
            accent = 0.5 if kind == "hype" else 0.4
        if kind == "intro":
            speeds = (style.speed_intro,) * 2 + (0.0,)
        elif style.ramp and e - s >= style.ramp_min_shot:
            speeds = tuple(style.ramp)
        else:
            speeds = (style.speed_hype,) * 2 + (0.0,)
        segments.append(Segment(s, e, float(m.intensity[c]), kind, accent, speeds))

    drop_rel = float(rel[drop_i]) if drop_i is not None else -1.0
    keep = (rel > -1e-3) & (rel < total)
    downbeat = np.array([m.is_downbeat(i) for i in range(len(rel))])
    return segments, rel[keep], downbeat[keep], drop_rel
