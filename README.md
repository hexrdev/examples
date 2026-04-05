# Hexr Examples — A2A Agent Team

Example agents for [Hexr Cloud](https://hexr.cloud) demonstrating agent-to-agent (A2A) communication with automatic SPIFFE identity, mTLS encryption, OPA policy enforcement, and LLM observability.

**Documentation:** [docs.hexr.dev](https://docs.hexr.dev)

## Hexr Concepts Used

| Concept | What It Does | Docs |
|---------|-------------|------|
| `@hexr_agent` | Decorator that registers your class as a Hexr agent. `hexr build` discovers these via AST analysis. | [docs.hexr.dev/sdk/hexr-agent](https://docs.hexr.dev/sdk/hexr-agent) |
| `hexr_tool()` | Request cloud credentials (AWS, GCP) via SPIFFE identity. No API keys in code. | [docs.hexr.dev/sdk/hexr-tool](https://docs.hexr.dev/sdk/hexr-tool) |
| `hexr_llm()` | Wrap any LLM client (OpenAI, Anthropic) for automatic OTel tracing + LLM Guard scanning. | [docs.hexr.dev/sdk/hexr-llm](https://docs.hexr.dev/sdk/hexr-llm) |
| `A2ABridge` | Expose your agent over the A2A protocol so other agents can call it. | [docs.hexr.dev/sdk/hexr-a2a](https://docs.hexr.dev/sdk/hexr-a2a) |
| `VaultClient` | Fetch secrets (API keys) from Hexr Vault using your SPIFFE identity. | [docs.hexr.dev/sdk/vault](https://docs.hexr.dev/sdk/vault) |
| LLM Guard | Automatic prompt/output scanning for prompt injection, PII, toxicity. Configured via SDK. | [docs.hexr.dev/security/llm-guard](https://docs.hexr.dev/security/llm-guard) |

## Agents

| Directory | Agent | Description |
|-----------|-------|-------------|
| `content_creation/` | Content Pipeline | 3-stage sequential pipeline: Research → Write → Edit |
| `financial_analysis/` | Financial Analysis | 5-agent pipeline: Market Data → Research → Model → Risk → Synthesis |
| `orchestrator/` | Due Diligence Orchestrator | Fan-out/fan-in: calls both workers in parallel via A2A, synthesizes results |

## Quick Start

### 1. Sign up at [app.hexr.cloud/onboard](https://app.hexr.cloud/onboard)

Use invite code: `HEXR-VOLUNTEER-2026`

Save your API key (`hxr_live_...`).

### 2. Install SDK & login

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install "hexr-sdk[cli]" --extra-index-url https://pypi.hexr.cloud/simple/
hexr login --key hxr_live_YOUR_API_KEY_HERE
```

### 3. Build, push, deploy (repeat for each agent)

Deploy workers first, then the orchestrator:

```bash
# Content agent
cd content_creation
hexr build content_creation_crew_a2a.py --tenant YOUR_TENANT
hexr push --cloud --tenant YOUR_TENANT
hexr deploy .hexr --cloud
cd ..

# Financial agent
cd financial_analysis
hexr build financial_analysis_agents_a2a.py --tenant YOUR_TENANT
hexr push --cloud --tenant YOUR_TENANT
hexr deploy .hexr --cloud
cd ..

# Orchestrator (depends on both workers)
cd orchestrator
hexr build due_diligence_orchestrator.py --tenant YOUR_TENANT
hexr push --cloud --tenant YOUR_TENANT
hexr deploy .hexr --cloud
cd ..
```

### 4. Test

```bash
kubectl exec -n tenant-YOUR_TENANT \
  YOUR_TENANT-due-diligence-orchestrator -c agent -- \
  curl -s http://localhost:8080/execute -X POST \
  -H 'Content-Type: application/json' \
  -d '{"message":{"role":"user","parts":[{"type":"text","text":"Analyze Anthropic"}]}}'
```

## What Hexr Adds Automatically

Each agent pod gets 4 containers — your code + 3 sidecars:

| Container | Purpose |
|-----------|---------|
| `agent` | Your Python code |
| `envoy-sidecar` | mTLS encryption via SPIFFE X.509 SVIDs |
| `a2a-sidecar` | JSON-RPC 2.0 agent-to-agent protocol, task lifecycle |
| `pid-mapper` | Per-process identity tracking for SPIRE registration |

Zero config required. `hexr build` generates everything from your Python source.

## Full Guide

See [VOLUNTEER_WEEKEND_GUIDE.md](https://github.com/hexrdev/examples/blob/main/VOLUNTEER_WEEKEND_GUIDE.md) for the complete walkthrough with troubleshooting.

## Architecture

```
Developer                     Hexr Cloud (GKE)
─────────                     ────────────────
hexr build .py       →   AST analysis, Dockerfile, K8s manifests
hexr push --cloud    →   GCP Cloud Build → Artifact Registry
hexr deploy --cloud  →   Cloud API → K8s Pod + Envoy + A2A + pid-mapper

At runtime:
  SPIRE → SVID per process
  Envoy → mTLS between agents
  OPA   → policy enforcement
  OTel  → traces, metrics, LLM attribution
  Vault → secrets (OpenAI key, no env vars)
```

## License

These examples are provided for the Hexr Volunteer Weekend (April 5-6, 2026). See [hexr.cloud](https://hexr.cloud) for platform details.
