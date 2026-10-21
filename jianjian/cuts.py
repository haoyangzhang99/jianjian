"""Pause detection -> keep ranges, and mapping between source and edited timelines.

All public times are in seconds. Keep-range boundaries are snapped to a frame grid
(1/fps) so that the Jianying timeline, the FFmpeg render and the subtitles share exactly
the same edit and nothing drifts over a long episode.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass, asdict
from typing import Iterable, List, Sequence, Tuple

Interval = Tuple[float, float]

# Pause presets: shorten silences longer than max_pause to keep_pause (seconds). Based on what
# silence-removal tools use (researched 2026-10): Mubert Cast defaults to >0.5 s -> 0.3 s, FireCut
# suggests starting at 750 ms with 250+250 ms padding, AutoCut calls 0.3-0.5 s ideal for YouTube,
# auto-editor keeps 0.2 s each side, Descript's example is >750 ms -> 200 ms; Chinese 口播 guidance
# keeps 0.2-0.8 s (0.8-1.2 s for interviews). There is no default: ask which one fits each video.
PRESETS = {
    # name: (max_pause, keep_pause, best for)
    "shorts": (0.5, 0.25, "Shorts / Reels / TikTok, one speaker, fastest pace"),
    "youtube": (0.6, 0.3, "YouTube talking head, one speaker"),
    "conversation": (0.6, 0.35, "YouTube conversation, 2+ speakers (keeps turn-taking natural)"),
    "podcast": (0.75, 0.4, "podcast / long-form listening, relaxed pace"),
    "interview": (1.0, 0.6, "slow, reflective interview; keeps thinking pauses"),
}
PRESET_ALIASES = {"tight": "youtube", "normal": "podcast", "gentle": "interview"}  # pre-2026-10 names


def preset_table() -> str:
    rows = [f"  {n:<13} pauses > {m:.2f}s -> {k:.2f}s   {use}" for n, (m, k, use) in PRESETS.items()]
    return "\n".join(rows)


@dataclass
class CutSettings:
    max_pause: float = 0.9      # silences longer than this get shortened
    keep_pause: float = 0.45    # ...to this length (split half before, half after)
    min_edge: float = 0.15      # never keep less than this much air next to speech
    min_cut: float = 0.25       # don't bother cutting less than this
    max_word_span: float = 1.5  # ignore suspiciously long whisper word spans
    fps: int = 30               # frame grid for snapping

    def to_dict(self):
        return asdict(self)


@dataclass
class KeepRange:
    src_start: float
    src_end: float
    tl_start: float
    media: int = 0  # 0 = the recording; n = the n-th inserted clip (--insert)

    @property
    def dur(self) -> float:
        return self.src_end - self.src_start

    @property
    def tl_end(self) -> float:
        return self.tl_start + self.dur


def merge_intervals(intervals: Iterable[Interval], join_gap: float = 0.0) -> List[Interval]:
    items = sorted((float(a), float(b)) for a, b in intervals if b > a)
    out: List[List[float]] = []
    for a, b in items:
        if out and a <= out[-1][1] + join_gap:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def subtract_intervals(spans: Sequence[Interval], remove: Sequence[Interval]) -> List[Interval]:
    out: List[Interval] = []
    for a, b in spans:
        pieces = [(a, b)]
        for r0, r1 in remove:
            nxt = []
            for x, y in pieces:
                if r1 <= x or r0 >= y:
                    nxt.append((x, y))
                    continue
                if r0 > x:
                    nxt.append((x, r0))
                if r1 < y:
                    nxt.append((r1, y))
            pieces = nxt
        out += pieces
    return out


def speech_intervals(vad: Sequence[Interval], words: Sequence[dict], s: CutSettings,
                     fillers: Sequence[Interval] = ()) -> List[Interval]:
    """Union of VAD speech and whisper word spans (word spans protect words VAD missed).
    Filler spans count as silence: VAD hears "uh" as speech, but it is being removed."""
    spans = list(vad)
    if fillers:
        spans = [(a, b) for a, b in subtract_intervals(spans, fillers) if b - a >= 0.15]
    for w in words:
        a, b = float(w["s"]), float(w["e"])
        mid = (a + b) / 2
        if any(f0 <= mid <= f1 for f0, f1 in fillers):
            continue
        if 0 < b - a <= s.max_word_span:
            spans.append((a, b))
    return merge_intervals(spans, join_gap=0.05)


def compute_cuts(speech: Sequence[Interval], duration: float, s: CutSettings,
                 fillers: Sequence[Interval] = ()) -> List[Interval]:
    """Return the regions to remove (source seconds): long silences, plus any filler spans.
    A gap's length is measured without the fillers in it, so "pause, uh, pause" is shortened once
    as one pause instead of leaving two pauses either side of the removed "uh"."""
    edge = max(s.keep_pause / 2.0, s.min_edge)
    cuts: List[Interval] = []
    if not speech:
        return list(fillers)

    def silence(a, b):
        return (b - a) - sum(max(0.0, min(b, f1) - max(a, f0)) for f0, f1 in fillers)

    # leading silence
    first = speech[0][0]
    if silence(0.0, first) > s.max_pause:
        cuts.append((0.0, first - edge))
    # gaps between speech
    for (a0, b0), (a1, b1) in zip(speech, speech[1:]):
        if silence(b0, a1) > s.max_pause:
            cuts.append((b0 + edge, a1 - edge))
    # trailing silence
    last = speech[-1][1]
    if silence(last, duration) > s.max_pause:
        cuts.append((last + edge, duration))
    cuts = [(a, b) for a, b in cuts if b - a >= s.min_cut]
    return merge_intervals(cuts + list(fillers))


def keep_ranges_from_cuts(cuts: Sequence[Interval], duration: float, fps: int) -> List[KeepRange]:
    """Complement of cuts within [0, duration], snapped to the 1/fps grid."""
    total_frames = int(duration * fps + 1e-6)  # floor: never reference past the end
    keeps_frames: List[List[int]] = []
    pos = 0.0
    raw: List[Interval] = []
    for a, b in sorted(cuts):
        if a > pos:
            raw.append((pos, a))
        pos = max(pos, b)
    if pos < duration:
        raw.append((pos, duration))
    for a, b in raw:
        fa = int(round(a * fps))
        fb = min(int(round(b * fps)), total_frames)
        if fb <= fa:
            continue
        if keeps_frames and fa <= keeps_frames[-1][1]:
            keeps_frames[-1][1] = max(keeps_frames[-1][1], fb)
        else:
            keeps_frames.append([fa, fb])
    out: List[KeepRange] = []
    tl_frames = 0
    for fa, fb in keeps_frames:
        out.append(KeepRange(fa / fps, fb / fps, tl_frames / fps))
        tl_frames += fb - fa
    return out


def source_runs(keeps: Sequence[KeepRange]) -> List[List[KeepRange]]:
    """Split keep ranges (in timeline order) into runs that are in source order. An ordinary edit
    is one run; a cold open (--hook) puts runs before it that jump back in the source, and an
    inserted clip (--insert) is a run of its own."""
    runs: List[List[KeepRange]] = []
    for k in keeps:
        if runs and k.media == runs[-1][-1].media and k.src_start >= runs[-1][-1].src_end - 1e-9:
            runs[-1].append(k)
        else:
            runs.append([k])
    return runs


def apply_hooks(keeps: Sequence[KeepRange], hooks: Sequence[Interval], fps: int,
                move: bool = False) -> List[KeepRange]:
    """Cold open: play the kept parts of each hook span (source seconds, in the order given) first,
    then the whole edit from the start. Pauses and fillers inside a hook stay cut, and the hook
    bounds are snapped to the frame grid. move=False repeats the hook at its original place (a
    teaser); move=True removes it there."""
    frames = [(int(round(k.src_start * fps)), int(round(k.src_end * fps))) for k in keeps]
    spans = [(int(round(a * fps)), int(round(b * fps))) for a, b in hooks]
    for i, (a, b) in enumerate(spans):
        if b <= a:
            raise ValueError(f"hook {hooks[i][0]}-{hooks[i][1]} is empty")
        for c, d in spans[:i]:
            if a < d and c < b:
                raise ValueError(f"hooks {hooks[i][0]}-{hooks[i][1]} and {c / fps}-{d / fps} overlap")
    order: List[Tuple[int, int]] = []
    for a, b in spans:
        part = [(max(fa, a), min(fb, b)) for fa, fb in frames if min(fb, b) > max(fa, a)]
        if not part:
            raise ValueError(f"hook {a / fps:.2f}-{b / fps:.2f} lies entirely in cut material")
        order += part
    if move:
        frames = [(int(x), int(y)) for x, y in subtract_intervals(frames, spans) if y > x]
    joined: List[List[int]] = []
    for fa, fb in order + frames:
        if joined and joined[-1][1] == fa:  # continues in the source: one range, no extra cut
            joined[-1][1] = fb
        else:
            joined.append([fa, fb])
    out: List[KeepRange] = []
    tl = 0
    for fa, fb in joined:
        out.append(KeepRange(fa / fps, fb / fps, tl / fps))
        tl += fb - fa
    return out


def apply_inserts(keeps: Sequence[KeepRange], inserts: Sequence[Tuple[float, float]], fps: int) -> List[KeepRange]:
    """Put clips into the edit: inserts are (source second of the recording, clip length in seconds),
    clip n+1 is media n+1. Each clip goes in where that moment plays (the in-context place if a cold
    open repeats it); a moment inside a cut snaps to the cut, and a keep range is split if needed.
    Everything after a clip moves later by its length. A moment within 0.3 s of a keep range's edge
    snaps to that edge instead of splitting the range: a piece that short can't hold a word."""
    out = [KeepRange(k.src_start, k.src_end, k.tl_start, k.media) for k in keeps]
    snap = int(round(0.3 * fps))
    for n, (at, length) in sorted(enumerate(inserts), key=lambda x: x[1][0]):
        f, nf = int(round(at * fps)), int(round(length * fps))
        if nf <= 0:
            raise ValueError(f"inserted clip {n + 1} is empty")
        main = [i for i, k in enumerate(out) if k.media == 0]
        # the last source-ordered run of the recording that reaches this moment (cf. TimeMap.to_timeline)
        pos = None
        for i in reversed(main):
            k = out[i]
            fa, fb = int(round(k.src_start * fps)), int(round(k.src_end * fps))
            if fa < f < fb:
                if fb - f <= snap:  # near the end of a keep range: after it (a split left a 1-frame
                    pos = i + 1     # sliver of the next word playing after the clip)
                elif f - fa <= snap:
                    pos = i
                else:  # inside a keep range: split it
                    out[i:i + 1] = [KeepRange(fa / fps, f / fps, k.tl_start),
                                    KeepRange(f / fps, fb / fps, k.tl_start + (f - fa) / fps)]
                    pos = i + 1
                break
            if fb <= f:  # in the cut (or at the boundary) after this range
                pos = i + 1
                break
        if pos is None:
            pos = main[0] if main else 0
        tl = out[pos - 1].tl_end if pos > 0 else 0.0
        out.insert(pos, KeepRange(0.0, nf / fps, tl, media=n + 1))
        t = tl
        for k in out[pos:]:
            k.tl_start = round(t * fps) / fps
            t = k.tl_start + k.dur
    return out


class TimeMap:
    """Maps source time <-> edited timeline time through a list of keep ranges (in timeline
    order). With a cold open a source moment can appear twice; to_timeline() then returns the
    later, in-context place and spans() returns every place. Inserted clips take up timeline time
    but map to no source time."""

    def __init__(self, keeps: Sequence[KeepRange]):
        self.keeps = list(keeps)
        self._tl_starts = [k.tl_start for k in self.keeps]
        self.runs = [(r, [k.src_start for k in r]) for r in source_runs(self.keeps) if r[0].media == 0]

    @property
    def edited_duration(self) -> float:
        return self.keeps[-1].tl_end if self.keeps else 0.0

    @staticmethod
    def _in_run(run, starts, t: float) -> float:
        """Source time -> timeline time within one run. Times inside a cut snap to the cut point."""
        i = bisect.bisect_right(starts, t) - 1
        if i < 0:
            return run[0].tl_start
        k = run[i]
        if t <= k.src_end:
            return k.tl_start + (t - k.src_start)
        return k.tl_end  # inside the cut after range i

    def to_timeline(self, t: float) -> float:
        """Source time -> timeline time: the last run that keeps t; for a moment inside a cut, the
        last run that starts before it (an inserted clip splits the edit into several runs, so the
        last run is not always the one that holds the cut)."""
        if not self.keeps:
            return 0.0
        for run, starts in reversed(self.runs):
            i = bisect.bisect_right(starts, t) - 1
            if i >= 0 and t <= run[i].src_end:
                return self._in_run(run, starts, t)
        for run, starts in reversed(self.runs):
            if starts[0] <= t:
                return self._in_run(run, starts, t)
        return self._in_run(*self.runs[-1], t)

    def spans(self, a: float, b: float) -> List[Interval]:
        """Every timeline span that plays source [a, b], in timeline order (empty ones left out)."""
        out = []
        for run, starts in self.runs:
            if b <= run[0].src_start or a >= run[-1].src_end:
                continue
            x, y = self._in_run(run, starts, a), self._in_run(run, starts, b)
            if y > x:
                out.append((x, y))
        return out

    def to_source(self, tl: float) -> float:
        i = bisect.bisect_right(self._tl_starts, tl) - 1
        i = max(0, min(i, len(self.keeps) - 1))
        k = self.keeps[i]
        if k.media:  # inside an inserted clip: the moment of the recording it was put at
            rest = [x for x in self.keeps[i:] if not x.media]
            return rest[0].src_start if rest else max((x.src_end for x in self.keeps[:i] if not x.media), default=0.0)
        return k.src_start + min(max(tl - k.tl_start, 0.0), k.dur)


def plan(vad: Sequence[Interval], words: Sequence[dict], duration: float, s: CutSettings,
         fillers: Sequence[Interval] = ()):
    """fillers: spans to remove regardless of silence (already clamped and frame-snapped)."""
    fillers = merge_intervals(fillers)
    speech = speech_intervals(vad, words, s, fillers)
    cuts = compute_cuts(speech, duration, s, fillers)
    keeps = keep_ranges_from_cuts(cuts, duration, s.fps)
    return speech, cuts, keeps


def stats(keeps: Sequence[KeepRange], duration: float, fps: int = 30) -> dict:
    """Keeps end on the 1/fps grid, so the source's last partial frame is never used; it is not a cut."""
    end = int(duration * fps + 1e-6) / fps
    edited = keeps[-1].tl_end if keeps else 0.0
    # source used (a hook may repeat; inserted clips aren't the source)
    kept = merge_intervals((k.src_start, k.src_end) for k in keeps if k.media == 0)
    removed = []
    prev_end = 0.0
    for a, b in kept:
        if a > prev_end + 1e-9:
            removed.append(a - prev_end)
        prev_end = b
    if end - prev_end > 1e-3:
        removed.append(end - prev_end)
    gone = max(0.0, end - sum(b - a for a, b in kept))
    return {
        "source_duration": round(duration, 3),
        "edited_duration": round(edited, 3),
        "removed_seconds": round(gone, 3),
        "removed_percent": round(100.0 * gone / duration, 1) if duration else 0.0,
        "num_cuts": len(removed),
        "longest_cut": round(max(removed), 3) if removed else 0.0,
        "num_segments": len(keeps),
        "inserted_seconds": round(sum(k.dur for k in keeps if k.media), 3),
    }
