"""Clips put into the edit (--insert): a film scene, a screen recording, B-roll with its own sound.

Each clip is converted once into a file that fits the edit, so the draft, the MP4 render and the
checks treat it like the recording itself:
- scaled to fit the frame and padded (never cropped: a screen recording of a film keeps the
  film's own subtitles in the black bar under the picture, and a crop would cut them off);
- the edit's constant frame rate, 48-kHz audio;
- its loudness matched to the recording (film sound is mixed much quieter than a conversation);
- slowed down by --speed, so that after the whole edit is sped up the clip plays at its normal
  speed (a film scene shouldn't be sped up with the talk).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Optional, Tuple

from .media import MediaInfo, probe
from .util import log


def loudness(ffmpeg: str, path: str) -> Tuple[Optional[float], Optional[float]]:
    """Integrated loudness (LUFS) and true peak (dBTP) of a file's audio, via ffmpeg's ebur128."""
    proc = subprocess.run([ffmpeg, "-hide_banner", "-nostats", "-i", path, "-vn", "-af", "ebur128=peak=true",
                           "-f", "null", "-"], capture_output=True, text=True)
    summary = proc.stderr.rsplit("Summary:", 1)[-1]
    i = re.search(r"I:\s*(-?[\d.]+|-inf) LUFS", summary)
    p = re.search(r"Peak:\s*(-?[\d.]+|-inf) dBFS", summary)
    val = lambda m: float(m.group(1)) if m and m.group(1) != "-inf" else None  # noqa: E731
    return val(i), val(p)


def prepare(ffmpeg: str, clip: str, out_path: str, width: int, height: int, fps: int, speed: float,
            target_lufs: Optional[float], encoder: str = "libx264") -> Tuple[MediaInfo, dict]:
    """Write the converted clip to out_path (reused when the clip and settings are unchanged).
    Returns its MediaInfo and what was done."""
    st = os.stat(clip)
    key = {"clip": os.path.abspath(clip), "size": st.st_size, "mtime": int(st.st_mtime), "w": width,
           "h": height, "fps": fps, "speed": speed, "target_lufs": target_lufs, "v": 1}
    side = out_path + ".json"
    if os.path.exists(out_path) and os.path.exists(side):
        with open(side, encoding="utf-8") as f:
            done = json.load(f)
        if done.get("key") == key:
            log(f"insert: reusing {os.path.basename(out_path)}")
            return probe(out_path), done["info"]
    src = probe(clip)
    if not src.has_audio:
        raise ValueError(f"{clip}: no audio stream")
    lufs, peak = loudness(ffmpeg, clip)
    gain = 0.0
    if target_lufs is not None and lufs is not None:
        gain = target_lufs - lufs
        if peak is not None:
            gain = min(gain, -1.0 - peak)  # never push the clip's peaks over -1 dBFS
    frames = int(src.duration * speed * fps)  # whole frames of the edit's grid
    vf = f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1"
    af = f"volume={gain:.2f}dB,aresample=48000"
    if speed != 1.0:
        vf += f",setpts=PTS*{speed}"
        af += f",atempo={1 / speed:.6f}"
    vf += f",fps={fps},format=yuv420p"
    venc = ["-c:v", "libx264", "-crf", "16", "-preset", "veryfast"] if encoder == "libx264" else \
        ["-c:v", encoder, "-b:v", "16M"]
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", clip, "-map", "0:v:0", "-map", "0:a:0",
           "-vf", vf, "-af", af, "-ac", "2", "-frames:v", str(frames), "-t", f"{frames / fps:.6f}",
           *venc, "-c:a", "aac", "-b:a", "320k", "-movflags", "+faststart", out_path]
    log(f"insert: converting {os.path.basename(clip)} ({src.width}x{src.height}, {src.duration:.1f}s) -> "
        f"{width}x{height} @ {fps} fps, {gain:+.1f} dB" + (f", slowed {speed}x for --speed" if speed != 1.0 else ""))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed converting {clip}:\n{proc.stderr[-2000:]}")
    info = {"clip": os.path.abspath(clip), "seconds": round(src.duration, 3), "gain_db": round(gain, 1),
            "clip_lufs": lufs, "target_lufs": target_lufs, "frames": frames}
    with open(side, "w", encoding="utf-8") as f:
        json.dump({"key": key, "info": info}, f, indent=1)
    return probe(out_path), info
