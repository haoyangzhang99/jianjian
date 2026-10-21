"""Optional explainer cards (term definitions, background notes).

The pipeline doesn't decide *what* deserves a card; your coding agent (or you) writes a small
cards.json from the transcript, e.g.

    [{"at": 125.4, "duration": 6, "title": "RAG", "text": "检索增强生成：先检索资料，再让模型回答"}]

`at` is in SOURCE seconds (the times in cues.json / original-timeline.srt), so cards stay attached
to the moment they explain even when pause settings change.
"""
from __future__ import annotations

from typing import List

from .cuts import TimeMap
from .util import read_json


def load_cards(path: str, tmap: TimeMap) -> List[dict]:
    raw = read_json(path)
    out = []
    end_tl = tmap.edited_duration
    # sorted by timeline position: with a cold open (--hook) that can differ from source order
    placed = sorted((tmap.to_timeline(float(c["at"])), i, c) for i, c in enumerate(raw))
    for a, i, c in placed:
        b = min(a + float(c.get("duration", 6.0)), end_tl)
        if out and a < out[-1]["tl_end"]:          # one card at a time
            out[-1]["tl_end"] = a - 0.05
        if b - a < 1.0:
            continue
        out.append({"id": i + 1, "tl_start": a, "tl_end": b,
                    "title": str(c.get("title", "")).strip(), "text": str(c.get("text", "")).strip()})
    return [c for c in out if c["tl_end"] - c["tl_start"] >= 1.0]
