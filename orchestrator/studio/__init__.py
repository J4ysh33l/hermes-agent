"""The studio: video, audio, b-roll and images made on your server (posting is another workflow's job).

Modules:
- ``settings``        the ``studio:`` section of brief.yaml (voices, speed, threads, models).
- ``voice``           text → speech with Kokoro or Edge TTS; Hinglish in Latin script goes into Devanagari first.
- ``voice_worker``    runs inside the studio's own environment (``install.sh``), never imported here.
- ``profile``         a page's profile (look, motion, captions, voice, writing, allowed elements); ``profiles/`` built-ins.
- ``storyboard``      a storyboard JSON → checked, frozen scenes (6 types: title, bullets, code, stat, image, compare).
- ``video``           storyboard → voice → word captions → Remotion render (1080×1920, 30 fps).
- ``remotion/``       the React templates Remotion renders (its own Node project; ``install.sh``).
- ``chat``            /studio voice · voices.
- ``cli``             ``python -m orchestrator.studio voice|video ...`` on the host.
"""
