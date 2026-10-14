"""Smoke test WITHOUT ML models: uses ffmpeg silencedetect as a stand-in for VAD and placeholder
subtitle text, then runs the real draft/render/validation stages. Used to test the Jianying and
FFmpeg parts on machines where Whisper isn't installed.

    python3 tools/vm_smoke.py VIDEO --out DIR [jianjian edit options...]
"""
import json
import os
import re
import subprocess
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

try:
    import faster_whisper  # noqa: F401
except ImportError:
    import numpy as np
    fw = types.ModuleType("faster_whisper")

    def decode_audio(path, sampling_rate=16000):
        out = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(sampling_rate),
                              "-f", "f32le", "-"], capture_output=True, check=True).stdout
        return np.frombuffer(out, dtype=np.float32).copy()
    fw.decode_audio = decode_audio
    sys.modules["faster_whisper"] = fw


def silence_vad(path, duration, noise="-35dB", d=0.25):
    err = subprocess.run(["ffmpeg", "-hide_banner", "-i", path, "-vn", "-af", f"silencedetect=n={noise}:d={d}",
                          "-f", "null", "-"], capture_output=True, text=True).stderr
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", err)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", err)]
    sil = list(zip(starts, ends + [duration] * (len(starts) - len(ends))))
    speech, pos = [], 0.0
    for a, b in sil:
        if a > pos:
            speech.append((pos, a))
        pos = b
    if pos < duration:
        speech.append((pos, duration))
    return speech


def main():
    from jianjian.cli import main as jianjian_main
    from jianjian.media import probe
    video = os.path.abspath(sys.argv[1])
    rest = sys.argv[2:]
    out = os.path.abspath(rest[rest.index("--out") + 1])
    work = os.path.join(out, "work")
    os.makedirs(work, exist_ok=True)
    info = probe(video)
    speech = silence_vad(video, info.duration)
    json.dump(speech, open(os.path.join(work, "vad.json"), "w"))
    words = []
    for i, (a, b) in enumerate(speech):
        words.append({"s": round(a, 3), "e": round(min(b, a + 4.0), 3), "w": f"测试字幕第{i + 1}段", "p": 1.0})
    json.dump({"language": "zh", "model": "silencedetect-placeholder", "duration": info.duration, "segments": [],
               "words": words, "model_arg": "large-v3-turbo", "lang_arg": "auto"},
              open(os.path.join(work, "transcript.json"), "w"), ensure_ascii=False)
    # pass 1: build cues; pass 2: add placeholder English and produce draft/render
    jianjian_main(["edit", video, "--preset", "podcast", "--translator", "none", "--no-draft", "--no-render"] + rest)
    cues = json.load(open(os.path.join(out, "cues.json")))
    tr = {str(c["id"]): f"Test subtitle {c['id']} — English line" for c in cues}
    json.dump(tr, open(os.path.join(work, "placeholder_translations.json"), "w"))
    return jianjian_main(["edit", video, "--preset", "podcast", "--translator", "none",
                       "--translations", os.path.join(work, "placeholder_translations.json")] + rest)


if __name__ == "__main__":
    sys.exit(main())
