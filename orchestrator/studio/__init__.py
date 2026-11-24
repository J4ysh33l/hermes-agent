"""The studio: video, audio, b-roll and images made on your server (posting is another workflow's job).

Modules:
- ``settings``        the ``studio:`` section of brief.yaml (voices, speed, threads, models).
- ``voice``           text → speech with Kokoro or Edge TTS; Hinglish in Latin script goes into Devanagari first.
- ``voice_worker``    runs inside the studio's own environment (``install.sh``), never imported here.
- ``profile``         a page's profile (look, motion, captions, voice, writing, allowed elements); ``profiles/`` built-ins.
- ``storyboard``      a storyboard JSON → checked, frozen scenes (17 types; the format is its docstring).
- ``writer``          notes or a draft script → a storyboard with 3 hook variants (Gemini, prompted from the
                      profile's writing and PLAYBOOK.md; checked in code: evidence from the notes only).
- ``custom``          custom scenes: Claude writes a component for one video; checked (static, tsc, probe
                      frames, review) or drawn as its fallback library scene. ``LIMITS``: the pipeline's real limits.
- ``direction``       voice directions in the narration ([beat], [pause 0.8], [slow], [fast]).
- ``video``           storyboard → voice → word captions → Remotion render (1080×1920, 30 fps).
- ``cover``           a storyboard scene + 2–5 big words → a 1080×1920 cover PNG (Remotion still).
- ``audio``           the soundtrack at -14 LUFS (gain + limiter, measured with loudnorm).
- ``qc``              the finished file checked with ffprobe/ffmpeg (format, length, clipping, loudness, dead air).
- ``drive``           uploads to the user's Drive folder "Hermes Studio" (scope drive.file).
- ``handoff``         Claude on the user's plan through the handoff repo (request.md → storyboard.json).
- ``queue``           jobs: writing → ready → rendered → done; renders in the window, delivers to Telegram/Drive.
- ``remotion/``       the React templates Remotion renders (its own Node project; ``install.sh``).
- ``chat``            /studio voice · voices · write · make · run · pick · queue.
- ``cli``             ``python -m orchestrator.studio voice|write|video|cover|queue|auth|wishes ...`` on the host.
"""
