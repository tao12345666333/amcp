# AMCP on GMI Cloud AgentBox

This directory contains the files needed to prepare AMCP for GMI Cloud AgentBox
Marketplace registration. The current plan targets **GMI CE Deployment + MaaS
integration**, where GMI hosts the container and injects MaaS model access
environment variables at runtime.

## GMI Requirements Covered

- The image does not include `GMI_MAAS_API_KEY`; GMI injects it at runtime.
- The entrypoint maps GMI-injected variables to AMCP's existing OpenAI-compatible config:
  - `GMI_MAAS_BASE_URL` -> `AMCP_OPENAI_BASE`
  - `GMI_MAAS_API_KEY` -> `OPENAI_API_KEY`
  - `GMI_MODELS` -> AMCP `chat.model`
- Set `AMCP_CHAT_MODEL` if you need to choose a primary AMCP model from multiple GMI models.
- The container listens on `8080`, matching GMI's default port mapping `443 -> 8080`.
- The health check path is `/api/v1/health`; API docs are available at `/docs`.

## Files

| File | Purpose |
| --- | --- |
| `Dockerfile` | AMCP container image prepared for GMI AgentBox. |
| `gmi-entrypoint.sh` | Generates AMCP runtime config and maps GMI MaaS environment variables. |
| `agentbox-registration.json` | Draft values for the GMI registration wizard and smoke test commands. |

## Local Build and Test

Run from the repository root:

```bash
docker build -f deploy-gmi/Dockerfile -t amcp-gmi:latest .
docker run --rm -p 8080:8080 \
  -e GMI_MAAS_BASE_URL=https://api.gmi-serving.com \
  -e GMI_MAAS_API_KEY="$GMI_MAAS_API_KEY" \
  -e GMI_MODELS="zai-org/GLM-5.2-FP8" \
  amcp-gmi:latest
```

Verify from another terminal:

```bash
curl -fsS http://localhost:8080/api/v1/health
curl -fsS http://localhost:8080/api/v1/info
```

## Suggested GMI Registration Wizard Values

### Step 1: Basics & Template

- Project name: `amcp-agent`
- Template/path: choose a custom container image.

### Step 2: Infrastructure

- Deployment path: `GMI CE Deployment`
- Docker image source:
  - Upload a local image, or
  - Registry URL: `ghcr.io/tao12345666333/amcp:gmi-0.11.0`
- Compute tier: `Container, 2 vCPU, 4 GB RAM`
- Region: `IOWA IDC-1`
- MaaS integration: enabled
- Models: select the GMI MaaS models AMCP should be allowed to call at runtime

### Step 3: Networking

- Protocol: `HTTPS/2`
- Listening port: `443`
- Internal port: `8080`
- Port name: `web`

### Step 4: Env Variables

GMI automatically injects and locks:

- `GMI_MAAS_API_KEY`
- `GMI_MAAS_BASE_URL`
- `GMI_MODELS`

Optional custom variables:

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `AMCP_WORK_DIR` | `TEXT` | `/workspace` | Default working directory for AMCP sessions. |
| `AMCP_GMI_REWRITE_CONFIG` | `TEXT` | `0` | Set to `1` to rewrite the AMCP config on every startup. |
| `AMCP_CHAT_MODEL` | `TEXT` | unset | Optional override for the primary AMCP model instead of `GMI_MODELS`. |

Do not manually add `GMI_MAAS_API_KEY` to the image or registration form.

### Step 5: Review & Register

After registration, test the live endpoint first:

```bash
curl -fsS https://<gmi-public-url>/api/v1/health
curl -fsS https://<gmi-public-url>/api/v1/info
```

## Marketplace Listing Draft

- Name: `AMCP Agent`
- Short description: `A coding-agent runtime with CLI, HTTP/WebSocket APIs, tools, subagents, skills, hooks, memory, and automation.`
- Category: Developer tools / Coding agent
- Access endpoint: `https://<gmi-public-url>`
- Health endpoint: `https://<gmi-public-url>/api/v1/health`
- API docs: `https://<gmi-public-url>/docs`
- Infrastructure badge target: `Verified`, because the image runs on GMI infrastructure and uses GMI MaaS.

## Follow-ups to Confirm

- Final image registry URL and tag.
- Marketplace copy, screenshots, and pricing information.
- Exact GMI MaaS model list to enable.
