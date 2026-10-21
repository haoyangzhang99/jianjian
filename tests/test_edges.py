import numpy as np

from jianjian.edges import SR, Loudness, edges_in_sound, refine_cuts


def signal(*parts):
    """[("tone"|"quiet", seconds), ...] -> 16-kHz audio: speech-loud tone or faint room noise."""
    rng = np.random.default_rng(0)
    out = []
    for kind, sec in parts:
        n = int(sec * SR)
        if kind == "tone":
            out.append(0.3 * np.sin(2 * np.pi * 220 * np.arange(n) / SR))
        else:
            out.append(0.0005 * rng.standard_normal(n))
    return np.concatenate(out).astype(np.float32)


def on_grid(t, fps=30):
    return abs(t * fps - round(t * fps)) < 1e-6


def test_edges_move_out_of_sound_into_quiet():
    # word 0-1 s, pause 1-3 s, word 3-4 s; a cut that starts and ends inside the words
    loud = Loudness(signal(("tone", 1.0), ("quiet", 2.0), ("tone", 1.0), ("quiet", 1.0)))
    assert edges_in_sound([(0.9, 3.1)], loud) == 2
    cuts, st = refine_cuts([(0.9, 3.1)], [], loud, 30)
    [(a, b)] = cuts
    assert 1.0 < a < 1.2 and 2.8 < b < 3.0
    assert on_grid(a) and on_grid(b)
    assert edges_in_sound(cuts, loud) == 0 and st["moved"] == 1


def test_sound_inside_a_pause_is_kept():
    # a short sound (laugh, "oh") in the middle of a long pause: the cut is split around it
    loud = Loudness(signal(("tone", 1.0), ("quiet", 1.0), ("tone", 0.2), ("quiet", 1.0), ("tone", 1.0)))
    cuts, st = refine_cuts([(1.1, 3.1)], [], loud, 30)
    assert len(cuts) == 2 and st["split"] == 1
    assert cuts[0][1] < 2.0 and cuts[1][0] > 2.2


def test_filler_inside_a_cut_is_still_removed():
    # the same sound, marked as a filler: it is cut, not protected
    loud = Loudness(signal(("tone", 1.0), ("quiet", 1.0), ("tone", 0.2), ("quiet", 1.0), ("tone", 1.0)))
    cuts, _ = refine_cuts([(1.1, 3.1)], [(2.0, 2.2)], loud, 30)
    assert len(cuts) == 1 and cuts[0][0] < 2.0 and cuts[0][1] > 2.2


def test_glued_filler_is_still_cut():
    # "and-uh" with no quiet point: fillers are always cut (at the quietest point nearby)
    loud = Loudness(signal(("quiet", 2.0), ("tone", 2.0), ("quiet", 1.0)))
    cuts, st = refine_cuts([(3.0, 3.5)], [(3.0, 3.5)], loud, 30)
    assert len(cuts) == 1 and st["dropped"] == 0


def test_pause_cut_with_no_quiet_point_is_dropped():
    # a "pause" that is really continuous sound: never cut into it
    loud = Loudness(signal(("quiet", 2.0), ("tone", 2.0), ("quiet", 1.0)))
    cuts, st = refine_cuts([(3.0, 3.5)], [], loud, 30)
    assert cuts == [] and st["dropped"] == 1


def test_room_tone_counts_as_quiet_next_to_digital_silence():
    # video-call apps mute the line (exact zeros) between words; a pause with faint room tone
    # must still count as quiet, so the cut is kept rather than dropped
    a = signal(("tone", 1.0), ("quiet", 2.0), ("tone", 1.0))
    a[int(1.2 * SR):int(1.5 * SR)] = 0.0
    loud = Loudness(a)
    cuts, st = refine_cuts([(1.1, 2.9)], [], loud, 30)
    assert len(cuts) == 1 and st["dropped"] == 0


def test_glued_filler_with_a_valley_is_cut_there():
    # word, then a filler that follows without a pause but with a clear dip (valley) between them
    # (real recordings have pauses, so the room tone is known: 2 s of quiet before and after)
    a = signal(("quiet", 2.0), ("tone", 1.0), ("tone", 0.3), ("tone", 1.0), ("quiet", 2.0))
    a[int(3.0 * SR):int(3.04 * SR)] *= 0.05      # ~26 dB valley between word and filler
    a[int(3.3 * SR):int(3.34 * SR)] *= 0.05      # and between filler and the next word
    loud = Loudness(a)
    cuts, st = refine_cuts([(3.0, 3.32)], [(3.0, 3.32)], loud, 30)
    assert len(cuts) == 1 and st["valley"] == 1
