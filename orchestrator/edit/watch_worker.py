"""Looks at the footage for the editor (runs in the studio venv, which has OpenCV and numpy).

stdin:  {"video": "source.mp4", "step": 1.0}
stdout: {"step": 1.0, "samples": [{"t": 0.0, "face": [x, y, w, h] | null, "faces": 1, "light": 0–255,
         "sharp": n, "motion": 0–255, "cut": false}, ...]}

The video is decoded once by ffmpeg at 5 frames a second, grey, 360×640. For every ``step`` seconds:
the largest frontal face (fractions of the frame), the mean brightness, the sharpness (variance of the
Laplacian over the face, or the whole frame without one), how much moved (mean change between frames)
and whether the picture jumped (a cut inside the raw footage, or something covering the lens).
"""

from __future__ import annotations

import json
import subprocess
import sys

import cv2
import numpy as np

W, H, FPS = 360, 640, 5


def main() -> None:
    job = json.loads(sys.stdin.read())
    step = float(job.get("step", 1.0))
    every = max(1, round(step * FPS))
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    pipe = subprocess.Popen(["ffmpeg", "-v", "error", "-i", job["video"], "-vf", f"fps={FPS},scale={W}:{H},format=gray",
                             "-f", "rawvideo", "-"], stdout=subprocess.PIPE)
    samples, prev, moves, n = [], None, [], 0
    size = W * H
    while True:
        raw = pipe.stdout.read(size)
        if len(raw) < size:
            break
        frame = np.frombuffer(raw, np.uint8).reshape(H, W)
        if prev is not None:
            moves.append(float(np.mean(cv2.absdiff(frame, prev))))
        prev = frame
        if n % every == 0:
            found = cascade.detectMultiScale(frame, scaleFactor=1.1, minNeighbors=6, minSize=(40, 40))
            face, region = None, frame
            if len(found):
                x, y, w, h = max(found, key=lambda f: f[2] * f[3])
                face = [round(x / W, 3), round(y / H, 3), round(w / W, 3), round(h / H, 3)]
                region = frame[y:y + h, x:x + w]
            motion = max(moves) if moves else 0.0
            samples.append({"t": round(n / FPS, 2), "face": face, "faces": len(found),
                            "light": round(float(np.mean(frame)), 1),
                            "sharp": round(float(cv2.Laplacian(region, cv2.CV_64F).var()), 1),
                            "motion": round(float(np.mean(moves)) if moves else 0.0, 2), "cut": motion > 40})
            moves = []
        n += 1
    pipe.wait()
    print(json.dumps({"step": step, "samples": samples}))


if __name__ == "__main__":
    main()
