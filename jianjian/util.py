from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import time
from typing import Optional

_T0 = time.time()
_LOG_FILE = None


def set_log_file(path: str) -> None:
    global _LOG_FILE
    _LOG_FILE = open(path, "a", encoding="utf-8")


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')} +{time.time() - _T0:6.0f}s] {msg}"
    print(line, flush=True)
    if _LOG_FILE:
        _LOG_FILE.write(line + "\n")
        _LOG_FILE.flush()


def die(msg: str, code: int = 1):
    log("ERROR: " + msg)
    sys.exit(code)


def read_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: str, data) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def is_mac() -> bool:
    return platform.system() == "Darwin"


def mac_ram_gb() -> Optional[float]:
    try:
        out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, check=True)
        return int(out.stdout.strip()) / 1024 ** 3
    except Exception:
        return None


def find_ffmpeg() -> Optional[str]:
    """$JIANJIAN_FFMPEG if set; otherwise the first ffmpeg with libass (needed to burn in subtitles),
    checking the system ones before imageio-ffmpeg's bundled build. Homebrew's ffmpeg 8+ ships
    without libass, so on a typical Mac the bundled build is the one that gets used."""
    if os.environ.get("JIANJIAN_FFMPEG"):
        return os.environ["JIANJIAN_FFMPEG"]
    cands = [shutil.which("ffmpeg"), "/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg",
             os.path.expanduser("~/.homebrew/bin/ffmpeg")]
    try:
        import imageio_ffmpeg
        cands.append(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        pass
    seen = []
    for p in cands:
        if p and p not in seen and os.path.exists(p):
            seen.append(p)
    for p in seen:
        if ffmpeg_caps(p)["libass"]:
            return p
    return seen[0] if seen else None


def ffmpeg_caps(ffmpeg: str) -> dict:
    def q(arg):
        try:
            return subprocess.run([ffmpeg, "-hide_banner", arg], capture_output=True, text=True).stdout
        except Exception:
            return ""
    filters, encoders = q("-filters"), q("-encoders")
    ver = subprocess.run([ffmpeg, "-version"], capture_output=True, text=True).stdout.split("\n")[0]
    major = 0
    try:
        tok = ver.split()[2]
        major = int(tok.lstrip("n").split(".")[0])
    except Exception:
        pass
    return {
        "path": ffmpeg,
        "version": ver,
        "major": major,
        "libass": " subtitles " in filters,
        "videotoolbox": "h264_videotoolbox" in encoders,
        "libx264": "libx264" in encoders,
    }


def fmt_dur(sec: float) -> str:
    sec = int(round(sec))
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
