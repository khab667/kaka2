"""Rendu image par image : décodage des passages, effets synchronisés sur les beats, encodage."""

import math
import os
import subprocess
from dataclasses import dataclass

import cv2
import numpy as np

from .clips import Shot
from .styles import Style
from .timeline import Segment

FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/inter/InterDisplay-Black.otf",
    "/usr/share/fonts/opentype/inter/Inter-Black.otf",
    "/System/Library/Fonts/Supplemental/Impact.ttf",
    "C:/Windows/Fonts/impact.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


@dataclass
class Output:
    width: int = 1080
    height: int = 1920
    fps: int = 30
    preset: str = "medium"
    crf: int = 18


def _even(x: float) -> int:
    return max(2, int(round(x / 2)) * 2)


def _source_filter(shot: Shot, style: Style, out: Output) -> str:
    c = shot.clip
    W, H = out.width, out.height
    src_fps = c.fps if c.fps <= 61 else 60
    pre = f"fps={src_fps:.6f}"
    if style.framing == "square":
        # Carré centré sur l'action, posé au milieu d'un fond noir.
        side = min(c.width, c.height)
        side = min(_even(side / style.frame_zoom), side - side % 2)
        x = int(np.clip(shot.center_x * c.width - side / 2, 0, c.width - side))
        y = (c.height - side) // 2
        return (f"{pre},crop={side}:{side}:{x}:{y},scale={W}:{W}:flags=lanczos,{style.grade},"
                f"pad={W}:{H}:0:{(H - W) // 2 // 2 * 2}:black")
    if style.framing == "fit":
        fg_w = _even(W * style.frame_zoom)
        return (
            f"{pre},split[a][b];"
            f"[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=24:2,eq=brightness=-0.12[bg];"
            f"[b]scale={fg_w}:-2:flags=lanczos,crop=min(iw\\,{W}):ih[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,{style.grade}"
        )
    # Recadrage plein écran sur le centre de l'action, puis mise à l'échelle.
    factor = max(W / c.width, H / c.height) * style.frame_zoom
    cw, ch = min(_even(W / factor), c.width - c.width % 2), min(_even(H / factor), c.height - c.height % 2)
    x = int(np.clip(shot.center_x * c.width - cw / 2, 0, c.width - cw))
    y = (c.height - ch) // 2
    return f"{pre},crop={cw}:{ch}:{x}:{y},scale={W}:{H}:flags=lanczos,{style.grade}"


class SourceReader:
    """Lit les images d'un passage source dans l'ordre, à la cadence native."""

    def __init__(self, shot: Shot, span: float, style: Style, out: Output):
        self.fps = shot.clip.fps if shot.clip.fps <= 61 else 60
        self.size = out.width * out.height * 3
        self.shape = (out.height, out.width, 3)
        self.proc = subprocess.Popen(
            ["ffmpeg", "-v", "error", "-ss", f"{shot.src_start:.3f}", "-i", shot.clip.path,
             "-t", f"{span + 3 / self.fps:.3f}", "-an", "-filter_complex", _source_filter(shot, style, out),
             "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
            stdout=subprocess.PIPE,
        )
        self.index = -1
        self.frame = None

    def _next(self) -> bool:
        buf = self.proc.stdout.read(self.size)
        if len(buf) < self.size:
            return False
        self.frame = np.frombuffer(buf, np.uint8).reshape(self.shape)
        self.index += 1
        return True

    def frames_until(self, t: float, blur: int) -> np.ndarray:
        """Image au temps t (s) du passage ; moyenne les images sautées si blur > 1 (flou de mouvement)."""
        target = int(round(t * self.fps))
        skipped = []
        while self.index < target and self._next():
            skipped.append(self.frame)
        if self.frame is None:
            return np.zeros(self.shape, np.uint8)
        if blur > 1 and len(skipped) > 1:
            stack = skipped[-blur:]
            acc = np.zeros(self.shape, np.float32)
            for f in stack:
                acc += f
            return (acc / len(stack)).astype(np.uint8)
        return self.frame

    def close(self):
        self.proc.kill()
        self.proc.wait()


def _title_image(title: str, subtitle: str, width: int, size_frac: float = 0.16,
                 upper: bool = True) -> np.ndarray | None:
    if not title and not subtitle:
        return None
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    font_path = next((p for p in FONT_CANDIDATES if os.path.exists(p)), None)

    def font(size):
        return ImageFont.truetype(font_path, size) if font_path else ImageFont.load_default()

    case = str.upper if upper else str
    lines = []
    if title:
        size = int(width * size_frac)
        f = font(size)
        while f.getlength(case(title)) > width * 0.88 and size > 20:
            size -= 4
            f = font(size)
        lines.append((case(title), f, (255, 255, 255)))
    if subtitle:
        lines.append((case(subtitle), font(max(12, int(width * size_frac * 0.32))), (235, 235, 235)))
    pad = max(4, int(width * size_frac * 0.25))
    heights = [f.getbbox(t)[3] for t, f, _ in lines]
    h = sum(heights) + pad * (len(lines) + 1)
    img = Image.new("RGBA", (width, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    y = pad
    for (text, f, color), lh in zip(lines, heights):
        x = (width - f.getlength(text)) / 2
        draw.text((x, y), text, font=f, fill=color + (255,))
        y += lh + pad
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    shadow.putalpha(img.getchannel("A").filter(ImageFilter.GaussianBlur(max(2, width * size_frac * 0.075))))
    out = Image.alpha_composite(shadow, img)
    return cv2.cvtColor(np.array(out), cv2.COLOR_RGBA2BGRA)


class Effects:
    def __init__(self, style: Style, out: Output, beats: np.ndarray, downbeat: np.ndarray,
                 drop: float, total: float, title: np.ndarray | None, title_end: float, seed: int,
                 caption: np.ndarray | None = None):
        self.s, self.out = style, out
        self.beats, self.downbeat, self.drop, self.total = beats, downbeat, drop, total
        self.k = out.width / 1080  # les réglages en pixels sont donnés pour du 1080p
        rng = np.random.default_rng(seed)
        self.dirs = rng.uniform(0, 2 * math.pi, 512)
        self.title, self.title_end, self.caption = title, title_end, caption
        W, H = out.width, out.height
        if style.vignette:
            yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
            r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2) / math.sqrt(2)
            v = np.clip(1 - 0.45 * np.clip(r - 0.45, 0, 1) ** 1.6 * 2.2, 0, 1)
            self.vig = cv2.merge([np.round(v * 255).astype(np.uint8)] * 3)
        self.grain = None
        if style.grain > 0:
            g = rng.normal(0, 255 * style.grain, (4, H // 2, W // 2)).astype(np.float32)
            g = [cv2.resize(x, (W, H)) for x in g]
            # Bruit séparé en partie positive / négative pour rester en uint8 (rapide).
            self.grain = [(cv2.merge([np.clip(x, 0, 255).astype(np.uint8)] * 3),
                           cv2.merge([np.clip(-x, 0, 255).astype(np.uint8)] * 3)) for x in g]

    def _last_beat(self, T: float):
        i = int(np.searchsorted(self.beats, T + 1e-6)) - 1
        if i < 0:
            return 9.0, 0.0
        strength = 1.0 if self.downbeat[i] else 0.6
        if self.drop >= 0 and T < self.drop:
            strength *= 0.5
        return T - self.beats[i], strength

    def apply(self, frame: np.ndarray, T: float, t_cut: float, seg: Segment, seg_index: int, n_frame: int) -> np.ndarray:
        s, W, H = self.s, self.out.width, self.out.height
        a = seg.accent
        dt_beat, b = self._last_beat(T)
        punch = math.exp(-t_cut / 0.12)

        zoom = 1 + s.zoom_cut * a * punch + s.zoom_beat * b * math.exp(-dt_beat / 0.1)
        shake = s.shake * self.k * a * math.exp(-t_cut / 0.1) if a >= 0.6 else 0.0
        ang = self.dirs[seg_index % 512]
        phase = 2 * math.pi * 14 * t_cut
        dx, dy = shake * math.cos(ang) * math.sin(phase), shake * math.sin(ang) * math.cos(phase * 0.8)
        rot = s.rotation * (a if a >= 0.6 else 0) * math.exp(-t_cut / 0.12) * math.sin(phase * 0.7)
        if zoom > 1.001 or abs(dx) + abs(dy) > 0.3 or abs(rot) > 0.02:
            M = cv2.getRotationMatrix2D((W / 2, H / 2), rot, zoom)
            M[0, 2] += dx
            M[1, 2] += dy
            frame = cv2.warpAffine(frame, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

        split = int(round(s.rgb_split * a * 18 * self.k * math.exp(-t_cut / 0.12))) if a >= 0.6 else 0
        if split >= 1:
            b_, g_, r_ = cv2.split(frame)
            frame = cv2.merge([np.roll(b_, -split, axis=1), g_, np.roll(r_, split, axis=1)])

        f = frame
        if self.s.vignette:
            f = cv2.multiply(f, self.vig, scale=1 / 255)
        if self.grain is not None:
            pos, neg = self.grain[n_frame % len(self.grain)]
            f = cv2.subtract(cv2.add(f, pos), neg)
        if a >= s.flash_min_accent and s.flash > 0:
            alpha = s.flash * math.exp(-t_cut / 0.07)
            if alpha > 0.01:
                f = cv2.convertScaleAbs(f, alpha=1 - alpha, beta=255 * alpha)
        if self.title is not None and T < self.title_end:
            f = self._draw_text(f if f is not frame else f.copy(), self.title, T, 0.0, self.title_end, dt_beat)
        elif self.caption is not None and T >= self.title_end:
            f = self._draw_text(f if f is not frame else f.copy(), self.caption, T, self.title_end, self.total, dt_beat)
        fade = 1.0
        if s.fade_in > 0:
            fade = min(fade, T / s.fade_in)
        if s.fade_out > 0:
            fade = min(fade, (self.total - T) / s.fade_out)
        drop_frame = round(self.drop * self.out.fps)
        if self.drop > 0 and s.pre_drop_black > 0 and drop_frame - s.pre_drop_black * self.out.fps <= n_frame < drop_frame:
            fade = 0.0
        if fade < 1:
            f = cv2.convertScaleAbs(f, alpha=max(fade, 0.0))
        out = f if f is not frame else f.copy()
        if s.bars:
            bh = int(s.bars * self.k)
            out[:bh] = 0
            out[H - bh :] = 0
        return out

    def _draw_text(self, f: np.ndarray, img: np.ndarray, T: float, start: float, end: float, dt_beat: float) -> np.ndarray:
        t = T - start
        appear = min(1.0, t / 0.25) * min(1.0, (end - T) / 0.15)
        pop = self.s.text_pulse / 0.07 * 0.15
        scale = 1 + self.s.text_pulse * math.exp(-dt_beat / 0.1) + pop * max(0.0, 1 - t / 0.25) ** 2
        h, w = img.shape[:2]
        nw, nh = int(w * scale), int(h * scale)
        img = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
        W, H = self.out.width, self.out.height
        x0, y0 = (W - nw) // 2, int(H * self.s.text_y - nh / 2)
        xa, ya, xb, yb = max(0, x0), max(0, y0), min(W, x0 + nw), min(H, y0 + nh)
        crop = img[ya - y0 : yb - y0, xa - x0 : xb - x0].astype(np.float32)
        alpha = crop[..., 3:4] / 255 * appear
        region = f[ya:yb, xa:xb].astype(np.float32)
        f[ya:yb, xa:xb] = (region * (1 - alpha) + crop[..., :3] * alpha).astype(np.uint8)
        return f


def render(segments: list[Segment], shots: list[Shot], style: Style, out: Output,
           music: str, music_start: float, beats: np.ndarray, downbeat: np.ndarray, drop: float,
           output_path: str, title: str = "", subtitle: str = "", caption: str = "", seed: int = 0, log=print):
    total = segments[-1].end
    n_total = int(round(total * out.fps))
    title_img = _title_image(title, subtitle, out.width, style.text_size, style.text_upper)
    caption_img = _title_image(caption, "", out.width, style.text_size, style.text_upper)
    title_end = drop if drop > 0 else min(3.5, total)
    if segments and title_img is not None and segments[0].kind != "intro":
        title_end = min(title_end, segments[0].end)
    fx = Effects(style, out, beats, downbeat, drop, total, title_img, title_end, seed, caption_img)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    afade_out = max(0.0, total - style.fade_out * 1.5)
    enc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-y",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{out.width}x{out.height}", "-r", str(out.fps), "-i", "-",
         "-ss", f"{music_start:.3f}", "-t", f"{total:.3f}", "-i", music,
         "-map", "0:v", "-map", "1:a",
         "-af", f"afade=t=in:d=0.08,afade=t=out:st={afade_out:.3f}:d={total - afade_out:.3f}",
         "-c:v", "libx264", "-preset", out.preset, "-crf", str(out.crf), "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", output_path],
        stdin=subprocess.PIPE,
    )
    frame_no = 0
    try:
        for k, (seg, shot) in enumerate(zip(segments, shots)):
            f0, f1 = int(round(seg.start * out.fps)), int(round(seg.end * out.fps))
            if k == len(segments) - 1:
                f1 = n_total
            reader = SourceReader(shot, seg.source_span, style, out)
            src_step = max(seg.speeds[:2]) * reader.fps / out.fps
            blur = min(4, int(src_step)) if style.motion_blur else 1
            ts = (np.arange(f0, f1) - f0) / out.fps
            offsets = seg.source_offset(ts)
            for i, (t_cut, src_t) in enumerate(zip(ts, offsets)):
                frame = reader.frames_until(float(src_t), blur)
                T = (f0 + i) / out.fps
                enc.stdin.write(fx.apply(frame, T, float(t_cut), seg, k, frame_no).tobytes())
                frame_no += 1
            reader.close()
            log(f"  plan {k + 1}/{len(segments)} ✓", end="\r")
    finally:
        enc.stdin.close()
        enc.wait()
    log("")
    if enc.returncode != 0:
        raise SystemExit("L'encodage ffmpeg a échoué.")
    return frame_no
