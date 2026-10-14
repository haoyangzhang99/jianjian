from conftest import words

from jianjian.subs import CueSettings, _ends_sentence, build_cues
from jianjian.translate import sentence_groups, split_translation


def test_sentence_end_detection():
    assert _ends_sentence("planned.") and _ends_sentence("right?") and _ends_sentence("好。")
    assert not _ends_sentence("U.S.") and not _ends_sentence("Mr.") and not _ends_sentence("well,")


def test_short_scraps_merge_into_a_neighbour():
    w = words(("Yeah,", 0.0, 0.3), ("you", 0.4, 0.6), ("don't", 0.6, 0.8), ("live", 0.8, 1.0),
              ("here", 1.0, 1.3), ("now,", 1.3, 1.6), ("man.", 2.0, 2.3))
    cues = build_cues(w, CueSettings(max_units=8))
    assert all(len(c.text.split()) > 1 for c in cues)
    assert cues[-1].text.endswith("man.")


def test_split_translation_keeps_words_and_latin_names_whole():
    pieces = split_translation("这几年我最开心的事情之一就是认识了Mary Smith。", [58, 16], "zh")
    assert len(pieces) == 2 and "Mary Smith" in pieces[1]
    pieces = split_translation("这个项目还要两个星期，你知道吗？", [45, 9], "zh")
    assert pieces[0].endswith("两个星期")
    pieces = split_translation("那位演员Jean-Luc Picard演得非常好。", [60, 25], "zh")
    assert "".join(pieces).count("Jean-Luc Picard") == 1 and not any(p.startswith("Picard") for p in pieces)
    assert split_translation("是的。", [5, 5], "zh") == ["是的。", "是的。"]  # too short to split


def test_sentence_groups_follow_sentence_ends():
    from jianjian.subs import Cue
    cues = [Cue(1, 0, 1, "en", "It was one of my"), Cue(2, 1, 2, "en", "favourite days."),
            Cue(3, 2.1, 3, "en", "Also, my name is Sam.")]
    assert [[c.id for c in g] for g in sentence_groups(cues)] == [[1, 2], [3]]
