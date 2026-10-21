"""Render the same edit straight from the source with FFmpeg (no Jianying needed).

Sync strategy: video is resampled to a constant `fps` and cut with `select`; the audio is cut in
Python (build_audio) at 48 kHz, where one video frame is exactly 48000/fps samples. Every
keep-range boundary lies on that shared grid, so both streams drop exactly the same spans and the
result cannot drift, no matter how many cuts a 60-minute episode has. Each cut gets a few-ms
fade so cuts inside speech (removed filler words) don't click.
"""
from __future__ import annotations

import os
import subprocess
import time
from typing import Optional, Sequence

from .cuts import KeepRange, source_runs
from .media import MediaInfo
from .util import log

AUDIO_SR = 48000


def _select_expr(keeps: Sequence[KeepRange], fps: int) -> str:
    half = 0.5 / fps
    terms = [f"between(t+{half:.6f},{k.src_start:.6f},{k.src_end:.6f})" for k in keeps]
    return "+".join(terms) if terms else "0"


def build_audio(src: str, keeps: Sequence[KeepRange], out_wav: str, audio_start: float = 0.0,
                fade_ms: float = 6.0) -> float:
    """Write the edited audio (keep ranges joined, short fade at every join) as 16-bit WAV.
    Streams the source, so memory stays small even for a 2-hour episode. Keep ranges may jump back
    in the source (a cold open): each source-ordered run is streamed on its own. Returns seconds."""
    import wave

    import av

    sr = AUDIO_SR
    runs = source_runs(keeps)
    with av.open(src) as c:
        ch = min(c.streams.audio[0].codec_context.channels or 1, 2)
    total, gi = 0, 0
    with wave.open(out_wav, "wb") as wf:
        wf.setnchannels(ch)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        for run in runs:
            ranges = [(int(round(k.src_start * sr)), int(round(k.src_end * sr))) for k in run]
            # no fade-in only at the very start of the source; no fade-out only at the very end
            fade_in = [gi + j > 0 or a > 0 for j, (a, _b) in enumerate(ranges)]
            fade_out = [gi + j < len(keeps) - 1 for j in range(len(ranges))]
            total += _write_run(src, ranges, fade_in, fade_out, wf, ch, audio_start, fade_ms)
            gi += len(run)
    return total / sr


def _write_run(src, ranges, fade_in, fade_out, wf, ch, audio_start, fade_ms) -> int:
    """Append one source-ordered run of ranges (48-kHz sample indices) to wf; returns samples."""
    import av
    import numpy as np

    sr = AUDIO_SR
    total = sum(b - a for a, b in ranges)
    fade = max(1, int(sr * fade_ms / 1000))
    with av.open(src) as c:
        st = c.streams.audio[0]
        res = av.AudioResampler(format="flt", layout="stereo" if ch == 2 else "mono", rate=sr)
        pos = int(round(max(audio_start, 0.0) * sr))  # source sample index of the next sample
        ri, written = 0, 0

        def emit(buf: "np.ndarray", start: int):
            nonlocal ri, written
            end = start + len(buf)
            while ri < len(ranges) and ranges[ri][1] <= start:
                ri += 1
            k = ri
            while k < len(ranges) and ranges[k][0] < end:
                a, b = ranges[k]
                x0, x1 = max(a, start), min(b, end)
                seg = buf[x0 - start:x1 - start].copy()
                idx = np.arange(x0, x1)
                gain = np.ones(len(idx), dtype=np.float32)
                if fade_in[k]:
                    gain = np.minimum(gain, (idx - a + 0.5) / fade)
                if fade_out[k]:
                    gain = np.minimum(gain, (b - idx - 0.5) / fade)
                seg *= np.clip(gain, 0.0, 1.0)[:, None]
                wf.writeframes((np.clip(seg, -1.0, 1.0) * 32767).astype("<i2").tobytes())
                written += len(seg)
                k += 1

        if pos > 0:  # audio stream starts after the video: that stretch is silence
            emit(np.zeros((pos, ch), dtype=np.float32), 0)
        last = ranges[-1][1]
        for packet in c.demux(st):
            for frame in packet.decode():
                for out in res.resample(frame):
                    arr = out.to_ndarray().reshape(-1, ch)
                    emit(arr, pos)
                    pos += len(arr)
            if pos >= last:  # the rest of the source isn't in this run
                break
        else:
            for out in res.resample(None):
                arr = out.to_ndarray().reshape(-1, ch)
                emit(arr, pos)
                pos += len(arr)
    if written < total:  # source audio ended early: pad so A/V lengths match exactly
        wf.writeframes(b"\x00" * 2 * ch * (total - written))
    return total


def render(src: str, out_path: str, keeps: Sequence[KeepRange], info: MediaInfo, caps: dict,
           fps: int = 30, ass_path: Optional[str] = None, srt_tracks: Sequence[tuple] = (),
           video_bitrate: str = "8M", crf: int = 20, encoder: str = "auto",
           duration_limit: Optional[float] = None, speed: float = 1.0) -> dict:
    if AUDIO_SR % fps:
        raise ValueError(f"fps {fps} must divide {AUDIO_SR} (use 24, 25, 30, 48, 50 or 60)")
    work = os.path.dirname(os.path.abspath(out_path))
    # One input per source-ordered run: a cold open (--hook) jumps back in the source, which a
    # single select can't do. Later runs are opened with a fast seek near their start (PTS put
    # back so the frame grid and select times stay in source time) and joined with concat.
    runs = source_runs(keeps)
    inputs, chains = [], []
    for i, run in enumerate(runs):
        seek = max(0.0, run[0].src_start - 2.0) if len(runs) > 1 else 0.0
        inputs += (["-ss", f"{seek:.3f}"] if seek > 0 else []) + ["-i", src]
        restore = f"setpts=PTS+{seek:.3f}/TB," if seek > 0 else ""
        chains.append(f"[{i}:v]{restore}fps={fps},select='{_select_expr(run, fps)}',setpts=N/({fps}*TB)")
    if len(runs) == 1:
        vchain = chains[0]
    else:
        vchain = "".join(f"{c}[r{i}];\n" for i, c in enumerate(chains))
        vchain += "".join(f"[r{i}]" for i in range(len(runs)))
        vchain += f"concat=n={len(runs)}:v=1:a=0,setpts=N/({fps}*TB)"
    wav_in = len(runs)
    if speed != 1.0:  # speed the whole edit up uniformly (subtitle times are already scaled)
        vchain += f",setpts=PTS/{speed},fps={fps}"
    burn = bool(ass_path) and caps.get("libass")
    if burn:
        vchain += f",subtitles=filename='{os.path.basename(ass_path)}'"
    vchain += ",format=yuv420p[v]"
    script = os.path.join(work, "_render_filter.txt")
    with open(script, "w", encoding="utf-8") as f:
        f.write(vchain + (f";\n[{wav_in}:a]atempo={speed}[a]" if speed != 1.0 else ""))
    wav = os.path.join(work, "_render_audio.wav")
    t0 = time.time()
    build_audio(src, keeps, wav, audio_start=info.audio_start)
    log(f"audio built in {time.time() - t0:.0f}s (fades at {len(keeps) - 1} cuts"
        f"{f', {len(runs)} source runs' if len(runs) > 1 else ''})")

    if encoder == "auto":
        encoder = "h264_videotoolbox" if caps.get("videotoolbox") else ("libx264" if caps.get("libx264") else "mpeg4")
    venc = ["-c:v", encoder]
    if encoder == "h264_videotoolbox":
        venc += ["-b:v", video_bitrate, "-maxrate", video_bitrate, "-bufsize", "16M", "-profile:v", "high"]
    elif encoder == "libx264":
        venc += ["-crf", str(crf), "-preset", "veryfast", "-profile:v", "high"]
    else:
        venc += ["-q:v", "3"]

    fc_flag = ["-/filter_complex", script] if caps.get("major", 0) >= 7 else ["-filter_complex_script", script]
    cmd = [caps["path"], "-hide_banner", "-loglevel", "error", "-stats", "-y"] + inputs + ["-i", wav]
    for p, _lang in srt_tracks:
        cmd += ["-i", p]
    cmd += fc_flag + ["-map", "[v]", "-map", "[a]" if speed != 1.0 else f"{wav_in}:a"]
    for i, (_p, lang) in enumerate(srt_tracks):
        cmd += ["-map", f"{wav_in + 1 + i}:0", f"-metadata:s:s:{i}", f"language={'chi' if lang == 'zh' else 'eng'}"]
    cmd += venc + ["-r", str(fps), "-c:a", "aac", "-b:a", "192k", "-ar", str(AUDIO_SR)]
    if srt_tracks:
        cmd += ["-c:s", "mov_text"]
    if duration_limit:
        cmd += ["-t", f"{duration_limit:.3f}"]
    cmd += ["-movflags", "+faststart", out_path]

    log(f"rendering with {encoder}{' + burned-in subtitles' if burn else ''} ...")
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=work, capture_output=True, text=True)
    try:
        os.remove(wav)
    except OSError:
        pass
    if proc.returncode != 0:
        tail = (proc.stderr or "")[-3000:]
        raise RuntimeError(f"ffmpeg failed ({proc.returncode}):\n{tail}")
    el = time.time() - t0
    log(f"render done in {el:.0f}s -> {out_path}")
    return {"encoder": encoder, "burned_subtitles": burn, "seconds": round(el, 1), "fps": fps,
            "cmd": " ".join(cmd)}
