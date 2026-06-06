# Hexr Examples

Production-ready agent examples for [Hexr Cloud](https://hexr.cloud) — covering every capability of the Hexr agent runtime security platform across multiple frameworks, clouds, and use cases.

**Documentation:** [docs.hexr.dev](https://docs.hexr.dev) · **Platform:** [app.hexr.cloud](https://app.hexr.cloud)

## Examples Index

### Flagship Demos (Tier 3) — Cover Entire Platform

| Demo | Frameworks | Capabilities | Status |
|------|-----------|-------------|--------|
| [**F1: The Governed Agent**](flagship/governed-agent/) | LangChain + CrewAI | 17/17 — GRC compliance evidence, 18 agentic controls, 5 frameworks, identity, OPA, progressive enforcement, audit export | 🔲 Planned |
| [**F2: The Rogue Agent**](flagship/rogue-agent/) | Raw Python + LangChain + CrewAI | 17/17 — progressive enforcement, threat chains, Impact Reach, all security layers | 🔲 Planned |

### Capability Deep-Dives (Tier 2)

| Example | Capability | Framework | Status |
|---------|-----------|-----------|--------|
| `capabilities/identity-spiffe/` | SPIFFE per-process identity | Raw Python | 🔲 |
| `capabilities/vault-secrets/` | SPIFFE-native secret management | Raw Python | 🔲 |
| `capabilities/gateway-mcp/` | REST → MCP tool translation | LangChain | 🔲 |
| `capabilities/sandbox-exec/` | Firecracker microVM code exec | Claude SDK | 🔲 |
| `capabilities/browse/` | Sandboxed browser (Stagehand) | Raw Python | 🔲 |
| `capabilities/llm-guard/` | Prompt injection / PII scanning | OpenAI | 🔲 |
| `capabilities/a2a-protocol/` | Agent-to-agent communication | Multi | 🔲 |
| `capabilities/multi-cloud-creds/` | SPIFFE → AWS STS + GCP WIF + Azure | Raw Python | 🔲 |
| `capabilities/opa-governance/` | Policy authoring + enforcement | Raw Python | 🔲 |
| `capabilities/progressive-enforcement/` | Simulate → Audit → Enforce | Raw Python | 🔲 |
| `capabilities/threat-chains/` | 6 threat chain detectors | Multi | 🔲 |
| `capabilities/compliance-packs/` | SOC 2, NIST, ISO, PCI, EU AI Act | Raw Python | 🔲 |
| `capabilities/metering-hcu/` | HCU cost attribution | Raw Python | 🔲 |
| `capabilities/stripe-acp/` | Stripe SharedPaymentTokens | Claude SDK | 🔲 |
| `capabilities/google-a2a/` | Google A2A protocol interop | Google ADK | 🔲 |
| `capabilities/hexr-cloud-deploy/` | Full cloud deploy lifecycle | CLI | 🔲 |

### Framework Examples (Tier 1) — One Per Framework

| Example | Framework | Agent | Status |
|---------|-----------|-------|--------|
| `frameworks/raw-python/` | Raw Python | Data Summarizer | 🔲 |
| `frameworks/langchain/` | LangChain | Research Assistant | 🔲 |
| `frameworks/crewai/` | CrewAI | Content Creation Crew | 🔲 |
| `frameworks/strands-aws/` | Strands (AWS) | Financial Analyst | 🔲 |
| `frameworks/claude-sdk/` | Claude SDK (Anthropic) | Code Reviewer | 🔲 |
| `frameworks/google-adk/` | Google ADK | Task Planner | 🔲 |
| `frameworks/openai-agents/` | OpenAI Agents SDK | Customer Support | 🔲 |

### A2A Team (Volunteer Weekend Examples)

| Example | Agent | Description |
|---------|-------|-------------|
| [content_creation/](content_creation/) | Content Pipeline | 3-stage pipeline: Research → Write → Edit |
| [financial_analysis/](financial_analysis/) | Financial Analysis | 5-agent pipeline: Market → Research → Model → Risk → Synthesis |
| [orchestrator/](orchestrator/) | Due Diligence Orchestrator | Fan-out/fan-in: calls both workers via A2A |

## Hexr SDK Concepts

| Concept | What It Does | Docs |
|---------|-------------|------|
| `@hexr_agent` | Register agent class — `hexr build` discovers via AST | [docs.hexr.dev/sdk/hexr-agent](https://docs.hexr.dev/sdk/hexr-agent) |
| `hexr_tool()` | Cloud credentials via SPIFFE identity (no API keys) | [docs.hexr.dev/sdk/hexr-tool](https://docs.hexr.dev/sdk/hexr-tool) |
| `hexr_llm()` | Wrap any LLM client for OTel + LLM Guard | [docs.hexr.dev/sdk/hexr-llm](https://docs.hexr.dev/sdk/hexr-llm) |
| `VaultClient` | Fetch secrets via SPIFFE identity | [docs.hexr.dev/sdk/vault](https://docs.hexr.dev/sdk/vault) |
| `A2ABridge` | Expose agent over A2A protocol | [docs.hexr.dev/sdk/hexr-a2a](https://docs.hexr.dev/sdk/hexr-a2a) |
| `A2AClient` | Call remote agents via A2A | [docs.hexr.dev/sdk/hexr-a2a](https://docs.hexr.dev/sdk/hexr-a2a) |
| `GatewayClient` | Access REST APIs as MCP tools | [docs.hexr.dev/sdk/gateway](https://docs.hexr.dev/sdk/gateway) |
| `sandbox.exec()` | Run code in Firecracker microVM | [docs.hexr.dev/sdk/sandbox](https://docs.hexr.dev/sdk/sandbox) |
| `browser.browse()` | Sandboxed browser in microVM | [docs.hexr.dev/sdk/browser](https://docs.hexr.dev/sdk/browser) |

## Quick Start

```bash
# Install SDK
pip install "hexr-sdk[cli]" --extra-index-url https://pypi.hexr.cloud/simple/
hexr login --key $HEXR_API_KEY

# Deploy an example (e.g., F1 Agentic Commerce)
cd flagship/agentic-commerce
./deploy_all.sh --tenant hexr-internal --cloud
```

## What Hexr Adds Automatically

Each agent pod gets 4 containers — your code + 3 sidecars:

| Container | Purpose |
|-----------|---------|
| `agent` | Your Python code |
| `envoy-sidecar` | mTLS encryption via SPIFFE X.509 SVIDs |
| `a2a-sidecar` | Agent-to-agent protocol, task lifecycle |
| `pid-mapper` | Per-process identity tracking for SPIRE |

## Architecture

```
Developer                     Hexr Cloud
─────────                     ──────────
hexr build .py       →   AST analysis → Dockerfile + K8s manifests
hexr push --cloud    →   Cloud Build → Artifact Registry
hexr deploy --cloud  →   Cloud API → K8s Pod + sidecars

Runtime security (automatic):
  SPIRE  → Cryptographic identity per process
  Envoy  → mTLS between all agents
  OPA    → Policy enforcement (deterministic, zero LLM cost)
  Vault  → SPIFFE-native secrets (no env vars)
  OTel   → Distributed traces + LLM attribution
  Guard  → Prompt injection / PII scanning
```

## Cloud Agnostic

Hexr works on any Kubernetes cluster — GKE, EKS, AKS, bare metal. Cloud credential exchange supports AWS, GCP, and Azure (via SPIFFE → STS/WIF federation). Examples demonstrate multi-cloud access patterns.

## Guides

- [Volunteer Weekend Guide](VOLUNTEER_WEEKEND_GUIDE.md) — Hands-on walkthrough for A2A team examples
