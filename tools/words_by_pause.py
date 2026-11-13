"""Word timings transcribed chunk by chunk between pauses, so that no take is skipped.

Whole-file Whisper can drop a retake that follows a long pause: the transcript shows one word
stretched over several seconds and the repeated sentence is simply missing. On a scripted solo talk
that hides exactly the takes the speaker wants removed. Transcribing each stretch of speech on its
own finds them.

    .venv/bin/python tools/words_by_pause.py VIDEO_OR_AUDIO -o words.json [--lang en] [--model large-v3-turbo]

Output: {"runs": [[start, end], ...], "words": [{"w", "s", "e", "p"}, ...]} in seconds of the input.
Single-word errors are more common than in a whole-file pass (each chunk has less context): use it
to find takes and to check a cut word by word, and read proper names with care.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _audio import SR, envelope, load_audio, speech_runs  # noqa: E402

from jianjian.asr import MODEL_ALIASES  # noqa: E402


def chunks(runs, max_len=20.0, max_gap=0.6):
    """Join speech runs into chunks of at most `max_len` seconds, never across a gap of `max_gap`."""
    out = []
    for a, b in runs:
        if out and b - out[-1][0] <= max_len and a - out[-1][1] < max_gap:
            out[-1][1] = b
        else:
            out.append([a, b])
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("media")
    p.add_argument("-o", "--out", required=True)
    p.add_argument("--lang", default=None, help="spoken language, e.g. en or zh (default: detect per chunk)")
    p.add_argument("--model", default="large-v3-turbo")
    a = p.parse_args()
    from faster_whisper import WhisperModel
    audio = load_audio(a.media)
    runs = speech_runs(envelope(audio))
    model = WhisperModel(MODEL_ALIASES.get(a.model, a.model), device="cpu", compute_type="int8")
    words = []
    for c0, c1 in chunks(runs):
        s0, e0 = max(0.0, c0 - 0.25), min(len(audio) / SR, c1 + 0.25)
        segs, _ = model.transcribe(audio[int(s0 * SR):int(e0 * SR)], language=a.lang, word_timestamps=True, vad_filter=False,
                                   condition_on_previous_text=False, beam_size=5, temperature=0.0)
        for sg in segs:
            for x in sg.words:
                words.append({"w": x.word.strip(), "s": round(s0 + x.start, 3), "e": round(s0 + x.end, 3), "p": round(x.probability, 3)})
    json.dump({"runs": [[round(x, 2), round(y, 2)] for x, y in runs], "words": words}, open(a.out, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"{len(runs)} stretches of speech, {len(words)} words -> {a.out}")


if __name__ == "__main__":
    main()
