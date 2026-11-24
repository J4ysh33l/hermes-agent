# Studio playbook: how the best faceless explainers are made, and what we copy

The style reference for `/studio` videos. The script → storyboard step (Gemini by default, Claude on
request) will be prompted from this file, and the scene library is built against it.

Researched 2026-11-24 from interviews, studio pages, editor tutorials, a 522-video Fireship transcript
dataset and Remotion's docs. YouTube itself could not be fetched (captcha), so no videos were watched
frame by frame. Every claim carries its evidence:

- **[measured]** counted from data (Fireship word-timed transcripts, or our own renders)
- **[sourced]** stated by the creator, their studio or a credible report (links in § 12)
- **[vendor]** from caption-tool or tutorial vendors, who sell the style; plausible, not first-hand
- **[observed]** a style note from familiarity with the channel; check against 3–5 current uploads
  before hard-coding it
- **[ours]** our recommendation, not a fact about any channel

---

## 1. The ten rules (what every channel studied has in common)

1. **No intro. The topic or the claim is the first thing said.** Fireship says the subject's name as
   word one; Zack D. Films asks the question at 0 s; Hormozi's editors cut until the video "starts on
   the hook". Fireship speaks a median **7 words in the first 3 s**. [measured/sourced]
2. **Fast voice, zero dead air.** Fireship reads at a median **211 wpm** ("in 100 Seconds") to 225 wpm
   (Code Report), with **no pauses over 0.5 s** in the final cut. Hormozi and the Varun Mayya handbook
   both say: cut every silence, breath and "umm". [measured/sourced]
3. **Something changes every 1–4 seconds.** A cut, a punch-in, a new element, a camera move. Hormozi
   cuts or zooms every 1–3 s; Zack D's camera "is almost always moving". The Mayya handbook's floor:
   a bigger pattern interrupt every 15–30 s. [vendor/sourced]
4. **The voice is the clock.** Kurzgesagt: "his voiceover provides the timing for the animation team".
   Every channel records narration first and animates to it. (Our pipeline already works this way.)
   [sourced]
5. **Captions are a second picture.** On shorts: 2–4 words at a time, all caps, heavy font, the
   spoken word in yellow, a pop on each new word. [vendor]
6. **One question, answered completely, then stop.** Zack D's 31-second "How Stitches Work" (~253M
   views) ends the moment it answers; rewatches gave ~1.4 views per viewer. "A 31-second video you
   watch 1.4 times beats a 60-second video you abandon halfway." [sourced]
7. **A ritual frame.** "X in 100 Seconds" / "This has been X in 100 seconds" (110 of 143 transcripts);
   "It is <date>, and you're watching The Code Report". Repeated openers and closers build recognition.
   [measured]
8. **A joke or an emotional beat every few lines.** Fireship's sarcasm, OverSimplified's anachronisms,
   Dhruv Rathee's tension music, Zack D's gross-out curiosity. [sourced/observed]
9. **Show the evidence.** Screenshots, headline clippings with a highlighter sweep, charts, maps. Claims
   feel sourced when the proof is on screen. [observed]
10. **Sound marks the structure.** Whoosh into a cut, pop on a text entrance, riser into the reveal,
    impact on the key word; music well under the voice. [vendor/sourced]

---

## 2. Script formats (pick one per video)

All lengths assume ~205 wpm. 30 s ≈ 100 words, 45 s ≈ 150, 60 s ≈ 200.

### A. "X in N seconds" explainer (Fireship) — tech, tools, concepts

| Beat | Time | What happens |
|---|---|---|
| Hook | 0–3 s | `<Name>, a <category> that <does X> <joke twist>.` Name is word one. |
| Origin | 3–10 s | Who made it, when, the problem it solved. |
| Why it's different | 10–20 s | Contrast with the incumbent; often a rhetorical question. |
| Walkthrough | 20–50 s | One concept per sentence, one code change per sentence. |
| Payoff | last 3 s | "Congratulations, you just…" or the one-line takeaway. |

Real openers from the dataset [measured]:
- "Bun.js, a mega-fast JavaScript runtime … built by someone who woke up one day, looked at their
  node_modules folder, and chose violence."
- "RabbitMQ, an open source distributed message broker that works like a post office in the cloud."
- "Java, a boilerplate-driven language designed for writing verbose object-oriented instant legacy code."

Style: sentences ~16 words; one concrete fact each; one everyday analogy per concept ("think of it like
a ride-hailing app…"); a joke every 2–3 sentences. For shorts, drop the long-form sign-off. [measured/ours]

### B. News take (Code Report, Varun Mayya) — something just happened

| Beat | Time | What happens |
|---|---|---|
| Hook | 0–3 s | The news as a stake: "`<Company>` just did something that should scare every `<job>`." Screenshot/headline card on screen in the first second. |
| What happened | 3–15 s | Facts, fast. |
| What it actually means | 15–40 s | 2–3 implications, each with a visual. |
| Take | last 5–10 s | Contrarian or forward-looking: "most people are missing…". |

Mayya's process [sourced]: he voice-notes his take on a news item each morning; writers script it "in
his natural speaking style"; pods of 4 editors split each 1-minute video into chunks. **Our analogue:
you send a voice note or link; Gemini drafts in your voice; the storyboard is the edit.**

### C. "How does X work / what happens if" (Zack D. Films) — curiosity

| Beat | Time | What happens |
|---|---|---|
| Question | 0–3 s | "This is what happens when…", "Here's how `<everyday thing>` works", "If you're ever `<scenario>`, do this." |
| Process | 3–25 s | Step by step, each step a visual. |
| Reveal | last 2 s | Hard stop on the answer; last line flows back into the first (loop). |

Length 25–40 s. Constant camera motion. [sourced/observed]

### D. Business case (Think School) — Indian brands and markets

Question ("Why is `<brand>` losing to `<competitor>`?") → context → a named framework ("3 reasons") →
evidence (charts, clippings) → lesson for India. Shorts 45–90 s: one question, one framework, one
insight. Clean "consulting deck" visuals, few memes. [observed]

### E. Hindi / Hinglish explainer (Dhruv Rathee) — social, history, geography

Shocking fact or question ("Kya aap jaante hain ki…?") → "aaiye samajhte hain" → 2–3 facts with map or
clipping evidence → a moral or open question. Maps with animated borders and arrows, newspaper clippings
with yellow highlight sweeps, tension music with risers. [observed/vendor]

### Long-form animated formats (for reference)

- **OverSimplified** (history comedy, 20–40 min parts): third-person narrator sets up a fact → a
  character undercuts it in modern slang → hard cut to a reaction. Big topics split into parts. [secondary/observed]
- **Kurzgesagt** (8–15 min): intriguing question → intuition via a visual metaphor → scale escalation →
  optimistic reflection. About a dozen script drafts per video. [sourced/observed]
- **Vox / Johnny Harris / Wendover / PolyMatter**: counter-intuitive question → system explained in
  chunks → "but here's the catch" → implications; maps are the stage. [sourced/observed]

---

## 3. Hooks

**Rules [ours, from § 1]:** 6–9 words; the topic noun or the claim first; one picture that matches the
words in frame 1; never a greeting, never "in this video".

**Formula bank** (fill-in templates; examples are in the style, not quotes):

| Family | Template | Example |
|---|---|---|
| Definition + twist | `<Name>, a <category> that <does X> <twist>.` | "Redis, a database that forgot it was supposed to be slow." |
| Stake / threat | `<Company> just <did X>, and it should scare every <role>.` | "Google just shipped a model that should scare every junior dev." |
| Contrarian | `Everyone's wrong about <trend>.` / `Most people get <X> backwards.` | "Most people get compound interest backwards." |
| Curiosity / process | `This is what happens when <event>.` / `Here's how <thing> works.` | "This is what happens to your phone when it hits 100%." |
| Number | `<Big number> <surprising unit>.` | "₹40,000 crore. That's what India spends on chai every year." |
| Question | `Why is <X> <surprising state>?` | "Why is Zepto losing money on every order?" |
| Pain point | `If you're <situation>, stop doing this.` | "If your app feels slow, stop blaming the language." |
| Hindi | `Kya aap jaante hain ki <fact>?` / `<Country> ne ye kaise kar diya?` | "Kya aap jaante hain ki India ka 40% doodh…" |

**Variants:** each video gets **3 hooks from 3 different families**, rendered as 3-second openings
(item 4 of the plan). You pick one, or later we A/B them.

---

## 4. Visual language and pacing

**Cadence [ours, from § 1]:** a new visual every **45–90 frames (1.5–3 s)**; a punch-in on emphasis
words; never more than 4 s without something moving.

**Scene vocabulary** (✅ = in our library now, ◻️ = planned in the scene library):

| Scene | Used by | Status |
|---|---|---|
| Kinetic title (words land one by one) | all | ✅ `title` |
| Numbered list, item on its sentence | Hormozi, Think School | ✅ `bullets` |
| Code editor typing itself | Fireship | ✅ `code` |
| Big number counting up | Think School, Dhruv | ✅ `stat` |
| Full-screen image/clip, slow push + caption card | all | ✅ `image` |
| Two cards with VS | Fireship, Think School | ✅ `compare` |
| Terminal with commands | Fireship | ◻️ |
| Logo / name reveal (subject logo big as it is said) | Fireship | ◻️ |
| Box-and-arrow diagram (nodes connect on their sentence) | Fireship, Kurzgesagt | ◻️ |
| Bar / line / pie chart from data | Think School, Wendover | ◻️ |
| Headline clipping with highlighter sweep (rebuilt as a card) | Dhruv, Think School, Vox | ◻️ |
| Tweet / post card | Varun Mayya, Code Report | ◻️ |
| Map: zoom to region, highlight, route draws on, labels | Dhruv, Vox, Harris, Wendover | ◻️ (d3-geo + Natural Earth, no API key) |
| Meme card (text over a CC0 image) | Fireship | ◻️ |
| Timeline (dates slide past) | history channels | ◻️ |
| Quote card | all | ◻️ |
| Emoji / icon burst on a key word | Hormozi | ◻️ |
| Before → after split | all | ◻️ |

---

## 5. Motion grammar

| Move | Spec | Where from |
|---|---|---|
| Entrance | spring, damping 12–15, stiffness ~180–200 (snappy, settles without wobble); scale 0.7→1 or 1.12→1 with a 12 px blur clearing | Hormozi captions [vendor], ours |
| Punch-in | scale 1.0→1.10–1.20 over ~6 frames on an emphasis word | Hormozi [vendor] |
| Constant push | every scene drifts 1.00→1.04 (graphics) or 1.00→1.12 (photos) | Kurzgesagt, Zack D [observed] |
| Idle motion | nothing ever fully still: slow background glow, bobbing, drifting particles (`noise2D`) | Kurzgesagt [sourced: loops via expressions] |
| Transitions | 6–10 frames; whip / slide / zoom-through, with a whoosh 3–6 frames before the cut | ours from tutorials |
| Motion blur | on whips and fast moves only (it multiplies render cost) | tutorials |
| "Handmade" feel | step graphics at 12 fps (`Math.floor(frame/2)*2`), cycle 3 paper textures 2–3×/s, multiply paper overlay | Vox [secondary], Harris [tutorial] |
| Film burn / light leak | between sections, Dhruv-style; `@remotion/transitions` has `filmBurn` | Dhruv [vendor] |
| Sound sync | every visual event gets its sound on the same frame | all |

---

## 6. Captions (spec, implemented)

- 2–3 words per page (Hormozi uses up to 4–6 over 2 lines); new page after a 0.35 s gap or a sentence end.
- Inter 900, all caps, 92 px; white with a 14 px black stroke and a soft shadow; the spoken word yellow
  (`#ffd23f`), popping 1.18→1.06. Sources disagree on Hormozi's font (Montserrat Black, TheBoldFont,
  Anton); Anton or Montserrat Black are drop-in options. [vendor]
- Centred, bottom edge 400 px above the bottom (platform buttons cover ~380–390 px at the bottom, ~180
  at the top, ~120 at the right). [vendor]
- Text from the script, not from Whisper, so Hinglish stays as written. [ours]

---

## 7. Looks (presets to build as themes)

| Preset | Background | Accent | Type | Feel | For |
|---|---|---|---|---|---|
| **Dev dark** (current default) | `#0b0f19` navy-black, moving glow, faint grid | yellow `#ffd23f` + cyan | Inter + JetBrains Mono | Fireship | tech, AI, tools |
| **Black & yellow** | crushed black | yellow, white | Montserrat Black / Anton | Hormozi | money, business advice |
| **Flat space** | dark navy, soft radial glows | saturated per scene, no outlines | rounded sans | Kurzgesagt | science, "what if" |
| **Paper collage** | paper texture, multiply | one accent (yellow highlighter) | serif headlines + sans | Vox / Harris | history, geography, news |
| **Consulting deck** | off-white or deep blue | brand colour of the company | clean sans | Think School | business cases |

A brand kit from you (name, 2 colours, font, logo) overrides any preset.

---

## 8. Audio

| Layer | Spec |
|---|---|
| **Voice** | Target **190–220 wpm**. Ours: **217 wpm** with Kokoro `speed 1.15`, `pause 0.12` and each line's own silence trimmed (was 178 wpm at `speed 1.05`, `pause 0.25`, untrimmed). Gaps between sentences average ~0.18 s. |
| **Music** | One bed per video, chosen by mood tag; ducked to about −18 to −24 dB under the voice, rising in gaps; normalised mix at −14 LUFS. Free sources: Pixabay Music, YouTube Audio Library (YouTube only), Kevin MacLeod (CC-BY, credit required, as OverSimplified did). |
| **SFX** | whoosh before each cut; pop on text/item entrance; riser into the reveal; impact on the key word or number; click/typing under code; sparse for data/maps, dense for comedy. Pixabay SFX, Mixkit (check each licence). |

---

## 9. Covers and thumbnails

- **Faceless:** one striking visual + **2–4 huge words** in the caption font, high contrast, one
  accent colour; the text complements the title, never repeats it. [vendor/ours]
- Fireship: subject logo big and centred on dark. Kurzgesagt: one illustrated subject on dark + 2–4
  caps words. OverSimplified: a big cartoon head, almost no text. Dhruv: 2–4 words + red arrows/circles.
  Zack D: a frame from the video; title of a few words + one emoji. [observed/sourced]
- Built with Remotion's `renderStill` from the same scenes, so covers always match the video. [ours]

---

## 10. Channel cards

| Channel | Made with | Team / time | What we take |
|---|---|---|---|
| **Fireship** | not published; a community Remotion remake exists (wcandillon/remotion-fireship) | Jeff writes and voices every video; small team | definition+twist hook, 211 wpm, code scenes, joke density, ritual sign-off |
| **Varun Mayya** | in-house tools; editing pods of 4 | 17 people; daily voice note → script | news-take format, "change something every 15–30 s", screenshots as evidence |
| **Alex Hormozi** | Premiere (per tutorials) | 5-person repurposing team; ~6 videos/day planned | caption style, punch-ins every 1–3 s, Hook → Retain → Reward |
| **Zack D. Films** | Blender, ~50-person team (weak source) | ~$3,000/short (weak) | the script formula, 30 s discipline, loop ending, camera always moving |
| **Think School** | not published | 2 → ~40 people | business-case structure, charts, clippings |
| **Dhruv Rathee** | Premiere + After Effects (tutorial recreation); maps via Google Earth Studio / GeoLayers (imitators) | 10–15 researchers and editors | Hindi structure, maps, highlighted clippings, 4-layer sound |
| **Kurzgesagt** | Illustrator + After Effects | 1,200 h/video; ~200 panels; 2–3 illustrators + 2–3 animators | motion grammar, idle loops, voice-first timing |
| **OverSimplified** | After Effects + Photoshop (secondary) | unknown; <4 uploads/year | simple characters on rich backgrounds, humour carries the facts |
| **Alan Becker** | Adobe Animate (frame by frame), Blender | first episode ~3 months | (not reproducible; see § 11) |
| **Vox / Johnny Harris** | After Effects + GEOlayers, Mapbox, Natural Earth | Vox: one producer, 4–6 weeks | maps as the stage, paper texture, 12 fps stepping |

---

## 11. What Remotion can and cannot make

| Style | Can we make it? | Cost to get there [ours] |
|---|---|---|
| Fireship / Hormozi / Think School / Varun-style faceless shorts | **Yes, fully.** Kinetic text, code, charts, cards, stock b-roll, captions | the scene library (§ 4) |
| Vox / Harris / Wendover maps and data | **Yes, fully by code** (d3-geo + public-domain Natural Earth, paper overlay, 12 fps stepping) | ~1–2 weeks for a map kit |
| Kurzgesagt-lite flat vector | **Partly.** Same palette, glow and motion grammar; needs a library of ~20–50 reusable SVG props drawn once; will look more templated | ~3–6 weeks of illustration |
| OverSimplified-lite cut-out comedy | **Partly.** An SVG puppet with jointed limbs, pose and expression JSON, mouth flaps from voice loudness, 10–20 reusable backgrounds | ~2–4 weeks; the funny writing is the hard part |
| Stick War-style armies | **Yes.** Reusable walk/attack/die cycles repeated across many units | ~1–2 weeks |
| Alan Becker-grade stick fights | **No.** Bespoke frame-by-frame choreography is months of hand animation | — |
| Zack D 3D realism, realistic faces, talking heads | **No.** Needs Blender + animators, or paid/GPU AI video, or your own footage | — |

---

## 12. Sources

Fireship: [transcript dataset](https://huggingface.co/datasets/CognitiveLab/FS_transcribe_summary),
[Engineer's Codex](https://read.engineerscodex.com/p/how-fireship-became-youtubes-favorite),
[fireship.dev/about](https://fireship.dev/about), [rosetta.to (Bun)](https://rosetta.to/u/fireship/bun-in-100-seconds),
[remotion-fireship](https://github.com/wcandillon/remotion-fireship).
Varun Mayya: [YourStory](https://yourstory.com/2026/01/ai-authenticity-the-creators-edge-lessons-from-varun-mayya),
[handbook ch. 22](https://sachinjain024.github.io/awesome-books-mindmap/content-creator-handbook/chapters/chapter-22.html),
[ch. 11](https://sachinjain024.github.io/awesome-books-mindmap/content-creator-handbook/chapters/chapter-11.html).
Hormozi: [Submagic](https://www.submagic.co/blog/how-to-make-alex-hormozi-captions),
[Choppity](https://www.choppity.com/tools/recreate-video-editing-style/alex-hormozi/),
[Riverside](https://riverside.fm/blog/hormozi-style-videos), [Copyblogger](https://copyblogger.com/content-repurposing/).
Zack D. Films: [Substack breakdown](https://danielrusnok.substack.com/p/how-a-faceless-channel-engineered).
Think School: [DNA](https://www.dnaindia.com/business/report-meet-engineers-turned-youtubers-who-started-thinkschool-with-just-rs-25000-now-have-344-million-subscribers-3063003).
Dhruv Rathee: [The Swaddle](https://www.theswaddle.com/the-people-s-youtuber),
[editing tutorial summary](https://videohighlight.com/v/KvH3Hd0qR6c).
Kurzgesagt: [kurzgesagt.org/youtube](https://kurzgesagt.org/youtube/),
[1,200 hours](https://kottke.org/20/02/how-to-make-a-kurzgesagt-video-in-just-1200-hours).
OverSimplified: [Creator Handbook](https://www.creatorhandbook.net/oversimplified-a-youtube-empire/),
[Viducer](https://viducer.ai/blog/how-to-make-videos-like-oversimplified).
Alan Becker: [Wikipedia](https://en.wikipedia.org/wiki/Animator_vs._Animation).
Vox / Harris: [Storybench](https://www.storybench.org/?p=12232),
[PremiumBeat (Vox look)](https://www.premiumbeat.com/blog/replicating-vox-motion-graphic/),
[How I Make My Maps](https://rosetta.to/u/johnnyharris/how-i-make-my-maps).
Remotion: [captions](https://remotion.dev/docs/captions/create-tiktok-style-captions),
[transitions](https://www.remotion.dev/docs/transitions), [maps](https://www.remotion.dev/docs/maps),
[licence](https://www.remotion.dev/docs/license/pricing).
Safe zones: [revid](https://www.revid.ai/youtube-shorts-safe-zone).
