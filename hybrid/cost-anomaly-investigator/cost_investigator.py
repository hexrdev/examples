"""
Cost Anomaly Investigator — LangGraph ReAct single-agent
========================================================

Tenant:    acme-aws (Client 1)
Cluster:   EKS hexr-runtime-eks-1, us-east-1
Namespace: tenant-acme-aws
Framework: LangGraph (create_react_agent)
Pattern:   ReAct — single agent + tool-use loop
LLM:       OpenAI gpt-4o-mini (API key from K8s Secret, env var)

What it proves
--------------
The agent runs inside EKS but pulls cost data from THREE different clouds in
the same reasoning loop:

    AWS  Cost Explorer  via hexr_tool("aws_ce")        ← SPIFFE → STS
    GCP  BigQuery       via hexr_tool("gcp_bigquery")  ← SPIFFE → WIF
    Azure Blob          via hexr_tool("azure_storage") ← SPIFFE → Az Workload Identity

Same SDK call. Same SPIFFE identity. Three different cloud trust exchanges
hidden behind one Python function. That is the hexr_tool abstraction — what
hyperscaler-native SDKs (boto3, google-auth, azure-identity) cannot do
because each one only knows its own cloud.

Every tool call emits an evidence row to the local evidence-api; the audit
pack PDF (`hexr audit --tenant acme-aws --framework soc2`) maps these to
SOC 2 CC6.1 / NIST AC-6 control points.

Build / push / deploy
---------------------
    cd hexr-examples/hybrid/cost-anomaly-investigator
    rm -rf .hexr

    hexr build cost_investigator.py --tenant acme-aws --no-mock-mode \\
      --trust-domain agents.hexr.cloud \\
      --pypi-url https://pypi.hexr.cloud/simple/ \\
      --registry 697675504955.dkr.ecr.us-east-1.amazonaws.com/hexr

    hexr push --tenant acme-aws \\
      --registry 697675504955.dkr.ecr.us-east-1.amazonaws.com/hexr \\
      --platform linux/amd64

    kubectl config use-context hexr-eks-1
    hexr deploy .hexr --namespace tenant-acme-aws

The deploy step expects a K8s Secret `openai-api-key` in tenant-acme-aws
namespace with key `api-key`. Create it once:
    kubectl --context hexr-eks-1 -n tenant-acme-aws \\
      create secret generic openai-api-key --from-literal=api-key=sk-...
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, timedelta
from typing import Any

import hexr
from hexr.a2a.bridge import A2ABridge
from hexr.a2a.models import Artifact, Message, TextPart

from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("cost-investigator")


# ---------------------------------------------------------------------------
# Cross-cloud tools — each one uses hexr_tool() so creds come from the local
# SPIRE agent's SVID via the credential injector, not env-var keys.
# ---------------------------------------------------------------------------

def _date_range(days: int = 7) -> tuple[str, str]:
    end = date.today()
    start = end - timedelta(days=days)
    return start.isoformat(), end.isoformat()


@tool
def fetch_aws_costs(days: int = 7) -> str:
    """Return total AWS cost grouped by service for the last N days.

    Uses AWS Cost Explorer. Auth: SPIFFE SVID → STS AssumeRoleWithWebIdentity.
    """
    start, end = _date_range(days)
    ce = hexr.hexr_tool("aws_ce")
    resp = ce.get_cost_and_usage(
        TimePeriod={"Start": start, "End": end},
        Granularity="DAILY",
        Metrics=["UnblendedCost"],
        GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
    )
    return json.dumps({"cloud": "aws", "period": [start, end], "results": resp["ResultsByTime"]})


@tool
def fetch_gcp_costs(days: int = 7) -> str:
    """Return total GCP cost grouped by service for the last N days.

    Reads the billing-export BigQuery dataset. Auth: SPIFFE SVID →
    Workload Identity Federation → BigQuery API.
    """
    start, end = _date_range(days)
    dataset = os.getenv("GCP_BILLING_DATASET", "billing.gcp_billing_export_v1")
    bq = hexr.hexr_tool("gcp_bigquery")
    sql = f"""
        SELECT service.description AS service, SUM(cost) AS cost
        FROM `{dataset}`
        WHERE _PARTITIONDATE BETWEEN '{start}' AND '{end}'
        GROUP BY service
        ORDER BY cost DESC
        LIMIT 25
    """
    rows = [dict(r) for r in bq.query(sql).result()]
    return json.dumps({"cloud": "gcp", "period": [start, end], "results": rows})


@tool
def fetch_azure_costs(days: int = 7) -> str:
    """Return total Azure cost grouped by service for the last N days.

    Reads the daily Cost Management CSV exported to a Blob container. Auth:
    SPIFFE SVID → Azure Workload Identity → Blob Storage.
    """
    start, end = _date_range(days)
    account_url = os.getenv("AZURE_COST_ACCOUNT_URL", "")
    container = os.getenv("AZURE_COST_CONTAINER", "cost-exports")
    blob_name = f"daily/{end}.csv"
    blob = hexr.hexr_tool("azure_storage")
    if not account_url:
        return json.dumps({"cloud": "azure", "error": "AZURE_COST_ACCOUNT_URL not set"})
    container_client = blob.get_container_client(container)
    data = container_client.download_blob(blob_name).readall().decode("utf-8")
    return json.dumps({"cloud": "azure", "period": [start, end], "csv": data[:4000]})


@tool
def flag_anomaly(cloud: str, service: str, cost: float, baseline: float) -> str:
    """Record an anomaly finding. Returns a confirmation string for the agent's trace.

    The fact that we ran this tool is itself the evidence — the SDK auto-emits
    an OTel span which the evidence-api converts to a row.
    """
    delta_pct = ((cost - baseline) / baseline * 100) if baseline else float("inf")
    return f"ANOMALY recorded: {cloud}/{service} cost ${cost:.2f} vs baseline ${baseline:.2f} ({delta_pct:+.1f}%)"


# ---------------------------------------------------------------------------
# ReAct agent. LangGraph's create_react_agent gives us the classic
# thought→action→observation loop with no boilerplate.
# ---------------------------------------------------------------------------

_TOOLS = [fetch_aws_costs, fetch_gcp_costs, fetch_azure_costs, flag_anomaly]
_SYSTEM = (
    "You are a FinOps investigator. When asked about cost anomalies you MUST: "
    "(1) call fetch_aws_costs, fetch_gcp_costs, fetch_azure_costs in that order; "
    "(2) compare each service's last-day cost to its 7-day average; "
    "(3) for any service > 30% above its average, call flag_anomaly; "
    "(4) return a markdown report listing all anomalies grouped by cloud."
)

_agent = None


def _build_llm() -> ChatOpenAI:
    # Provider selection: DeepSeek (OpenAI-compatible) if DEEPSEEK_API_KEY is
    # mounted from `hexr-llm-credentials`, otherwise native OpenAI. Both env
    # vars are auto-mounted by the Hexr SDK (build/k8s.py).
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if deepseek_key:
        return ChatOpenAI(
            model=os.getenv("LLM_MODEL", "deepseek-chat"),
            api_key=deepseek_key,
            base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1"),
            temperature=0,
        )
    return ChatOpenAI(
        model=os.getenv("LLM_MODEL", os.getenv("OPENAI_MODEL", "gpt-4o-mini")),
        api_key=os.environ["OPENAI_API_KEY"],
        temperature=0,
    )


def _react_agent():
    global _agent
    if _agent is None:
        _agent = create_react_agent(_build_llm(), tools=_TOOLS, prompt=_SYSTEM)
    return _agent


# ---------------------------------------------------------------------------
# A2A entrypoint.
# ---------------------------------------------------------------------------

async def handle(message: Message) -> list[Artifact]:
    prompt = message.text_content() or "Find cost anomalies across all clouds for the last 7 days."
    logger.info("cost-investigator received: %s", prompt)
    result = await _react_agent().ainvoke({"messages": [{"role": "user", "content": prompt}]})
    final = result["messages"][-1].content
    return [
        Artifact(
            artifact_id="cost-anomaly-report",
            name="anomaly_report.md",
            parts=[TextPart(text=final)],
        )
    ]


# ---------------------------------------------------------------------------
# resources= lists the cloud actions the agent needs. hexr build copies
# these into the SPIFFE→cloud trust policies created by hexr-credential-
# injector at deploy time.
# ---------------------------------------------------------------------------

@hexr.hexr_agent(
    name="cost-investigator",
    tenant="acme-aws",
    resources=[
        "ce:GetCostAndUsage",
        "bigquery.jobs.create",
        "bigquery.tables.getData",
        "azure:storage.blob.read",
    ],
    regions={"aws": "us-east-1", "gcp": "us-central1", "azure": "eastus"},
    a2a=True,
    description="Cross-cloud FinOps investigator. ReAct over AWS+GCP+Azure cost data.",
    version="1.0.0",
    skills=[
        {
            "id": "cost-anomaly-scan",
            "name": "Cross-cloud cost anomaly scan",
            "description": "Pull cost data from AWS Cost Explorer, GCP BigQuery billing export, and Azure Blob cost CSV, then flag services >30% above their 7-day baseline.",
        }
    ],
)
class CostInvestigator:
    def __init__(self) -> None:
        logger.info("CostInvestigator initialised (LangGraph ReAct, OpenAI %s)",
                    os.getenv("OPENAI_MODEL", "gpt-4o-mini"))


if __name__ == "__main__":
    import asyncio
    bridge = A2ABridge(handler=handle)
    asyncio.run(bridge.start())
