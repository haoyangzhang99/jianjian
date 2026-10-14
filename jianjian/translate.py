"""Local subtitle translation (zh <-> en) with an MLX language model on Apple Silicon.

Lines are translated in small numbered batches with a little preceding context, which keeps
terminology consistent. Any line the model drops or garbles is retried on its own; if that
still fails, the cue keeps an empty translation and is listed in the report.
"""
from __future__ import annotations

import json
import re
import time
from typing import Dict, List, Optional, Sequence

from .subs import Cue, cjk_ratio, is_cjk, to_simplified
from .util import log

DEFAULT_MODELS = {
    "large": "mlx-community/Qwen2.5-7B-Instruct-4bit",   # >= 16 GB RAM
    "small": "mlx-community/Qwen2.5-1.5B-Instruct-4bit", # < 16 GB RAM (3B is not Apache-2.0)
}

SYSTEM = {
    "en": ("You are a professional subtitle translator for a Chinese podcast. Translate each numbered "
           "Chinese subtitle line into natural, concise spoken English suitable for on-screen subtitles. "
           "Translate meaning, not word by word. Keep names, product names and technical terms accurate; "
           "keep English words that already appear. {glossary}"
           "Each numbered line is one sentence of speech: translate every line on its own and never move "
           "words between lines. "
           "Reply with exactly one line per input line, formatted as '<number>. <translation>', using the same "
           "numbers, and nothing else."),
    "zh": ("你是专业的播客字幕译者。把每一行编号的英文字幕翻译成自然、简洁、口语化的简体中文字幕。"
           "按意思翻译，不要逐字直译。人名、产品名和专业术语要准确，常见英文术语可以保留英文。{glossary}"
           "每个编号行是一句话：每行只翻译该行自己的内容，不要把其他行的内容挪进来。"
           "每个输入行只输出一行，格式为“<编号>. <译文>”，编号保持一致，不要输出任何其他内容。"),
}

_LINE_RE = re.compile(r"^\s*(\d+)\s*[\.\)、:：]\s*(.*?)\s*$")


class Translator:
    def __init__(self, model_id: str, glossary: Optional[Dict[str, str]] = None):
        from mlx_lm import load
        t0 = time.time()
        log(f"loading translation model {model_id} ...")
        self.model, self.tokenizer = load(model_id)
        self.model_id = model_id
        log(f"translation model ready in {time.time() - t0:.1f}s")
        self.glossary = glossary or {}

    def _gloss(self, target: str) -> str:
        if not self.glossary:
            return ""
        pairs = "; ".join(f"{k} = {v}" for k, v in self.glossary.items())
        return (f"Use this glossary: {pairs}. " if target == "en" else f"请使用以下术语表：{pairs}。")

    def _chat(self, system: str, user: str, max_tokens: int) -> str:
        from mlx_lm import generate
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        prompt = self.tokenizer.apply_chat_template(msgs, add_generation_prompt=True)
        return generate(self.model, self.tokenizer, prompt=prompt, max_tokens=max_tokens, verbose=False)

    def translate_batch(self, lines: Sequence[str], context: Sequence[str], target: str,
                        after: Sequence[str] = ()) -> List[Optional[str]]:
        system = SYSTEM[target].format(glossary=self._gloss(target))
        ctx, nxt = "\n".join(context), "\n".join(after)
        numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(lines))
        if target == "en":
            user = (f"Previous lines for context (do not translate):\n{ctx}\n\n" if ctx else "") + \
                   (f"Following lines for context (do not translate):\n{nxt}\n\n" if nxt else "") + \
                   f"Translate these {len(lines)} lines:\n{numbered}"
        else:
            user = (f"上文（仅供参考，不要翻译）：\n{ctx}\n\n" if ctx else "") + \
                   (f"下文（仅供参考，不要翻译）：\n{nxt}\n\n" if nxt else "") + f"翻译以下{len(lines)}行：\n{numbered}"
        out = self._chat(system, user, max_tokens=64 + 60 * len(lines))
        res: List[Optional[str]] = [None] * len(lines)
        for line in out.splitlines():
            m = _LINE_RE.match(line)
            if m:
                i = int(m.group(1)) - 1
                if 0 <= i < len(lines) and m.group(2):
                    res[i] = m.group(2)
        return res

    def translate_one(self, line: str, target: str, before: Sequence[str] = (),
                      after: Sequence[str] = ()) -> Optional[str]:
        r = self.translate_batch([line], before, target, after)
        return r[0]


def _cjk_count(text: str) -> int:
    return sum(1 for c in text if is_cjk(c))


def _valid(src: str, out: Optional[str], target: str, prev: Optional[str] = None) -> bool:
    if not out:
        return False
    if target == "en" and cjk_ratio(out) > 0.3:
        return False
    if target == "zh" and cjk_ratio(out) < 0.2 and cjk_ratio(src) < 0.2 and len(out) > 12:
        return False
    # Far longer than the source, or the same as the line before: the model pulled in text from
    # neighbouring lines (an English word is ~1.5-2 Chinese characters).
    if target == "zh" and _cjk_count(out) > 2.0 * len(src.split()) + 5:
        return False
    if target == "en" and len(out.split()) > 1.2 * _cjk_count(src) + 6:
        return False
    if prev and out.strip() == prev.strip():
        return False
    return True


SENTENCE_END = tuple("。！？!?….")
BREAK_AFTER = set("，。！？、；：,;:!?.")


def sentence_groups(cues: Sequence[Cue], max_cues: int = 4, max_gap: float = 1.5) -> List[List[Cue]]:
    """Consecutive cues that make up one sentence (cues are often partial sentences)."""
    groups: List[List[Cue]] = []
    cur: List[Cue] = []
    for c in cues:
        if cur and (c.start - cur[-1].end > max_gap or c.lang != cur[-1].lang):
            groups.append(cur)
            cur = []
        cur.append(c)
        if c.text.rstrip().endswith(SENTENCE_END) or len(cur) >= max_cues:
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    return groups


def _join(texts: Sequence[str], lang: str) -> str:
    return ("" if lang == "zh" else " ").join(t.strip() for t in texts)


def _tokens(text: str, target: str) -> List[str]:
    """Units a translation may be split between: words (jieba for Chinese, if installed)."""
    if target != "zh":
        return re.findall(r"\S+\s*", text)
    try:
        import logging
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            import jieba
        jieba.setLogLevel(logging.WARNING)
        return list(jieba.cut(text))
    except ImportError:
        return list(text)


def _latin(tok: str) -> bool:
    """Part of a Latin-script name/term (letters, digits, spaces, hyphens, apostrophes)."""
    return bool(tok) and tok.isascii() and all(ch.isalnum() or ch in " -'&" for ch in tok)


def split_translation(text: str, weights: Sequence[float], target: str) -> List[str]:
    """Split a sentence translation over n cues in proportion to their source lengths: only between
    words, never inside a Latin name, and preferably right after punctuation."""
    n = len(weights)
    text = text.strip()
    if n == 1:
        return [text]
    toks = _tokens(text, target)
    L = len(toks)
    pos = [0]
    for t in toks:
        pos.append(pos[-1] + len(t))
    chars = pos[-1]
    if chars < (4 if target == "zh" else 8) * n or L < n:
        return [text] * n  # too short to split well: show the whole sentence for the group
    total = float(sum(weights)) or 1.0
    bonus = 0.3 * chars / n  # how far we'll move a cut to land on punctuation

    def allowed(j):
        if _latin(toks[j - 1]) and _latin(toks[j]) and target == "zh":
            return False
        return toks[j].strip() not in BREAK_AFTER  # a piece never starts with punctuation

    def has_text(a, b):
        return any(t.strip() and t.strip() not in BREAK_AFTER for t in toks[a:b])

    cuts, prev, acc = [], 0, 0.0
    for k, w in enumerate(weights[:-1]):
        acc += w
        ideal = chars * acc / total
        hi = L - (n - 1 - k)
        best = None
        for j in range(prev + 1, hi + 1):
            if not allowed(j) or not has_text(prev, j):
                continue
            score = abs(pos[j] - ideal) - (bonus if toks[j - 1].strip()[-1:] in BREAK_AFTER else 0)
            if best is None or score < best[0]:
                best = (score, j)
        if best is None:
            return [text] * n
        cuts.append(best[1])
        prev = best[1]
    if not has_text(prev, L):
        return [text] * n
    out, a = [], 0
    for j in cuts + [L]:
        piece = "".join(toks[a:j]).strip()
        out.append(piece.rstrip("，、；：,;:") if j < L else piece)
        a = j
    return out


def translate_cues(cues: Sequence[Cue], model_id: str, batch: int = 1, context: int = 3,
                   glossary: Optional[Dict[str, str]] = None) -> dict:
    """Translate whole sentences (groups of cues), then split each translation back over its cues.

    Tested on a 15-min episode: translating cue by cue, or several numbered sentences per request,
    let the model shift text into a neighbouring line (and every later line of the batch slid by
    one). One sentence per request, with the sentences around it as context, avoids that and costs
    ~0.4 s per sentence with Qwen2.5-7B on Apple Silicon."""
    tr = Translator(model_id, glossary)
    t0 = time.time()
    failed: List[int] = []
    retried = 0
    for target in ("en", "zh"):
        src_lang = "zh" if target == "en" else "en"
        todo = [c for c in cues if c.lang == src_lang and not c.translation]
        groups = sentence_groups(todo)
        texts = [_join([c.text for c in g], src_lang) for g in groups]
        results: List[Optional[str]] = [None] * len(groups)
        for bi in range(0, len(groups), batch):
            idx = list(range(bi, min(bi + batch, len(groups))))
            ctx = texts[max(0, bi - context):bi]
            res = tr.translate_batch([texts[i] for i in idx], ctx, target,
                                     after=texts[idx[-1] + 1:idx[-1] + 2])
            for i, r in zip(idx, res):
                prev_src = texts[i - 1] if i > 0 else None
                prev = results[i - 1] if i > 0 and prev_src != texts[i] else None
                if not _valid(texts[i], r, target, prev):
                    retried += 1
                    r = tr.translate_one(texts[i], target, before=texts[max(0, i - 2):i],
                                         after=texts[i + 1:i + 2])
                if _valid(texts[i], r, target, prev):
                    results[i] = to_simplified(r) if target == "zh" else r.strip()
            if (idx[-1] + 1) % 25 < batch or idx[-1] + 1 == len(groups):
                log(f"  translated {idx[-1] + 1}/{len(groups)} sentences -> {target} ({time.time() - t0:.0f}s)")
        for g, r in zip(groups, results):
            if not r:
                failed += [c.id for c in g]
                continue
            pieces = split_translation(r, [len(c.text) for c in g], target)
            for c, piece in zip(g, pieces):
                c.translation = piece
    log(f"translation done in {time.time() - t0:.0f}s; {retried} sentences retried one by one, "
        f"{len(failed)} lines failed")
    return {"model": model_id, "seconds": round(time.time() - t0, 1), "retried": retried,
            "failed_ids": failed}


def apply_translation_file(cues: Sequence[Cue], path: str) -> int:
    """Import translations (e.g. written or corrected by your coding agent).

    Accepts either {"<cue id>": "translation", ...} or a list of {"id":..,"translation":..}.
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        data = {str(d["id"]): d.get("translation", "") for d in data}
    n = 0
    for c in cues:
        t = data.get(str(c.id))
        if t:
            c.translation = t
            n += 1
    return n
