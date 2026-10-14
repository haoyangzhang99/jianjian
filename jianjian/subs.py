"""Subtitle cues: build from word timestamps, remap onto the edited timeline, write SRT/ASS."""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Sequence

from .cuts import TimeMap

STRONG_END = tuple("。！？!?…")
_ABBREV_RE = re.compile(r"^(?:[A-Za-z]\.)+$|^(?:mr|mrs|ms|dr|st|vs|etc|jr|sr|no)\.$", re.I)


def _ends_sentence(word: str) -> bool:
    """True for words like "planned." / "好。" / "right?" — but not "U.S." or "Mr."."""
    if word.endswith(STRONG_END):
        return True
    return word.endswith(".") and not word.endswith("..") and not _ABBREV_RE.match(word)
WEAK_END = tuple("，、,；;：:")
TRAILING_STRIP = "，。、；：,.;: "

# Whisper hallucinations that commonly appear in silence / music.
HALLUCINATION_PATTERNS = [
    r"字幕(由|提供|製作|制作)", r"Amara\.org", r"请不吝点赞", r"訂閱", r"订阅.*(转发|打赏)",
    r"^(谢谢|謝謝)(观看|觀看|大家)[。!！]*$", r"^[Tt]hanks? (you )?for watching", r"^[Ss]ubtitles? by",
    r"明镜与点点", r"^\W*$",
]
_HALLU_RE = re.compile("|".join(HALLUCINATION_PATTERNS))


def is_cjk(ch: str) -> bool:
    o = ord(ch)
    return (0x4E00 <= o <= 0x9FFF) or (0x3400 <= o <= 0x4DBF) or (0xF900 <= o <= 0xFAFF) \
        or (0x20000 <= o <= 0x2A6DF)


def visual_units(text: str) -> float:
    """Approximate rendered width: CJK = 1, everything else = 0.5."""
    return sum(1.0 if is_cjk(c) or 0x3000 <= ord(c) <= 0x303F or 0xFF00 <= ord(c) <= 0xFFEF else 0.5
               for c in text)


def cjk_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha() or is_cjk(c)]
    if not letters:
        return 0.0
    return sum(1 for c in letters if is_cjk(c)) / len(letters)


def detect_cue_lang(text: str) -> str:
    return "zh" if cjk_ratio(text) >= 0.3 else "en"


_t2s = None


def to_simplified(text: str) -> str:
    global _t2s
    if _t2s is None:
        try:
            from opencc import OpenCC  # opencc-python-reimplemented
            _t2s = OpenCC("t2s")
        except Exception:
            _t2s = False
    return _t2s.convert(text) if _t2s else text


def clean_text(text: str, lang: str) -> str:
    t = re.sub(r"\s+", " ", text).strip()
    if lang == "zh":
        t = to_simplified(t)
        # no space between two CJK characters
        t = re.sub(r"(?<=[\u4e00-\u9fff，。！？、])\s+(?=[\u4e00-\u9fff，。！？、])", "", t)
        t = re.sub(r"(?<=[，。！？、；：])\s+", "", t)
        t = t.rstrip(TRAILING_STRIP)
    else:
        t = t.rstrip(",;: ")
    return t


@dataclass
class Cue:
    id: int
    start: float          # source seconds
    end: float
    lang: str             # language of the spoken text: zh / en
    text: str             # spoken text (cleaned)
    translation: str = ""
    tl_start: Optional[float] = None  # edited timeline seconds
    tl_end: Optional[float] = None

    @property
    def zh(self) -> str:
        return self.text if self.lang == "zh" else self.translation

    @property
    def en(self) -> str:
        return self.text if self.lang == "en" else self.translation

    def to_dict(self):
        return asdict(self)


@dataclass
class CueSettings:
    max_units: float = 20.0     # ~20 CJK chars per cue
    soft_units: float = 12.0    # break at a comma once we're past this
    latin_scale: float = 1.6    # English cues may be longer (~64 chars): the English line is
                                # rendered smaller, and fewer mid-sentence splits help translation
    max_gap: float = 0.6        # break when words are this far apart
    max_dur: float = 7.0
    min_dur: float = 0.8
    hold: float = 0.25          # keep text on screen a bit after the last word
    merge_gap: float = 2.0      # max pause across which a one/two-word scrap joins a neighbour
                                # (pause removal shortens such gaps on the timeline anyway)


def _merge_fragments(groups, cs, units, scale):
    """Fold one- or two-word scraps ("man.", "All", "though?") into a neighbouring cue: on their own
    they flash by and can't be translated sensibly. Merges into the previous cue if that one doesn't
    end a sentence, otherwise into the next one; only across short gaps, up to 1.3x the size limit."""
    def tiny(g):
        return len(g) <= 2 and units(g) < 5

    def fits(a, b):
        return (b[0]["s"] - a[-1]["e"] <= cs.merge_gap and b[-1]["e"] - a[0]["s"] <= cs.max_dur * 1.5
                and units(a + b) <= cs.max_units * scale(a + b) * 1.3)

    out = []
    for g in groups:
        if out and tiny(g) and not _ends_sentence(out[-1][-1]["w"].strip()) and fits(out[-1], g):
            out[-1] = out[-1] + g
        else:
            out.append(g)
    res = []
    i = 0
    while i < len(out):
        g = out[i]
        if tiny(g) and i + 1 < len(out) and fits(g, out[i + 1]):
            out[i + 1] = g + out[i + 1]
        else:
            res.append(g)
        i += 1
    return res


def build_cues(words: Sequence[dict], cs: CueSettings = CueSettings()) -> List[Cue]:
    groups: List[List[dict]] = []
    cur: List[dict] = []

    def units(ws):
        return visual_units("".join(w["w"] for w in ws).strip())

    def scale(ws):
        return 1.0 if cjk_ratio("".join(w["w"] for w in ws)) >= 0.3 else cs.latin_scale

    for w in words:
        if not w["w"].strip():
            continue
        if cur:
            gap = w["s"] - cur[-1]["e"]
            too_long = units(cur + [w]) > cs.max_units * scale(cur + [w])
            too_slow = w["e"] - cur[0]["s"] > cs.max_dur
            if gap > cs.max_gap or too_long or too_slow:
                groups.append(cur)
                cur = []
        cur.append(w)
        tail = w["w"].strip()
        u = units(cur)
        if _ends_sentence(tail) and u >= 4:
            groups.append(cur)
            cur = []
        elif tail.endswith(WEAK_END) and u >= cs.soft_units * scale(cur):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    groups = _merge_fragments(groups, cs, units, scale)

    cues: List[Cue] = []
    for g in groups:
        raw = "".join(w["w"] for w in g)
        lang = detect_cue_lang(raw)
        text = clean_text(raw, lang)
        if not text or _HALLU_RE.search(text):
            continue
        cues.append(Cue(id=len(cues) + 1, start=float(g[0]["s"]), end=float(g[-1]["e"]), lang=lang, text=text))

    # timing polish: hold + minimum duration, never overlapping the next cue
    for i, c in enumerate(cues):
        nxt = cues[i + 1].start if i + 1 < len(cues) else c.end + 10
        c.end = min(max(c.end + cs.hold, c.start + cs.min_dur), nxt - 0.04)
        c.end = max(c.end, c.start + 0.2)
    return cues


def remap(cues: Sequence[Cue], tmap: TimeMap, min_dur: float = 0.3) -> List[Cue]:
    out: List[Cue] = []
    for c in cues:
        a, b = tmap.to_timeline(c.start), tmap.to_timeline(c.end)
        if b - a < 0.05:
            continue
        c.tl_start, c.tl_end = a, b
        out.append(c)
    # resolve tiny overlaps created by snapping, enforce min duration where room allows
    for i, c in enumerate(out):
        nxt = out[i + 1].tl_start if i + 1 < len(out) else c.tl_end + 10
        if c.tl_end - c.tl_start < min_dur:
            c.tl_end = min(c.tl_start + min_dur, nxt - 0.02)
        if c.tl_end > nxt - 0.02:
            c.tl_end = max(nxt - 0.02, c.tl_start + 0.1)
    return out


# ---------- writers ----------

def _srt_ts(t: float) -> str:
    t = max(t, 0.0)
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(path: str, cues: Sequence[Cue], which: str, timeline: bool = True) -> int:
    """which: 'zh' | 'en' | 'bi' | 'src'"""
    n = 0
    with open(path, "w", encoding="utf-8") as f:
        for c in cues:
            if which == "zh":
                txt = c.zh
            elif which == "en":
                txt = c.en
            elif which == "src":
                txt = c.text
            else:
                txt = "\n".join(x for x in (c.zh, c.en) if x)
            if not txt:
                continue
            a, b = (c.tl_start, c.tl_end) if timeline else (c.start, c.end)
            n += 1
            f.write(f"{n}\n{_srt_ts(a)} --> {_srt_ts(b)}\n{txt}\n\n")
    return n


def _ass_ts(t: float) -> str:
    cs = int(round(max(t, 0.0) * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def _ass_escape(t: str) -> str:
    return t.replace("\\", "＼").replace("{", "（").replace("}", "）").replace("\n", " ")


def write_ass(path: str, cues: Sequence[Cue], width: int, height: int, font: str,
              order=("zh", "en"), cards: Sequence[dict] = ()) -> None:
    k = height / 1080.0
    fs_main, fs_sub = round(54 * k), round(38 * k)
    outline = max(2, round(3 * k))
    margin_v = round(48 * k)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Bi,{font},{fs_main},&H00FFFFFF,&H000000FF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,{outline},1,2,{round(80*k)},{round(80*k)},{margin_v},1
Style: Card,{font},{round(34*k)},&H00FFFFFF,&H000000FF,&H60000000,&H60000000,0,0,0,0,100,100,0,0,3,{round(14*k)},0,9,{round(60*k)},{round(60*k)},{round(60*k)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(header)
        for c in cues:
            parts = []
            for i, which in enumerate(order):
                t = c.zh if which == "zh" else c.en
                if not t:
                    continue
                t = _ass_escape(t)
                if i == 0:
                    parts.append(t)
                else:
                    parts.append("{\\fs%d\\c&H00E6E6E6&}%s" % (fs_sub, t))
            if not parts:
                continue
            body = "\\N".join(parts)
            f.write("Dialogue: 0,%s,%s,Bi,,0,0,0,,%s\n" % (_ass_ts(c.tl_start), _ass_ts(c.tl_end), body))
        for cd in cards:
            text = "{\\b1}%s{\\b0}" % _ass_escape(cd["title"])
            if cd["text"]:
                text += "\\N{\\fs%d}%s" % (round(28 * k), _ass_escape(cd["text"]))
            f.write("Dialogue: 1,%s,%s,Card,,%d,0,0,,%s\n" % (_ass_ts(cd["tl_start"]), _ass_ts(cd["tl_end"]),
                                                             round(width * 0.58), text))
