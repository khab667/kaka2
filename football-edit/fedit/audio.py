"""Analyse de la musique : tempo, beats, premiers temps de mesure, énergie et drop."""

import hashlib
import os
import subprocess
from dataclasses import dataclass

import numpy as np

SR = 22050
HOP = 512


@dataclass
class MusicAnalysis:
    path: str
    duration: float
    tempo: float
    beats: np.ndarray  # temps de chaque beat (s), grille régulière recalée sur les attaques
    downbeat_phase: int  # index du premier beat qui est un "1" de mesure (0..3)
    intensity: np.ndarray  # énergie normalisée 0..1 pour chaque beat
    drop_index: int  # index du beat où la musique "explose"

    @property
    def drop(self) -> float:
        return float(self.beats[self.drop_index])

    def is_downbeat(self, i: int) -> bool:
        return (i - self.downbeat_phase) % 4 == 0


def _to_wav(path: str, cache_dir: str) -> str:
    """Convertit n'importe quel fichier audio/vidéo en WAV mono (lisible par soundfile)."""
    st = os.stat(path)
    key = hashlib.md5(f"{os.path.abspath(path)}:{st.st_size}:{st.st_mtime}".encode()).hexdigest()[:12]
    out = os.path.join(cache_dir, f"audio_{key}.wav")
    if not os.path.exists(out):
        os.makedirs(cache_dir, exist_ok=True)
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", path, "-vn", "-ac", "1", "-ar", str(SR), out],
            check=True,
        )
    return out


def _refine(beats: np.ndarray, fine_env: np.ndarray, fine_hop: float) -> np.ndarray:
    """Recale chaque beat sur le pic d'attaque le plus proche (±45 ms) d'une enveloppe haute résolution."""
    out = beats.copy()
    w = int(0.045 / fine_hop)
    for i, b in enumerate(beats):
        c = int(round(b / fine_hop))
        lo, hi = max(0, c - w), min(len(fine_env), c + w + 1)
        if hi > lo and fine_env[lo:hi].max() > 0:
            out[i] = (lo + int(np.argmax(fine_env[lo:hi]))) * fine_hop
    return out


def _regular_grid(beats: np.ndarray, duration: float, fine_env: np.ndarray, fine_hop: float) -> np.ndarray:
    """Ajuste une grille à tempo constant sur les beats détectés (recalés finement), puis
    garde l'attaque réelle quand elle est proche. Donne des beats même dans une intro sans batterie."""
    if len(beats) < 8:
        return _refine(beats, fine_env, fine_hop), float(np.median(np.diff(beats))) if len(beats) > 1 else 0.5
    period = float(np.median(np.diff(beats)))
    # Indice de chaque beat : somme des écarts arrondis entre beats successifs (pas de dérive).
    k = np.concatenate([[0], np.cumsum(np.maximum(1, np.round(np.diff(beats) / period)))])
    refined = _refine(beats, fine_env, fine_hop)
    slope, intercept = np.polyfit(k, refined, 1)
    resid = refined - (intercept + slope * k)
    good = np.abs(resid) < 0.05
    if good.sum() >= 8:
        slope, intercept = np.polyfit(k[good], refined[good], 1)
    beats = refined
    k_min = int(np.floor(-intercept / slope))
    k_max = int(np.ceil((duration - intercept) / slope))
    grid = intercept + slope * np.arange(k_min, k_max + 1)
    grid = grid[(grid >= 0) & (grid < duration)]
    idx = np.clip(np.searchsorted(beats, grid), 1, len(beats) - 1)
    nearest = np.where(
        np.abs(beats[idx] - grid) < np.abs(beats[idx - 1] - grid), beats[idx], beats[idx - 1]
    )
    return np.where(np.abs(nearest - grid) < 0.06 * slope, nearest, grid), float(slope)


def _per_beat(values: np.ndarray, frame_times: np.ndarray, beats: np.ndarray) -> np.ndarray:
    edges = np.append(beats, beats[-1] + np.median(np.diff(beats)))
    out = np.zeros(len(beats))
    for i in range(len(beats)):
        sel = (frame_times >= edges[i]) & (frame_times < edges[i + 1])
        out[i] = values[sel].mean() if sel.any() else 0.0
    return out


def _normalize(x: np.ndarray) -> np.ndarray:
    lo, hi = np.percentile(x, 5), np.percentile(x, 95)
    return np.clip((x - lo) / max(hi - lo, 1e-9), 0, 1)


def analyze(path: str, cache_dir: str = ".fedit-cache") -> MusicAnalysis:
    import librosa

    y, sr = librosa.load(_to_wav(path, cache_dir), sr=SR, mono=True)
    duration = len(y) / sr

    onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=HOP)
    tempo, beat_frames = librosa.beat.beat_track(
        onset_envelope=onset_env, sr=sr, hop_length=HOP, trim=False
    )
    beats = librosa.frames_to_time(beat_frames, sr=sr, hop_length=HOP)
    fine_hop = 128
    fine_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=fine_hop, n_fft=512)
    beats, period = _regular_grid(beats, duration, fine_env, fine_hop / sr)
    tempo = 60.0 / period

    frame_times = librosa.frames_to_time(np.arange(len(onset_env)), sr=sr, hop_length=HOP)
    spec = np.abs(librosa.stft(y, n_fft=2048, hop_length=HOP))
    low = (spec[: int(250 / (sr / 2048))] ** 2).sum(axis=0)  # énergie des basses (< 250 Hz)

    # Le "1" de la mesure est en général là où la grosse caisse / la basse frappe le plus fort.
    bass_env = np.concatenate([[0], np.maximum(0, np.diff(np.log1p(low)))])
    bass_at_beats = np.array([bass_env[max(0, j - 1) : j + 2].max() if j < len(bass_env) else 0
                              for j in np.round(beats * sr / HOP).astype(int)])
    phase = int(np.argmax([bass_at_beats[p::4].sum() for p in range(4)]))

    rms = librosa.feature.rms(y=y, hop_length=HOP)[0]
    rms_db = librosa.amplitude_to_db(rms + 1e-6)
    energy = (
        0.5 * _normalize(_per_beat(rms_db, frame_times[: len(rms_db)], beats))
        + 0.3 * _normalize(_per_beat(np.log1p(low), frame_times[: len(low)], beats))
        + 0.2 * _normalize(_per_beat(onset_env, frame_times, beats))
    )
    intensity = np.convolve(np.pad(energy, 1, mode="edge"), [0.25, 0.5, 0.25], mode="valid")

    # Drop : le beat où l'énergie des 8 beats suivants dépasse le plus celle des 8 précédents,
    # en privilégiant les premiers temps de mesure.
    best, drop_index = -np.inf, min(len(beats) - 1, 16)
    for i in range(8, len(beats) - 8):
        score = energy[i : i + 8].mean() - energy[i - 8 : i].mean()
        if (i - phase) % 4 == 0:
            score += 0.05
        if score > best:
            best, drop_index = score, i

    return MusicAnalysis(path, duration, tempo, beats, phase, intensity, drop_index)


def choose_window(m: MusicAnalysis, duration: float, start: float | None = None) -> tuple[float, float]:
    """Choisit l'extrait de musique : par défaut le drop tombe vers 35 % du montage.
    Début et fin sont recalés sur des premiers temps de mesure."""
    downbeats = m.beats[m.downbeat_phase :: 4]
    if start is None:
        lead = float(np.clip(0.35 * duration, 3.0, 10.0))
        target = m.drop - lead
        cands = downbeats[downbeats <= max(target, downbeats[0]) + 1e-6]
        start = float(cands[-1]) if len(cands) else float(downbeats[0])
    else:
        start = float(m.beats[np.argmin(np.abs(m.beats - start))])
    start = max(0.0, min(start, m.duration - duration))
    end_target = start + duration
    ends = downbeats[(downbeats > start + 0.6 * duration) & (downbeats <= m.duration - 0.05)]
    end = float(ends[np.argmin(np.abs(ends - end_target))]) if len(ends) else min(end_target, m.duration)
    return start, end
