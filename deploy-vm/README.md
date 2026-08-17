# AMCP on a bare VM (no Docker)

Deploy AMCP from the public repo (`https://github.com/tao12345666333/amcp`)
directly onto a Linux server, running on a uv-managed venv with the same
in-place self-restart ability as the `deploy_k8s` setup.

## Layout on the server

| Path | Purpose |
| --- | --- |
| `/opt/amcp/repo` | Git clone of the amcp repo. `git pull` + self-restart picks up new code. |
| `/opt/amcp/venv` | uv virtualenv (created with `uv venv --python 3.12`). |
| `/opt/amcp/data` | `AMCP_WORK_DIR`: logs, generated commands; `XDG_CONFIG_HOME` is `/opt/amcp/data/.config`, so `config.toml`, sessions, memory, and Telegram state live under `/opt/amcp/data/.config/amcp`. |
| `/opt/amcp/run` | Runtime control files only (supervisor PID + in-place restart marker). |
| `/etc/amcp/amcp.env` | Runtime configuration (chmod 600): LLM base URL, API key, model, optional Telegram settings. |
| `/usr/local/bin/amcp-vm-supervisor` | Supervisor loop (systemd `ExecStart`). |
| `/usr/local/bin/amcp-vm-restart` | In-place restart helper (`/vm:restart` or manual). |
| `/etc/systemd/system/amcp.service` | systemd unit; binds 127.0.0.1:8080. |

## Self-restart without stopping the service

Mirrors the K8s (`deploy_k8s`) and e2b designs:

```text
systemd (Restart=always)          <- only acts when the supervisor exits
└── amcp-vm-supervisor            <- bash loop, long-running
    └── amcp serve --telegram     <- the actual server, a CHILD process
```

- In-place restart (no systemd restart, code checkout/venv/state survive):
  - from inside the agent: `/vm:restart` (slash command installed by the
    supervisor on every start at `$AMCP_WORK_DIR/.amcp/commands/vm/restart.toml`)
  - from a shell: `amcp-vm-restart` (or `systemctl kill --signal=SIGUSR1 amcp.service`)
  - flow: marker file `/opt/amcp/run/restart-requested` is touched, the child
    gets SIGTERM, the supervisor sees the marker and immediately re-execs
    `amcp serve`. systemd never notices.
- Real crash (no marker): the supervisor exits with the child's status and
  systemd restarts the service (`Restart=always`).
- Upgrade flow: `cd /opt/amcp/repo && git pull && amcp-vm-restart` — the
  supervisor runs `uv pip install --no-editable '.[telegram]'` before
  every start, so the new code is installed into the venv automatically.

## Deploy (from your workstation)

`install-vm.sh` installs its sibling scripts and the systemd unit from its
own directory, so copy the whole `deploy_vm/` payload (not just the installer)
to the server.

```bash
# 1. Create the env file locally from your existing config (never commit it)
cp deploy_vm/amcp.env.example deploy_vm/amcp.env
#    or reuse values from deploy_k8s/secret.yaml (same keys)
$EDITOR deploy_vm/amcp.env

# 2. Copy the deploy_vm payload + your env to the server
ssh root@<server> 'mkdir -p /tmp/deploy_vm'
scp deploy_vm/install-vm.sh \
    deploy_vm/amcp-vm-supervisor.sh \
    deploy_vm/amcp-vm-restart.sh \
    deploy_vm/amcp.service \
    deploy_vm/amcp.env \
    root@<server>:/tmp/deploy_vm/

# 3. Run the installer on the server (idempotent; re-run to update/redeploy)
ssh root@<server> 'bash /tmp/deploy_vm/install-vm.sh /tmp/deploy_vm/amcp.env && rm -rf /tmp/deploy_vm'

# 4. Verify
ssh root@<server> 'systemctl status amcp --no-pager; curl -fsS http://127.0.0.1:8080/api/v1/health'
```

`install-vm.sh` is idempotent; re-running it updates scripts/unit and redeploys.

## Day-2 operations

| Task | Command |
| --- | --- |
| Logs | `journalctl -u amcp -f` |
| In-place restart | `ssh root@<server> amcp-vm-restart` |
| Upgrade to latest main | `ssh root@<server> 'cd /opt/amcp/repo && git pull && amcp-vm-restart'` |
| Full service restart | `systemctl restart amcp` |
| Change config | edit `/etc/amcp/amcp.env`, then `systemctl restart amcp` (env is only read at process start) |
| Edit repo code manually | `cd /opt/amcp/repo` … then `amcp-vm-restart` |

## Notes / security

- All AMCP state lives under `/opt/amcp` on the root ext4 filesystem and
  survives reboots: repo/venv, work dir + config (`/opt/amcp/data`), and the
  runtime control dir (`/opt/amcp/run`). Secrets are at `/etc/amcp/amcp.env`.
  Nothing is on tmpfs — `/run` is not used at all — so a reboot loses nothing.
  (The very first deployment put repo/venv under `/run`, which is tmpfs and
  wiped on reboot; that's what lost data. Everything now lives under `/opt`.)
- The server binds to `127.0.0.1` (override with `AMCP_VM_HOST` in
  `/etc/amcp/amcp.env`). AMCP's HTTP API has no built-in auth in this
  configuration, so if you expose it publicly put an authenticating reverse
  proxy in front. Telegram uses outbound long polling — no inbound port is
  needed for the bot.
- `/etc/amcp/amcp.env` holds the API key and Telegram token: mode 0600, never
  commit it to git.
- The venv pins Python 3.12 via `uv venv --python 3.12` (uv installs it on
  first use), matching the Docker images, instead of using the OS Python.
- Before switching the supervisor loop on, verify the unit logs show the
  server healthy for ~2 minutes (`journalctl -u amcp --since -2m`). Otherwise
  enable the safeguard `Environment=AMCP_VM_MIN_UPTIME=30` in the unit so a
  crash-looping child can't be hidden by the supervisor.
