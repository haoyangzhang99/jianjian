import pytest

from jianjian.cuts import (PRESET_ALIASES, PRESETS, CutSettings, TimeMap, compute_cuts, keep_ranges_from_cuts,
                           merge_intervals, plan, stats)


def test_merge_intervals_joins_overlaps_and_small_gaps():
    assert merge_intervals([(0, 1), (0.5, 2), (2.02, 3)], join_gap=0.05) == [(0, 3)]
    assert merge_intervals([(3, 4), (0, 1)]) == [(0, 1), (3, 4)]


def test_long_pause_is_shortened_to_keep_pause():
    s = CutSettings(max_pause=0.9, keep_pause=0.4, fps=30)
    cuts = compute_cuts([(0.0, 2.0), (5.0, 6.0)], 6.0, s)
    assert cuts == [(2.2, 4.8)]  # 0.2 s of air kept on each side


def test_short_pause_is_left_alone():
    s = CutSettings(max_pause=0.9, keep_pause=0.4, fps=30)
    assert compute_cuts([(0.0, 2.0), (2.8, 4.0)], 4.0, s) == []


def test_filler_between_pauses_is_one_pause_not_two():
    # "word ... uh ... word": with the "uh" removed the gap is shortened once, as one pause
    s = CutSettings(max_pause=0.9, keep_pause=0.4, fps=30)
    vad = [(0.0, 2.0), (2.5, 2.8), (3.3, 5.0)]
    speech, cuts, keeps = plan(vad, [], 5.0, s, fillers=[(2.5, 2.8)])
    kept_gap = sum(k.dur for k in keeps) - (2.0 + 1.7)
    assert abs(kept_gap - 0.4) < 1 / 30 + 1e-6


def test_filler_without_pause_is_still_cut():
    s = CutSettings(max_pause=0.9, keep_pause=0.4, fps=30)
    speech, cuts, keeps = plan([(0.0, 3.0)], [], 3.0, s, fillers=[(1.0, 1.3)])
    assert cuts == [(1.0, 1.3)]


def test_keep_ranges_are_on_the_frame_grid_and_contiguous():
    keeps = keep_ranges_from_cuts([(1.01, 2.49), (4.333, 5.0)], 10.0, 30)
    t = 0.0
    for k in keeps:
        assert abs(k.src_start * 30 - round(k.src_start * 30)) < 1e-9
        assert abs(k.src_end * 30 - round(k.src_end * 30)) < 1e-9
        assert abs(k.tl_start - t) < 1e-9
        t = k.tl_end


def test_timemap_round_trip_and_cut_snapping():
    tm = TimeMap(keep_ranges_from_cuts([(2.0, 4.0)], 10.0, 30))
    assert abs(tm.to_timeline(5.0) - 3.0) < 1e-9
    assert abs(tm.to_source(3.0) - 5.0) < 1e-9
    assert abs(tm.to_timeline(3.0) - 2.0) < 1e-9  # inside the cut -> the cut point
    assert abs(tm.edited_duration - 8.0) < 1e-9


def test_presets_are_sane():
    for name, (max_pause, keep_pause, use) in PRESETS.items():
        assert 0 < keep_pause < max_pause <= 1.5, name
        assert use
    for old, new in PRESET_ALIASES.items():
        assert new in PRESETS


def test_no_cut_keeps_everything_and_reports_zero_cuts():
    # 120.016 s is not a whole number of frames: the partial last frame must not count as a cut
    keeps = keep_ranges_from_cuts([], 120.016, 30)
    assert len(keeps) == 1 and keeps[0].src_start == keeps[0].tl_start == 0.0
    assert TimeMap(keeps).to_timeline(60.0) == 60.0
    st = stats(keeps, 120.016, 30)
    assert st["num_cuts"] == 0 and st["removed_seconds"] == 0.0 and st["longest_cut"] == 0.0


def test_whole_frame_duration_keeps_its_last_frame():
    assert keep_ranges_from_cuts([], 4.0, 30)[0].src_end == pytest.approx(4.0)
