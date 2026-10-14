"""Media probing (PyAV, with an ffprobe fallback)."""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, asdict


@dataclass
class MediaInfo:
    path: str
    duration: float
    width: int
    height: int
    fps: float
    has_audio: bool
    video_start: float = 0.0
    audio_start: float = 0.0
    video_codec: str = ""
    audio_codec: str = ""

    def to_dict(self):
        return asdict(self)


def _probe_av(path: str) -> MediaInfo:
    import av
    with av.open(path) as c:
        v = next((s for s in c.streams if s.type == "video"), None)
        a = next((s for s in c.streams if s.type == "audio"), None)
        if v is None:
            raise ValueError("no video stream")
        dur = float(c.duration / 1_000_000) if c.duration else float(v.duration * v.time_base)
        rate = v.average_rate or v.guessed_rate or 30
        vs = float(v.start_time * v.time_base) if v.start_time is not None else 0.0
        as_ = float(a.start_time * a.time_base) if (a is not None and a.start_time is not None) else 0.0
        return MediaInfo(path, dur, v.codec_context.width, v.codec_context.height, float(rate),
                         a is not None, vs, as_, v.codec_context.name, a.codec_context.name if a else "")


def _probe_ffprobe(path: str) -> MediaInfo:
    exe = shutil.which("ffprobe")
    if not exe:
        raise RuntimeError("neither PyAV nor ffprobe available")
    out = subprocess.run([exe, "-v", "error", "-show_format", "-show_streams", "-of", "json", path],
                         capture_output=True, text=True, check=True).stdout
    d = json.loads(out)
    v = next(s for s in d["streams"] if s["codec_type"] == "video")
    a = next((s for s in d["streams"] if s["codec_type"] == "audio"), None)
    num, den = (v.get("avg_frame_rate") or "30/1").split("/")
    fps = float(num) / float(den) if float(den) else 30.0
    return MediaInfo(path, float(d["format"]["duration"]), int(v["width"]), int(v["height"]), fps,
                     a is not None, float(v.get("start_time", 0) or 0), float((a or {}).get("start_time", 0) or 0),
                     v.get("codec_name", ""), (a or {}).get("codec_name", ""))


def probe(path: str) -> MediaInfo:
    try:
        return _probe_av(path)
    except ImportError:
        return _probe_ffprobe(path)
