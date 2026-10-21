"""Filler words: find candidates in a verbatim transcript, review them, turn them into cuts.

Three kinds of candidate, each covering a run of words (indices into the verbatim transcript):
  hesitation  uh / um / 嗯 / 呃 ...                      cut automatically
  repeat      "have you, have you", "the, the"           cut automatically (the first copy)
  discourse   like / so / you know / I mean / 那个 ...    NOT cut until a reviewer says so
"Like" can be a verb or mean "such as"; "so" can mean "therefore". Only context tells, so those are
written to fillers.json with cut=false, and a reviewer (person or agent) flips the ones to cut and
may add restarts (false starts) by word range. Rerun with --fillers reviewed.json to apply.
"""
from __future__ import annotations

import bisect
import math
import re
from typing import Dict, List, Sequence, Tuple

HESITATIONS = {"uh", "um", "umm", "uhm", "uhh", "er", "erm", "ah", "hmm", "hm", "mm", "mmm", "eh",
               "嗯", "呃", "额", "唔"}
# exact one-word repeats of these are stutters ("I, I think", "the, the movie")
FUNCTION_WORDS = {"i", "the", "a", "an", "to", "and", "of", "it", "that", "in", "is", "we", "you",
                  "they", "he", "she", "my", "this", "but", "for", "on", "with", "be", "was", "are",
                  "我", "你", "他", "这", "那", "就", "是", "的"}
# repeated for emphasis, not stutters
INTENSIFIERS = {"very", "really", "so", "yeah", "yes", "no", "ok", "okay", "right", "bye", "ha",
                "first", "more", "much", "too", "对", "好", "很", "非常"}
DISCOURSE = [("you", "know"), ("i", "mean"), ("kind", "of"), ("sort", "of"), ("like",), ("so",),
             ("basically",), ("actually",), ("literally",), ("well",),
             ("那个",), ("就是",), ("然后",), ("就是说",)]


def norm(w: str) -> str:
    return re.sub(r"[^\w']", "", w.lower()).strip("'")


def _ends_sentence(w: dict) -> bool:
    t = w["w"].strip()
    return t.endswith((".", "?", "!", "。", "？", "！")) and not t.endswith("..")


def detect(words: Sequence[dict]) -> List[dict]:
    toks = [norm(w["w"]) for w in words]
    n = len(toks)
    taken = [False] * n
    cands: List[dict] = []

    def add(i, j, kind, cut):
        for k in range(i, j + 1):
            taken[k] = True
        cands.append({"words": [i, j], "kind": kind, "cut": cut})

    for i, t in enumerate(toks):
        if t in HESITATIONS:
            add(i, i, "hesitation", True)
    for size in (3, 2, 1):
        for i in range(n - 2 * size + 1):
            a, b = toks[i:i + size], toks[i + size:i + 2 * size]
            if a != b or not all(a) or any(taken[i:i + 2 * size]):
                continue
            if size == 1 and (a[0] in INTENSIFIERS or a[0] not in FUNCTION_WORDS):
                continue
            if words[i + size]["s"] - words[i + size - 1]["e"] > 1.0:
                continue  # a long pause between the copies: probably deliberate
            if _ends_sentence(words[i + size - 1]):
                continue  # "what do you call this? This is art", "it's for. For real": two sentences
            add(i, i + size - 1, "repeat", True)
    # stutters with a hesitation between the copies ("they, uh, they", "the, um, the"): compare the
    # words with uh/um left out; the uh between them is already a hesitation candidate
    idx = [k for k in range(n) if toks[k] and toks[k] not in HESITATIONS]
    ft = [toks[k] for k in idx]
    for size in (3, 2, 1):
        for p in range(len(ft) - 2 * size + 1):
            first, second = idx[p:p + size], idx[p + size:p + 2 * size]
            if ft[p:p + size] != ft[p + size:p + 2 * size] or second[0] == first[-1] + 1:
                continue  # different words, or adjacent copies (handled above)
            if any(taken[k] for k in first + second):
                continue
            if size == 1 and (ft[p] in INTENSIFIERS or ft[p] not in FUNCTION_WORDS):
                continue
            if words[second[0]]["s"] - words[first[-1]]["e"] > 1.5:
                continue
            if _ends_sentence(words[first[-1]]):
                continue
            add(first[0], first[-1], "repeat", True)
    # word restarts: a word cut short and said again in full ("re-, re-, uh, remember"); a judgement
    # call ("the, there" can be two words), so suggested for review
    for p in range(len(ft) - 1):
        a, q = ft[p], p + 1
        while q < len(ft) and ft[q] == a:
            q += 1
        if q < len(ft) and len(a) >= 3 and len(ft[q]) >= len(a) + 2 and ft[q].startswith(a) \
                and not any(taken[k] for k in idx[p:q]) and words[idx[q]]["s"] - words[idx[q - 1]]["e"] <= 1.5:
            add(idx[p], idx[q - 1], "restart", False)
    for i in range(n):
        for pat in DISCOURSE:
            j = i + len(pat) - 1
            if j < n and tuple(toks[i:j + 1]) == pat and not any(taken[i:j + 1]):
                add(i, j, "discourse", False)
                break
    cands.sort(key=lambda c: c["words"][0])
    for k, c in enumerate(cands):
        c["id"] = k + 1
    return cands


def describe(cands: Sequence[dict], words: Sequence[dict], ctx: int = 6) -> List[dict]:
    """Add text, times and a context line ('... you'll [like] notice ...') to each candidate."""
    out = []
    for c in cands:
        i, j = c["words"]
        left = "".join(w["w"] for w in words[max(0, i - ctx):i]).strip()
        mid = "".join(w["w"] for w in words[i:j + 1]).strip()
        right = "".join(w["w"] for w in words[j + 1:j + 1 + ctx]).strip()
        out.append({**c, "text": mid, "start": round(words[i]["s"], 3), "end": round(words[j]["e"], 3),
                    "context": f"{left} [{mid}] {right}"})
    return out


def load_review(data: Sequence[dict], words: Sequence[dict]) -> List[dict]:
    """Reviewed candidates: keep entries whose word range is valid for this transcript."""
    out = []
    for c in data:
        i, j = int(c["words"][0]), int(c["words"][1])
        if 0 <= i <= j < len(words):
            item = {"id": c.get("id", len(out) + 1), "words": [i, j],
                    "kind": c.get("kind", "restart"), "cut": bool(c.get("cut"))}
            if c.get("reason"):
                item["reason"] = c["reason"]
            out.append(item)
    return out


SR = 16000
HOP = 160  # 10-ms energy frames


def _db(audio, t0: float, t1: float):
    import numpy as np
    seg = audio[max(0, int(t0 * SR)):max(0, int(t1 * SR))]
    n = len(seg) // HOP
    if n == 0:
        return np.zeros(0)
    fr = seg[:n * HOP].reshape(n, HOP)
    return 20 * np.log10(np.sqrt((fr ** 2).mean(1)) + 1e-6)


def locate_hesitation(audio, lo: float, hi: float, guess: Tuple[float, float]) -> Tuple[float, float]:
    """Where the "uh" really is. Whisper reliably puts a hesitation in the right gap between two
    words, but its timestamps for it are often off by 0.1-0.5 s (sometimes a 40-ms "uh"). Within
    [lo, hi] (end of the previous word .. start of the next) find the voiced burst nearest Whisper's
    guess and return all of it, so no "mm" tail is left behind. Falls back to the guess."""
    import numpy as np
    if hi - lo < 0.08:
        return guess
    ctx = _db(audio, lo - 1.0, hi + 1.0)
    if len(ctx) < 20:
        return guess
    floor, peak = np.percentile(ctx, 15), np.percentile(ctx, 95)
    thr = max(floor + 6.0, floor + 0.3 * (peak - floor))
    e = _db(audio, lo, hi)
    on = e > thr
    # bridge dips shorter than 50 ms; collect bursts of at least 80 ms
    runs, k = [], 0
    while k < len(on):
        if on[k]:
            s = k
            while k < len(on) and (on[k] or (k + 5 < len(on) and on[k:k + 5].any())):
                k += 1
            if k - s >= 8:
                runs.append((lo + s * HOP / SR, lo + k * HOP / SR))
        k += 1
    if not runs:
        return guess
    g0, g1 = guess
    gm = (g0 + g1) / 2

    def score(r):
        overlap = max(0.0, min(r[1], g1 + 0.3) - max(r[0], g0 - 0.3))
        return (-overlap, abs((r[0] + r[1]) / 2 - gm))

    a, b = min(runs, key=score)
    return max(lo, a - 0.03), min(hi, b + 0.05)  # a little air: onsets and decays are quiet


def spans(cands: Sequence[dict], words: Sequence[dict], fps: int, min_len: float = 0.06,
          audio=None) -> List[Tuple[float, float]]:
    """Source-time spans to remove for the candidates marked cut. Each span is clamped so it never
    reaches into the neighbouring words, then snapped inward to the frame grid. With the 16-kHz
    audio, hesitations are re-located on the waveform (see locate_hesitation).
    Content cuts that touch (no kept word between them, e.g. a passage and the restart next to it)
    are joined into one span: speech the transcript skipped between them was left in otherwise."""
    out = []
    joined: List[dict] = []
    for c in sorted((c for c in cands if c["cut"]), key=lambda c: c["words"][0]):
        p = joined[-1] if joined else None
        if p and c["words"][0] <= p["words"][1] + 1 and "content" in (p["kind"], c["kind"]):
            joined[-1] = {**p, "words": [p["words"][0], max(p["words"][1], c["words"][1])], "kind": "content"}
        else:
            joined.append(c)
    for c in joined:
        i, j = c["words"]
        a, b = words[i]["s"], words[j]["e"]
        lo = words[i - 1]["e"] if i > 0 else max(0.0, a - 1.0)
        hi = words[j + 1]["s"] if j + 1 < len(words) else b + 1.0
        if audio is not None and c["kind"] == "hesitation" and i == j:
            a, b = locate_hesitation(audio, lo, hi, (a, b))
        a, b = max(a, lo), min(b, hi)
        a = math.ceil(a * fps - 1e-6) / fps
        b = math.floor(b * fps + 1e-6) / fps
        if b - a >= min_len:
            out.append((a, b))
    return out


_END_PUNCT = ".?!…。？！"
_CONJ = ("and", "but", "so", "or", "then", "because", "cause")
# Chinese renderings of discourse fillers: a reviewed translation that still has one of these after
# its English filler was cut is flagged for review (translations made after the strip never see it)
ZH_FILLER_HINTS = ("你知道", "就像", "我是说", "有点")


def _strip_phrase(text: str, phrase: List[str], repeat: bool, frac: float) -> str:
    """Remove one occurrence of the word sequence `phrase` from subtitle text. For a repeat, remove
    the first copy of the doubled sequence. `frac` (0..1) picks the occurrence nearest that point."""
    toks = text.split()
    keys = [norm(t) for t in toks]
    n = len(phrase)
    hits = [i for i in range(len(toks) - n + 1) if keys[i:i + n] == phrase
            and (not repeat or keys[i + n:i + 2 * n] == phrase)]
    if not hits:
        return text
    i = min(hits, key=lambda k: abs(k / max(len(toks) - 1, 1) - frac))
    removed, rest = toks[i:i + n], toks[:i] + toks[i + n:]
    end = removed[-1][-1:] if removed[-1][-1:] in _END_PUNCT else ""
    if end == "?" and not repeat:
        end = "."  # a cut tag question ("it's late, you know?") leaves a statement
    if end and i > 0:  # "that, you know." -> "that."
        rest[i - 1] = rest[i - 1].rstrip(",;:") + ("" if rest[i - 1][-1:] in _END_PUNCT else end)
    elif i > 0 and removed[-1].endswith(",") and rest[i - 1].endswith(","):
        rest[i - 1] = rest[i - 1][:-1]  # "And, you know, they're" -> "And they're"
    if i < len(rest) and removed[0][:1].isupper():  # "You know, they're" -> "They're"
        rest[i] = rest[i][:1].upper() + rest[i][1:]
    if i == 0 and rest and rest[0][:1] == ",":
        rest[0] = rest[0][1:]
    out = " ".join(rest).strip()
    if out.startswith(","):
        out = out[1:].strip()
    return out


_PURE_FILLERS = {"uh", "um", "umm", "uhm", "uhh", "er", "erm"}  # never meant: unlike "hmm" or "ah"


def tidy_subtitle(text: str) -> str:
    """Subtitle hygiene: no uh/um, no doubled small words ("the the"), no dangling comma."""
    toks = text.split()
    kept: List[str] = []
    for t in toks:
        if norm(t) in HESITATIONS:
            if kept and t[-1:] in _END_PUNCT and kept[-1][-1:] not in _END_PUNCT:
                kept[-1] = kept[-1].rstrip(",;:") + t[-1]  # "about it, uh. I" -> "about it. I"
            elif kept and kept[-1].endswith(",") and (t.endswith(",") or norm(kept[-1]) in _CONJ):
                kept[-1] = kept[-1][:-1]  # "It was, uh, one" -> "It was one"
            continue
        kept.append(t)
    if not kept and all(norm(t) in _PURE_FILLERS for t in toks):
        return ""  # a line that is only "Uh" or "Um, um" goes (the caller drops empty lines)
    kept = kept or toks  # never empty a "Hmm." line
    out: List[str] = []
    for t in kept:
        if out and norm(t) == norm(out[-1]) and norm(t) in FUNCTION_WORDS and out[-1][-1:] not in _END_PUNCT:
            out[-1] = t if out[-1][-1:] in ",;:" else out[-1]  # keep the second copy's punctuation
            continue
        out.append(t)
    text = " ".join(out).strip()
    text = re.sub(r"\s+([,.?!…])", r"\1", text).rstrip(",;: ")
    return text[:1].upper() + text[1:] if toks and toks[0][:1].isupper() else text


def _count(toks: Sequence[str], phrase: List[str]) -> int:
    """Non-overlapping occurrences of the word sequence `phrase` in toks (compared with norm())."""
    phrase = [p for p in phrase if p not in HESITATIONS]
    keys = [k for k in (norm(t) for t in toks) if k and k not in HESITATIONS]
    if not phrase:
        return 0
    n, i, hits = len(phrase), 0, 0
    while i + n <= len(keys):
        if keys[i:i + n] == phrase:
            hits, i = hits + 1, i + n
        else:
            i += 1
    return hits


def _kept_count(q, phrase: List[str], words: Sequence[dict], gone: set, mids: List[float]) -> int:
    """How often `phrase` is still spoken (no word of it cut) while subtitle q is on screen.
    mids: the words' midpoints (sorted), for a quick lookup."""
    phrase = [p for p in phrase if p not in HESITATIONS]
    lo, hi = bisect.bisect_left(mids, q.start - 0.1), bisect.bisect_right(mids, q.end + 0.1)
    idx = [i for i in range(lo, hi) if norm(words[i]["w"]) and norm(words[i]["w"]) not in HESITATIONS]
    keys = [norm(words[i]["w"]) for i in idx]
    if not phrase:
        return 0
    n, k, hits = len(phrase), 0, 0
    while k + n <= len(keys):
        if keys[k:k + n] == phrase and not any(idx[j] in gone for j in range(k, k + n)):
            hits, k = hits + 1, k + n
        else:
            k += 1
    return hits


def strip_from_cues(cues, cands: Sequence[dict], words: Sequence[dict]) -> Tuple[List[int], List[int]]:
    """Remove cut words (repeats, discourse words, restarts) from the subtitle text so the subtitles
    match the edited audio, then tidy every English line (tidy_subtitle). Longest cuts go first, so a
    restart is removed before the "like" inside it.
    Returns (ids of changed cues, ids whose existing translation may still contain a cut filler)."""
    changed, flag = [], []
    gone = cut_word_indices(cands)
    mids = [(w["s"] + w["e"]) / 2 for w in words]
    ordered = sorted(describe(cands, words), key=lambda c: c["words"][0] - c["words"][1])
    for c in ordered:
        if not c["cut"] or c["kind"] == "hesitation":
            continue
        span = words[c["words"][0]:c["words"][1] + 1]
        if c["kind"] == "content":
            # a removed passage can cover several subtitle lines: drop the lines inside it, and strip
            # from each line it touches the part of the passage spoken while that line is on screen
            for q in cues:
                if q.lang != "en" or q.end < c["start"] or q.start > c["end"]:
                    continue
                if q.start >= c["start"] - 0.05 and q.end <= c["end"] + 0.35:
                    q.text = ""
                    changed.append(q.id)
                    continue
                part = [norm(w["w"]) for w in span if q.start - 0.05 <= (w["s"] + w["e"]) / 2 <= q.end + 0.05
                        and norm(w["w"]) and norm(w["w"]) not in HESITATIONS]
                if part and _count(q.text.split(), part) <= _kept_count(q, part, words, gone, mids):
                    continue  # the line already leaves the cut copy out (see below)
                new = _strip_phrase(q.text, part, False, 0.0 if c["start"] <= q.start else 1.0) if part else q.text
                if new != q.text:
                    q.text = new
                    changed.append(q.id)
                    if q.translation:
                        flag.append(q.id)
            continue
        phrase = [norm(w["w"]) for w in span if norm(w["w"])]
        if not phrase:
            continue
        mid = (c["start"] + c["end"]) / 2

        def overlap(q):
            return min(q.end, c["end"] + 0.5) - max(q.start, c["start"] - 0.5)

        near = sorted((q for q in cues if q.lang == "en" and overlap(q) > 0), key=lambda q: -overlap(q))
        for q in near:
            if _count(q.text.split(), phrase) <= _kept_count(q, phrase, words, gone, mids):
                # the subtitle text (from the clean transcript) often already leaves the cut copy out
                # ("it took a, maybe a whole week" -> "it took maybe a whole week"); stripping again
                # removed a word that is still spoken
                break
            frac = (mid - q.start) / max(q.end - q.start, 1e-3)
            new = _strip_phrase(q.text, phrase, c["kind"] == "repeat", min(max(frac, 0.0), 1.0))
            if new != q.text:
                shrunk = len(new) < 0.6 * len(q.text)  # e.g. a restart removed: translation too long now
                q.text = new
                changed.append(q.id)
                if q.translation and (shrunk or any(h in q.translation for h in ZH_FILLER_HINTS)):
                    flag.append(q.id)
                break
    for q in cues:
        if q.lang == "en":
            new = tidy_subtitle(q.text)
            if new != q.text:
                q.text = new
                changed.append(q.id)
    return sorted(set(changed)), sorted(set(flag))


def cut_word_indices(cands: Sequence[dict]) -> set:
    return {k for c in cands if c["cut"] for k in range(c["words"][0], c["words"][1] + 1)}


def write_review_md(path: str, cands: Sequence[dict], words: Sequence[dict]) -> None:
    d = describe(cands, words)
    cut = [c for c in d if c["cut"]]
    lines = ["# Filler words", "",
             f"{len(cut)} of {len(d)} candidates are cut. Hesitations and repeats are cut "
             "automatically; content suggestions (preamble, logistics, restarts …) and discourse "
             'words (like / so / you know …) only when a reviewer sets `"cut": true` in '
             "fillers.json. Rerun with `--fillers fillers.json` to apply edits.", ""]
    by_kind: Dict[str, List[dict]] = {}
    for c in d:
        by_kind.setdefault(c["kind"], []).append(c)
    for kind in ("content", "discourse", "restart", "repeat", "hesitation"):
        items = by_kind.get(kind, [])
        if not items:
            continue
        lines += [f"## {kind} ({sum(1 for c in items if c['cut'])} of {len(items)} cut)", ""]
        for c in items:
            m, s = divmod(int(c["start"]), 60)
            shown = c["context"].replace(f"[{c['text']}]", f"~~{c['text']}~~" if c["cut"] else f"**{c['text']}**")
            if kind == "content":
                shown = f"*{c.get('reason', '')}* ({c['end'] - c['start']:.1f} s): " + \
                    ("~~" + c["text"] + "~~" if c["cut"] else "**" + c["text"] + "**")
            lines.append(f"- `{c['id']}` {m}:{s:02d} {'✂️' if c['cut'] else 'keep'} — {shown}")
        lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
