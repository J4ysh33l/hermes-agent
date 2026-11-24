# Voice notes

Everything the studio knows about the voice, in one place. The sources are named, and the code holds the
same values. The writer's prompt gets these rules for every script; the voice and the checks enforce the
numbers.

## Pace

| | Value | Where it lives |
|---|---|---|
| Target | **190–220 words a minute**, no pause over 0.5 s in the final cut | PLAYBOOK § 1 rule 2: Fireship reads at a median 211 wpm, Code Report at 225 |
| Your pick | **~196 wpm**. 217 (Fireship's pace) was too fast for you; 167 was too slow | PLAYBOOK § 8 |
| Default voice | Kokoro `speed 1.15`, `pause 0.10` s between sentences | `profiles/default.yaml` → `voice:` |
| Why 1.15 | Plain sentences at 1.0 measured 196, but a real 55 s short with voice directions came out at 167. Directions and pauses cost about 15% | measured 2026-11-24 |
| Word budget | `writer.WPM = 170` at speed 1.0, scaled by the page's speed: about 196 at 1.15, so a 45 s video gets ~147 words | `writer.py` |
| Numbers | counted as the voice reads them: 1887 is three words ("eighteen eighty-seven"), 2.5 million is four. A script full of years ran 53 s instead of 45 before this | `writer.said_words` |
| Silence | each line's own leading and trailing silence is trimmed, so only `pause` sets the gap; dead air over max(1.2 s, the longest scripted pause + 0.5 s) is flagged by QC | `voice.py`, `qc.py` |
| Loudness | the mix is brought to **-14 LUFS**, true peak under -1.5 dBTP; music sits ~15 dB under the voice and ducks while words are spoken | `audio.py`, `sound.py` |

A page can set its own pace in its profile (`voice: speed:` and `voice: pause:`). The writer's word budget
follows that speed automatically.

## Directions in the script

Written inside the narration, obeyed by the voice, never shown in the captions (`direction.py`):

    And the winner is [beat] India.          a 0.4 s pause at that point
    [pause 1.2] Three years later...         an exact pause (0 to 3 s), here before the sentence
    [slow] This is the part that matters.    the rest of the sentence at 0.9× the page's speed
    [fast] Faster, cheaper, smaller.         the rest at 1.1×

- Use 1–4 per video, where a human narrator would pause or lean in, never as decoration.
- Punctuation directs too: "?" lifts the voice, "..." hesitates, "—" breaks.
- **Never in a hook's first sentence:** the first seconds have no dead air (`writer._hook` refuses it).
- Captions show a word only once it is said, even inside a directed sentence: each part keeps its own time.

## Writing for the ear

These are in the writer's prompt (`writer.PROMPT`, from PLAYBOOK § 1–3):

- **The first words are the topic or the claim.** No intro, no greeting, never "in this video".
- **Hook:** first sentence 6–9 words; the whole hook scene at most 2 sentences and 16 words (~5 s). There are
  3 hooks from 3 different families; hooks 2 and 3 come as clips for you to pick from.
- One idea per sentence; sentences under 24 words; spoken English (contractions, plain words).
- Wrap 1–2 key words per scene in `*asterisks*`: the caption colours them and the camera punches in. The
  voice never hears the asterisks.
- A scene says at most ~6 s (20 words) unless it has parts (list items, bars, events): then one sentence per
  part, in order, so each part appears as it is said.
- Numbers, quotes and headlines come only from your notes.

## Engines

- **Kokoro** (default, on your server, no network): `voice_en` / `voice_hi` per profile.
- **Edge TTS** (Microsoft, online): `engine: edge`, `edge_voice_en` / `edge_voice_hi`.
- Hinglish written in Latin script is turned into Devanagari before the Hindi voice reads it; the
  captions keep your Latin spelling.
