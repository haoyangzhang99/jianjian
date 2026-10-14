"""Local speech analysis with faster-whisper: Silero VAD + transcription with word timestamps."""
from __future__ import annotations

import os
import time
from typing import List, Optional, Tuple

from .util import log

SR = 16000

ZH_PROMPT = "以下是一段普通话播客对话，可能夹杂英文术语。请使用简体中文，并加上标点符号。"
EN_PROMPT = "The following is a podcast conversation. Use proper punctuation."
BI_PROMPT = "以下是一段中英文双语播客对话，请使用简体中文和标点。The speakers switch between Chinese and English."
# Verbatim style: an example full of fillers makes Whisper keep "uh/um/嗯" (it normally drops them).
# Used only to find fillers to cut; subtitles come from the clean transcript.
VERBATIM_PROMPTS = {
    "en": "Umm, let me think, like, hmm... Okay, so, uh, here's what I'm, you know, thinking. I I mean, uh, yeah.",
    "zh": "嗯，那个，我觉得，呃，就是说……然后，嗯，对，对。",
    "bi": "嗯，那个，呃……Umm, let me think, like, hmm... 就是说，uh, you know, 然后，嗯。",
}

MODEL_ALIASES = {
    "turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
    "large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
}


def load_audio(path: str):
    from faster_whisper import decode_audio
    t0 = time.time()
    audio = decode_audio(path, sampling_rate=SR)
    log(f"decoded audio: {len(audio) / SR:.1f}s in {time.time() - t0:.1f}s")
    return audio


def run_vad(audio, threshold: float = 0.5, min_silence_ms: int = 200,
            speech_pad_ms: int = 60, min_speech_ms: int = 120) -> List[Tuple[float, float]]:
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    t0 = time.time()
    opts = VadOptions(threshold=threshold, min_silence_duration_ms=min_silence_ms,
                      speech_pad_ms=speech_pad_ms, min_speech_duration_ms=min_speech_ms)
    ts = get_speech_timestamps(audio, opts)
    out = [(d["start"] / SR, d["end"] / SR) for d in ts]
    log(f"VAD: {len(out)} speech regions in {time.time() - t0:.1f}s")
    return out


def detect_languages(model, audio, n: int = 8) -> dict:
    """Detect the language of n 30-s windows spread over the audio; returns {lang: count}."""
    win = 30 * SR
    if len(audio) <= win:
        starts = [0]
    else:
        step = (len(audio) - win) / max(n - 1, 1)
        starts = [int(i * step) for i in range(n)]
    counts: dict = {}
    for st in starts:
        lang, prob, _ = model.detect_language(audio[st:st + win], vad_filter=True)
        counts[lang] = counts.get(lang, 0) + 1
    return counts


def pick_prompt(counts: dict) -> Tuple[str, str]:
    """Choose the style prompt from the detected language mix: (kind, prompt)."""
    total = sum(counts.values()) or 1
    zh, en = counts.get("zh", 0) / total, counts.get("en", 0) / total
    if en >= 0.75:
        return "en", EN_PROMPT
    if zh >= 0.75:
        return "zh", ZH_PROMPT
    return "bi", BI_PROMPT


def transcribe(audio, model_name: str = "large-v3-turbo", language: Optional[str] = None,
               beam_size: int = 5, threads: int = 0, progress_every: float = 60.0,
               verbatim: bool = False) -> dict:
    from faster_whisper import WhisperModel
    repo = MODEL_ALIASES.get(model_name, model_name)
    threads = threads or max(1, (os.cpu_count() or 4) - 1)
    log(f"loading Whisper model {repo} (int8, {threads} threads) ...")
    t0 = time.time()
    model = WhisperModel(repo, device="cpu", compute_type="int8", cpu_threads=threads)
    log(f"model ready in {time.time() - t0:.1f}s")

    lang = language
    # No language given: detect per 30-s window, so Chinese and English speakers in the same
    # episode are each transcribed in their own language.
    multilingual = not lang
    detected = None
    if lang:
        prompt_kind, prompt = lang, {"zh": ZH_PROMPT, "en": EN_PROMPT}.get(lang, BI_PROMPT)
    else:
        detected = detect_languages(model, audio)
        prompt_kind, prompt = pick_prompt(detected)
    if verbatim:
        prompt = VERBATIM_PROMPTS.get(prompt_kind, VERBATIM_PROMPTS["bi"])
    log(f"language: {lang or 'auto (per-segment detection)'}"
        + (f"; sampled windows {detected} -> {prompt_kind} prompt" if detected else "")
        + (" (verbatim, keeps fillers)" if verbatim else ""))
    # The style prompt goes in as hotwords: faster-whisper only applies initial_prompt to the first
    # window when condition_on_previous_text=False, and later windows then lose punctuation and
    # capitals. Hotwords are added to every window. Don't add names/terms here: tested on a real
    # episode, a name list leaked into the transcript and set off a loop repeating one title that
    # swallowed 30 s of speech. Fix names afterwards via --cues instead (see docs/DECISIONS.md).

    duration = len(audio) / SR
    t0 = time.time()
    segments, info = model.transcribe(
        audio,
        language=lang,
        multilingual=multilingual,
        task="transcribe",
        beam_size=beam_size,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        condition_on_previous_text=False,
        hotwords=prompt,
        temperature=[0.0, 0.2, 0.4, 0.6],
        compression_ratio_threshold=2.4,
        no_speech_threshold=0.6,
        hallucination_silence_threshold=2.0,
    )
    words, segs = [], []
    next_report = progress_every
    for seg in segments:
        segs.append({"s": round(seg.start, 3), "e": round(seg.end, 3), "text": seg.text,
                     "lang": getattr(seg, "language", None)})
        for w in (seg.words or []):
            words.append({"s": round(w.start, 3), "e": round(w.end, 3), "w": w.word,
                          "p": round(w.probability, 3)})
        if seg.end >= next_report:
            el = time.time() - t0
            log(f"  transcribed {seg.end / 60:.1f}/{duration / 60:.1f} min "
                f"({seg.end / max(el, 1e-6):.1f}x realtime)")
            next_report = seg.end + progress_every
    el = time.time() - t0
    log(f"transcription done: {len(segs)} segments, {len(words)} words in {el:.0f}s "
        f"({duration / max(el, 1e-6):.1f}x realtime)")
    del model
    return {"language": info.language if not lang else lang, "model": repo,
            "detected": detected, "prompt": prompt_kind, "verbatim": verbatim,
            "duration": duration, "segments": segs, "words": words}
