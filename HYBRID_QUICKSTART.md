# Hexr Hybrid Quickstart

> **Wedge:** Audit-grade evidence for AI agents — in your Kubernetes cluster,
> mapped to your SOC 2, HIPAA, and NIST controls.

This guide walks through deploying the two reference agents end-to-end across
the live CP+2DP topology. Use it after reading [`README.md`](README.md).

---

## 0. Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.11+ | `python --version` |
| Hexr SDK + CLI | `pip install "hexr-sdk[cli]>=0.5.5" --extra-index-url https://pypi.hexr.cloud/simple/` |
| Docker (or compatible) | Local build target is `linux/amd64` |
| `kubectl` contexts | `hexr-eks-1` (DP-1), `hexr-runtime-aks-1` (DP-2), `gke_hexr-cloud-prod_us-central1-a_hexr-cloud-control` (CP) |
| Registry auth | `aws ecr get-login-password ...` for EKS, `az acr login --name hexrglobex` for AKS |
| Cloud creds for `hexr_tool` | AWS profile `hexr` (CE read), Azure principal w/ `Storage Blob Data Reader` on cost-exports container, GCP SA w/ `bigquery.dataViewer` on `billing` dataset |
| LLM keys | OpenAI for Client 1, Azure OpenAI for Client 2 (created as K8s Secrets in §3.1) |

```bash
hexr --version    # expect 0.5.5 or newer
hexr --help       # 8 commands: init, analyze, build, push, deploy, audit, cluster, ca
```

---

## 1. Topology recap

```
                    ┌──────────────────────────────────────┐
                    │  CP  (GCP, hexr-cloud-control GKE)   │
                    │  SPIRE root · license-api · CP UI    │
                    └───────────────┬──────────────────────┘
                                    │ nested SPIRE
              ┌─────────────────────┼─────────────────────┐
              ▼                                           ▼
  ┌───────────────────────┐                  ┌───────────────────────┐
  │ DP-1 / Client 1       │                  │ DP-2 / Client 2       │
  │ EKS hexr-runtime-eks-1│  ◄── mTLS A2A ── │ AKS hexr-runtime-aks-1│
  │ tenant-acme-aws       │                  │ tenant-globex-azure   │
  │ cost-investigator     │                  │ investment-memo-crew  │
  │ (LangGraph ReAct)     │                  │ (CrewAI hierarchical) │
  └───────────────────────┘                  └───────────────────────┘
```

Trust domain `agents.hexr.cloud` shared across all three clusters via nested
SPIRE. No federation handshake. Each DP holds its own evidence in local
Postgres — never sent to CP.

---

## 2. Demo A — `cost-investigator` on EKS

### 2.1 Build

```bash
cd hexr-examples/hybrid/cost-anomaly-investigator

# ECR auth (one-time per shell)
export REGISTRY=697675504955.dkr.ecr.us-east-1.amazonaws.com/hexr
aws ecr get-login-password --region us-east-1 --profile hexr | \
  docker login --username AWS --password-stdin "$REGISTRY"

# Always start fresh — never reuse a stale .hexr/
rm -rf .hexr

hexr build cost_investigator.py \
  --tenant acme-aws \
  --no-mock-mode \
  --trust-domain agents.hexr.cloud \
  --pypi-url https://pypi.hexr.cloud/simple/ \
  --registry "$REGISTRY"
```

What this produces under `.hexr/`:
- `Dockerfile` with pinned base image
- `manifests/agent.yaml` (Pod + Service + NetworkPolicy)
- `agent-card.json` (A2A `/.well-known/agent.json` payload)
- `policy.rego` (allow-list derived from `resources=[...]` in the decorator)

### 2.2 Push

```bash
hexr push --tenant acme-aws --registry "$REGISTRY" --platform linux/amd64
```

> **Never** pass `--cloud` to `hexr push` — that's the dead SaaS path.

### 2.3 Create the OpenAI secret

```bash
kubectl --context hexr-eks-1 -n tenant-acme-aws create secret generic openai-api-key \
  --from-literal=api-key="$OPENAI_API_KEY"
```

### 2.4 Deploy

```bash
kubectl config use-context hexr-eks-1
hexr deploy .hexr --namespace tenant-acme-aws
```

> **Never** `kubectl apply -f .hexr/manifests/`. The CP needs the registration
> heartbeat that `hexr deploy` triggers; without it evidence rows are
> unaddressable.

### 2.5 Verify

```bash
# Pod should be 4/4 Ready (agent + pid-mapper init + envoy + a2a-sidecar)
kubectl --context hexr-eks-1 -n tenant-acme-aws get pod -l app=cost-investigator

# SPIRE entry exists
kubectl --context hexr-eks-1 -n spire-system exec sts/spire-server -- \
  /opt/spire/bin/spire-server entry show -spiffeID spiffe://agents.hexr.cloud/ns/tenant-acme-aws/sa/cost-investigator

# Agent card served by the A2A sidecar
kubectl --context hexr-eks-1 -n tenant-acme-aws port-forward svc/cost-investigator 8090:8090 &
curl -s http://localhost:8090/.well-known/agent.json | jq .

# Grab the public LoadBalancer hostname (needed for Demo B)
COST_URL=$(kubectl --context hexr-eks-1 -n tenant-acme-aws get svc cost-investigator \
  -o jsonpath='https://{.status.loadBalancer.ingress[0].hostname}:8443')
echo "$COST_URL"
```

### 2.6 Trigger

```bash
kubectl --context hexr-eks-1 -n tenant-acme-aws exec deploy/cost-investigator -c agent -- \
  curl -s -X POST http://localhost:8080/execute \
       -H 'Content-Type: application/json' \
       -d '{"message":{"role":"user","parts":[{"text":"scan last 7 days across all three clouds"}]}}'
```

You should see the agent loop through `fetch_aws_costs` → `fetch_gcp_costs` →
`fetch_azure_costs` → `flag_anomaly`, and return an artifact named
`anomaly_report.md`.

---

## 3. Demo B — `investment-memo-crew` on AKS

### 3.1 Build

```bash
cd hexr-examples/hybrid/investment-memo-crew
export REGISTRY=hexrglobex.azurecr.io/hexr
az acr login --name hexrglobex

rm -rf .hexr

hexr build investment_memo_crew.py \
  --tenant globex-azure \
  --no-mock-mode \
  --trust-domain agents.hexr.cloud \
  --pypi-url https://pypi.hexr.cloud/simple/ \
  --registry "$REGISTRY"
```

### 3.2 Push

```bash
hexr push --tenant globex-azure --registry "$REGISTRY" --platform linux/amd64
```

### 3.3 Create the Azure OpenAI secret

```bash
kubectl --context hexr-runtime-aks-1 -n tenant-globex-azure create secret generic azure-openai \
  --from-literal=api-key="$AZURE_OPENAI_KEY" \
  --from-literal=endpoint="https://hexr-globex.openai.azure.com"
```

### 3.4 Deploy (wired to EKS)

`COST_URL` from §2.5 — this is what makes the cross-cluster A2A hop possible.

```bash
kubectl config use-context hexr-runtime-aks-1
hexr deploy .hexr --namespace tenant-globex-azure \
  --set env.COST_INVESTIGATOR_URL="$COST_URL"
```

### 3.5 Verify

```bash
kubectl --context hexr-runtime-aks-1 -n tenant-globex-azure get pod -l app=investment-memo-crew
kubectl --context hexr-runtime-aks-1 -n tenant-globex-azure port-forward svc/investment-memo-crew 8090:8090 &
curl -s http://localhost:8090/.well-known/agent.json | jq .
```

### 3.6 Trigger

```bash
kubectl --context hexr-runtime-aks-1 -n tenant-globex-azure exec deploy/investment-memo-crew -c agent -- \
  curl -s -X POST http://localhost:8080/execute \
       -H 'Content-Type: application/json' \
       -d '{"message":{"role":"user","parts":[{"text":"draft memo for ACME"}]}}'
```

The Director kicks off the hierarchical crew. The Legal Editor role will make
a cross-cluster A2A call against `COST_URL` — that connection establishes
mTLS using SPIFFE IDs from both AKS and EKS without anyone configuring
federation.

---

## 4. The hero step — `hexr audit`

After both agents have run a few times, generate signed PDFs:

```bash
hexr audit --tenant acme-aws     --framework soc2  --output /tmp/acme-soc2.pdf
hexr audit --tenant globex-azure --framework hipaa --output /tmp/globex-hipaa.pdf
hexr audit --tenant globex-azure --framework nist  --output /tmp/globex-nist.pdf
```

Each PDF contains, per control:
- `control_id`, `control_text`, `mapped_evidence_count`
- sample evidence rows (SPIFFE ID, timestamp, decision, span_id)
- cryptographic signature from the CP audit-pack signing key

This is the artefact you hand an auditor. Everything above this section is
plumbing.

---

## 5. Inspect from the dashboards

| Dashboard | Where | What to look at |
|---|---|---|
| CP UI | GCP GKE `hexr-cloud-control` | `/tenants` shows both tenants with `agent_count > 0` and recent `heartbeat_at`. `/heartbeat` shows fleet history. `/settings` shows API keys + invite codes + CA status. |
| DP UI (EKS) | `kubectl --context hexr-eks-1 -n hexr-system port-forward svc/hexr-dp-dashboard 3000:80` | `/evidence?tenant_id=acme-aws` shows tool-call rows from `cost-investigator`. `/svids` lists the agent SVID. `/a2a` shows outbound A2A spans (empty here). `/settings` shows cluster identity + evidence retention. |
| DP UI (AKS) | `kubectl --context hexr-runtime-aks-1 -n hexr-system port-forward svc/hexr-dp-dashboard 3000:80` | `/evidence?tenant_id=globex-azure` shows tool-call rows from each CrewAI role. `/a2a` shows the outbound A2A span targeting the EKS cost-investigator SPIFFE ID. |

---

## 5a. Calling agents from your laptop

The `kubectl exec` calls in §2.6 and §3.6 are the trigger pattern you'd put in a script that runs *inside* the same Kubernetes cluster (an operator job, a CronJob, another agent calling back). When you're sitting at your own machine, use `kubectl port-forward` instead — no public LoadBalancer needed, no IAM/ingress paperwork to wire up before a demo, traffic stays on your kube-config's authenticated tunnel.

### 5a.1 Cost-investigator from your laptop (EKS)

```bash
# Forward the agent's HTTP port. Backgrounded so you keep your prompt.
kubectl --context hexr-eks-1 -n tenant-acme-aws \
  port-forward svc/cost-investigator 9101:8080 &

# Trigger from localhost. SPIRE identity is still verified inside the cluster —
# port-forward is just kubectl's authenticated tunnel; the request still
# transits the agent's Envoy sidecar exactly the same way.
curl -sS -X POST http://localhost:9101/execute \
     -H 'Content-Type: application/json' \
     -d '{"message":{"role":"user","parts":[{"text":"scan last 7 days across all three clouds"}]}}' | jq .

# When done:
kill %1
```

### 5a.2 Investment-memo-crew from your laptop (AKS)

```bash
kubectl --context hexr-runtime-aks-1 -n tenant-globex-azure \
  port-forward svc/investment-memo-crew 9102:8080 &

curl -sS -X POST http://localhost:9102/execute \
     -H 'Content-Type: application/json' \
     -d '{"message":{"role":"user","parts":[{"text":"draft memo for ACME"}]}}' | jq .

kill %1
```

### 5a.3 When NOT to use port-forward

| Caller | Use |
|---|---|
| Your laptop, ad-hoc trigger or demo | `kubectl port-forward` (this section) |
| Another agent in the SAME cluster | In-cluster Service DNS (`http://cost-investigator.tenant-acme-aws.svc.cluster.local:8080`) |
| Another agent in a DIFFERENT cluster (cross-cloud A2A) | Public LoadBalancer + SPIFFE mTLS (`COST_URL` pattern in §2.5/§3.4) — port-forward does not work because the remote pod cannot dial back into your laptop |
| Production user/web traffic | Ingress (typically restricted to internal LoadBalancer + corporate IdP; we deliberately do NOT expose agents on the public internet by default — they are tools called by other agents, not human-facing endpoints) |

### 5a.4 Why this is fine for an enterprise demo

The agent's Envoy sidecar still verifies the caller's SPIFFE identity on every request. Port-forward changes the *transport* (a kubectl tunnel instead of an LB) but not the *trust model* — the request still has to pass the credential-injector's OPA decision and produce an evidence row. The customer sees the same audit trail whether the trigger came from their laptop, an in-cluster job, or another DP cluster's agent.

---

## 6. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `hexr build` errors with `framework=unknown` | Decorator missing or import-time error | Run `python -c 'import cost_investigator'` to surface the real exception |
| `hexr push` `unauthorized: authentication required` | Registry creds expired | Re-run `aws ecr get-login-password ...` or `az acr login` |
| Pod stuck `Init:0/1` | `pid-mapper` init container can't see the SPIRE agent socket | `kubectl describe pod` and confirm the SPIRE agent DaemonSet pod is running on the same node |
| Pod stuck `PodInitializing` past 60s | `envoy-sidecar` can't reach SPIRE Workload API | Check `kubectl logs -c envoy-sidecar`; usually means the workload entry hasn't propagated yet — wait or restart spire-agent on the node |
| Agent returns `KeyError: 'OPENAI_API_KEY'` | Secret missing or wrong namespace | `kubectl get secret -n tenant-acme-aws openai-api-key` |
| Tool call returns `botocore.exceptions.NoCredentialsError` | SPIFFE→AWS trust exchange not wired for this tenant | Check the credential-injector logs and the AWS IAM Role's trust policy contains the tenant's SPIFFE ID |
| Cross-cluster A2A times out (Demo B Legal Editor stalls) | `COST_INVESTIGATOR_URL` wrong, EKS Service has no public LB, or NetworkPolicy on EKS blocks ingress from AKS SPIFFE ID | Re-export `COST_URL` from §2.5; `kubectl get svc cost-investigator -o wide` |
| Evidence rows missing in DP UI | Agent isn't using `hexr_tool` / `hexr_llm` wrappers | Only those wrappers emit evidence spans; raw `boto3.client(...)` produces nothing |

---

## 7. Hard rules (worth re-reading before each demo run)

- **Never** `kubectl apply -f .hexr/manifests/`. Always `hexr deploy`.
- **Never** `--cloud` flag on `hexr push`.
- **Always** `rm -rf .hexr` before a rebuild.
- **Never** point the DP dashboard at `api.hexr.cloud`. DP UI only reads local
  `hexr-evidence-api`; CP UI only reads `hexr-license-api`.
- The auditor cares about `hexr audit` output. The dashboards exist for ops.
