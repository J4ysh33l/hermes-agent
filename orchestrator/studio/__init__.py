"""The studio: video, audio, b-roll and images made on your server (posting is another workflow's job).

Modules:
- ``settings``        the ``studio:`` section of brief.yaml (voices, speed, threads, models).
- ``voice``           text → speech with Kokoro or Edge TTS; Hinglish in Latin script goes into Devanagari first.
- ``voice_worker``    runs inside the studio's own environment (``install.sh``), never imported here.
- ``chat``            /studio voice · voices.
- ``cli``             ``python -m orchestrator.studio voice "text" --out x.wav`` on the host.
"""
