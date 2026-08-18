# AMCP on Kubernetes

Manifests to run AMCP as a single-replica Deployment using the
`ghcr.io/tao12345666333/amcp:gmi-latest` image. LLM provider settings
(base URL, API key, model) are passed purely through environment variables,
same as the GMI AgentBox flow.

## Self-restart without stopping the pod

The core feature mirrors `e2b/start-sandbox.sh` + `e2b/restart-amcp.sh`:

```text
tini (PID 1)
└── /scripts/supervisor.sh        <- from ConfigMap, replaces image entrypoint
    └── /usr/local/bin/gmi-entrypoint   <- stock gmi entrypoint, runs as a child
        └── amcp serve [--telegram]
```

- The agent can run `/k8s:restart` (slash command installed into
  `/workspace/.amcp/commands/k8s/restart.toml` on first boot), which executes
  `/scripts/restart-amcp.sh`: it touches `/tmp/amcp-restart-requested` and
  SIGTERMs the AMCP process.
- `supervisor.sh` sees the marker and starts AMCP again **without the
  container ever exiting** — the pod keeps running, `restartCount` stays
  unchanged, and container-local state (e.g. anything installed outside
  `/workspace`) survives.
- If AMCP exits **without** the marker (a real crash), the supervisor exits
  too and Kubernetes restarts the container as usual.
- Manual restart from outside: `kubectl -n amcp exec deploy/amcp -- /scripts/restart-amcp.sh`
- Set env `AMCP_K8S_REINSTALL_ON_RESTART=1` on the Deployment to make
  `restart-amcp.sh` run `uv sync --reinstall-package amcp-agent` in `/app`
  before the restart (equivalent to the e2b default, off here by default).

## Files

| File | Purpose |
| --- | --- |
| `namespace.yaml` | `amcp` namespace. |
| `configmap-scripts.yaml` | `supervisor.sh` + `restart-amcp.sh`, mounted at `/scripts`. |
| `deployment.yaml` | Single replica, `Recreate` strategy, no resource requests/limits, probes on `/api/v1/health`. `/workspace` is an `emptyDir` — no persistence; sessions, memory, config, and logs live only as long as the pod. |
| `secret.example.yaml` | Template for the `amcp-env` Secret (copy to `secret.yaml`, which is gitignored). |
| `kustomization.yaml` | `kubectl apply -k` entrypoint (Secret intentionally excluded). |

## Deploy

```bash
# 1. Create the Secret with real values (never commit it)
cp deploy-k8s/secret.example.yaml deploy-k8s/secret.yaml
$EDITOR deploy-k8s/secret.yaml

# 2. Apply everything
kubectl apply -k deploy-k8s/
kubectl apply -f deploy-k8s/secret.yaml

# 3. Watch it come up
kubectl -n amcp rollout status deployment/amcp
kubectl -n amcp logs -f deployment/amcp
```

Required Secret keys: `OPENAI_API_KEY` (or `GMI_MAAS_API_KEY`) and
`AMCP_CHAT_MODEL` (or `GMI_MODELS`). Optional: `AMCP_OPENAI_BASE` /
`GMI_MAAS_BASE_URL` (defaults to `https://api.gmi-serving.com/v1`),
`AMCP_TELEGRAM_BOT_TOKEN` + `AMCP_TELEGRAM_ALLOWED_USERS` to enable the
Telegram polling bot.

## Access

No Service is created on purpose. Reach the API directly through the pod:

```bash
kubectl -n amcp port-forward deployment/amcp 8080:8080
curl -fsS http://localhost:8080/api/v1/health
curl -fsS http://localhost:8080/api/v1/info
```

If you later expose the API through a Service/Ingress, put an authenticating
gateway in front — AMCP's gmi configuration ships with
`server.auth.enabled = false`.

## Persistence (optional)

`/workspace` is an `emptyDir` by default: sessions, memory, generated config,
skills, and logs are lost when the pod is replaced (in-place self-restart via
`/k8s:restart` does NOT wipe them, since the container keeps running).

If you need the data to survive pod rescheduling, create and manage your own
PVC — it is intentionally not included in this directory:

```bash
# 1. Create a PVC yourself, e.g.:
kubectl -n amcp apply -f - <<EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: amcp-workspace
spec:
  accessModes: ["ReadWriteOnce"]
  resources:
    requests:
      storage: 10Gi
EOF
```

Then point the `workspace` volume in `deployment.yaml` at it:

```yaml
        - name: workspace
          persistentVolumeClaim:
            claimName: amcp-workspace
```

The `Recreate` strategy already matches ReadWriteOnce volumes.

## Notes

- `imagePullPolicy: Always` + the moving `gmi-latest` tag means a pod
  reschedule picks up the newest image. Pin `image:` to `gmi-<version>` if
  you prefer stability.
- Liveness probe is intentionally tolerant (`failureThreshold: 12`) so a
  self-restart does not make Kubernetes kill the container mid-restart.
