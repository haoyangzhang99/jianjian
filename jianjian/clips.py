"""Cut a finished video into clips: topic parts for a series, or highlights for short-video feeds.

Each clip is one or more spans of the video (several spans are joined, e.g. to leave out a line
in the middle). Every edge is moved to the quietest frame within `snap` seconds, so a clip starts
and ends in a pause rather than inside a word; where speakers run straight on, that is the dip
between two words. Clips are re-encoded (stream copy can only cut at keyframes) with a short
fade at each edge, so a cut that lands on the tail of a word doesn't click.

Which moments make good highlights is a judgement made from the transcript: docs/HIGHLIGHTS.md.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from typing import List, Sequence, Tuple

import numpy as np

from .util import log

Span = Tuple[float, float]
SR = 16000
FADE_IN, FADE_OUT, FADE_JOIN = 0.015, 0.03, 0.01


def seconds(t: str) -> float:
    """"312.4", "5:12.4" or "1:05:12.4" -> seconds."""
    v = 0.0
    for part in t.strip().split(":"):
        v = v * 60 + float(part)
    return v


def parse_spec(text: str) -> Tuple[str, List[Span]]:
    """"NAME=START-END[,START-END...]" -> (name, spans). Times are seconds or [h:]m:ss."""
    name, sep, rest = text.partition("=")
    name = re.sub(r"[^\w.-]+", "-", name.strip()).strip("-")
    if not sep or not name:
        raise ValueError(f"expected NAME=START-END[,START-END...], got {text!r}")
    spans = []
    for part in rest.split(","):
        a, dash, b = part.strip().partition("-")
        if not dash:
            raise ValueError(f"expected START-END in {text!r}")
        s, e = seconds(a), seconds(b)
        if e <= s:
            raise ValueError(f"span {part.strip()!r} ends before it starts")
        spans.append((s, e))
    for (_, e0), (s1, _) in zip(spans, spans[1:]):
        if s1 < e0:
            raise ValueError(f"spans in {text!r} overlap or go backwards")
    return name, spans


def frame_db(audio: np.ndarray, t: float, win: float = 0.03) -> float:
    """Loudness (dBFS) of the `win` seconds of 16-kHz audio centred on t."""
    x = audio[max(0, int((t - win / 2) * SR)):max(0, int((t + win / 2) * SR))]
    return float(20 * np.log10(np.sqrt((x.astype(np.float64) ** 2).mean()) + 1e-9)) if len(x) else -200.0


def snap(audio: np.ndarray, t: float, fps: int, window: float, lo: float = 0.0, hi: float = float("inf")) -> float:
    """The quietest frame (on the 1/fps grid) within `window` seconds of t, kept inside [lo, hi]."""
    frames = [f for f in range(int((t - window) * fps), int((t + window) * fps) + 1) if lo <= f / fps <= hi]
    if not frames:
        return t
    return min(frames, key=lambda f: (frame_db(audio, f / fps), abs(f / fps - t))) / fps


def plan(spans: Sequence[Span], audio: np.ndarray, duration: float, fps: int = 30,
         window: float = 0.25) -> List[Span]:
    """Move every edge to a quiet frame. A clip edge at 0 or at the end of the video stays put."""
    out = []
    for a, b in spans:
        a2 = a if a <= 1e-6 else snap(audio, a, fps, window, 0.0, b)
        b2 = b if b >= duration - 1e-3 else snap(audio, b, fps, window, a2 + 1.0 / fps, duration)
        out.append((round(a2, 4), round(b2, 4)))
    return out


def cut(ffmpeg: str, video: str, out_path: str, spans: Sequence[Span], encoder: List[str]) -> float:
    """Write the spans of `video`, joined in order, to out_path; returns the expected length."""
    base = max(0.0, spans[0][0] - 1.0)  # fast seek close to the first span, then trim exactly
    fc = ""
    for i, (a, b) in enumerate(spans):
        a0, b0 = a - base, b - base
        fi = FADE_IN if i == 0 else FADE_JOIN
        fo = FADE_OUT if i == len(spans) - 1 else FADE_JOIN
        fc += f"[0:v]trim=start={a0:.4f}:end={b0:.4f},setpts=PTS-STARTPTS[v{i}];"
        fc += (f"[0:a]atrim=start={a0:.4f}:end={b0:.4f},asetpts=PTS-STARTPTS,"
               f"afade=t=in:d={fi},afade=t=out:st={max(0.0, b0 - a0 - fo):.4f}:d={fo}[a{i}];")
    n = len(spans)
    fc += "".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[v][a]"
    total = spans[-1][1] - base + 0.5
    cmd = [ffmpeg, "-v", "error", "-y", "-ss", f"{base:.4f}", "-t", f"{total:.3f}", "-i", video,
           "-filter_complex", fc, "-map", "[v]", "-map", "[a]", *encoder, "-movflags", "+faststart", out_path]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode:
        raise RuntimeError(f"ffmpeg failed for {os.path.basename(out_path)}:\n{proc.stderr[-1500:]}")
    return sum(b - a for a, b in spans)


def run(video: str, specs: Sequence[Tuple[str, List[Span]]], out_dir: str, ffmpeg: str, caps: dict,
        fps: int = 30, window: float = 0.25, prefix: str = "") -> List[dict]:
    from .asr import load_audio
    from .media import probe

    info = probe(video)
    audio = load_audio(video)
    if info.has_audio and len(audio) / SR < info.duration - 1.0:
        log(f"WARNING: audio ({len(audio) / SR:.1f}s) is shorter than the video ({info.duration:.1f}s)")
    enc = (["-c:v", "libx264", "-preset", "veryfast", "-crf", "18"] if caps.get("libx264") else
           ["-c:v", "h264_videotoolbox", "-b:v", "10M"])
    enc += ["-pix_fmt", "yuv420p", "-r", str(fps), "-c:a", "aac", "-b:a", "192k"]
    os.makedirs(out_dir, exist_ok=True)
    width = len(str(len(specs)))
    done = []
    for k, (name, spans) in enumerate(specs, 1):
        if spans[-1][1] > info.duration + 0.05:
            raise ValueError(f"{name}: ends at {spans[-1][1]:.2f}s, after the end of the video ({info.duration:.2f}s)")
        final = plan(spans, audio, info.duration, fps, window)
        fname = f"{prefix}{k:0{width}d}_{name}.mp4"
        path = os.path.join(out_dir, fname)
        expected = cut(ffmpeg, video, path, final, enc)
        got = probe(path).duration
        # loudness at each cut (the start and end of the video aren't cuts)
        edges = [round(frame_db(audio, t), 1) for s in final for t in s if 1e-6 < t < info.duration - 1e-3]
        ok = abs(got - expected) < 0.15
        done.append({"file": fname, "spans": [list(s) for s in final], "requested": [list(s) for s in spans],
                     "seconds": round(got, 2), "edge_db": edges, "ok": ok})
        loud = [d for d in edges if d > -40]
        log(f"{fname}: {got:.1f}s from {len(final)} span(s)" + ("" if ok else f" (expected {expected:.1f}s!)")
            + (f"; NOTE: an edge sits in sound ({max(loud):.0f} dB): the speakers don't pause there, listen to it"
               if loud else ""))
    with open(os.path.join(out_dir, "plan.json"), "w", encoding="utf-8") as f:
        json.dump({"video": os.path.abspath(video), "snap_seconds": window, "clips": done}, f, indent=1)
    return done
