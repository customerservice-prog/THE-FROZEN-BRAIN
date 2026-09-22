#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="\${COLDVAULT_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
PYTHON_BIN="\${PYTHON_BIN:-python}"
LLAMA_SERVER_BIN="\${LLAMA_SERVER_BIN:-llama-server}"
MODEL_DIR="\${COLDVAULT_MODEL_DIR:-$HOME/coldvault-models}"
COLDVAULT_HOME="\${COLDVAULT_HOME:-$HOME/.coldvault}"
LLAMA_PORT="\${COLDVAULT_LLAMA_PORT:-11434}"
UI_PORT="\${COLDVAULT_UI_PORT:-7777}"
LOG_DIR="$COLDVAULT_HOME/logs"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required local command: $1" >&2
    echo "Restore it from the ColdVault offline software archive. This script will not download it." >&2
    exit 1
  fi
}

require_command "$PYTHON_BIN"
require_command "$LLAMA_SERVER_BIN"

if [ ! -d "$REPO_ROOT/coldvault" ]; then
  echo "ColdVault source not found at: $REPO_ROOT" >&2
  exit 1
fi

mkdir -p "$COLDVAULT_HOME" "$LOG_DIR"

cd "$REPO_ROOT"
SELECTION_JSON="$("$PYTHON_BIN" -m coldvault.cli survival-select "$MODEL_DIR")"
MODEL_PATH="$(printf '%s' "$SELECTION_JSON" | "$PYTHON_BIN" -c 'import json,sys; print(json.load(sys.stdin).get("model_path") or "")')"
CONTEXT_TOKENS="$(printf '%s' "$SELECTION_JSON" | "$PYTHON_BIN" -c 'import json,sys; print(json.load(sys.stdin).get("context_tokens") or 2048)')"
SELECTION_REASON="$(printf '%s' "$SELECTION_JSON" | "$PYTHON_BIN" -c 'import json,sys; print(json.load(sys.stdin).get("reason") or "")')"

if [ -z "$MODEL_PATH" ]; then
  echo "No safe GGUF model could be selected." >&2
  echo "$SELECTION_REASON" >&2
  exit 1
fi

export COLDVAULT_HOME
export COLDVAULT_BASE_URL="http://127.0.0.1:$LLAMA_PORT/v1"
export COLDVAULT_MODEL="frozen-brain-mobile"
export COLDVAULT_TOOL_PERMISSION="\${COLDVAULT_TOOL_PERMISSION:-read}"

echo "ColdVault Survival Mode"
echo "Model: $MODEL_PATH"
echo "Context: $CONTEXT_TOKENS tokens"
echo "Data: $COLDVAULT_HOME"
echo "Internet: not required"

"$LLAMA_SERVER_BIN" \
  -m "$MODEL_PATH" \
  --alias frozen-brain-mobile \
  --host 127.0.0.1 \
  --port "$LLAMA_PORT" \
  -c "$CONTEXT_TOKENS" \
  -ngl 0 \
  >"$LOG_DIR/llama-server.log" 2>&1 &
LLAMA_PID=$!
CORE_PID=""

cleanup() {
  set +e
  if [ -n "$CORE_PID" ] && kill -0 "$CORE_PID" >/dev/null 2>&1; then
    kill -INT "$CORE_PID" >/dev/null 2>&1
    wait "$CORE_PID" >/dev/null 2>&1
  fi
  if kill -0 "$LLAMA_PID" >/dev/null 2>&1; then
    kill "$LLAMA_PID" >/dev/null 2>&1
    wait "$LLAMA_PID" >/dev/null 2>&1
  fi
}

on_signal() {
  cleanup
  exit 0
}

trap cleanup EXIT
trap on_signal INT TERM

READY=0
for _ in $(seq 1 90); do
  if ! kill -0 "$LLAMA_PID" >/dev/null 2>&1; then
    echo "llama-server exited during startup. See $LOG_DIR/llama-server.log" >&2
    exit 1
  fi
  if "$PYTHON_BIN" - "$LLAMA_PORT" >/dev/null 2>&1 <<'PY'
import sys
import urllib.request
port = int(sys.argv[1])
with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/models", timeout=1) as response:
    raise SystemExit(0 if response.status == 200 else 1)
PY
  then
    READY=1
    break
  fi
  sleep 1
done

if [ "$READY" -ne 1 ]; then
  echo "Local model server did not become ready. See $LOG_DIR/llama-server.log" >&2
  exit 1
fi

MODEL_CONFIG="$COLDVAULT_HOME/mobile-models.json"
LAN_URL=""

if { [ -n "${COLDVAULT_DISCOVERY_KEY:-}" ] || [ -n "${COLDVAULT_DISCOVERY_KEY_FILE:-}" ]; } && [ -n "${COLDVAULT_ACCESS_TOKEN:-}" ]; then
  DISCOVERY_JSON="$("$PYTHON_BIN" -m coldvault.cli discover --timeout "${COLDVAULT_DISCOVERY_TIMEOUT:-3}" 2>/dev/null || printf '[]')"
  LAN_URL="$(printf '%s' "$DISCOVERY_JSON" | "$PYTHON_BIN" -c 'import json,sys; x=json.load(sys.stdin); print((x[0].get("url") if x else "") or "")' 2>/dev/null || true)"
fi

if [ -n "$LAN_URL" ]; then
  "$PYTHON_BIN" - "$MODEL_CONFIG" "$LAN_URL" "$LLAMA_PORT" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
lan = sys.argv[2].rstrip("/")
local_port = int(sys.argv[3])
payload = {
    "profiles": {
        "lan-brain": {
            "purpose": "strong offline LAN brain",
            "model": "coldvault-lan",
            "base_url": lan + "/v1",
            "capabilities": ["general", "reasoning", "coding", "vision"],
            "priority": 100,
            "enabled": True,
        },
        "phone-local": {
            "purpose": "on-device survival fallback",
            "model": "frozen-brain-mobile",
            "base_url": f"http://127.0.0.1:{local_port}/v1",
            "capabilities": ["general", "reasoning", "coding"],
            "priority": 10,
            "enabled": True,
        },
    }
}
path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
PY
  export COLDVAULT_MODELS="$MODEL_CONFIG"
  export COLDVAULT_API_KEY="$COLDVAULT_ACCESS_TOKEN"
  echo "LAN brain discovered: $LAN_URL"
  echo "Failover: LAN brain -> phone-local GGUF"
else
  echo "No authenticated LAN brain discovered; using phone-local GGUF only."
fi

"$PYTHON_BIN" -m coldvault.cli checkpoint --reason "android-survival-start" >/dev/null 2>&1 || true
"$PYTHON_BIN" -m coldvault.cli serve --host 127.0.0.1 --port "$UI_PORT" &
CORE_PID=$!

echo "ColdVault is local at http://127.0.0.1:$UI_PORT"
echo "Keep this terminal open. Ctrl+C performs a graceful shutdown checkpoint."

wait "$CORE_PID"
