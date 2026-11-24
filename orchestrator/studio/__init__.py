"""The studio: video, audio, b-roll and images made on your server (posting is another workflow's job).

Modules:
- ``settings``        the ``studio:`` section of brief.yaml (voices, speed, threads, models).
- ``voice``           text → speech with Kokoro; Hinglish in Latin script is put into Devanagari first.
- ``kokoro_worker``   runs inside Kokoro's own environment (``install_kokoro.sh``), never imported here.
- ``chat``            /studio voice · voices.
- ``cli``             ``python -m orchestrator.studio voice "text" --out x.wav`` on the host.
"""
