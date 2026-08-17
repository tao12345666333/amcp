#!/usr/bin/env bash
# Install or update AMCP on a bare VM (Ubuntu/Debian) without Docker.
# Usage: bash install-vm.sh [path-to-amcp.env]
# Idempotent: safe to re-run; it updates the repo, venv, scripts, and unit.
set -euo pipefail

REPO_URL="${AMCP_REPO_URL:-https://github.com/tao12345666333/amcp.git}"
REPO_DIR=/opt/amcp/repo
VENV_DIR=/opt/amcp/venv
WORK_DIR=/opt/amcp/data
RUNTIME_DIR=/opt/amcp/run
ENV_FILE=/etc/amcp/amcp.env
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_SRC="${1:-${SELF_DIR}/amcp.env}"

if [ "$(id -u)" -ne 0 ]; then
    echo "install-vm.sh must run as root" >&2
    exit 1
fi

echo "==> [1/7] Install prerequisites (git, uv)"
export DEBIAN_FRONTEND=noninteractive
if ! command -v git >/dev/null; then
    apt-get update -qq && apt-get install -y -qq git
fi
if ! command -v uv >/dev/null 2>&1; then
    if [ -x "$HOME/.local/bin/uv" ]; then
        export PATH="$HOME/.local/bin:$PATH"
    else
        curl -LsSf https://astral.sh/uv/install.sh | sh
        export PATH="$HOME/.local/bin:$PATH"
    fi
fi
UV_BIN="$(command -v uv)"
# Do not create a self-referential symlink when uv already lives in
# /usr/local/bin (e.g. from a previous run of this script).
if [ "${UV_BIN}" != "/usr/local/bin/uv" ]; then
    ln -sf "${UV_BIN}" /usr/local/bin/uv
fi

echo "==> [2/7] Clone/update repo at ${REPO_DIR}"
mkdir -p /opt/amcp
if [ -d "${REPO_DIR}/.git" ]; then
    git -C "${REPO_DIR}" fetch --prune origin
    git -C "${REPO_DIR}" reset --hard origin/main
else
    git clone --depth=50 "${REPO_URL}" "${REPO_DIR}"
fi

echo "==> [3/7] Create venv (python 3.12) and install amcp"
uv venv --clear --python 3.12 "${VENV_DIR}"
# Install the project non-editably into the standalone venv. `uv sync` skips
# the root package when the venv is not the active project venv, so install
# it explicitly; supervisor re-syncs deps on every start via the same command.
(cd "${REPO_DIR}" && uv pip install --python "${VENV_DIR}/bin/python" --no-editable '.[telegram]')

echo "==> [4/7] Install supervisor/restart scripts and systemd unit"
install -m 0755 "${SELF_DIR}/amcp-vm-supervisor.sh" /usr/local/bin/amcp-vm-supervisor
install -m 0755 "${SELF_DIR}/amcp-vm-restart.sh" /usr/local/bin/amcp-vm-restart
install -m 0644 "${SELF_DIR}/amcp.service" /etc/systemd/system/amcp.service

echo "==> [5/7] Install runtime config"
# Stop any running instance so the state migration below captures a quiet
# snapshot (SQLite WAL) rather than copying live databases.
if systemctl is-active --quiet amcp.service; then
    echo "    stopping amcp.service for state migration"
    systemctl stop amcp.service
fi
mkdir -p /etc/amcp "${WORK_DIR}" "${RUNTIME_DIR}"
# Migrate state from the old /var/lib/amcp layout (pre-/opt consolidation)
# so existing sessions/memory/config survive the move. Idempotent: only
# copies when the old dir has content and the new work dir is still empty.
if [ -d /var/lib/amcp ] && [ "$(ls -A /var/lib/amcp 2>/dev/null)" ]; then
    if [ "$(ls -A "${WORK_DIR}" 2>/dev/null)" ]; then
        echo "    ${WORK_DIR} already populated; leaving /var/lib/amcp in place"
    else
        echo "    migrating /var/lib/amcp -> ${WORK_DIR}"
        cp -a /var/lib/amcp/. "${WORK_DIR}/"
    fi
fi
if [ -f "${ENV_SRC}" ]; then
    install -m 0600 "${ENV_SRC}" "${ENV_FILE}"
    echo "    installed ${ENV_FILE} (0600)"
elif [ -f "${ENV_FILE}" ]; then
    echo "    keeping existing ${ENV_FILE}"
else
    echo "ERROR: no env file at ${ENV_SRC} or ${ENV_FILE}" >&2
    echo "Copy deploy_vm/amcp.env.example, fill it in, and re-run." >&2
    exit 1
fi

echo "==> [6/7] Enable and (re)start amcp.service"
systemctl daemon-reload
systemctl enable amcp.service
systemctl restart amcp.service

echo "==> [7/7] Wait for health endpoint"
for i in $(seq 1 30); do
    if curl -fsS -m 2 http://127.0.0.1:8080/api/v1/health >/dev/null 2>&1; then
        echo "    AMCP is healthy on 127.0.0.1:8080"
        systemctl --no-pager --full status amcp.service | head -5
        exit 0
    fi
    sleep 2
done
echo "ERROR: health check did not pass in 60s; recent logs:" >&2
journalctl -u amcp --no-pager -n 30 >&2
exit 1
