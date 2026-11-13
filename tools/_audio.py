"""Small audio helpers shared by the tools: load a file as 16 kHz mono, a level envelope, and where
speech starts and stops. Cut points for retakes are placed from this envelope, not from Whisper's
word times, which can be a second off around a retake."""
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from jianjian.util import find_ffmpeg  # noqa: E402

SR = 16000
HOP = 0.01  # seconds per envelope frame


def load_audio(path):
    """Any media file -> float32 mono at 16 kHz."""
    raw = subprocess.run([find_ffmpeg(), "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"],
                         check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768


def envelope(a, sr=SR, smooth=5):
    """Level in dB per 10 ms, lightly smoothed."""
    n = int(sr * HOP)
    m = len(a) // n
    e = 10 * np.log10((a[:m * n].reshape(m, n) ** 2).mean(1) + 1e-10)
    return np.convolve(e, np.ones(smooth) / smooth, mode="same") if smooth > 1 else e


def threshold(e, above=18.0):
    """Speech threshold: `above` dB over the noise floor (10th percentile of the envelope)."""
    return float(np.percentile(e, 10)) + above


def speech_runs(e, thr=None, bridge=0.30, min_len=0.08):
    """[(start, end)] in seconds where the level is above the threshold, gaps shorter than `bridge`
    joined and blips shorter than `min_len` dropped."""
    thr = threshold(e) if thr is None else thr
    on = e > thr
    runs, i = [], 0
    while i < len(on):
        if on[i]:
            j = i
            while j < len(on) and on[j]:
                j += 1
            if runs and (i - runs[-1][1]) * HOP < bridge:
                runs[-1][1] = j
            else:
                runs.append([i, j])
            i = j
        else:
            i += 1
    return [(a * HOP, b * HOP) for a, b in runs if (b - a) * HOP >= min_len]


def quiet(e, lo, hi):
    """Time of the quietest envelope frame in [lo, hi]."""
    i0, i1 = max(0, int(lo / HOP)), min(len(e) - 1, int(hi / HOP))
    return (i0 + int(np.argmin(e[i0:i1 + 1]))) * HOP


def onset_after(e, t, thr):
    """First time at or after t where speech starts (three frames in a row above the threshold)."""
    i = int(t / HOP)
    while i < len(e) - 3 and not (e[i] > thr and e[i + 1] > thr and e[i + 2] > thr):
        i += 1
    return i * HOP


def offset_before(e, t, thr):
    """Last time before t where speech was still going."""
    i = int(t / HOP)
    while i > 2 and not (e[i] > thr and e[i - 1] > thr):
        i -= 1
    return (i + 1) * HOP


def speech_level(e):
    """Mean level of the frames above the speech threshold (for matching a re-recorded clip)."""
    return float(np.mean(e[e > threshold(e)]))
