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


class TimeMap:
    """Maps source time <-> edited timeline time through a list of keep ranges."""

    def __init__(self, keeps: Sequence[KeepRange]):
        self.keeps = list(keeps)
        self._src_starts = [k.src_start for k in self.keeps]
        self._tl_starts = [k.tl_start for k in self.keeps]

    @property
    def edited_duration(self) -> float:
        return self.keeps[-1].tl_end if self.keeps else 0.0

    def to_timeline(self, t: float) -> float:
        """Source time -> timeline time. Times inside a cut snap to the cut point."""
        if not self.keeps:
            return 0.0
        i = bisect.bisect_right(self._src_starts, t) - 1
        if i < 0:
            return 0.0
        k = self.keeps[i]
        if t <= k.src_end:
            return k.tl_start + (t - k.src_start)
        return k.tl_end  # inside the cut after range i

    def to_source(self, tl: float) -> float:
        i = bisect.bisect_right(self._tl_starts, tl) - 1
        i = max(0, min(i, len(self.keeps) - 1))
        k = self.keeps[i]
        return k.src_start + min(max(tl - k.tl_start, 0.0), k.dur)


def plan(vad: Sequence[Interval], words: Sequence[dict], duration: float, s: CutSettings,
         fillers: Sequence[Interval] = ()):
    """fillers: spans to remove regardless of silence (already clamped and frame-snapped)."""
    fillers = merge_intervals(fillers)
    speech = speech_intervals(vad, words, s, fillers)
    cuts = compute_cuts(speech, duration, s, fillers)
    keeps = keep_ranges_from_cuts(cuts, duration, s.fps)
    return speech, cuts, keeps


def stats(keeps: Sequence[KeepRange], duration: float) -> dict:
    edited = keeps[-1].tl_end if keeps else 0.0
    removed = []
    prev_end = 0.0
    for k in keeps:
        if k.src_start > prev_end + 1e-9:
            removed.append(k.src_start - prev_end)
        prev_end = k.src_end
    if duration - prev_end > 1e-3:
        removed.append(duration - prev_end)
    return {
        "source_duration": round(duration, 3),
        "edited_duration": round(edited, 3),
        "removed_seconds": round(duration - edited, 3),
        "removed_percent": round(100.0 * (duration - edited) / duration, 1) if duration else 0.0,
        "num_cuts": len(removed),
        "longest_cut": round(max(removed), 3) if removed else 0.0,
        "num_segments": len(keeps),
    }
