# Hexr Examples

Production-ready agent examples for the **Hexr hybrid pivot** — a single Helm install in the customer's Kubernetes cluster that adds per-process SPIFFE identity, mTLS via Envoy sidecars, and A2A protocol bridging to any Python AI agent.

## Working demos (live as of 2026-06-08)

These three agents are built with `hexr build`, deployed to live data planes, and have been running 14–15 days on two clouds.

| Demo | Framework | Live on | Pattern |
|---|---|---|---|
| [`financial_analysis/`](financial_analysis/) | LangChain (5-agent pipeline) | EKS `tenant-acme-aws` (`acme-aws-acme-due-diligence` 4/4 + `acme-aws-market-analysis-team` 3/3) | `@hexr_agent` + function-based tools + A2A bridge |
| [`content_creation/`](content_creation/) | CrewAI (3-stage pipeline: research → write → edit) | EKS `tenant-acme-aws` | `@hexr_agent` + `hexr_llm` + A2A bridge |
| [`orchestrator/`](orchestrator/) | Plain Python fan-out/fan-in over A2A | AKS `tenant-globex-azure` (public LB `20.246.232.160`) | `@hexr_agent(a2a=True)` + `A2AClient` calling both workers in parallel |

All three demos prove the **same SDK contract works on two clouds, two managed-PG flavors (RDS PG16 + Flex PG16), same trust domain (`agents.hexr.cloud`), same chart (`attestor-0.5.5`)**. See hexr spec [§1.26.5.6](../hexr/docs/HEXR_HYBRID_PIVOT_TECH_SPEC.md) for the end-to-end proof.

### Build + deploy one

```bash
cd financial_analysis
HEXR_REGISTRY=697675504955.dkr.ecr.us-east-1.amazonaws.com/hexr \
  hexr build financial_analysis_agents_a2a.py \
    --tenant acme-aws --target staging

# Generated artifacts:
ls .hexr/
#   Dockerfile  enterprise_pid_mapper.py  hexr_sdk-0.5.5-cp311-*.whl
#   manifests/  requirements.txt  build-summary.json

# Deploy (manifests pass `kubectl apply --dry-run=server` against live EKS):
kubectl --context hexr-eks-1 apply -f .hexr/manifests/
```

## Hexr SDK concepts used by the working demos

| Concept | What it does | Used in |
|---|---|---|
| `@hexr_agent` | Register agent class — `hexr build` discovers via AST | all three |
| `@hexr_agent(a2a=True)` | Marks an agent as A2A-discoverable; generates `a2a-agent-card.json` + sidecar wiring | `orchestrator/` |
| `hexr_tool()` | Cloud credentials via SPIFFE identity (no API keys in pod) | `financial_analysis/` |
| `hexr_llm()` | Wrap any LLM client for OTel + LLM-Guard prompt/output scanning | all three |
| `VaultClient` | Fetch secrets via SPIFFE identity | `financial_analysis/`, `content_creation/` |
| `A2ABridge` | Expose agent over A2A protocol (`/execute` on `:8080`) | all three |
| `A2AClient` | Call remote agents via A2A | `orchestrator/` |

## What Hexr injects automatically

Every agent pod gets your code + 3 sidecars, all wired by `hexr build`:

| Container | Purpose | Image source |
|---|---|---|
| `agent` | Your Python code | built from `.hexr/Dockerfile` |
| `envoy-sidecar` | mTLS termination via SPIFFE X.509 SVIDs | upstream Envoy |
| `a2a-sidecar` | A2A protocol task lifecycle on `:8090` | `hexr-a2a-sidecar:v1.0.0` |
| `pid-mapper` (init) | Per-process identity tracking for SPIRE | `hexr-pod-uid-attestor:v0.1.2` |

## Architecture

```
Developer                              Hexr Data Plane (EKS / AKS / GKE)
─────────                              ──────────────────────────────
hexr build *.py                  →    AST analysis → Dockerfile + K8s manifests
kubectl apply -f .hexr/manifests →    Pod scheduled with 3 sidecars + init
                                      ├── spire-agent (DS) attests pod
                                      ├── auto-registrar issues per-process SVIDs
                                      └── envoy-sidecar terminates mTLS
```

## Planned demos (not yet built)

> Honest status: the entries below are roadmap, not shipped. The three working demos above are the canonical proof of the SDK contract for the current hybrid pivot.

<details>
<summary>Click to expand the full demo plan</summary>

### Flagship demos (Tier 3) — cover entire platform

| Demo | Frameworks | Capabilities | Status |
|---|---|---|---|
| `flagship/governed-agent/` | LangChain + CrewAI | 17/17 — GRC compliance evidence, 18 agentic controls, 5 frameworks, identity, OPA, progressive enforcement, audit export | 🔲 Planned |
| `flagship/rogue-agent/` | Raw Python + LangChain + CrewAI | 17/17 — progressive enforcement, threat chains, Impact Reach, all security layers | 🔲 Planned |

### Capability deep-dives (Tier 2)

| Example | Capability | Framework | Status |
|---|---|---|---|
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
| `capabilities/threat-chains/` | 6 threat-chain detectors | Multi | 🔲 |
| `capabilities/compliance-packs/` | SOC 2, NIST, ISO, PCI, EU AI Act | Raw Python | 🔲 |
| `capabilities/metering-hcu/` | HCU cost attribution | Raw Python | 🔲 |
| `capabilities/stripe-acp/` | Stripe SharedPaymentTokens | Claude SDK | 🔲 |
| `capabilities/google-a2a/` | Google A2A protocol interop | Google ADK | 🔲 |

### Framework examples (Tier 1) — one per framework

| Example | Framework | Agent | Status |
|---|---|---|---|
| `frameworks/raw-python/` | Raw Python | Data Summarizer | 🔲 |
| `frameworks/langchain/` | LangChain | Research Assistant | 🔲 |
| `frameworks/crewai/` | CrewAI | Content Creation Crew | 🔲 |
| `frameworks/strands-aws/` | Strands (AWS) | Financial Analyst | 🔲 |
| `frameworks/claude-sdk/` | Claude SDK (Anthropic) | Code Reviewer | 🔲 |
| `frameworks/google-adk/` | Google ADK | Task Planner | 🔲 |
| `frameworks/openai-agents/` | OpenAI Agents SDK | Customer Support | 🔲 |

</details>

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
