"""Keep every cut out of audible sound.

Cuts are planned from the speech detector (VAD) and Whisper's word timestamps, but neither marks
where sound actually stops: VAD calls soft sounds (a trailing syllable, a breath, a short "oh")
silence, and Whisper's word edges are often 0.05-0.2 s off. On a 15-minute test recording a
listener heard words cut off where a cut stopped a soft tail (35-40 dB below the speech).

This module looks at the audio itself, and only the audio that stays matters:
- A pause cut starts and ends where the kept audio next to the edge is EDGE_DB (45 dB) below the
  speech level; a sound inside the pause (a laugh, a short "oh") is kept by splitting the cut; a
  pause with no such point is not cut (a slightly longer pause beats a chopped word).
- A cut that contains a filler keeps each edge within 70 ms *inside* its boundary (moving outward
  clipped the neighbouring word; searching the whole cut skipped the filler or half a stutter):
  a quiet point there if there is one, otherwise the valley (quietest point) between filler and
  word. Glued fillers are always cut: in a listening test, leaving them in bothered more than the
  valley cuts, which didn't sound clipped.
"""
from __future__ import annotations

import math
from typing import Dict, List, Sequence, Tuple

import numpy as np

Interval = Tuple[float, float]
SR = 16000
HOP = 160            # 10-ms analysis frames
FRAME = HOP / SR
EDGE_DB = 45.0       # the kept audio at a cut edge must be this far below the speech level
AUDIBLE_DB = 40.0    # within this of the speech level = audible sound. (30/25 dB let a cut start
                     # while a soft tail 35-40 dB below speech was still sounding, and a listener heard
                     # the word cut off.)
DIGITAL_SILENCE = -100.0  # dBFS; call apps mute the line between words, so ignore these frames
KEPT_SIDE = 0.03     # seconds of kept audio next to an edge that must be quiet
# A filler glued to a word is always cut, at the valley (quietest point) between them. A listening
# test preferred that to leaving glued fillers in, and the valley cuts didn't sound clipped.



class Loudness:
    """Loudness of a 16-kHz mono signal in 10-ms frames, relative to a local quiet threshold:
    9 dB above the room tone (10th percentile within +-5 s) or 40 dB below the speech level
    (90th percentile within +-10 s), whichever is higher. Digital silence is left out of both
    estimates: video-call apps mute the line between words, and counting those frames put the
    "room tone" at -120 dB, so ordinary pauses looked loud."""

    def __init__(self, audio: np.ndarray):
        n = len(audio) // HOP
        frames = audio[:n * HOP].reshape(n, HOP).astype(np.float64)
        self.db = 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-6)
        self.n = n
        if not n:
            self.speech = self.rel = self.db
            return
        centers = np.arange(0, n, 100)
        floors, speech = [], []
        for c in centers:
            near = self.db[max(0, c - 500):c + 500]
            near = near[near > DIGITAL_SILENCE]
            wide = self.db[max(0, c - 1000):c + 1000]
            wide = wide[wide > DIGITAL_SILENCE]
            floors.append(np.percentile(near, 10) if len(near) else DIGITAL_SILENCE)
            speech.append(np.percentile(wide, 90) if len(wide) else DIGITAL_SILENCE)
        self.speech = np.interp(np.arange(n), centers, speech)
        # dB relative to the local speech level (0 = as loud as speech, -30 = 30 dB quieter). Room
        # tone never counts as sound: frames within 9 dB of it are clamped to -inf.
        floor = np.interp(np.arange(n), centers, floors)
        self.rel = np.where(self.db <= floor + 9.0, -np.inf, self.db - self.speech)

    def frame(self, t: float) -> int:
        return min(max(int(round(t / FRAME)), 0), max(self.n - 1, 0))

    def at(self, t: float) -> float:
        """Loudness (dB rel. speech) of the 10-ms frame at time t, where the cut and its fade are.
        (A wider window would miss the narrow valleys between a filler and a word.)"""
        if not self.n:
            return -np.inf
        return float(self.rel[min(int(t / FRAME + 1e-9), self.n - 1)])

    def kept_side(self, t: float, after: bool) -> float:
        """Loudest frame (dB rel. speech) in the KEPT_SIDE seconds of audio kept next to a cut edge at
        t: before t for a cut start, after t for a cut end."""
        if not self.n:
            return -np.inf
        k = int(round(t / FRAME)); m = int(round(KEPT_SIDE / FRAME))
        seg = self.rel[k:k + m] if after else self.rel[max(0, k - m):k]
        return float(seg.max()) if len(seg) else -np.inf


def _runs(mask: np.ndarray, min_len: int, bridge: int = 0) -> List[Tuple[int, int]]:
    """[start, end) frame runs where mask is True, bridging gaps up to `bridge` frames."""
    out: List[Tuple[int, int]] = []
    k, n = 0, len(mask)
    while k < n:
        if not mask[k]:
            k += 1
            continue
        s = k
        while k < n and (mask[k] or (bridge and mask[k:k + bridge + 1].any())):
            k += 1
        if k - s >= min_len:
            out.append((s, k))
    return out


def refine_cuts(cuts: Sequence[Interval], fillers: Sequence[Interval], loud: Loudness, fps: int,
                min_cut: float = 0.06) -> Tuple[List[Interval], Dict[str, int]]:
    """Keep every cut edge out of audible sound. Only the audio that stays matters: at a cut start the
    audio just before the edge, at a cut end the audio just after it, must be EDGE_DB below the speech
    level (the dip between two words is enough). Edges are searched on the 1/fps frame grid, moving
    inward. Audible sounds inside a pause cut that aren't fillers are kept by splitting the cut.
    A filler glued to a word (no quiet point) is still cut, at the valley between them. A pause cut
    with no valid edges is dropped: a slightly longer pause is better than a chopped word.
    Returns the new cuts and counts of what changed."""
    audible = loud.rel >= -AUDIBLE_DB
    filler_frames = np.zeros(loud.n, dtype=bool)
    for f0, f1 in fillers:  # fillers are meant to be cut even though they are voiced
        filler_frames[loud.frame(f0 - 0.05):loud.frame(f1 + 0.05) + 1] = True
    out: List[Interval] = []
    st = {"cuts": len(cuts), "unchanged": 0, "moved": 0, "split": 0, "dropped": 0, "valley": 0}
    for a, b in cuts:
        k0, k1 = loud.frame(a), loud.frame(b)
        keep = [(s + k0, e + k0) for s, e in _runs(audible[k0:k1] & ~filler_frames[k0:k1], 4, bridge=5)]
        pieces, s0 = [], a
        for s, e in keep:
            pieces.append((s0, s * FRAME))
            s0 = e * FRAME
        pieces.append((s0, b))
        got = []
        for p0, p1 in pieces:
            if not filler_frames[loud.frame(p0):loud.frame(p1) + 1].any():
                # a pure pause: its edges may slide anywhere inside it, to the first and last
                # quiet points; with none, the cut is dropped (a longer pause beats a chopped word)
                grid = [g / fps for g in range(math.ceil(p0 * fps - 1e-6), math.floor(p1 * fps + 1e-6) + 1)]
                na = next((t for t in grid if loud.kept_side(t, after=False) <= -EDGE_DB), None)
                nb = next((t for t in reversed(grid) if loud.kept_side(t, after=True) <= -EDGE_DB), None)
                if na is not None and nb is not None and nb - na >= min_cut:
                    got.append((na, nb))
                continue
            # a cut that contains a filler: each edge stays within 70 ms inside the cut's boundary.
            # (Searching the whole cut found quiet points that skipped the filler entirely, or the
            # dip inside a stutter like "have you" and kept half of it.) Use the quiet point closest
            # to the boundary; with none (a filler glued to a word), the quietest point there.
            # The two windows stop at the middle so they can't cross.
            # Edges only move inward (toward the filler), never outward: moving outward reached into
            # the neighbouring word and clipped its end in a listening test ("because" -> "becau-").
            mid = (p0 + p1) / 2
            a0, a1 = p0, min(p0 + 0.07, mid)
            b0, b1 = max(p1 - 0.07, mid), p1
            ga = [g / fps for g in range(math.ceil(a0 * fps - 1e-6), math.floor(a1 * fps + 1e-6) + 1)] \
                or [math.floor(a1 * fps + 1e-6) / fps]
            gb = [g / fps for g in range(math.ceil(b0 * fps - 1e-6), math.floor(b1 * fps + 1e-6) + 1)] \
                or [math.ceil(b0 * fps - 1e-6) / fps]
            qa = [t for t in ga if loud.kept_side(t, after=False) <= -EDGE_DB]
            qb = [t for t in gb if loud.kept_side(t, after=True) <= -EDGE_DB]
            va = min(qa, key=lambda t: abs(t - p0)) if qa else min(ga, key=lambda t: (loud.at(t), abs(t - p0)))
            vb = min(qb, key=lambda t: abs(t - p1)) if qb else min(gb, key=lambda t: (loud.at(t), abs(t - p1)))
            if vb - va >= min_cut:
                got.append((va, vb))
                if not qa or not qb:
                    st["valley"] += 1
        if not got:
            st["dropped"] += 1
        elif len(got) > 1:
            st["split"] += 1
        elif abs(got[0][0] - a) < 1.5 / fps and abs(got[0][1] - b) < 1.5 / fps:
            st["unchanged"] += 1
        else:
            st["moved"] += 1
        out += got
    return out, st


def edges_in_sound(cuts: Sequence[Interval], loud: Loudness) -> int:
    """How many cut edges chop audible sound: the kept audio next to the edge is within AUDIBLE_DB of
    the speech level (the thing refine_cuts prevents)."""
    return sum((loud.kept_side(a, after=False) >= -AUDIBLE_DB) + (loud.kept_side(b, after=True) >= -AUDIBLE_DB)
               for a, b in cuts)
