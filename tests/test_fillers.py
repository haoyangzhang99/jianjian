from conftest import words

from jianjian.fillers import _strip_phrase, detect, spans, tidy_subtitle


def test_detect_cuts_hesitations_and_stutters_but_only_lists_discourse_words():
    w = words(("So,", 0.0, 0.2), ("uh,", 0.3, 0.6), ("have", 0.7, 0.8), ("you,", 0.8, 0.9),
              ("have", 1.0, 1.1), ("you", 1.1, 1.2), ("seen", 1.2, 1.4), ("it,", 1.4, 1.5),
              ("like,", 1.6, 1.8), ("really,", 1.9, 2.1), ("really", 2.1, 2.3), ("good?", 2.3, 2.6))
    c = {tuple(x["words"]): x for x in detect(w)}
    assert c[(1, 1)]["kind"] == "hesitation" and c[(1, 1)]["cut"]
    assert c[(2, 3)]["kind"] == "repeat" and c[(2, 3)]["cut"]          # first "have you"
    assert c[(8, 8)]["kind"] == "discourse" and not c[(8, 8)]["cut"]   # "like" needs review
    assert not any(9 in range(a, b + 1) for a, b in c)                 # "really, really" is emphasis


def test_spans_never_reach_into_neighbouring_words_and_snap_inward():
    w = words(("and", 0.0, 0.50), ("uh", 0.40, 1.00), ("then", 0.95, 1.4))
    [(a, b)] = spans([{"words": [1, 1], "kind": "hesitation", "cut": True}], w, fps=30)
    assert a >= 0.50 and b <= 0.95
    assert abs(a * 30 - round(a * 30)) < 1e-9 and abs(b * 30 - round(b * 30)) < 1e-9


def test_strip_phrase_fixes_punctuation_and_capitals():
    assert _strip_phrase("We should leave early, you know.", ["you", "know"], False, 0.9) == \
        "We should leave early."
    assert _strip_phrase("I've got three months left, you know?", ["you", "know"], False, 0.9) == \
        "I've got three months left."
    assert _strip_phrase("And, you know, they're known", ["you", "know"], False, 0.1) == "And they're known"
    assert _strip_phrase("You know, they said so.", ["you", "know"], False, 0.0) == "They said so."
    assert _strip_phrase("How many times have you have you seen it?", ["have", "you"], True, 0.5) == \
        "How many times have you seen it?"
    assert _strip_phrase("the, the movie", ["the"], True, 0.1) == "the movie"


def test_tidy_subtitle():
    assert tidy_subtitle("It was, uh, one of my") == "It was one of my"
    assert tidy_subtitle("And, uh, today") == "And today"
    assert tidy_subtitle("about it, uh. I know") == "about it. I know"
    assert tidy_subtitle("Well, the the entire film") == "Well, the entire film"
    assert tidy_subtitle("Um, um") == "" and tidy_subtitle("Uh") == ""
    assert tidy_subtitle("that's what it's for. For real.") == "that's what it's for. For real."
    assert tidy_subtitle("with China already,") == "with China already"
    assert tidy_subtitle("Hmm.") == "Hmm."  # never empties a line


def test_strip_leaves_a_line_alone_when_the_cut_copy_is_already_missing():
    from jianjian.fillers import strip_from_cues
    from jianjian.subs import Cue
    # spoken: "it took a, maybe a whole week"; the clean transcript already dropped "a,"
    w = words(("it", 0.0, 0.1), ("took", 0.1, 0.3), ("a,", 0.3, 0.4), ("maybe", 0.5, 0.9), ("a", 0.9, 1.0),
              ("whole", 1.0, 1.4), ("week", 1.4, 1.8))
    q = Cue(id=1, start=0.0, end=1.8, lang="en", text="It took maybe a whole week")
    strip_from_cues([q], [{"words": [2, 2], "kind": "restart", "cut": True}], w)
    assert q.text == "It took maybe a whole week"
    # when the line does show both, the cut copy goes
    q2 = Cue(id=2, start=0.0, end=1.8, lang="en", text="It took a maybe a whole week")
    strip_from_cues([q2], [{"words": [2, 2], "kind": "restart", "cut": True}], w)
    assert q2.text == "It took maybe a whole week"
    # two cut "like"s in one line: both go
    w2 = words(("it", 0.0, 0.2), ("was,", 0.2, 0.4), ("like,", 0.5, 0.7), ("huge,", 0.8, 1.1),
               ("like,", 1.2, 1.4), ("really", 1.5, 1.8))
    q3 = Cue(id=3, start=0.0, end=1.8, lang="en", text="It was, like, huge, like, really")
    strip_from_cues([q3], [{"words": [2, 2], "kind": "discourse", "cut": True},
                           {"words": [4, 4], "kind": "discourse", "cut": True}], w2)
    assert "like" not in q3.text


def test_a_cut_restart_leaves_the_line_alone_when_the_line_never_had_it():
    from jianjian.fillers import strip_from_cues
    from jianjian.subs import Cue
    # spoken: "or even if you see it, even if you see it, you don't"; the clean line has one copy
    w = words(("or", 0.0, 0.2), ("even", 0.2, 0.4), ("if", 0.4, 0.5), ("you", 0.5, 0.6), ("see", 0.6, 0.8),
              ("it,", 0.8, 0.9), ("even", 1.0, 1.2), ("if", 1.2, 1.3), ("you", 1.3, 1.4), ("see", 1.4, 1.6),
              ("it,", 1.6, 1.7), ("you", 1.8, 1.9), ("don't", 1.9, 2.1))
    q = Cue(id=1, start=0.0, end=2.1, lang="en", text="Or even if you see it, you don't")
    strip_from_cues([q], [{"words": [1, 5], "kind": "content", "cut": True}], w)
    assert q.text == "Or even if you see it, you don't"


def test_touching_content_cuts_also_cut_the_untranscribed_gap_between_them():
    # the transcript skipped 3 s of speech between words 1 and 2: both sides are cut, so the gap goes too
    w = words(("we", 0.0, 0.3), ("record", 0.3, 0.8), ("you", 3.8, 4.0), ("should", 4.0, 4.3), ("keep", 5.0, 5.3))
    got = spans([{"words": [0, 1], "kind": "content", "cut": True},
                 {"words": [2, 3], "kind": "content", "cut": True}], w, fps=30)
    assert len(got) == 1 and got[0][0] <= 0.0 + 1e-9 and got[0][1] >= 4.29
    # two hesitations next to each other stay separate (the pause between them is the pause logic's job)
    got = spans([{"words": [0, 0], "kind": "hesitation", "cut": True},
                 {"words": [1, 1], "kind": "hesitation", "cut": True}], w, fps=30)
    assert len(got) == 2


def test_a_repeat_across_a_sentence_end_is_not_a_stutter():
    w = words(("what", 0.0, 0.2), ("do", 0.2, 0.3), ("you", 0.3, 0.4), ("call", 0.4, 0.5), ("this?", 0.5, 0.8),
              ("This", 0.9, 1.1), ("is", 1.1, 1.2), ("art.", 1.2, 1.6))
    assert not [c for c in detect(w) if c["kind"] == "repeat"]
