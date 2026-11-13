---
name: jianjian
description: Edit a podcast/meeting video on this Mac — remove long pauses, add synchronized Chinese+English subtitles, optional explainer cards, create an editable Kdenlive project (or a Jianying Pro 剪映专业版 draft) and export an MP4. Use when the user asks to edit/cut/subtitle a podcast or episode, "剪播客", "去掉停顿", "加双语字幕", or to make a Kdenlive or Jianying project from a recording, including short videos for Douyin (抖音), Xiaohongshu (小红书) or Shorts, a scripted solo talk with retakes to remove, and explainer visuals over the talk or filling the screen with the speaker in a small window. Also use it to split a finished episode into parts or pick and cut highlights ("切片", "高光", "clips", "highlights") for Douyin, TikTok, Reels or Shorts.
---

# Podcast → Kdenlive / Jianying pipeline (jianjian)

Everything runs locally. Tool: the `jianjian` command (`setup.sh` links it into `~/.local/bin`); call it
`JIANJIAN` below. If it isn't on the PATH, it is `bin/jianjian` in the jianjian repo — this skill folder is a
symlink into that repo, so the repo is the parent of this file's real location. If `JIANJIAN doctor` says it
isn't set up, run `bash <repo>/setup.sh` first.

## 0. Before every new video: ask which pause preset and what to make

There is no default pace. Before you start editing a new video, show the user this table and ask
which preset to use, even if they already said "remove pauses". The only exceptions are when they
named a preset or gave exact numbers for this video. Reruns of the same video keep the preset
already chosen.

| Preset | Pauses longer than | become | Best for |
|---|---|---|---|
| `shorts` | 0.5 s | 0.25 s | Shorts / Reels / TikTok, one speaker, fastest pace |
| `youtube` | 0.6 s | 0.3 s | YouTube talking head, one speaker |
| `conversation` | 0.6 s | 0.35 s | YouTube conversation, 2+ speakers (keeps turn-taking natural) |
| `podcast` | 0.75 s | 0.4 s | Podcast / long-form listening, relaxed pace |
| `interview` | 1.0 s | 0.6 s | Slow, reflective interview; keeps thinking pauses |

If unsure, suggest one: `conversation` for a two-person YouTube show, `podcast` for audio-first.
`jianjian presets` prints the list. Exact values: `--max-pause S --keep-pause S`.

In the same message, ask what they want out of it: "直接生成一个 MP4，还是在视频编辑器里打开、方便自己手动调整？"
(an MP4 ready to post, or a Kdenlive / Jianying project to adjust by hand). Skip the question only
when they already said, e.g. "只要 MP4", "open it in Kdenlive", "做个剪映草稿". MP4 only →
`--no-draft`; editor → the default (the project, plus an MP4 to compare against). Reruns of the
same video keep the answer.

**Scripted solo talk (口播, read from a script):** in the same message, also ask whether they want
to go through the transcript before the cut, and recommend it: "要不要先过一遍逐字稿？我会把你实际说的
每一句列出来，标出重读和疑似读错的地方，你删掉不要的，我再按你改过的稿子剪。推荐这样做。" If they agree,
do §4b before any pause cutting. If they decline, cut only the retakes they point out. Skip the
question when they already asked for the transcript, or said they don't want it.

## 0b. Short-video platforms: plan the first 30 seconds

If the video is for Douyin (抖音), Xiaohongshu (小红书), Kuaishou, WeChat Channels (视频号), Shorts,
Reels or TikTok, suggest this opening structure along with the preset question, and build the
deliverable to it. If the platform isn't clear and the video is short or vertical, ask. These feeds
rank on completion, engagement and share rate, and the opening decides whether people stay.

**Speed: a short-video solo talk (口播) always goes out at 1.2× overall, relative to the raw
recording.** Don't ask; say so with the preset question and in the report. A plain edit or an
overlay edit (`--animations`): add `--speed 1.2`. The small-window layout (§5c): build and render
at 1.0, then speed up the final render (§5c step 7). Plan the length on the sped-up time: a 3:33 cut
is 2:57 at 1.2×. Conversations and podcasts keep their own pace (≤ 1.15, §1); highlights from them
follow their show's rule.

| By | Goal | How |
|---|---|---|
| 0–3 s | **Hook** | One of three: a counter-intuitive claim (反常识); suspense: a striking result without the how (设置悬念); credentials + result, then empathy with the viewer's problem (身份 + 成绩) |
| 15 s | **Deliver value** | The first concrete tip or core insight, so staying feels worth it (值回票价) |
| 30 s | **Show the structure** | Say what the video covers and what the viewer gets, e.g. "今天分享三点：第一…第二…第三…" |

1. Run the edit once with `--cut-fillers` (the transcript is cached for reruns). Read
   `<out>/<name>.original-timeline.srt`.
2. Show the user an opening plan: the line that will open the video and its hook type, the value
   line, the roadmap line (source timestamps for each), and what gets cut to bring them forward:
   greetings, "大家好我是…", setup chatter, warm-up before the point. Content cuts are judgment
   calls, so wait for the user's OK.
3. Apply it: in `<out>/fillers.json`, add `{"words": [i, j], "kind": "restart", "cut": true}` for
   each span to remove (indices into `work/transcript_verbatim.json`), then rerun with
   `--fillers <out>/fillers.json`. If the user didn't ask for filler cuts, set the automatic
   candidates to `"cut": false`.
4. Check the edited timeline (`<out>/<name>.zh.srt` or `.bilingual.srt`, already speed-adjusted):
   hook within the first second, value by 15 s, roadmap by 30 s. Put these three times in your report.
5. If the best hook comes later in the recording, open on it with a cold open:
   `--hook START-END` (source time from `original-timeline.srt`, seconds or m:ss; repeat the flag
   for several spans, played in the given order). Take START and END from the line's cue times so
   the hook starts and ends on whole words; jianjian logs a NOTE when a bound falls inside a word.
   By default the hook plays first and again at its original place (`--hook-mode teaser`, like a
   精彩预告); `--hook-mode move` plays it only at the start. Ask which the user wants: a teaser
   repeats the line, a move takes it out of its context. Pauses and fillers inside the hook stay
   cut, its subtitles appear at 0 s, and the draft, MP4 and checks all follow the new order. If the
   recording has no usable hook, offer to record a 3-second hook line to add in the editor, or
   (weaker) a card at 0 s with the hook as text (`--cards`, see §5). Never claim the structure is
   met when it isn't.

## 1. Map the request to flags

| User says | Flags |
|---|---|
| pause pace | `--preset NAME`: **always ask first**, §0 |
| MP4 or editor project | **ask first** unless they said, §0 (MP4 only: `--no-draft`) |
| for Douyin / 小红书 / Shorts / 短视频 | suggest `--preset shorts` and the 3/15/30 s opening plan (§0b) |
| open on a later line / cold open / 先放高光 | `--hook START-END` (source time; `--hook-mode move` to not repeat it), §0b |
| put this clip / scene / B-roll in / 插入片段 | `--insert AT=CLIP` (source time; plays at normal speed with its own sound), §4 |
| exact numbers ("cut pauses over 1.5 s down to 0.5 s") | `--max-pause 1.5 --keep-pause 0.5` |
| don't cut anything / subtitles only | `--no-cut` |
| remove filler words / uh, um / 去掉嗯啊、口头禅 | `--cut-fillers`, then review (§4) |
| make it faster / speed up / 加速 | `--speed 1.05` (subtle) or `1.1` (brisk); keep conversations ≤ 1.15. A short-video solo talk is always `1.2` (§0b) |
| bilingual subtitles (default) | `--subs bi` |
| Chinese only / English only / no subtitles | `--subs zh` / `--subs en` / `--subs none` |
| the podcast is all Chinese (more accurate) | `--lang zh` (default `auto` handles mixed zh/en speakers) |
| don't burn subtitles into the MP4 | `--no-burn` (add `--soft-subs` for selectable tracks) |
| only the editor project, no export | `--no-render` |
| only the MP4 / 只要 MP4 | `--no-draft` |
| name the project | `--draft-name "..."` |
| for Jianying / 剪映 instead of Kdenlive | `--editor jianying` (default `auto`: Kdenlive, or Jianying when only Jianying is installed) |
| term list for translation | `--glossary terms.txt` (lines `源词 = target`) |
| explainer animation / 演示动画 / show a diagram while I talk | `--animations animations.json` (HyperFrames pages, source time), §5b |
| scripted solo talk (口播) / retakes / 有几句说了两三遍 / give me a transcript to mark | ask whether to go through the marking transcript first and recommend it (§0); then the transcript, their edit, the assembled source, §4b |
| 60-fps recording, or "keep the source frame rate" | `--fps 60` (the default is 30 whatever the source is) |
| visuals fill the screen, speaker in a small window / 人缩到小窗里 | one HyperFrames composition for the whole video, §5c |
| background music / 配乐 / sound effects | §7 |
| split the finished video into parts / pick highlights / 切片 / 高光 | `JIANJIAN clips VIDEO NAME=START-END ...`, §6 |

Default output folder: next to the video, `<name>_edit/`. Never pass paths you haven't checked exist.

## 2. Run

```bash
JIANJIAN edit "/path/to/episode.mp4" [flags]
```
A 60-min episode takes roughly 15–20 min on Apple Silicon (measured: 15-min clip in 4.5 min).
Stages are cached in `<out>/work/`: re-running with different pause/subtitle/card settings skips
transcription. Use `--redo-asr` only if the transcript itself is bad.

## 3. Check and report

Read `<out>/report.md`. Report to the user: edited length and how much was removed, number of
subtitle lines, the editor project (the `.kdenlive` file to open in Kdenlive, or the Jianying draft
name in Jianying's 本地草稿 list), the MP4 path, and
any PROBLEMS lines. For short-video platforms, also give the hook / value / roadmap times (§0b). Exit code 2 means a validation check failed — say which, don't claim success.

## 4. Review filler words (with --cut-fillers)

uh/um and stutter repeats are cut automatically; like / so / you know / I mean / 那个 / 就是 are only
listed. Read `<out>/fillers_review.md` (each candidate in context), then edit `<out>/fillers.json`:
- set `"cut": true` for fillers ("it was, **like**, huge", "that's fine, **you know**") and keep
  meaning ("I **like** this song", "**so** important", "I don't think **so**", "fruit **like** apples");
- set `"cut": false` on a "repeat" that is really two speakers or emphasis;
- add restarts: `{"words": [i, j], "kind": "restart", "cut": true}` (indices into
  `work/transcript_verbatim.json`);
- content suggestions (kind "content", with a reason: preamble before the greeting, talk about the
  recording, logistics, word search, back-and-forth, restart, unfinished ending) are never cut until
  approved. Show the user the list (time, reason, text) and ask before setting `"cut": true`. If
  `editing-style.local.md` exists, propose the kinds the user usually cuts. Reject false restarts:
  lists ("a red shirt or a red hat") and plain repetition ("talking about it"). Each
  approved passage also leaves the subtitles; recheck the Chinese of the lines listed as CHECK;
- B-roll: `report.md` lists insert points where a speaker asks for something to be shown ("put the
  clip here"), with their time in the edit. Tell the user; jianjian can't source the footage. When
  they give you the clip, add `--insert AT=CLIP` with AT = the end of the sentence before the
  request (source time), and cut the request itself ("we should show that clip") as a content cut.
Rerun with `--fillers <out>/fillers.json` (fast: both transcripts are cached). Optionally check with
`.venv/bin/python tools/verify_words.py <out>`: "inside a removed span" must be 0.

## 4b. Scripted solo talk: the marking transcript (recommended default)

A person reading their own script says some sentences two or three times and misreads a few. They
know which take they want; you don't. The recommended way to cut a 口播 is to let them mark a
transcript first and cut from what they kept. Ask before starting (§0); they can decline.

1. **Read the script** (and the visual brief, if there is one) in the video's folder. If you can't
   find one, ask.
2. **Transcribe by pauses**, not only in one pass:
   `.venv/bin/python tools/words_by_pause.py VIDEO -o words.json --lang en`
   A whole-file pass can drop a retake that follows a long pause without a trace (README →
   Pitfalls → Transcription).
3. **Make the transcript:** `.venv/bin/python tools/marking.py make words.json -o transcript.md`
   (`--english` for an English header). One line per sentence or false start: `L012 [0:50] text`.
   Tidy it against the script: split lines the tool joined, put every false start on its own line,
   correct names the recogniser got wrong. Then put a flag after each line's time, and a note on a
   `>` line under it where the flag needs explaining:

   | Flag | Use it for | Suggest |
   |---|---|---|
   | 🔁 | an abandoned take or false start | delete |
   | ✅ | the complete take of a retake | keep |
   | ❓ | two complete takes | they pick; say which you would keep and why |
   | ⚠️ | a wrong word, number or meaning with no retake to replace it | their call; quote the script |
   | 〰️ | a small difference from the script (a plural, a dropped "the") | keep |

   No flag means the line matches the script. Say in your message that you compared transcripts and
   did not listen, list the ⚠️ lines with their times, and ask them to listen to those. Check that
   every sentence of the script has at least one complete take, and say so. When the flags are in,
   copy the file over `transcript.orig.md` again (the base for the diff) and send the path.
4. **They edit the file.** They delete the lines they don't want, delete words inside a line to
   drop just those, and for a ⚠️ line they may record the sentence again and write the clip's path
   under the line. Don't start cutting until they send it back.
5. **Read their edit:** `.venv/bin/python tools/marking.py diff transcript.orig.md transcript.md`.
   Transcribe each re-recorded clip to see which line it replaces: one clip can hold several
   sentences.
6. **Assemble the source:** write a plan and run
   `.venv/bin/python tools/assemble_takes.py plan.json assembled.mov` (`--dry-run` first). A `drop`
   for each deleted line or run of lines, `clip` + `say` where a re-recorded sentence goes in, `cut`
   for a single word. It places the cuts on the level envelope, not on word times, and levels each
   clip to the recording's speech.
7. **Check word by word.** Transcribe `assembled.mov` with `words_by_pause.py` and diff it against
   the lines they kept (difflib over normalised words). Single-word noise is expected; look at
   every difference that sits at a cut. Typical faults: half a word of the dropped take left in,
   the last word before a cut gone, a false start that neither transcript had shown. Fix the plan
   and assemble again. After a single-word `cut`, transcribe just that sentence on its own. A word
   glued to its neighbours, with no dip on either side, can't be cut cleanly: keep it and tell them.
8. **Cut the pauses:** `JIANJIAN edit assembled.mov --preset … --no-draft --no-burn` with the
   preset and speed agreed in §0 (`--speed 1.2` for a short-video talk). Write the subtitles from
   the lines they kept (§5), not from the automatic cues.
9. **Report** the final length against the script's target, anything you could not cut and why, and
   that nobody has listened to the cuts yet: name the sentence at each replaced clip and each
   single-word cut so they can listen to those first. If it runs over, say by how much and what
   could still go (tighter pauses); don't cut arguments to make the target.

A foreign-language quote inside the talk (an English quote in a Chinese video) may be missing or
looped in the transcript: transcribe that span in its own language (`--lang`) and use those words.

Small jobs (two or three retakes, nothing re-recorded) can skip the assembly: add
`{"words": [i, j], "kind": "restart", "cut": true}` per deleted span to `<out>/fillers.json`
(indices into `work/transcript_verbatim.json`), set the automatic candidates to `"cut": false`
unless they asked for filler cuts, and rerun with `--fillers`. Check each cut the same way: a word's
end time is often too early, so a syllable of the dropped take survives. Extend that word's `e` in
both `work/transcript.json` and `work/transcript_verbatim.json` (save `*.orig.json` copies first,
and never `--redo-asr` afterwards, or the patch is lost), then rerun.

## 5. Review subtitles (recommended before publishing)

Do this after the filler review (§4), once the cut is final, so subtitle fixes aren't redone after
fillers are removed.

The automatic subtitles are well timed but not publish-ready: expect wrong proper names (film
titles, people, brands), a few mishearings, and about 1 in 10 lines mistranslated. Review all of
`cues.json`, then rerun with `--cues` as below. That rerun only rebuilds the draft and MP4, about
2 min for 15 min of video. Don't put names into the transcription prompt: it made Whisper loop.


- **Translations**: read `<out>/cues.json` (fields: id, lang, text, translation). Fix weak lines and
  write `{"<id>": "better translation", ...}` to `<out>/fixes.json`, then rerun with
  `--translations <out>/fixes.json` (fast: transcription is cached).
- **Transcript typos / names**: in a copy of cues.json, fix `text` (and its `translation`) and rerun
  with `--cues reviewed.json`. Translations you write there are kept; lines with an empty
  `translation` are translated again locally. Don't change ids or timings.
- **Explainer cards** (secondary feature): read the transcript (`<out>/<name>.original-timeline.srt`),
  pick a few terms a general audience wouldn't know, and write `cards.json`:
  `[{"at": <source seconds>, "duration": 6, "title": "术语", "text": "一句话解释"}]` then rerun with
  `--cards cards.json`. Keep it to a handful; cards appear top-right and are editable text in the editor (a second subtitle layer in Kdenlive).

## 5b. Explainer animations (`--animations`)

Animations play over the talk while it continues (unlike `--insert`): a panel, a diagram or a list
that builds up step by step on the words that introduce each step. Each one is an HTML page rendered
by [HyperFrames](https://github.com/heygen-com/hyperframes) (Apache-2.0; needs Node.js 22+, runs
locally via `npx`) to a transparent clip. It goes on an `animations` track (V2 in Kdenlive) above the recording in
the project (move, resize or delete it there) and is overlaid in the MP4 under the subtitles.

1. Read the transcript and pick a few moments a picture would explain (a concept, a structure, a
   list, numbers). Propose them to the user before building; keep it to a handful per episode.
2. For each one, take word times from `<out>/work/transcript.json` (`words`: `w`, `s`, `e`, source
   seconds): `from` = the first word of the passage, `to` = after its last word, and a beat for each
   word that should bring in the next step.
3. Start from `skill/animations/steps.html` (a title and steps, each on its beat). Copy it next to
   `animations.json`, or write a new page following HyperFrames' rules (a root element with
   `data-composition-id`, a paused GSAP timeline registered on `window.__timelines`, seekable
   animation only, no `Math.random` / `Date.now`; `npx hyperframes docs` explains more):
   ```json
   [{"html": "steps.html", "from": 372.6, "to": 411.0,
     "beats": {"red": 378.91, "white": 381.53},
     "data": {"title": "红事 · 白事",
              "steps": [{"text": "红事 = 婚礼", "beat": "red"}, {"text": "白事 = 葬礼", "beat": "white"}]}}]
   ```
   jianjian sets the page's duration and size and defines `window.jianjian` before the page's own
   scripts: `duration`, `width`, `height`, `fps`, `beats` (seconds from the animation's start, after
   cuts and `--speed`), `words` (`w`, `t`, `end`, same clock) and `data`. Write
   `data-duration="auto"` where a clip should last the whole animation. Files the page uses go in an
   `assets/` folder next to it.
4. Keep the page's background transparent and the drawing clear of every face and of the
   subtitles at the bottom. Look at a frame of the video first: the template's default box in the
   top right suits one speaker filling the frame, but on a side-by-side video call it covers the
   second speaker; use `"layout": "band"` in `data` there (a strip in the empty band above the picture). Declare every font with `@font-face`
   (a system font: `src: local("PingFang SC")`), or HyperFrames refuses the render.
5. Rerun with `--animations animations.json`. Rendered clips are cached in `<out>/animations/` (the
   draft uses those files, so keep the folder); only changed pages are rendered again, into new
   files, so older drafts keep theirs. Delete clips no draft uses any more (about 140 MB per 30 s). Check the
   MP4 at each animation, and look at one frame before showing the user (`ffmpeg -ss T -i <mp4>
   -frames:v 1 frame.png`).
6. **Vertical talk with a brief:** if a production brief lists the cues, follow its anchors, but
   look at the frame first: on a 9:16 head-and-shoulders shot the only empty space is a band above
   the head (about y 150–640). Before building many cues, ask which layout the user wants: aids in
   that band over the full-frame speaker (this section), or visuals filling the screen with the
   speaker in a small window (§5c), which suits knowledge videos on Douyin. If they point to a
   reference video they can't share as a link, ask for a screen recording.
7. **QA:** for every cue, take frames at its start, at each beat + 0.45 s, at its middle and its
   last frame; tile them into contact sheets (`ffmpeg ... -vf tile=4x3`) and look at all of them.
   Typical faults: a label hidden under a bubble, a highlight that arrives at the end of the cue,
   labels overlapping while cards move. Fix, rerender, look again.

## 5c. Full-screen visuals with the speaker in a small window

Here the visuals are the picture: the speaker fills the frame for the hook, then shrinks into a
small window (a circle in a corner) and the top two thirds show the cue's visuals, with a chapter
title, a progress marker, a show title and the subtitles inside the page. `--animations` can't do
this (it overlays clips on the full-frame recording), so build one HyperFrames composition for the
whole video and render it directly:

1. Make the clean cut first (`--no-burn`, `--no-draft`), and copy `<name>_edited.mp4` (muted
   `<video class="clip">`) and its audio (a separate `<audio class="clip">`) into the project's
   `assets/`.
2. Write the page from a template with a small build script: keep `animations.json` in source
   seconds and map every cue start, beat and chapter start onto the edit with jianjian's TimeMap
   (`jianjian.cuts.TimeMap` over `cuts.json` keep ranges), rounded to the frame grid. Read the
   final subtitles (`<name>.zh.srt` or your own reviewed `.srt`) into the same data.
3. One root timeline; each cue is its own layer, built by its own function and shown only between
   its start and end. The shrink is `transform` (scale, x, y) plus `clip-path: inset(... round
   ...)`, about 0.7 s, starting just before the first cue after the hook. Switch the subtitles from
   white with an outline (over video) to dark text (over the page) at the same moment.
4. Fill every gap longer than a few seconds with a title card for that passage: in this layout an
   empty top half looks broken, while in the overlay layout it was just the speaker. Cues that
   meant "cut back to the speaker" become large cards instead, as the speaker is always visible.
5. Keep templates outside the folder you render, animate with transforms only, and give each
   subtitle line its own element (README → Pitfalls: HyperFrames).
6. Before rendering the whole video, show the user three stills: the shrink, the most text-heavy
   card and the densest UI. On a first build also render a 10–30 s demo and wait for their OK, and
   when the look is still open, render the same few moments in several styles and let them pick
   from the stills: people choose a look from pictures, not from a description.
   Then `npx hyperframes lint`, and render with
   `npx hyperframes render <dir> --fps 60 --quality delivery -o <out>.mp4` (about 3 min for 3.5 min
   of 1080×1920 at 60 fps). QA as in §5b.7, and compare the audio with `<name>_edited.mp4` at a few
   points (cross-correlation); an AAC track can come out one frame (about 21 ms) off, which is
   inaudible.
7. For a short video, speed up the approved render 1.2× (§0b) as the last step, so the build
   keeps working in edit time:
   `ffmpeg -i <out>.mp4 -filter_complex "[0:v]setpts=PTS/1.2,fps=60[v];[0:a]atempo=1.2[a]" -map "[v]" -map "[a]" -c:v libx264 -preset slow -crf 17 -pix_fmt yuv420p -c:a aac -b:a 192k -movflags +faststart <out>_1.2x.mp4`.
   Check that the video and audio durations are both the original ÷ 1.2. The 1.2× file is the one
   to post; show the user that one.
   The other order also works: make the clean cut with `--speed 1.2` in step 1 and build the page
   on that timeline. The graphics are then rendered at their final timing and frame rate, and this
   step is skipped. Write in your notes that the cut is already sped up, so nobody speeds it twice.
8. A second-language version keeps the same timing: swap the on-screen text and the subtitles,
   nothing else. Latin text is much wider than Chinese at the same size, so check every line again.

## 6. Clips for short-video platforms: series parts and highlights

When the episode is finished, the user may want it in pieces: **series parts** (the whole episode
in 2–6 min parts, cut at topic changes) or **highlights** (the best 15–90 s moments). Picking is a
judgement made from the transcript; cutting is `JIANJIAN clips`.

1. **Get timed text for the exact video being cut.** If it is jianjian's own MP4, use
   `<out>/<name>.bilingual.srt` (already on the final timeline). If the user re-exported or joined
   parts in Jianying, check the length matches and compare the audio at a few points before reusing
   those times; otherwise transcribe the video first. Times are seconds in that video.
2. **Series parts:** cut where the topic changes, 2–6 min each, so each part starts with a line a
   new viewer can follow. Name each part after its topic.
3. **Highlights:** read `docs/HIGHLIGHTS.md` and score each candidate on its five points (hook in the
   first sentence, one idea that stands alone, an emotional spike, the payoff inside the clip,
   concrete and searchable). If `editing-style.local.md` describes the show's angle (for a
   two-culture show: a concrete contrast with a verdict), rank that highest. Start on the question
   or the line that sets the moment up, not on the answer; end on the payoff, on a full sentence.
4. **Show the user a table** (time, length, first line, score and why) and wait for their pick.
   Mention clips that contain film or music: they may be flagged for copyright on Douyin/TikTok.
5. **Cut:**
   ```bash
   JIANJIAN clips "/path/to/final.mp4" --prefix ep01_ --out "/path/to/highlights" \
     "big-question=12:03.5-13:10" "story=4:10-4:31.5,4:41-5:20"
   ```
   Each edge moves to the quietest frame within 0.25 s (`--snap`), every clip gets short fades, and
   `plan.json` records where each clip came from. Several spans are joined, which drops a line in the
   middle (e.g. "let's play the clip here"). In a video with burned-in subtitles, start the next
   span after that line's subtitle has gone, or it shows over the next shot. A NOTE about an edge
   in sound means the speakers don't pause there: listen to that cut.
6. **Report** each file with its length and opening line. The source video is never changed.

## 7. Music and sound effects

jianjian adds no music. HyperFrames can mix extra `<audio class="clip">` tracks (`data-start`,
`data-volume`); `npx hyperframes audio` measures where a sound peaks, so a click can land on a beat.
If the user wants background music, they choose the track; you can suggest sources whose license
allows use in videos on social platforms without credit (Pixabay Music, Mixkit) and say what to
check: the license on the track's own page, tracks registered with Content ID (claims can be
disputed with the download record), and length (most stock tracks are about 2 min: plan a loop at
a phrase boundary). Ask before downloading anything. Keep music well under the voice and fade it
with the last line. For sound effects, simple clicks and whooshes can be synthesized with ffmpeg,
which avoids licensing.

## 8. Cleaning up after the user approves

When the user says the video is done and asks to tidy up, list what you'd remove and how big it
is, ask about anything that was a deliverable (an earlier version, overlay clips), then move it to
a dated folder in the Trash (never `rm`; emptying the Trash is the user's call). Safe to remove:
render caches that duplicate exported files (`<out>/animations/` when no editor project uses it,
`work/animations/`), preview and snapshot folders, single QA frames once the contact sheets exist.
Keep the source, the edit folder's decisions (`cuts.json`, reviewed fillers and cues, patched
transcripts), the clean cut, the project sources needed to render again, and the final export.
Update the project's README and notes so they don't point at removed files.

## Rules

- Before the first edit on a Mac, run `JIANJIAN doctor`: on macOS 27, Kdenlive 26.04 and later crash
  at startup; tell the user to install Kdenlive 25.12.2 (README → Pitfalls → Kdenlive).
- Never modify or delete the source video or existing Kdenlive projects / Jianying drafts. jianjian only adds a new one
  (it auto-renames on a name clash) and writes into the output folder.
- Jianying 6+ encrypts drafts it saves, so a draft can't be edited by jianjian after you open/save it in
  Jianying. To change something, rerun jianjian to make a fresh draft.
- Export from inside Kdenlive (Render) or Jianying (导出) is manual; jianjian's own MP4 export is the automated path.
