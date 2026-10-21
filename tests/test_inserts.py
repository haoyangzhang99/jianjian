"""Inserted clips (--insert): a clip plays at a moment of the recording, and everything after it moves."""
import argparse

import numpy as np
import pytest

from jianjian.cli import parse_insert
from jianjian.cuts import TimeMap, apply_hooks, apply_inserts, keep_ranges_from_cuts, source_runs, stats
from jianjian.subs import Cue, remap
from jianjian.validate import _expected_audio


def _spans(keeps):
    return [(round(k.src_start, 4), round(k.src_end, 4), round(k.tl_start, 4), k.media) for k in keeps]


def base():
    return keep_ranges_from_cuts([(2.0, 4.0)], 10.0, 30)  # keeps 0-2 and 4-10


def test_insert_inside_a_cut_goes_at_the_cut():
    keeps = apply_inserts(base(), [(3.0, 1.5)], 30)
    assert _spans(keeps) == [(0.0, 2.0, 0.0, 0), (0.0, 1.5, 2.0, 1), (4.0, 10.0, 3.5, 0)]
    assert len(source_runs(keeps)) == 3


def test_insert_inside_a_keep_range_splits_it():
    keeps = apply_inserts(base(), [(6.0, 1.0), (1.0, 0.5)], 30)
    assert _spans(keeps) == [(0.0, 1.0, 0.0, 0), (0.0, 0.5, 1.0, 2), (1.0, 2.0, 1.5, 0),
                             (4.0, 6.0, 2.5, 0), (0.0, 1.0, 4.5, 1), (6.0, 10.0, 5.5, 0)]
    st = stats(keeps, 10.0, 30)
    assert st["edited_duration"] == pytest.approx(9.5) and st["inserted_seconds"] == pytest.approx(1.5)
    assert st["removed_seconds"] == pytest.approx(2.0)  # the clip is not source: only the cut counts


def test_timemap_skips_the_clip():
    tm = TimeMap(apply_inserts(base(), [(5.0, 2.0)], 30))
    assert tm.to_timeline(4.5) == pytest.approx(2.5)
    assert tm.to_timeline(5.5) == pytest.approx(5.5)  # after the 2-s clip
    assert tm.edited_duration == pytest.approx(10.0)
    assert tm.to_source(3.5) == pytest.approx(5.0)  # inside the clip: where it was put
    # subtitles before and after the clip keep their text and move with the timeline
    cues = remap([Cue(id=1, start=4.2, end=4.9, lang="en", text="before"),
                  Cue(id=2, start=5.1, end=6.0, lang="en", text="after")], tm)
    assert [(c.text, round(c.tl_start, 2)) for c in cues] == [("before", 2.2), ("after", 5.1)]


def test_insert_goes_to_the_in_context_place_after_a_cold_open():
    keeps = apply_inserts(apply_hooks(base(), [(5.0, 6.0)], 30), [(5.5, 1.0)], 30)
    clip = [k for k in keeps if k.media][0]
    assert clip.tl_start == pytest.approx(4.5)  # not inside the 1-s hook at the start


def test_expected_audio_takes_the_clip_audio():
    sr = 16000
    rec = np.ones(10 * sr, dtype=np.float32)
    clip = np.full(sr, 0.5, dtype=np.float32)
    exp = _expected_audio(rec, apply_inserts(base(), [(3.0, 1.0)], 30), [clip])
    assert len(exp) == 9 * sr
    assert exp[2 * sr + 100] == 0.5 and exp[3 * sr + 100] == 1.0


def test_parse_insert(tmp_path):
    f = tmp_path / "scene.mov"
    f.write_bytes(b"x")
    assert parse_insert(f"5:12.4={f}") == (pytest.approx(312.4), str(f))
    with pytest.raises(argparse.ArgumentTypeError):
        parse_insert(f"{f}")
    with pytest.raises(argparse.ArgumentTypeError):
        parse_insert(f"12={tmp_path / 'missing.mov'}")


def test_a_moment_inside_a_cut_maps_next_to_the_clip_put_there():
    # keeps 0-2 and 4-10, clip at 3 s (inside the cut), a second clip later at 8 s:
    # source 3.0 must map to where the first clip starts, not to the run after the second clip
    tm = TimeMap(apply_inserts(base(), [(3.0, 1.0), (8.0, 2.0)], 30))
    assert tm.to_timeline(3.0) == pytest.approx(2.0)
    assert tm.to_timeline(9.0) == pytest.approx(10.0)  # after both clips


def test_insert_near_the_edge_of_a_keep_range_snaps_to_it():
    # 1 frame before the end of the 0-2 keep: no 1-frame sliver after the clip
    keeps = apply_inserts(base(), [(2.0 - 1 / 30, 1.0)], 30)
    assert _spans(keeps) == [(0.0, 2.0, 0.0, 0), (0.0, 1.0, 2.0, 1), (4.0, 10.0, 3.0, 0)]
    keeps = apply_inserts(base(), [(4.1, 1.0)], 30)  # just after the start of 4-10: before it
    assert _spans(keeps) == [(0.0, 2.0, 0.0, 0), (0.0, 1.0, 2.0, 1), (4.0, 10.0, 3.0, 0)]
