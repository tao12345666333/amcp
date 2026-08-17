#!/usr/bin/env bash
# amcp-vm-restart: request an in-place AMCP restart without a systemd restart.
# Companion to amcp-vm-supervisor. Safe to run manually; also invoked by the
# agent itself through the /vm:restart slash command.
set -u

RUNTIME_DIR="${AMCP_RUNTIME_DIR:-/opt/amcp/run}"
MARKER="${RUNTIME_DIR}/restart-requested"
PID_FILE="${RUNTIME_DIR}/amcp.pid"
DELAY="${AMCP_VM_RESTART_DELAY:-1}"
LOG_FILE="${AMCP_WORK_DIR:-/opt/amcp/data}/logs/vm-restart.log"

mkdir -p "${RUNTIME_DIR}" "$(dirname "${LOG_FILE}")"

{
    echo "[amcp-vm] restart requested at $(date -Is)"
    [ -n "${AMCP_VM_RESTART_REASON:-}" ] && echo "[amcp-vm] reason: ${AMCP_VM_RESTART_REASON}"

    : > "${MARKER}"
    [ "${DELAY}" != "0" ] && sleep "${DELAY}"

    if [ -f "${PID_FILE}" ]; then
        pid="$(cat "${PID_FILE}")"
        if [ -n "${pid}" ] && kill -0 "${pid}" 2>/dev/null; then
            echo "[amcp-vm] stopping AMCP pid=${pid} (service stays up)"
            kill -TERM "${pid}"
            exit 0
        fi
    fi

    echo "[amcp-vm] pid file missing/stale; signalling supervisor via SIGUSR1"
    systemctl kill --signal=SIGUSR1 amcp.service
} >> "${LOG_FILE}" 2>&1
