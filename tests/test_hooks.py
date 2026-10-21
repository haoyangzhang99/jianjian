"""Cold open (--hook): a later span plays first, and every stage follows the reordered keep list."""
import json
import wave

import numpy as np
import pytest

from jianjian.cards import load_cards
from jianjian.cli import parse_span
from jianjian.cuts import TimeMap, apply_hooks, keep_ranges_from_cuts, source_runs, stats
from jianjian.subs import Cue, remap


def _spans(keeps):
    return [(round(k.src_start, 4), round(k.src_end, 4), round(k.tl_start, 4)) for k in keeps]


def flat(spans):
    return [t for span in spans for t in span]


def base():
    return keep_ranges_from_cuts([(2.0, 4.0)], 10.0, 30)  # keeps 0-2 and 4-10


def test_teaser_plays_the_hook_first_and_again_in_place():
    keeps = apply_hooks(base(), [(5.0, 6.0)], 30)
    assert _spans(keeps) == [(5.0, 6.0, 0.0), (0.0, 2.0, 1.0), (4.0, 10.0, 3.0)]
    assert len(source_runs(keeps)) == 2


def test_move_removes_the_hook_from_its_place():
    keeps = apply_hooks(base(), [(5.0, 6.0)], 30, move=True)
    assert _spans(keeps) == [(5.0, 6.0, 0.0), (0.0, 2.0, 1.0), (4.0, 5.0, 3.0), (6.0, 10.0, 4.0)]


def test_hook_keeps_pause_cuts_and_snaps_to_the_frame_grid():
    keeps = apply_hooks(base(), [(1.01, 4.52)], 30)
    assert _spans(keeps)[:2] == [(1.0, 2.0, 0.0), (4.0, 4.5333, 1.0)]  # the 2-4 s cut stays cut
    for k in keeps:
        assert abs(k.src_start * 30 - round(k.src_start * 30)) < 1e-9
        assert abs(k.tl_start * 30 - round(k.tl_start * 30)) < 1e-9


def test_several_hooks_play_in_the_given_order():
    keeps = apply_hooks(base(), [(8.0, 9.0), (5.0, 6.0)], 30)
    assert _spans(keeps)[:2] == [(8.0, 9.0, 0.0), (5.0, 6.0, 1.0)]


def test_bad_hooks_are_refused():
    with pytest.raises(ValueError):
        apply_hooks(base(), [(2.2, 3.8)], 30)  # entirely in a cut
    with pytest.raises(ValueError):
        apply_hooks(base(), [(5.0, 7.0), (6.0, 8.0)], 30)  # overlapping


def test_hook_at_the_start_in_move_mode_changes_nothing():
    assert _spans(apply_hooks(base(), [(0.0, 1.0)], 30, move=True)) == _spans(base())


def test_timemap_with_a_teaser_has_two_places_for_the_hook():
    tm = TimeMap(apply_hooks(base(), [(5.0, 6.0)], 30))
    assert flat(tm.spans(5.2, 5.8)) == pytest.approx([0.2, 0.8, 4.2, 4.8])
    assert tm.to_timeline(5.5) == pytest.approx(4.5)  # the in-context place
    assert tm.to_timeline(1.0) == pytest.approx(2.0)
    assert tm.to_timeline(3.0) == pytest.approx(3.0)  # inside the cut -> the cut point
    assert tm.to_source(0.5) == pytest.approx(5.5)
    assert tm.edited_duration == pytest.approx(9.0)


def test_timemap_with_a_moved_hook_has_one_place():
    tm = TimeMap(apply_hooks(base(), [(5.0, 6.0)], 30, move=True))
    assert flat(tm.spans(5.2, 5.8)) == pytest.approx([0.2, 0.8])
    assert tm.to_timeline(5.5) == pytest.approx(0.5)
    assert flat(tm.spans(4.5, 6.5)) == pytest.approx([0.0, 1.0, 3.5, 4.5])  # straddles the hook


def test_subtitles_follow_the_cold_open():
    cues = [Cue(1, 0.2, 1.5, "en", "Hi."), Cue(2, 5.1, 5.9, "en", "The hook."), Cue(3, 7.0, 8.0, "en", "More.")]
    teaser = remap([Cue(**c.to_dict()) for c in cues], TimeMap(apply_hooks(base(), [(5.0, 6.0)], 30)))
    assert [c.id for c in teaser] == [2, 1, 2, 3]
    assert teaser[0].tl_start == pytest.approx(0.1) and teaser[2].tl_start == pytest.approx(4.1)
    assert all(a.tl_end <= b.tl_start for a, b in zip(teaser, teaser[1:]))
    moved = remap([Cue(**c.to_dict()) for c in cues], TimeMap(apply_hooks(base(), [(5.0, 6.0)], 30, move=True)))
    assert [c.id for c in moved] == [2, 1, 3]


def test_cards_are_ordered_on_the_timeline(tmp_path):
    p = tmp_path / "cards.json"
    p.write_text(json.dumps([{"at": 1.0, "duration": 1.5, "title": "A", "text": ""},
                             {"at": 5.2, "duration": 1.0, "title": "B", "text": ""}]))
    cards = load_cards(str(p), TimeMap(apply_hooks(base(), [(5.0, 6.0)], 30, move=True)))
    assert [c["title"] for c in cards] == ["B", "A"]


def test_stats_count_source_removed_not_the_repeat():
    plain, teaser = stats(base(), 10.0), stats(apply_hooks(base(), [(5.0, 6.0)], 30), 10.0)
    assert teaser["removed_seconds"] == plain["removed_seconds"] == pytest.approx(2.0)
    assert teaser["edited_duration"] == pytest.approx(9.0)


def test_parse_span():
    assert parse_span("312.4-318.9") == (312.4, 318.9)
    assert parse_span("5:12.4-5:18") == pytest.approx((312.4, 318.0))
    for bad in ("12", "20-10", "a-b"):
        with pytest.raises(Exception):
            parse_span(bad)


def test_audio_follows_the_reordered_keeps(tmp_path):
    pytest.importorskip("av")
    from jianjian.render import AUDIO_SR, build_audio
    src = tmp_path / "ramp.wav"
    n = 10 * AUDIO_SR
    ramp = np.arange(n) / n * 0.9  # the sample value tells the source time
    with wave.open(str(src), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(AUDIO_SR)
        wf.writeframes((ramp * 32767).astype("<i2").tobytes())
    keeps = apply_hooks(base(), [(5.0, 6.0)], 30)
    out = tmp_path / "out.wav"
    assert build_audio(str(src), keeps, str(out)) == pytest.approx(9.0)
    with wave.open(str(out)) as wf:
        got = np.frombuffer(wf.readframes(wf.getnframes()), dtype="<i2") / 32767
    assert len(got) == 9 * AUDIO_SR
    for tl, src_t in ((0.5, 5.5), (2.0, 1.0), (4.5, 5.5), (8.0, 9.0)):
        assert got[int(tl * AUDIO_SR)] == pytest.approx(src_t / 10 * 0.9, abs=1e-3)
    assert abs(got[AUDIO_SR]) < 0.01  # faded to silence at the join from the hook back to 0 s
