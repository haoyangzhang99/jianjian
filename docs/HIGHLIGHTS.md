# Choosing highlights from a podcast

How to pick the moments of a long conversation that work as short clips (Douyin, TikTok, Reels,
Shorts, 视频号, 小红书). Gathered in October 2026 from research, clipping-tool documentation,
practitioner guides and a sample of real podcast Shorts. Most guides are written by companies
that sell clipping tools, and their numbers are self-reported, so the numbers here are rough
guidance; the patterns are what the sources agree on.

## What the evidence says

- **Arousal spreads.** In a study of about 7,000 New York Times articles plus experiments, content
  that evokes high-arousal emotions (awe, anger, anxiety) was shared more, and low-arousal
  content (sadness) less; positive content was shared more than negative overall. This held
  after controlling for how surprising, interesting or useful the content was
  ([Berger & Milkman 2012](https://faculty.wharton.upenn.edu/wp-content/uploads/2011/11/Virality.pdf)).
- **Viewers decide in the first seconds.** Clipping vendors report that most viewers who leave do
  so in the first 3 seconds, and that the best Shorts are watched rather than swiped by about 70%
  of viewers (self-reported or unverified; [QuickReel](https://quickreel.io/blog/10000-clips-what-makes-one-travel),
  [Subscribr](https://subscribr.ai/youtube-strategy/youtube-shorts-low-watch-time-boost)).
- **Most feed video is watched muted** (publisher figures of 75–85%), so captions are not optional.
- **Clip tools score the same four things.** OpusClip's virality score rates *hook* (does the
  opening grab attention and match the topic), *flow* (does it build to a satisfying end),
  *value* (useful or emotionally resonant) and *trend* (fits what audiences care about now)
  ([OpusClip](https://help.opus.pro/docs/article/virality-score)).
- **Clips bring new listeners to the full show.** Podcasters report that the fastest-growing
  shows on podcast apps grew because their clips were shared on Douyin, not through the app's own
  discovery ([少数派 discussion](https://sspai.com/post/105306)); shows like Modern Wisdom release
  mid-length clips to lead viewers to full episodes.

## What wins on real channels

A sample on 2026-10-22: the latest ~48 Shorts of seven podcast channels (Modern Wisdom, The Diary
of a CEO, Huberman Lab, Lex Fridman, Call Her Daddy, SmartLess, Colin and Samir), each clip
compared with its own channel's median views, so the audience size cancels out.

| Did far better than the channel's median (4–50×) | Did far worse (0.2–0.4×) |
|---|---|
| A concrete promise with a payoff: "Spot a psychopath in five seconds", "10 years of therapy in one minute", "Hack to fall asleep super fast" | Abstract advice: "Always trust your gut", "Don't quit before your breakthrough" |
| A universal life decision: choosing a partner, "people who sign prenups stay together longer" | A guest's niche anecdote that needs context about the guest |
| A counterintuitive finding: "why reading books makes us better at speaking" | Niche technical topics |
| High stakes: predictions, "the world is collapsing" | Sponsored or partner segments |
| A famous name or a current trend | Plain episode promos for less famous guests |

A Bilibili search for clips about Chinese–American cultural differences showed the same pattern:
the most-viewed clips state one concrete contrast and a surprising verdict ("刚到中国时不敢说'我是美国人'，
后来发现人家根本不在乎", "美国怕AI怕得要死，中国却当搜索引擎用"); clips titled with the bare topic
("聊聊中美男人的文化差异") got almost no views. Podcast highlight clips there run 45–60 s with a
question as the title ("当天才遇见资本，结局是？").

## Checklist

Score each candidate moment one point per line; clip the 4s and 5s first.

1. **Hook in the first sentence.** It opens on a claim, a question, a number or a confession, not a
   greeting, a name or "so, anyway". If the first sentence needs the sentence before it, the hook
   is too late: start later, or move the strongest line to the front (`--hook`).
2. **One idea that stands alone.** Read the transcript of the clip as a stranger: is it clear who
   is speaking, what "he" and "that" refer to, what the question was?
3. **An emotional spike.** Laughter, surprise, a disagreement, a vulnerable admission, awe, anger
   or anxiety, not calm agreement.
4. **The payoff is inside the clip.** It ends on the answer, the punchline or the twist, on a
   complete sentence; it doesn't stop where the interesting part begins.
5. **Concrete and searchable.** Specific nouns, numbers, a contrast (A vs B), a famous name or a
   current topic, rather than "an interesting conversation about life".

Length: the shortest cut that completes the idea, usually 15–45 s for a single point and 45–90 s
for a story or an argument. Longer only when the build-up is the point.

## Making the clip

`jianjian clips VIDEO NAME=START-END[,START-END...] ...` cuts approved moments, with every edge in
a pause; see the README.

- Cut greetings and setup; start mid-thought. Never cut a qualifier that changes the meaning, and
  don't publish a line that means something else without its context.
- Title and cover text state the payoff or the contrast in a few words (Chinese: under ~15 字),
  often as a question the clip answers.
- Captions always, with the key word easy to read and faces left clear.
- Vertical platforms: make it obvious who is speaking (for a two-person call, stack the speakers).
- Judge clips by completion rate, follows and visits to the full episode, not views alone, and
  compare clips within your own channel.

## Sources

- Berger, J. & Milkman, K. (2012), [What Makes Online Content Viral?](https://faculty.wharton.upenn.edu/wp-content/uploads/2011/11/Virality.pdf), Journal of Marketing Research
- OpusClip, [Virality score](https://help.opus.pro/docs/article/virality-score)
- QuickReel, [We analyzed 10,000 podcast clips](https://quickreel.io/blog/10000-clips-what-makes-one-travel)
- ShortMind, [播客视频切片怎么做](https://shortmind.ai/zh/blog/how-to-make-podcast-clips/)
- Choppity, [Podcast clips for social media](https://www.choppity.com/blog/podcast-clips-for-social-media/)
- Klap, [How to create podcast clips](https://klap.app/blog/podcast-clips)
- Callum McDonnell, [The podcast genius behind Modern Wisdom](https://callummcdonnell.substack.com/p/meet-the-podcast-genius-behind-chris)
- 少数派, [播客与切片的讨论](https://sspai.com/post/105306); 人人都是产品经理, [视频播客卷起来了](https://www.woshipm.com/share/6259025.html)
- YouTube Shorts and Bilibili search data collected on 2026-10-22 (titles and view counts only)
