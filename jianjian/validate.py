"""Automatic checks on the generated draft and the rendered MP4."""
from __future__ import annotations

import os
from typing import List, Sequence

import numpy as np

from .cuts import KeepRange
from .draft import summarize_draft
from .media import probe

SR = 16000


def check_draft(draft_dir: str, keeps: Sequence[KeepRange], fps: int, media_path: str,
                local_media: str = "", speed: float = 1.0, insert_paths: Sequence[str] = (),
                animations: Sequence[str] = ()) -> dict:
    """insert_paths: the converted clips (--insert) the draft may also use, as Jianying sees them.
    animations: the paths of the animation clips the draft should use, in timeline order."""
    s = summarize_draft(draft_dir)
    problems: List[str] = []
    expected_us = int(round(round(keeps[-1].tl_end * fps) * 1_000_000 / fps / speed)) if keeps else 0
    if abs((s["duration_us"] or 0) - expected_us) > 1_000_000 / fps:
        problems.append(f"draft duration {s['duration_us']} != expected {expected_us}")
    vtracks = [t for t in s["tracks"] if t["type"] == "video" and t["name"] != "animations"]
    if len(vtracks) != 1:
        problems.append(f"expected 1 video track, found {len(vtracks)}")
    else:
        spans = vtracks[0]["spans"]
        if len(spans) != len(keeps):
            problems.append(f"{len(spans)} video segments != {len(keeps)} keep ranges")
        pos = 0
        for i, (st, du, ss, sd, _mid) in enumerate(spans):
            if st != pos:
                problems.append(f"video segment {i} starts at {st}, expected {pos} (gap/overlap)")
                break
            if abs(sd - du * speed) > 2 * speed + 1000:
                problems.append(f"video segment {i} speed {sd / max(du, 1):.4f} != {speed}")
                break
            if i < len(keeps) and abs(ss / 1e6 - keeps[i].src_start) > 1.0 / fps:
                problems.append(f"video segment {i} source start {ss / 1e6:.3f}s != {keeps[i].src_start:.3f}s")
                break
            pos = st + du
    atrack = [t for t in s["tracks"] if t["type"] == "video" and t["name"] == "animations"]
    if len(atrack) != (1 if animations else 0) or (atrack and atrack[0]["segments"] != len(animations)):
        problems.append(f"expected {len(animations)} animations on an animations track, found "
                        f"{atrack[0]['segments'] if atrack else 0}")
    for t in s["tracks"]:
        if t["type"] == "text" or t["name"] == "animations":
            prev_end = -1
            for st, du, *_ in t["spans"]:
                if st < prev_end:
                    problems.append(f"text track {t['name']}: overlapping segments")
                    break
                if st + du > (s["duration_us"] or 0) + 1000:
                    problems.append(f"text track {t['name']}: segment beyond end of timeline")
                    break
                prev_end = st + du
    for m in s["video_materials"]:
        if m["path"] in animations:
            if not os.path.exists(m["path"]):
                problems.append(f"animation file missing: {m['path']}")
            continue
        if m["path"] != media_path and m["path"] not in insert_paths:
            problems.append(f"material path {m['path']} is not the recording or an inserted clip")
        local = (local_media or m["path"]) if m["path"] == media_path else m["path"]
        if not os.path.exists(local):
            problems.append(f"material file missing: {local}")
    return {
        "ok": not problems,
        "problems": problems,
        "tracks": [{"type": t["type"], "name": t["name"], "segments": t["segments"]} for t in s["tracks"]],
        "duration_s": round((s["duration_us"] or 0) / 1e6, 3),
    }


def _expected_audio(src_audio: np.ndarray, keeps: Sequence[KeepRange],
                    insert_audio: Sequence[np.ndarray] = ()) -> np.ndarray:
    # One frame is 16000/fps samples (533.33 at 30 fps), so each part's length comes from the
    # rounded timeline positions; rounding every part on its own drifts by a few samples per cut.
    audios = [src_audio] + list(insert_audio)
    parts = []
    for k in keeps:
        a = int(round(k.src_start * SR))
        n = int(round(k.tl_end * SR)) - int(round(k.tl_start * SR))
        part = audios[k.media][a:a + n]
        if len(part) < n:  # a clip's audio a few ms short: the render pads it with silence
            part = np.concatenate([part, np.zeros(n - len(part), dtype=np.float32)])
        parts.append(part)
    return np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)


def _best_lag(a: np.ndarray, b: np.ndarray, max_lag: int):
    """Lag (samples) that best aligns b to a, and the normalized correlation at that lag."""
    a = a - a.mean()
    coarse = _scan(a, b, range(-max_lag, max_lag + 1, 16))
    # refine to the exact sample: a few samples off already lowers the correlation a lot
    return _scan(a, b, range(coarse[0] - 16, coarse[0] + 17))


def _scan(a: np.ndarray, b: np.ndarray, lags):
    best = (0, -1.0)
    for lag in lags:
        if lag >= 0:
            x, y = a[lag:], b[:len(b) - lag] if lag else b
        else:
            x, y = a[:lag], b[-lag:]
        n = min(len(x), len(y))
        if n < SR:
            continue
        x, y = x[:n], y[:n] - y[:n].mean()
        den = float(np.linalg.norm(x) * np.linalg.norm(y)) or 1.0
        c = float(np.dot(x, y) / den)
        if c > best[1]:
            best = (lag, c)
    return best


def _tempo(audio: np.ndarray, speed: float, ffmpeg: str) -> np.ndarray:
    """The expected audio sped up with the same atempo filter the render uses."""
    import subprocess
    proc = subprocess.run([ffmpeg, "-v", "error", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "pipe:0",
                           "-af", f"atempo={speed}", "-f", "f32le", "-ar", str(SR), "-ac", "1", "pipe:1"],
                          input=audio.astype(np.float32).tobytes(), capture_output=True, check=True)
    return np.frombuffer(proc.stdout, dtype=np.float32)


def _envelope_lag(ref: np.ndarray, out: np.ndarray, i: int, win: int, max_lag: int, hop: int = 160):
    """Lag (samples, 10-ms steps) and correlation of the log-energy envelopes around sample i."""
    def env(x):
        n = len(x) // hop
        return np.log10((x[:n * hop].reshape(n, hop) ** 2).mean(1) + 1e-8)
    a = env(ref[i:i + win])
    best = (0, -1.0)
    for lag in range(-max_lag // hop, max_lag // hop + 1):
        j = i + lag * hop
        if j < 0:
            continue
        b = env(out[j:j + win])
        if len(b) < len(a) or a.std() == 0 or b.std() == 0:
            continue
        c = float(np.corrcoef(a, b[:len(a)])[0, 1])
        if c > best[1]:
            best = (lag * hop, c)
    return best


def check_render(out_path: str, src_audio: np.ndarray, keeps: Sequence[KeepRange], fps: int,
                 probe_times: Sequence[float], speed: float = 1.0, ffmpeg: str = "",
                 insert_audio: Sequence[np.ndarray] = ()) -> dict:
    """insert_audio: 16-kHz mono audio of the converted clips that keep ranges with media 1, 2, ... play."""
    from faster_whisper import decode_audio
    problems: List[str] = []
    info = probe(out_path)
    expected = (keeps[-1].tl_end if keeps else 0.0) / speed
    if abs(info.duration - expected) > 0.15:
        problems.append(f"output duration {info.duration:.3f}s != expected {expected:.3f}s")
    out_audio = decode_audio(out_path, sampling_rate=SR)
    exp_audio = _expected_audio(src_audio, keeps, insert_audio)
    if speed != 1.0:
        exp_audio = _tempo(exp_audio, speed, ffmpeg)
    audio_len_diff = len(out_audio) / SR - len(exp_audio) / SR
    if abs(audio_len_diff) > 0.1:
        problems.append(f"audio length differs from expected by {audio_len_diff:+.3f}s")
    probes = []
    win = 4 * SR
    for t in probe_times:
        i = int(t * SR)
        a = exp_audio[i:i + win]
        b = out_audio[i:i + win]
        if len(a) < win or len(b) < win or float(np.abs(a).max()) < 1e-3:
            continue
        if speed == 1.0:
            lag, corr = _best_lag(a, b, max_lag=int(0.25 * SR))
            min_corr = 0.6
        else:
            # time-stretched audio: atempo picks its overlap chunks differently at 48 kHz (render) and
            # 16 kHz (reference), so compare loudness envelopes, not waveforms
            lag, corr = _envelope_lag(exp_audio, out_audio, i, win, max_lag=int(0.25 * SR))
            min_corr = 0.8
        probes.append({"t": round(t, 2), "offset_ms": round(1000 * lag / SR, 1), "corr": round(corr, 3)})
        if abs(lag) > 0.045 * SR:
            problems.append(f"audio offset {1000 * lag / SR:+.0f} ms at {t:.1f}s")
        if corr < min_corr:
            problems.append(f"low audio match ({corr:.2f}) at {t:.1f}s")
    return {
        "ok": not problems,
        "problems": problems,
        "duration_s": round(info.duration, 3),
        "expected_s": round(expected, 3),
        "width": info.width, "height": info.height, "fps": round(info.fps, 3),
        "sync_probes": probes,
    }
