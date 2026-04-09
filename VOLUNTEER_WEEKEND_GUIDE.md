# Hexr Cloud — Volunteer Weekend Guide

> **Date:** April 5-6, 2026 (Saturday-Sunday)
> **Goal:** Clone the example agents, build them with Hexr, deploy to Hexr Cloud, and see A2A in action
> **Time:** ~45 minutes end-to-end
> **Prerequisites:** Python 3.11+, a terminal, Git

---

## What You'll Deploy

Three **A2A (Agent-to-Agent)** agents that collaborate via Hexr's protocol — already written and tested. You just build, push, and deploy.

```
┌───────────────────────────────────────────────────────────────────┐
│                      Hexr Cloud (GKE)                             │
│                                                                   │
│  ┌────────────────────────┐       ┌────────────────────────────┐ │
│  │  Content Creation       │       │  Financial Analysis         │ │
│  │  Pipeline               │       │  Pipeline                   │ │
│  │  (Research → Write      │       │  (Market Data → Model →    │ │
│  │   → Edit)               │       │   Risk → Synthesis)         │ │
│  └───────────┬────────────┘       └──────────────┬─────────────┘ │
│              │           A2A (mTLS)               │               │
│              └──────────┐   ┌─────────────────────┘               │
│                         ▼   ▼                                     │
│                  ┌──────────────────┐                             │
│                  │  Due Diligence    │                             │
│                  │  Orchestrator     │                             │
│                  │  (Fan-out/Fan-in) │                             │
│                  └──────────────────┘                             │
│                                                                   │
│  Every agent gets: SPIFFE identity, mTLS, OPA policy, traces     │
└───────────────────────────────────────────────────────────────────┘
```

**What makes this special:** Every agent automatically gets a cryptographic identity (SPIFFE SVID), encrypted communication (mTLS via Envoy), policy enforcement (OPA), and full observability (OpenTelemetry) — zero config from you.

### The 3 Example Agents

| Agent | File | What It Does |
|-------|------|-------------|
| **Content Pipeline** | `content_creation/content_creation_crew_a2a.py` | 3-stage pipeline: Research → Write → Edit. Uses `hexr_llm()` for traced LLM calls. |
| **Financial Analysis** | `financial_analysis/financial_analysis_agents_a2a.py` | 5-agent pipeline: Market Data → Company Research → Financial Model → Risk Assessment → Synthesis. |
| **Orchestrator** | `orchestrator/due_diligence_orchestrator.py` | Fan-out/fan-in: sends parallel A2A requests to both workers, combines results into a due diligence report. |

---

## Part 1: Sign Up for Hexr Cloud (~5 min)

### Option A: Via Dashboard (Recommended)

1. Go to **https://app.hexr.cloud/onboard**
2. Fill in:
   - **Name:** Your name or team name (e.g., `alice-team`)
   - **Email:** Your email
   - **Invite Code:** `HEXR-VOLUNTEER-2026`
3. Click **Create Account**
4. **SAVE YOUR API KEY** — it's shown only once:
   ```
   hxr_live_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```
   Copy it somewhere safe. You'll need it for every step.

### Option B: Via CLI

```bash
curl -s -X POST \
  -H "Content-Type: application/json" \
  -d '{
    "name": "YOUR-NAME-HERE",
    "contact_email": "your@email.com",
    "invite_code": "HEXR-VOLUNTEER-2026"
  }' \
  https://api.hexr.cloud/v1/tenants/onboard | python3 -m json.tool
```

Save the `api_key` from the response.

### What Just Happened — Your Own Hexr Cloud Tenant

The system automatically provisioned **your own isolated environment:**

- **Your Tenant:** A dedicated identity (`tnt_xxxx`) with 100 Hexr Compute Units (HCU)
- **Your Namespace:** `tenant-YOUR-NAME` — a Kubernetes namespace that is entirely yours
- **Network Isolation:** A `NetworkPolicy` blocks all cross-tenant traffic. Your agents can only talk to each other.
- **Resource Quota:** 3 pods max, 6 CPU limits, 8Gi memory — enough for the 3 example agents (each agent pod runs 4 containers)
- **Your API Key:** Authenticates all CLI commands to your tenant only

> **Multi-tenancy in action:** Every volunteer gets their own namespace with the same isolation guarantees. You cannot see or access anyone else's agents, and they cannot access yours. This is the same tenant isolation model Hexr provides in production.

---

## Part 2: Setup (~5 min)

### 2.1 Clone the example agents repo

```bash
git clone https://github.com/hexrdev/examples.git
cd examples
```

### 2.2 Create a virtualenv and install the Hexr SDK

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install "hexr-sdk[cli]" --extra-index-url https://pypi.hexr.cloud/simple/
```

> **Note:** `hexr-sdk[cli]` installs the Hexr CLI (`hexr build`, `hexr push`, `hexr deploy`). The `--extra-index-url` flag tells pip to check the Hexr package registry in addition to public PyPI.

### 2.3 Log in to Hexr Cloud

```bash
hexr login --key hxr_live_YOUR_API_KEY_HERE
```

Verify:

```bash
hexr login --status
```

You should see your tenant name and authentication status. To check your credits:

```bash
curl -s -H "Authorization: Bearer hxr_live_YOUR_KEY" \
  https://api.hexr.cloud/v1/auth/verify | python3 -m json.tool
```

Look for `credit_balance` under `tenant` in the response (you start with 100 HCU).

---

## Part 3: Build, Push, Deploy (~15 min)

You'll deploy the agents in order: **workers first, then orchestrator** (the orchestrator calls the workers via A2A).

### 3.1 Content Creation Pipeline

```bash
cd content_creation

# Build — analyzes Python, generates Dockerfile + K8s manifests
hexr build content_creation_crew_a2a.py --tenant YOUR_TENANT

# Push — sends to GCP Cloud Build, builds image, pushes to registry
hexr push --cloud --tenant YOUR_TENANT

# Deploy — creates pod with Envoy + A2A + pid-mapper sidecars
hexr deploy .hexr --cloud
```

Wait ~2 min for Cloud Build. You'll see a build ID and status.

### 3.2 Financial Analysis Pipeline

```bash
cd ../financial_analysis

hexr build financial_analysis_agents_a2a.py --tenant YOUR_TENANT
hexr push --cloud --tenant YOUR_TENANT
hexr deploy .hexr --cloud
```

### 3.3 Due Diligence Orchestrator

```bash
cd ../orchestrator

hexr build due_diligence_orchestrator.py --tenant YOUR_TENANT
hexr push --cloud --tenant YOUR_TENANT
hexr deploy .hexr --cloud
```

### 3.4 Check all 3 pods are running

Ask an admin to check your pods, or if you have `kubectl` access:

```bash
kubectl get pods -n tenant-YOUR_TENANT
```

Expected output — all pods **4/4 Running** (4 containers: agent + envoy + a2a-sidecar + pid-mapper):

```
NAME                                          READY   STATUS    AGE
YOUR_TENANT-content-creation-crew-a2a         4/4     Running   2m
YOUR_TENANT-financial-analysis-agents-a2a     4/4     Running   3m
YOUR_TENANT-due-diligence-orchestrator        4/4     Running   1m
```

---

## Part 4: Test It (~10 min)

### Send a Due Diligence Request

Ask an admin to run this for your tenant, or if you have `kubectl`:

```bash
kubectl exec -n tenant-YOUR_TENANT \
  YOUR_TENANT-due-diligence-orchestrator -c agent -- \
  curl -s http://localhost:8080/execute -X POST \
  -H 'Content-Type: application/json' \
  -d '{
    "message": {
      "role": "user",
      "parts": [{"type": "text", "text": "Analyze Anthropic"}]
    }
  }'
```

**What happens under the hood:**

1. Your request hits the **orchestrator** via the A2A sidecar
2. Orchestrator fans out **two parallel A2A calls** over mTLS:
   - Content pipeline: researches Anthropic, writes a report, edits it
   - Financial pipeline: gathers market data, builds a DCF model, assesses risk
3. Both results are **synthesized** into a combined due diligence report
4. Every step is **traced** (OpenTelemetry), **metered** (HCU), and **policy-checked** (OPA)

### Test a Single Worker

You can also test the content or financial agent directly:

```bash
# Content agent
kubectl exec -n tenant-YOUR_TENANT \
  YOUR_TENANT-content-creation-crew-a2a -c agent -- \
  curl -s http://localhost:8080/execute -X POST \
  -H 'Content-Type: application/json' \
  -d '{
    "message": {
      "role": "user",
      "parts": [{"type": "text", "text": "Write about zero-trust for AI agents"}]
    }
  }'
```

---

## Part 5: Explore What Hexr Did (~10 min)

### Check SPIFFE Identity

```bash
kubectl exec -n tenant-YOUR_TENANT \
  YOUR_TENANT-content-creation-crew-a2a -c agent -- \
  curl -s localhost:9901/certs 2>/dev/null | head -20
```

You'll see: `spiffe://hexr.cloud/YOUR_TENANT/content-creation-crew-a2a/...`

### Check Your Credits

```bash
curl -s -H "Authorization: Bearer hxr_live_YOUR_KEY" \
  https://api.hexr.cloud/v1/auth/verify | python3 -m json.tool
```

Look for `credit_balance` under `tenant` — each build, deploy, and agent call costs HCU.

### View the Agent Card

Each agent publishes a `.well-known/agent.json` describing its A2A capabilities:

```bash
kubectl exec -n tenant-YOUR_TENANT \
  YOUR_TENANT-content-creation-crew-a2a -c agent -- \
  curl -s http://localhost:8090/.well-known/agent.json
```

---

## What's Inside Each Agent

Look at the source code to understand the patterns:

| Pattern | Where to See It |
|---------|----------------|
| `@hexr.hexr_agent()` decorator | Top of each `.py` file — declares the agent with name, role, A2A skills |
| `hexr_llm()` wrapper | Wraps the OpenAI client for automatic tracing of every LLM call |
| `A2ABridge` | Entry point — connects your handler function to the A2A sidecar |
| `A2AClient` | In the orchestrator — sends A2A requests to sibling agents via K8s DNS |
| `hexr_tool()` | In worker agents — requests cloud credentials (e.g., AWS S3) via SPIFFE identity exchange |
| `VaultClient` | Fetches the OpenAI API key from Hexr Vault (no hardcoded secrets) |

---

## Troubleshooting

### "pip install hexr-sdk" fails

```bash
# Use --extra-index-url (not --index-url) so pip also checks public PyPI for dependencies
pip install "hexr-sdk[cli]" --extra-index-url https://pypi.hexr.cloud/simple/
```

### "hexr login" fails

```bash
# Key must start with hxr_live_ and be 73 characters
echo -n "hxr_live_YOUR_KEY" | wc -c
```

### "hexr build" fails

```bash
# Must be in the directory with the .py file
ls *.py
python3 --version  # Need 3.11+
hexr build FILENAME.py --tenant YOUR_TENANT -v
```

### "hexr push --cloud" fails

```bash
# Must have run hexr build first
ls .hexr/Dockerfile
# Must include --cloud and --tenant
hexr push --cloud --tenant YOUR_TENANT
```

### "hexr deploy --cloud" fails

```bash
# Must have run hexr push first
hexr deploy .hexr --cloud
```

### Pod stuck in ImagePullBackOff or CrashLoopBackOff

Ask an admin — usually means the Cloud Build is still running or the image tag doesn't match.

### General Issues

- **Ask in Slack** — admins are monitoring all weekend
- **Share your terminal output** — copy-paste the full error
- **Check credits** — you start with 100 HCU, each build costs ~1 HCU

---

## What You Just Experienced

You deployed a 3-agent A2A team to Hexr Cloud. Here's what the platform handled for you:

| Feature | What Happened |
|---------|--------------|
| **SPIFFE Identity** | Each agent process got a unique cryptographic identity (`spiffe://hexr.cloud/...`) |
| **mTLS** | All inter-agent traffic encrypted via Envoy sidecars with X.509 SVIDs |
| **A2A Protocol** | Agents communicated via JSON-RPC 2.0 with task lifecycle management |
| **OPA Policy** | Authorization checked on every request — only your agents can talk to each other |
| **Cloud Credentials** | `hexr_tool('aws_s3')` exchanged SPIFFE JWT-SVID for temporary AWS credentials via STS — no hardcoded keys |
| **Network Isolation** | Your tenant namespace has deny-all NetworkPolicy — no cross-tenant traffic |
| **LLM Observability** | Every LLM call traced: model, tokens, latency, cost — via `hexr_llm()` |
| **HCU Metering** | Credits decremented for builds, deploys, agent runtime, A2A messages |
| **Zero Config** | You ran 3 commands per agent. Hexr handled identity, encryption, policy, and deployment. |

**That's the point.** Developers write agent code. Hexr secures, deploys, and observes it.

---

## Feedback

After completing the guide:

1. How long did it take end-to-end? ___ minutes
2. Where did you get stuck? (Part #, step)
3. What error messages were confusing?
4. Smoothness: 1 (painful) to 5 (seamless)?
5. What would you improve?

Share feedback with an admin or in Slack.
