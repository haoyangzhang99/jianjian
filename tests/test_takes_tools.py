"""tools/_audio.py, tools/marking.py and tools/assemble_takes.py: pure functions, synthetic audio."""
import importlib.util
import os

import numpy as np

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")


def load(name):
    import sys
    sys.path.insert(0, TOOLS)
    spec = importlib.util.spec_from_file_location(name, os.path.join(TOOLS, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


audio = load("_audio")
marking = load("marking")
takes = load("assemble_takes")


def talk(spans, seconds, sr=16000, seed=1):
    """Quiet noise with louder noise in each (start, end) span: 'speech' and 'pauses'."""
    rng = np.random.default_rng(seed)
    a = rng.normal(0, 0.001, int(seconds * sr)).astype(np.float32)
    for s, e in spans:
        a[int(s * sr):int(e * sr)] += rng.normal(0, 0.1, int(e * sr) - int(s * sr)).astype(np.float32)
    return a


def test_speech_runs_bridge_short_gaps_and_keep_long_ones():
    e = audio.envelope(talk([(1.0, 2.0), (2.1, 3.0), (5.0, 6.0)], 8))
    runs = audio.speech_runs(e)
    assert len(runs) == 2
    assert abs(runs[0][0] - 1.0) < 0.06 and abs(runs[0][1] - 3.0) < 0.06
    assert abs(runs[1][0] - 5.0) < 0.06


def test_drop_points_sit_in_silence_and_keep_a_short_pause():
    # wanted 1-3, an abandoned take 4-5, the complete take from 7
    e = audio.envelope(talk([(1.0, 3.0), (4.0, 5.0), (7.0, 9.0)], 10))
    thr = audio.threshold(e)
    cs, ce, prev_end, on = takes.drop_points(e, thr, 4.0, 7.0)
    assert abs(prev_end - 3.0) < 0.06 and abs(on - 7.0) < 0.06
    assert prev_end < cs <= prev_end + takes.TAIL + 1e-6       # after the last wanted word, pause capped
    assert on - takes.LEAD - 1e-6 <= ce < on                    # before the next wanted word
    assert e[int(cs / audio.HOP)] < thr and e[int(ce / audio.HOP)] < thr


def test_plan_segments_drop_replace_and_exact_cut():
    e_main = audio.envelope(talk([(1.0, 3.0), (4.0, 5.0), (7.0, 9.0), (10.0, 12.0), (14.0, 16.0)], 18))
    e_clip = audio.envelope(talk([(1.0, 2.5)], 4, seed=2) * 0.5)  # a quieter re-recording
    ops = [{"drop": [4.0, 7.0]}, {"drop": [10.0, 14.0], "clip": "fix.mov", "say": [1.0, 2.5]}, {"cut": [15.0, 15.2]}]
    segs, rows = takes.plan_segments(ops, e_main, 18.0, {"fix.mov": e_clip}, 30)
    assert [s["src"] for s in segs] == ["source", "source", "fix.mov", "source", "source"]
    assert segs[2]["gain_db"] > 4                                # levelled up towards the recording
    assert all(abs(s["s"] * 30 - round(s["s"] * 30)) < 1e-3 for s in segs)   # on the frame grid
    kept = sum(s["e"] - s["s"] for s in segs if s["src"] == "source")
    assert 9.5 < kept < 11.5                                     # 18 s minus two takes and the 0.2 s cut
    assert segs[3]["e"] == 15.0 and segs[4]["s"] == round(round(15.2 * 30) / 30, 5)


def test_marking_make_and_diff():
    w = lambda t, s, e: {"w": t, "s": s, "e": e}
    words = [w("On", 1.0, 1.2), w("one", 1.2, 1.4), w("line,", 1.4, 1.8), w("On", 3.0, 3.2), w("line", 3.2, 3.5),
             w("one.", 3.5, 3.9), w("Easy.", 4.2, 4.6), w("Go", 65.0, 65.2), w("back", 65.2, 65.4), w("to", 65.4, 65.5),
             w("the", 65.5, 65.6), w("line.", 65.6, 66.0)]
    lines = marking.lines_from_words(words)
    assert [l["text"] for l in lines] == ["On one line,", "On line one.", "Easy.", "Go back to the line."]
    text = marking.render(lines)
    assert "L001 [0:01] On one line," in text and "L004 [1:05] Go back to the line." in text
    flagged = text.replace("L001 [0:01] On", "L001 [0:01] 🔁 On")
    edited = flagged.replace("L001 [0:01] 🔁 On one line,\n", "").replace("to the line.", "to line.\nfixed at /tmp/redo.mov")
    r = marking.diff(flagged, edited)
    assert [d["line"] for d in r["deleted"]] == [1]
    assert r["changed"][0]["line"] == 4 and r["changed"][0]["removed"] == ["the"]
    assert r["notes"] == [{"after_line": 4, "text": "fixed at /tmp/redo.mov"}]
    assert r["kept"] == 3 and r["of"] == 4
