#!/usr/bin/env bash
# The studio's voice engines in their own environment: $HERMES_HOME/venvs/studio (Kokoro + Edge TTS),
# Kokoro's model files in $HERMES_HOME/studio/models. Hermes' environment is never touched.
# Re-running is safe. Size: ~180 MB of packages + ~200 MB of model files. CPU only (no PyTorch).
set -euo pipefail
HOME_DIR="${HERMES_HOME:-$HOME/.hermes}"
VENV="$HOME_DIR/venvs/studio"
MODELS="$HOME_DIR/studio/models"
BASE="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
PY="${PYTHON:-python3}"   # 3.10 to 3.13 (kokoro-onnx 0.6.1 does not support 3.14 yet)

if [ ! -x "$VENV/bin/python" ]; then
    "$PY" -m venv "$VENV"
fi
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet "kokoro-onnx==0.6.1" "onnxruntime==1.32.0" "numpy==2.5.5" \
    "phonemizer==3.6.0" "espeakng-loader==0.2.4" "edge-tts==7.3.1"
echo "ready   $VENV (kokoro-onnx 0.6.1, edge-tts 7.3.1)"

mkdir -p "$MODELS"
fetch() {  # name sha256
    local path="$MODELS/$1"
    if [ -f "$path" ] && echo "$2  $path" | sha256sum -c --quiet - 2>/dev/null; then
        echo "have    $path"; return
    fi
    curl -fsSL --retry 4 -o "$path.part" "$BASE/$1"
    echo "$2  $path.part" | sha256sum -c --quiet - || { echo "checksum mismatch for $1" >&2; rm -f "$path.part"; exit 1; }
    mv "$path.part" "$path"
    echo "fetched $path"
}
# fp16 by default: half precision, faster than int8 on a CPU with AVX-512 FP16 (measured 2.6x vs 2.0x
# real time), ~110 MB more RAM. int8 is the low-memory fallback: studio.kokoro_model: kokoro-v1.0.int8.onnx
fetch kokoro-v1.0.fp16.onnx c1610a859f3bdea01107e73e50100685af38fff88f5cd8e5c56df109ec880204
if [ "${KOKORO_INT8:-0}" = 1 ]; then
    fetch kokoro-v1.0.int8.onnx 6e742170d309016e5891a994e1ce1559c702a2ccd0075e67ef7157974f6406cb
fi
if [ "${KOKORO_FP32:-0}" = 1 ]; then   # optional: studio.kokoro_model: kokoro-v1.0.onnx
    fetch kokoro-v1.0.onnx 7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5
fi

# Optional: OmniVoice (your cloned voice, studio.engine: omnivoice) and the Whisper model that checks
# every line it speaks. ~1 GB of packages (CPU PyTorch) + 2 GB of models. Run: install.sh --omnivoice
if [ "${1:-}" = "--omnivoice" ] || [ "${OMNIVOICE:-0}" = 1 ]; then
    "$VENV/bin/python" -m pip install --quiet "torch==2.8.0" "torchaudio==2.8.0" \
        --index-url https://download.pytorch.org/whl/cpu
    "$VENV/bin/python" -m pip install --quiet "omnivoice==0.2.1" "faster-whisper==1.2.1"
    if [ ! -f "$MODELS/omnivoice-bf16/model.safetensors" ]; then  # the half-size copy: ~1.9 GB peak instead of 2.9
        echo "{\"engine\": \"convert\", \"out\": \"$MODELS/omnivoice-bf16\"}" | \
            "$VENV/bin/python" -I "$(dirname "$0")/voice_worker.py"
    fi
    "$VENV/bin/python" -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8')"
    echo "ready   OmniVoice 0.2.1 (bf16 copy in $MODELS/omnivoice-bf16) + faster-whisper small"
    echo "Next:   your voice file, once: python -m orchestrator.studio clone <recording> [\"its exact words\"]"
fi
fetch voices-v1.0.bin bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d
command -v ffmpeg >/dev/null || echo "note    install ffmpeg (Edge TTS audio and Telegram voice messages need it)"
fc-list 2>/dev/null | grep -qi emoji || echo "note    install an emoji font for video emoji: sudo apt install fonts-noto-color-emoji"

# Video: the Remotion project next to this script (exact versions in package.json) and Chrome's headless
# shell, which Remotion downloads for itself (~100 MB). Needs Node 18+; skipped without it.
PROJECT="$(cd "$(dirname "$0")" && pwd)/remotion"
if command -v node >/dev/null && [ "$(node -p 'process.versions.node.split(".")[0]')" -ge 18 ]; then
    (cd "$PROJECT" && npm install --no-audit --no-fund --loglevel=error && npx remotion browser ensure)
    echo "ready   $PROJECT (Remotion $(node -p "require('$PROJECT/package.json').dependencies.remotion"))"
else
    echo "note    install Node 18+ and re-run for videos (sudo apt install nodejs npm, or nodesource)"
fi
echo "Try it: python -m orchestrator.studio voice \"Hello from Kokoro\" --out ~/hello.wav"
