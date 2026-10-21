from conftest import words

from jianjian.content import broll_markers, suggest
from jianjian.fillers import detect


def seq(text, start=0.0, step=0.3):
    """'Hi everyone. Today we ...' -> word dicts, one every `step` seconds."""
    out, t = [], start
    for w in text.split():
        out.append((w, t, t + step * 0.8))
        t += step
    return words(*out)


def reasons(ws):
    return {(s["reason"], "".join(w["w"] for w in ws[s["words"][0]:s["words"][1] + 1]).strip()) for s in suggest(ws)}


def test_preamble_before_the_greeting():
    ws = seq("Is it recording now? Yeah, we can start. Hi, everyone. Welcome to the show.")
    assert ("preamble before the greeting", "Is it recording now? Yeah, we can start.") in reasons(ws)


def test_logistics_and_word_search():
    ws = seq("Hi, everyone. Okay, let's start. It is getting more suburb. Is that how? Suburban. Yeah. Fine then.")
    r = reasons(ws)
    assert ("logistics / transition", "Okay, let's start.") in r
    assert ("word search", "Is that how? Suburban. Yeah.") in r


def test_restart_needs_a_break_and_no_sentence_end():
    real = seq("Hi, everyone. You have to be, uh, you have to have done something.")
    assert ("restart", "You have to be, uh,") in reasons(real)
    plain = seq("Hi, everyone. It starts at the station and it ends at the airport.")
    assert not [x for x in reasons(plain) if x[0] == "restart"]


def test_unfinished_ending():
    ws = seq("Hi, everyone. That was great. So one very obvious symbol is")
    assert ("unfinished ending", "So one very obvious symbol is") in reasons(ws)


def test_stutter_across_a_filler_is_cut():
    ws = seq("and they, uh, they went home")
    c = {tuple(x["words"]): x for x in detect(ws)}
    assert c[(1, 1)]["kind"] == "repeat" and c[(1, 1)]["cut"]     # first "they"
    assert c[(2, 2)]["kind"] == "hesitation" and c[(2, 2)]["cut"]  # the uh


def test_word_restart_is_suggested_not_cut():
    ws = seq("a rem, rem, uh, remember that")
    restarts = [x for x in detect(ws) if x["kind"] == "restart"]
    assert restarts and not restarts[0]["cut"]


def test_broll_marker():
    ws = seq("I remember that scene. Maybe we should put the clip here. Anyway.")
    assert [m["text"] for m in broll_markers(ws)] == ["Maybe we should put the clip here."]


def test_broll_more_phrasings_and_both_transcripts():
    clean = seq("I love that scene. Anyway.")
    verbatim = seq("I love that scene. Yeah, we need to show that clip. Anyway, maybe we could play it.")
    got = [m["text"] for m in broll_markers(clean, verbatim)]
    assert got == ["Yeah, we need to show that clip.", "Anyway, maybe we could play it."]
    # the same sentence in both transcripts is listed once
    assert len(broll_markers(verbatim, verbatim)) == 2
