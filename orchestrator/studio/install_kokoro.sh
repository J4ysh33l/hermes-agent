#!/usr/bin/env bash
# Kokoro (local text-to-speech) in its own environment: $HERMES_HOME/venvs/kokoro, models in
# $HERMES_HOME/studio/models. Hermes' environment is never touched. Re-running is safe.
# Size: ~170 MB of packages + 120 MB of model files. CPU only (no PyTorch, no GPU).
set -euo pipefail
HOME_DIR="${HERMES_HOME:-$HOME/.hermes}"
VENV="$HOME_DIR/venvs/kokoro"
MODELS="$HOME_DIR/studio/models"
BASE="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
PY="${PYTHON:-python3}"   # 3.10 to 3.13 (kokoro-onnx 0.6.1 does not support 3.14 yet)

if [ ! -x "$VENV/bin/python" ]; then
    "$PY" -m venv "$VENV"
fi
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet "kokoro-onnx==0.6.1" "onnxruntime==1.32.0" "numpy==2.5.5" \
    "phonemizer==3.6.0" "espeakng-loader==0.2.4"
echo "ready   $VENV (kokoro-onnx 0.6.1)"

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
fetch kokoro-v1.0.int8.onnx 6e742170d309016e5891a994e1ce1559c702a2ccd0075e67ef7157974f6406cb
fetch voices-v1.0.bin bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d
echo "Try it: python -m orchestrator.studio voice \"Hello from Kokoro\" --out ~/hello.wav"
