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
    assert tidy_subtitle("with China already,") == "with China already"
    assert tidy_subtitle("Hmm.") == "Hmm."  # never empties a line
