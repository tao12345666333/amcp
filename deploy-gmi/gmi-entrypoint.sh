#!/usr/bin/env sh
set -eu

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8080}"
WORK_DIR="${AMCP_WORK_DIR:-/workspace}"
GMI_BASE="${GMI_MAAS_BASE_URL:-https://api.gmi-serving.com}"

case "$GMI_BASE" in
    */v1) OPENAI_BASE="${GMI_BASE%/}" ;;
    *) OPENAI_BASE="${GMI_BASE%/}/v1" ;;
esac

export AMCP_OPENAI_BASE="${AMCP_OPENAI_BASE:-$OPENAI_BASE}"

if [ -n "${GMI_MAAS_API_KEY:-}" ] && [ -z "${OPENAI_API_KEY:-}" ]; then
    export OPENAI_API_KEY="$GMI_MAAS_API_KEY"
fi

RAW_MODEL="${AMCP_CHAT_MODEL:-${GMI_MODELS:-DeepSeek-V3.1-Terminus}}"
case "$RAW_MODEL" in
    *,*) MODEL="${RAW_MODEL%%,*}" ;;
    *) MODEL="$RAW_MODEL" ;;
esac
export AMCP_CHAT_MODEL="$MODEL"

CONFIG_ROOT="${XDG_CONFIG_HOME:-/root/.config}"
CONFIG_DIR="$CONFIG_ROOT/amcp"
CONFIG_FILE="$CONFIG_DIR/config.toml"
mkdir -p "$CONFIG_DIR" "$WORK_DIR"

if [ ! -f "$CONFIG_FILE" ] || [ "${AMCP_GMI_REWRITE_CONFIG:-0}" = "1" ]; then
    cat > "$CONFIG_FILE" <<EOF
[server]
host = "$HOST"
port = $PORT
session_timeout_minutes = 1440
max_sessions = 100
work_dir = "$WORK_DIR"
default_agent = "default"

[server.auth]
enabled = false

[server.cors]
enabled = true
allow_origins = ["*"]
allow_methods = ["*"]
allow_headers = ["*"]
allow_credentials = false

[chat]
api_type = "openai"
base_url = "$AMCP_OPENAI_BASE"
model = "$MODEL"
mcp_tools_enabled = true
write_tool_enabled = true
edit_tool_enabled = true
tool_loop_limit = 300
bash_tool_limit = 100
default_max_lines = 400

[context]
progressive_tools = true
progressive_skills = true
EOF
fi

exec amcp serve --host "$HOST" --port "$PORT" --work-dir "$WORK_DIR"
