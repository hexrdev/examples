# Hexr Examples

Reference agent demos for the **Hexr Hybrid runtime** (SDK 0.5.5+).

## Wedge (what Hexr actually sells)

> Audit-grade evidence for AI agents — in your Kubernetes cluster, mapped to
> your SOC 2, HIPAA, and NIST controls.

The SPIFFE / mTLS / A2A plumbing is how Hexr produces that evidence. The
PDF an auditor signs is the product.

## Topology these demos run on

One Hexr-managed **Control Plane** on GCP, two customer **Data Planes** on
two different clouds. The DPs pretend to be two independent customers —
they share no application data; the only thing they have in common is the
nested SPIRE chain back to the CP root.

| Role | Cloud | Cluster | What lives here |
|---|---|---|---|
| **CP** | GCP (Hexr accelerator account) | GKE `hexr-cloud-control` | SPIRE root, `hexr-license-api`, `hexr-control-api`, CP dashboard. **Never** holds tenant evidence rows. |
| **DP-1 / Client 1** | AWS (Hexr accelerator account, posing as `acme-aws`) | EKS `hexr-runtime-eks-1` | `tenant-acme-aws` namespace, downstream SPIRE chained to CP root, `hexr-evidence-api`, DP dashboard |
| **DP-2 / Client 2** | Azure (Hexr accelerator account, posing as `globex-azure`) | AKS `hexr-runtime-aks-1` | `tenant-globex-azure` namespace, downstream SPIRE chained to CP root, `hexr-evidence-api`, DP dashboard |

Shared SPIFFE trust domain `spiffe://agents.hexr.cloud`. Nested SPIRE — no
federation handshake — so an agent on AKS can mTLS-call an agent on EKS
out of the box.

## The two demos

Each client picked a fundamentally different agent pattern + framework, on
purpose, to prove Hexr is pattern- and framework-agnostic.

| | [`hybrid/cost-anomaly-investigator/`](hybrid/cost-anomaly-investigator/) | [`hybrid/investment-memo-crew/`](hybrid/investment-memo-crew/) |
|---|---|---|
| Client | acme-aws (Client 1) | globex-azure (Client 2) |
| Cluster | EKS | AKS |
| Pattern | **Single-agent ReAct** (classic tool-use loop) | **Hierarchical multi-agent** (director + 3 workers) |
| Framework | LangGraph | CrewAI |
| LLM | OpenAI gpt-4o-mini | Azure OpenAI gpt-4o |
| `hexr_tool` story | One agent reads AWS Cost Explorer + GCP BigQuery + Azure Blob in one ReAct loop — same SPIFFE identity, three trust exchanges | Each CrewAI role reads from a different cloud (researcher → Azure Blob, writer → S3, editor → GCS) |
| Cross-cluster A2A | exposed as a callable A2A service | Legal Editor role calls the cost-investigator on EKS via `A2AClient(spiffe_socket=…)` |
| Evidence emitted | Per-tool span → SOC 2 CC6.1 row | Per-tool span × 3 + outbound A2A span → SOC 2 CC6.1 / NIST AC-6 rows |

Together they make the auditor-facing pitch obvious:

1. Two customers, two clouds, one CP, one audit story.
2. An AKS-hosted hierarchical crew calls an EKS-hosted ReAct agent over
   mTLS without anyone configuring federation. Same trust domain, two CAs
   inside the same audit pack PDF.

## Canonical build → push → deploy flow

```bash
# 1. Static-analyse + generate Dockerfile + manifests + A2A card
hexr build <agent>.py --tenant <tenant> --no-mock-mode \
  --trust-domain agents.hexr.cloud \
  --pypi-url https://pypi.hexr.cloud/simple/ \
  --registry <REGISTRY>

# 2. Build OCI image and push
hexr push --tenant <tenant> --registry <REGISTRY> --platform linux/amd64

# 3. Deploy (Pod + 3 sidecars + Service + NetworkPolicy)
kubectl config use-context <DP-CONTEXT>
hexr deploy .hexr --namespace tenant-<tenant>
```

Hard rules — these will trip you up if you skip them:

- **Never** `kubectl apply -f .hexr/manifests/`. Always `hexr deploy` so the
  CP gets the registration heartbeat and evidence rows are addressable.
- **Never** pass `--cloud` to `hexr push` — that flag was the old SaaS path.
- **Always** `rm -rf .hexr` before a rebuild.

## Per-cloud one-liners

### AWS / EKS — `acme-aws` tenant

```bash
export REGISTRY=697675504955.dkr.ecr.us-east-1.amazonaws.com/hexr
aws ecr get-login-password --region us-east-1 --profile hexr | \
  docker login --username AWS --password-stdin "$REGISTRY"

cd hybrid/cost-anomaly-investigator
rm -rf .hexr
hexr build cost_investigator.py --tenant acme-aws --no-mock-mode \
  --trust-domain agents.hexr.cloud \
  --pypi-url https://pypi.hexr.cloud/simple/ \
  --registry "$REGISTRY"
hexr push --tenant acme-aws --registry "$REGISTRY" --platform linux/amd64
kubectl config use-context hexr-eks-1
hexr deploy .hexr --namespace tenant-acme-aws
```

### Azure / AKS — `globex-azure` tenant

```bash
export REGISTRY=hexrglobex.azurecr.io/hexr
az acr login --name hexrglobex

# Get the cost-investigator's LB hostname so the AKS crew can call it
COST_URL=$(kubectl --context hexr-eks-1 -n tenant-acme-aws get svc cost-investigator \
  -o jsonpath='https://{.status.loadBalancer.ingress[0].hostname}:8443')

cd hybrid/investment-memo-crew
rm -rf .hexr
hexr build investment_memo_crew.py --tenant globex-azure --no-mock-mode \
  --trust-domain agents.hexr.cloud \
  --pypi-url https://pypi.hexr.cloud/simple/ \
  --registry "$REGISTRY"
hexr push --tenant globex-azure --registry "$REGISTRY" --platform linux/amd64
kubectl config use-context hexr-runtime-aks-1
hexr deploy .hexr --namespace tenant-globex-azure \
  --set env.COST_INVESTIGATOR_URL="$COST_URL"
```

## The hero step — `hexr audit`

After the agents have run a few times and emitted evidence rows, generate
the audit PDF. This is the thing auditors actually look at.

```bash
# Per-tenant audit pack
hexr audit --tenant acme-aws --framework soc2  --output acme-aws-soc2.pdf
hexr audit --tenant globex-azure --framework hipaa --output globex-hipaa.pdf

# The PDF contains, per control:
#   - control_id, control_text, mapped_evidence_count
#   - sample evidence rows with SPIFFE ID, timestamp, decision, span_id
#   - cryptographic signature (audit-pack signing key in CP KMS)
```

## Pod shape

Every agent pod runs four containers (three if `a2a=False`), all wired by
`hexr build`:

| Container | Role |
|---|---|
| `agent` | Your Python code |
| `pid-mapper` (init) | Per-process SPIFFE attestation marker |
| `envoy-sidecar` | mTLS termination using X.509 SVIDs from local SPIRE agent |
| `a2a-sidecar` | A2A JSON-RPC + task lifecycle on `:8090` |

## Pre-pivot demos kept for reference only

`content_creation/`, `financial_analysis/`, `orchestrator/` predate the
hybrid pivot. Source still parses against the current SDK but the
deploy instructions in their docstrings refer to a SaaS CP that no longer
exists. **Use the `hybrid/` demos for any new work.**

## Reference

- Hybrid pivot spec: [`hexr/docs/HEXR_HYBRID_PIVOT_TECH_SPEC.md`](../hexr/docs/HEXR_HYBRID_PIVOT_TECH_SPEC.md)
- SDK overhaul spec: [`hexr/docs/HEXR_SDK_OVERHAUL_TECH_SPEC.md`](../hexr/docs/HEXR_SDK_OVERHAUL_TECH_SPEC.md)
