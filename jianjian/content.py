"""Content-cut suggestions and B-roll markers, for review.

Pause and filler cuts tighten delivery; editors also remove whole stretches of *content*: the
preamble before the show starts, talk about the recording itself, logistics ("let's start"),
word searches, runs of back-and-forth "yeah"s, abandoned and restarted phrases, and an unfinished
ending. These are judgement calls, so they are only suggested: each becomes a candidate in
fillers.json with kind "content", a reason and cut=false, and a reviewer (person or agent) decides.

B-roll markers point at places where a speaker asks for something to be shown ("we should put
the clip here"), so the editor can insert it; jianjian can't source footage itself.
"""
from __future__ import annotations

import re
from typing import Dict, List, Sequence

from .fillers import HESITATIONS, norm

END = (".", "?", "!", "。", "？", "！")
BACKCHANNEL = {"yeah", "yes", "yep", "yup", "right", "okay", "ok", "mm", "mmhmm", "hmm", "uhhuh", "sure",
               "exactly", "totally", "true", "cool", "nice", "oh", "wow", "uh", "um", "对", "嗯", "好", "是"}
GREETING = re.compile(r"^(hi|hello|hey|welcome|good (morning|evening|afternoon))\b|大家好|欢迎", re.I)
# only unmistakable talk about the call itself: "recording" or "delete this part" alone also occur
# in normal content ("before recording this", a joke about deleting a bad take)
META = re.compile(r"\b(is (it|this) (recording|being recorded)|are we recording|"
                  r"(this|the) (meeting|call) is being recorded|can you (hear|see) me|hear me (okay|ok)|"
                  r"(you're|you are|i'm|i am) (on )?mute(d)?|share (my|your) screen)\b", re.I)
LOGISTICS = re.compile(r"\b(let'?s (start|begin|get started|continue|move on|go on)|"
                       r"how (do|should|shall) we (start|begin)|should we (start|begin)|shall we|"
                       r"are (we|you) ready|where (were|was) (we|i))\b|我们开始|开始吧", re.I)
WORD_SEARCH = re.compile(r"\b(is that how( you say( it)?)?|how do you say|what'?s the word|what do you call( it)?|"
                         r"is that the (right )?word)\s*\??$|怎么说来着", re.I)
BROLL = re.compile(r"\b((put|insert|add|show|play|cut to|have|use) (the|a|that|this|some) "
                   r"(clip|scene|video|picture|photo|image|footage|trailer|screenshot)|"
                   r"(clip|scene|picture|photo|image|footage|screenshot) (here|in here|right here)|"
                   r"we (should|can|could|have to|need to|gotta) (show|play)|let me show you|here'?s the (clip|scene|picture))|"
                   r"放(一)?段|插(入|一段)|配(个|张)?图|这里放", re.I)


def sentences(words: Sequence[dict]) -> List[List[int]]:
    """Word-index lists, split after sentence-ending punctuation."""
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(i)
        t = w["w"].strip()
        if t.endswith(END) and not t.endswith(".."):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def _text(words, ids) -> str:
    return "".join(words[i]["w"] for i in ids).strip()


def _toks(words, ids) -> List[str]:
    return [t for t in (norm(words[i]["w"]) for i in ids) if t]


def suggest(words: Sequence[dict], max_preamble: float = 90.0) -> List[dict]:
    """Content-cut suggestions over a verbatim transcript: [{words: [i, j], reason}]."""
    sents = sentences(words)
    out: List[Dict] = []

    def add(i, j, reason):
        if j >= i:
            out.append({"words": [i, j], "reason": reason})

    # 1) preamble: everything before a greeting near the start ("Hi, everyone")
    for s in sents:
        if words[s[0]]["s"] > max_preamble:
            break
        if GREETING.search(_text(words, s)) and s[0] > 0:
            add(0, s[0] - 1, "preamble before the greeting")
            break
    pre_end = out[0]["words"][1] if out else -1
    for k, s in enumerate(sents):
        if s[-1] <= pre_end:
            continue
        text, toks = _text(words, s), _toks(words, s)
        # 2) talk about the recording itself
        if META.search(text):
            add(s[0], s[-1], "talk about the recording")
        # 3) logistics and transitions, only when the sentence is short
        elif LOGISTICS.search(text) and len(toks) <= 12:
            add(s[0], s[-1], "logistics / transition")
        # 4) a word search and the echoes that answer it ("Is that how? Suburban. Yeah. Suburban.")
        elif WORD_SEARCH.search(text):
            j = s[-1]
            for nxt in sents[k + 1:k + 3]:
                if len(_toks(words, nxt)) <= 3:
                    j = nxt[-1]
                else:
                    break
            add(s[0], j, "word search")
    # 5) runs of back-and-forth: 4+ consecutive short sentences that are mostly "yeah / right / ..."
    run: List[List[int]] = []
    for s in sents + [[]]:
        toks = _toks(words, s) if s else []
        if s and toks and len(toks) <= 4 and sum(t in BACKCHANNEL for t in toks) >= 0.7 * len(toks):
            run.append(s)
            continue
        if len(run) >= 4:
            add(run[0][0], run[-1][-1], "back-and-forth")
        run = []
    # 6) restarts: a phrase begun, abandoned and said again ("you have to be, uh, you have to have").
    #    A real restart has a break in the abandoned part (a comma, "...", a dash or an uh) and no
    #    sentence end in it; without that test, plain repetition like "it starts
    #    *at the* station and ends *at the* airport" was suggested.
    toks = [norm(w["w"]) for w in words]
    idx = [i for i, t in enumerate(toks) if t and t not in HESITATIONS]
    ft = [toks[i] for i in idx]

    def broken_off(i0, i1):  # words i0..i1-1 are the abandoned attempt
        if any(words[k]["w"].strip().endswith(END) and not words[k]["w"].strip().endswith("..")
               for k in range(i0, i1)):
            return False
        return any(words[k]["w"].strip().endswith((",", "...", "…", "-", "—")) or norm(words[k]["w"]) in HESITATIONS
                   for k in range(i0, i1))

    p, n = 0, len(ft)
    while p < n:
        hit = None
        for size in (4, 3, 2):
            a = ft[p:p + size]
            if len(a) < size or (size == 2 and all(len(t) <= 3 for t in a)):
                continue
            for gap in range(1, 6):  # the abandoned words between the two attempts
                q = p + size + gap
                if ft[q:q + size] == a and words[idx[q]]["s"] - words[idx[p]]["s"] < 8.0 \
                        and broken_off(idx[p], idx[q]):
                    hit = (p, q)
                    break
            if hit:
                break
        if hit:
            add(idx[hit[0]], idx[hit[1]] - 1, "restart")
            p = hit[1]
        else:
            p += 1
    # 7) an unfinished ending: words after the last complete sentence
    if sents and not _text(words, sents[-1]).endswith(END):
        add(sents[-1][0], sents[-1][-1], "unfinished ending")
    elif sents and _text(words, sents[-1]).endswith(("...", "…")):
        add(sents[-1][0], sents[-1][-1], "unfinished ending")
    return sorted(out, key=lambda c: c["words"][0])


def broll_markers(words: Sequence[dict], *more: Sequence[dict]) -> List[dict]:
    """Places where a speaker asks for something to be shown: [{start, end, text}]. Pass every
    transcript there is (clean and verbatim): each can skip a sentence the other has, and on a
    test episode the clean one dropped a request to show a clip."""
    out: List[Dict] = []
    for ws in (words, *more):
        for s in sentences(ws):
            text = _text(ws, s)
            t0, t1 = ws[s[0]]["s"], ws[s[-1]]["e"]
            if BROLL.search(text) and not any(m["start"] < t1 and t0 < m["end"] for m in out):
                out.append({"start": round(t0, 3), "end": round(t1, 3), "text": text})
    return sorted(out, key=lambda m: m["start"])
