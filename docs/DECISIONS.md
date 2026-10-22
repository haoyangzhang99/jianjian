# Design decisions

Why jianjian works the way it does. Most entries come from testing the pipeline on a real
15-minute, two-speaker English conversation recorded on a video call, on an Apple Silicon Mac with
Jianying Pro 11.5. Read this before "simplifying" something: several obvious-looking alternatives
were tried and failed.

## Jianying drafts

- **Only new drafts, never edits.** Jianying 6+ encrypts `draft_info.json` /
  `draft_meta_info.json` when it saves a draft. jianjian writes a fresh plaintext draft (plus a copy
  as `draft_content.json` for older builds) and never reads or edits an existing one. To change an
  edit, run jianjian again and get a new draft.
- **Draft library: [pyJianYingDraft](https://github.com/GuanYixuan/pyJianYingDraft)** (Apache-2.0),
  vendored unmodified in `vendor/` at the commit in `vendor/pyJianYingDraft/UPSTREAM_COMMIT`. Other
  projects considered: jianying-editor-skill (MIT; a wrapper around a modified pyJianYingDraft,
  export Windows-only), jianying-headless (non-commercial license, pinned to Jianying 11.4.x,
  needs macOS 26+), jianying-auto (needs a separate server, exports by scripting Cmd+E).
- **One bilingual subtitle track.** Chinese and English used to be two text tracks pinned about
  75 px apart. Jianying grows a text box both up and down from its centre, so lines collided as
  soon as one wrapped. Now each subtitle is one text box: a Chinese line and an English line, each
  with its own style range. Jianying lays them out, so they cannot overlap.
- **A name clash renames the draft only when installing.** With `--no-install` the staging copy
  keeps the requested name (renaming it there made a later manual copy pick up a stale folder).
- **Export from inside Jianying is not automated.** No reliable way on macOS / Jianying 11.5; the
  FFmpeg render is the automated MP4.

## Transcription (faster-whisper)

- **The style prompt is sent as `hotwords`, not `initial_prompt`.** With
  `condition_on_previous_text=False`, faster-whisper only uses `initial_prompt` for the first 30-s
  window; everything after it came out lowercase and unpunctuated. Hotwords go with every window.
- **The prompt language is chosen by sampling.** Language detection on 8 windows spread over the
  file picks an English, Chinese or bilingual prompt. A bilingual prompt on an English-only
  episode hurt punctuation.
- **No names or terms in the prompt.** Tested: a list of names in `hotwords` leaked into the
  transcript as text and set off a repetition loop (the same title over and over) that swallowed
  about 30 s of real speech. Fix names during review instead (`--cues`).
- **PyAV is pinned below 17.** faster-whisper 1.2.1 passes `metadata_errors=` to `av.open`, which
  PyAV 19 removed.

## Pauses and cuts

- **Every cut edge is checked against the audio** (`jianjian/edges.py`), because neither the
  speech detector nor Whisper marks where sound really stops. Only the kept side of an edge has to
  be quiet: 45 dB below the speech level for pause cuts (30 dB still let a listener hear a soft tail
  being chopped). Filler cuts move their edges at most 70 ms inward and fall back to the valley
  between filler and word; they are never dropped, since leaving glued fillers in bothered the
  listener more. Loudness ignores digital silence (video-call apps mute the line between words).
  Every cut gets a 15-ms fade. Tuned by listening tests on a 15-minute recording: the final
  version is 12 s longer than before and keeps the cut-off tails.
- **Cuts are snapped to the frame grid** (1/fps), and the draft, the render and the subtitles all
  use the same keep ranges, so nothing drifts over hundreds of cuts.
- **Presets come from common tools.** Mubert Cast defaults to pauses over 0.5 s shortened to 0.3 s;
  FireCut suggests 750 ms with 250 + 250 ms padding; AutoCut calls 0.3–0.5 s ideal for YouTube;
  auto-editor keeps 0.2 s each side; Descript's example is over 750 ms to 200 ms; Chinese 口播
  guidance keeps 0.2–0.8 s (0.8–1.2 s for interviews). There is **no default preset**: the right
  pace depends on the video, so the tool requires `--preset` and agents ask the user first.

## Short-video openings (Douyin / Xiaohongshu / Shorts)

- **The first 30 seconds follow a 3 / 15 / 30 plan:** a hook in the first 3 s (counter-intuitive
  claim, suspense, or credentials + result), real value by 15 s, and the video's structure stated
  by 30 s. It comes from creator advice on short-video feeds, which rank on completion, engagement
  and share rate, so the opening decides retention. Agents suggest it for these platforms and
  build the deliverable to it (skill/SKILL.md §0b).
- **Preamble is removed with content cuts.** Preamble and warm-up are removed as reviewed
  `restart` spans in `fillers.json`, which already cut cleanly and keep subtitles in sync.
- **A later hook is brought forward with a cold open (`--hook START-END`).** The keep list is then
  no longer in source order: the hook's keep ranges (pauses and fillers inside it stay cut,
  bounds on the frame grid) come first, then the whole edit. The default repeats the hook at its
  original place (a teaser, the usual cold open; the user chose this default); `--hook-mode move`
  removes it there. Every stage reads the same reordered list, split into source-ordered runs
  (`cuts.source_runs`): the draft and the checks already worked clip by clip; the subtitle and
  card mapping (`TimeMap`) maps a line into every run that plays it, so a teaser line appears
  twice; the audio is streamed once per run; and FFmpeg gets one input per run, joined with
  `concat`. A single `select` keeps frames in source order and can't jump back, and a `split`
  of one input into several `select` branches has to hold back the main branch's raw frames
  while the hook plays, up to the hook's position in the source. Each later input
  opens with a fast seek 2 s before its run, and its timestamps are shifted back so the frame
  grid and the `select` times stay in source time.

## Filler words (`--cut-fillers`)

- **A second, verbatim transcript.** Whisper drops "uh/um" when it punctuates. A prompt written
  full of fillers makes it keep them (25 instead of 3 in a 3-minute test) without the prompt
  leaking. Subtitles still come from the clean transcript.
- **Fillers are re-located on the waveform.** Whisper puts a filler in the right gap but its
  timestamps for it are often 0.1–0.5 s off (some "uh"s came out 40 ms long). Cutting Whisper's
  span left the sound audible: re-transcribing the edit still heard 101 of 118. Cutting the voiced
  burst between the neighbouring words instead brought that down to 13–16, with 0 real words cut.
- **Only hesitations and stutter repeats are cut automatically.** "like", "so", "you know" can
  carry meaning ("I like this song", "so important", "I don't think so"); they are listed for
  review. Review also catches "repeats" that are really two speakers echoing each other.
- **Cuts never reach into neighbouring words** and are snapped inward to the frame grid. Every cut
  gets a short audio fade (6 ms in the MP4, 10 ms in the draft) so cuts inside speech don't click.
- **Subtitles follow the cut.** Removed repeats, discourse words and restarts also leave the
  English subtitle text; reviewed translations that may now say too much are flagged.
- `tools/verify_words.py` re-transcribes an edit and reports real words cut and fillers left.

## Content cuts and B-roll

- **Content cuts are suggested, never automatic.** A comparison with a person's own edit of a
  15-minute recording showed they removed about 94 s of content (preamble, logistics, word
  searches, back-and-forth, restarts, an unfinished ending, one backstory detail). `content.py`
  suggests these with a reason (10 of the person's 12 cuts were found; the backstory and an
  abandoned phrase with no trace in the words were not), in fillers.json with `cut: false`, because
  they are editorial judgement and the detectors have false positives (lists, plain repetition).
- **Stutters across a filler** ("they, uh, they") are cut like adjacent ones; word restarts
  ("re-, re-, uh, remember") are only suggested ("the, there" can be two words).
- **B-roll markers** flag requests to show something ("put the clip here") in `report.md`.
- **Inserted clips (`--insert AT=CLIP`)** are converted once (`inserts.py`) and then treated as a
  second source: a keep range carries `media` (0 = the recording, n = clip n), so the draft, the
  render (one input per run), the audio and the checks need no special case. The clip is slowed by
  `--speed` when converted, so the global speed-up plays it at its normal speed: a film scene isn't
  sped up with the talk. It is scaled to fit and padded (a crop would cut off the film's subtitles), and
  its loudness is matched to the recording's integrated loudness, capped so peaks stay under -1 dBFS.
  The clip goes in where its moment plays; a moment inside a cut snaps to the cut, so give the end
  of the sentence before it.

## Explainer animations (`--animations`)

- **HyperFrames draws them** (HTML + GSAP rendered frame by frame in headless Chrome; Apache-2.0,
  so the open-source repo can depend on it; pinned to one version so a re-render looks the same).
  Considered: Remotion (company licence needed above 3 people), anything2explainer (non-commercial
  licence, and it builds its own TTS voiceover instead of following a recording), Manim (maths
  diagrams, not general explainers).
- **The agent writes the pages; jianjian owns the timing.** Times in animations.json are source
  seconds, like cards. jianjian maps them through the cuts, cold open and `--speed` and hands them to
  the page as `window.jianjian` (beats, words, duration) before its scripts run, so a page never
  holds an edit-dependent time and a re-edit only re-renders it.
- **A transparent overlay, not an insert.** The talk keeps playing; the clip (ProRes 4444 with alpha,
  the size of the video) goes on an `animations` video track above the recording in the draft,
  under the text tracks, and is overlaid in the MP4 before the subtitles are burned in. One
  animation at a time: an earlier one ends where the next starts.
- **Clips live in `<out>/animations/`** because the draft points at them, named by a hash of the page
  as rendered (timing included) and its `assets/`: a rerun reuses an unchanged clip, and a changed
  one gets a new file instead of replacing the clip an earlier draft uses. They are large
  (ProRes 4444: about 140 MB per 30 s at 1080p).

## Clips and highlights (`jianjian clips`)

- **Picking is judgement, cutting is a tool.** Clipping services score moments with opaque models;
  what they publish (hook, flow, value, trend) matches research and practitioner advice, collected
  with a sample of real channels in [HIGHLIGHTS.md](HIGHLIGHTS.md). jianjian doesn't score
  automatically: the agent reads the transcript, scores candidates on that checklist, and the
  user approves before anything is cut.
- **Re-encode, don't stream-copy.** Stream copy can only cut at keyframes (seconds apart);
  re-encoding starts each clip on the chosen frame.
- **Edges go to the quietest frame within 0.25 s**, measured on the video's own audio, because
  subtitle and word times are only roughly right; a short fade covers a cut where speakers run
  straight on. A clip may join several spans, so a line in the middle can be left out.

## Subtitles and translation

- **Cue splitting:** an English "." ends a cue (except abbreviations like "U.S."); English cues may
  be about 1.6× longer than Chinese ones; one- or two-word scraps merge into a neighbouring cue.
- **Translation is one sentence per request** with the neighbouring sentences as context, then
  split back over that sentence's cues at word boundaries (jieba), preferably at punctuation.
  Translating cue by cue, or several numbered sentences per request, let the model shift text into
  a neighbouring line, and every later line of the batch slid by one.
- **Automatic subtitles still need a review pass** before publishing: proper names, a few
  mishearings and roughly one mistranslated line in ten. The review edits `cues.json` and reruns
  with `--cues`.

## Render (FFmpeg)

- **Audio is built in Python** (`render.build_audio`): the keep ranges are joined at 48 kHz, where
  one video frame is exactly 48000/fps samples, with a fade at every join; FFmpeg cuts the video
  with `select` on the same grid.
- **An ffmpeg with libass is preferred.** Homebrew's ffmpeg 8+ has no libass, so subtitles could
  not be burned in; imageio-ffmpeg's bundled build has libass and VideoToolbox.
- **`--speed`** scales the whole edit after the frame-exact cut (video `setpts`, audio `atempo`,
  pitch kept); in the draft each clip gets the speed and `change_pitch` stays off; subtitle and
  card times are divided by the speed.

## Validation

- **Sync probes compare against sample-exact expected audio.** Rounding each keep range to 16 kHz
  on its own (533.33 samples per frame) drifted a few samples per cut and caused false failures.
- **Sped-up renders are compared by loudness envelope.** atempo chooses its overlap chunks
  differently at 48 kHz and 16 kHz, so waveforms differ (correlation ~0.3) although the audio is
  aligned (envelope correlation ~0.98, 0–10 ms offset; a 1.5-s misalignment scores −0.7).
- **Subtitle timing** was checked by re-transcribing the output: subtitle starts vs first spoken
  word, median within a few ms and no drift, at 1.0× and 1.05×.

## Models and licenses

- Translation uses Qwen2.5-7B-Instruct (Apache-2.0) on Macs with 16 GB+ RAM and
  Qwen2.5-1.5B-Instruct (Apache-2.0) below that. Qwen2.5-3B was dropped: it uses the
  "qwen-research" license, not an open-source one.
