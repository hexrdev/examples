"""
Investment Memo Crew — CrewAI hierarchical, with cross-cluster A2A
==================================================================

Tenant:    globex-azure (Client 2)
Cluster:   AKS hexr-runtime-aks-1, eastus
Namespace: tenant-globex-azure
Framework: CrewAI (Process.hierarchical with explicit manager)
Pattern:   Hierarchical multi-agent — manager delegates to 3 workers
LLM:       Azure OpenAI gpt-4o (key from K8s Secret, env var)

The crew (one pod, four CrewAI agents inside)
---------------------------------------------
    Investment Director  (manager)  ── delegates research / writing / review
        │
        ├── Filings Researcher      reads SEC filings  via hexr_tool("azure_storage")
        ├── Memo Writer             reads comparables  via hexr_tool("aws_s3")
        └── Legal Editor            reads precedents   via hexr_tool("gcp_storage")
                                                       calls cost-investigator
                                                       on EKS via Hexr A2A

What it proves
--------------
1. CrewAI hierarchical works unchanged inside a Hexr pod.
2. Every CrewAI role uses hexr_tool() against a DIFFERENT cloud — proves
   cross-cloud abstraction is per-tool, not per-pod.
3. The Legal Editor role makes a cross-CLUSTER A2A call from AKS into the
   cost-investigator agent running on EKS. Same trust domain
   (spiffe://agents.hexr.cloud), nested SPIRE, mTLS end-to-end — no
   federation handshake.
4. Single audit pack PDF for tenant-globex-azure will show four agent
   spans (manager + 3 workers) and one outbound A2A call to acme-aws.

Build / push / deploy
---------------------
    cd hexr-examples/hybrid/investment-memo-crew
    rm -rf .hexr

    hexr build investment_memo_crew.py --tenant globex-azure --no-mock-mode \\
      --trust-domain agents.hexr.cloud \\
      --pypi-url https://pypi.hexr.cloud/simple/ \\
      --registry hexrglobex.azurecr.io/hexr

    hexr push --tenant globex-azure \\
      --registry hexrglobex.azurecr.io/hexr \\
      --platform linux/amd64

    kubectl config use-context hexr-runtime-aks-1
    hexr deploy .hexr --namespace tenant-globex-azure \\
      --set env.COST_INVESTIGATOR_URL=https://<eks-cost-investigator-lb>:8443

The deploy expects two K8s Secrets in tenant-globex-azure namespace:
    kubectl -n tenant-globex-azure create secret generic azure-openai \\
      --from-literal=api-key=... --from-literal=endpoint=https://<resource>.openai.azure.com
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import hexr
from hexr.a2a.bridge import A2ABridge
from hexr.a2a.client import A2AClient
from hexr.a2a.models import Artifact, Message, TextPart

from crewai import Agent, Crew, Process, Task
from crewai.tools import BaseTool
from langchain_openai import AzureChatOpenAI

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("investment-memo-crew")


# ---------------------------------------------------------------------------
# Cross-cloud tools — each one wraps a single hexr_tool() call.
# CrewAI agents receive these as their `tools=[...]` list.
# ---------------------------------------------------------------------------

class FetchAzureFilings(BaseTool):
    name: str = "fetch_azure_filings"
    description: str = "Download a SEC 10-K filing from the Azure Blob filings cache. Input: ticker symbol."

    def _run(self, ticker: str) -> str:
        account_url = os.environ.get("AZURE_FILINGS_ACCOUNT_URL", "")
        container = os.environ.get("AZURE_FILINGS_CONTAINER", "sec-filings")
        if not account_url:
            return f"[unconfigured] AZURE_FILINGS_ACCOUNT_URL not set; would fetch {ticker} 10-K from azure_storage"
        blob = hexr.hexr_tool("azure_storage")
        client = blob.get_container_client(container)
        data = client.download_blob(f"{ticker.upper()}/latest-10k.txt").readall().decode("utf-8")
        return data[:4000]


class FetchS3Comparables(BaseTool):
    name: str = "fetch_s3_comparables"
    description: str = "Fetch a comparable-companies analysis from the S3 research bucket. Input: sector name."

    def _run(self, sector: str) -> str:
        bucket = os.environ.get("S3_RESEARCH_BUCKET", "globex-research")
        s3 = hexr.hexr_tool("aws_s3")
        try:
            obj = s3.get_object(Bucket=bucket, Key=f"comparables/{sector.lower()}.txt")
            return obj["Body"].read().decode("utf-8")[:4000]
        except Exception as exc:
            return f"[fallback] comparables for {sector} unavailable from s3://{bucket}: {exc}"


class FetchGcsPrecedents(BaseTool):
    name: str = "fetch_gcs_precedents"
    description: str = "Fetch legal precedent notes from the GCS legal-cache bucket. Input: deal-type."

    def _run(self, deal_type: str) -> str:
        bucket = os.environ.get("GCS_LEGAL_BUCKET", "globex-legal-cache")
        gcs = hexr.hexr_tool("gcp_storage")
        try:
            blob = gcs.bucket(bucket).blob(f"precedents/{deal_type.lower()}.txt")
            return blob.download_as_text()[:4000]
        except Exception as exc:
            return f"[fallback] precedents for {deal_type} unavailable from gs://{bucket}: {exc}"


class AskCostInvestigator(BaseTool):
    """Cross-CLUSTER A2A call from AKS into the cost-investigator agent on EKS.

    Uses A2AClient(spiffe_socket=...) so the call carries the orchestrator's
    own X.509 SVID; the EKS Envoy verifies it against the shared trust
    domain root before letting OPA decide.
    """

    name: str = "ask_cost_investigator"
    description: str = "Ask the FinOps cost-investigator agent on the partner cluster about cloud cost anomalies. Input: question."

    def _run(self, question: str) -> str:
        url = os.environ.get("COST_INVESTIGATOR_URL", "")
        socket = os.environ.get("SPIRE_AGENT_SOCKET", "/run/spire/sockets/agent.sock")
        if not url:
            return "[unconfigured] COST_INVESTIGATOR_URL not set; skipping cross-cluster A2A"
        return asyncio.run(_a2a_call(url, socket, question))


async def _a2a_call(url: str, socket: str, question: str) -> str:
    async with A2AClient(url, spiffe_socket=socket) as client:
        task = await client.send(Message.user(question))
        for art in (task.artifacts or []):
            for part in (art.parts or []):
                if getattr(part, "text", None):
                    return part.text
        return "[no text artifact returned]"


# ---------------------------------------------------------------------------
# CrewAI agents. Hierarchical = Investment Director delegates to workers.
# ---------------------------------------------------------------------------

def _llm():
    # Provider selection: DeepSeek (OpenAI-compatible) if DEEPSEEK_API_KEY is
    # mounted from `hexr-llm-credentials`, otherwise Azure OpenAI. Both env
    # vars are auto-mounted by the Hexr SDK (build/k8s.py).
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if deepseek_key:
        # CrewAI accepts a LangChain ChatOpenAI-compatible client.
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=os.getenv("LLM_MODEL", "deepseek-chat"),
            api_key=deepseek_key,
            base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1"),
            temperature=0.2,
        )
    return AzureChatOpenAI(
        azure_deployment=os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o"),
        api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-08-01-preview"),
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        temperature=0.2,
    )


def _build_crew() -> Crew:
    llm = _llm()

    director = Agent(
        role="Investment Director",
        goal="Produce a publication-grade investment memo by directing specialists.",
        backstory="20-year M&A veteran. Delegates ruthlessly; demands citations.",
        llm=llm,
        allow_delegation=True,
        verbose=False,
    )
    researcher = Agent(
        role="Filings Researcher",
        goal="Extract the key financial facts from the latest 10-K.",
        backstory="CFA charterholder; lives in SEC EDGAR.",
        tools=[FetchAzureFilings()],
        llm=llm,
        allow_delegation=False,
        verbose=False,
    )
    writer = Agent(
        role="Memo Writer",
        goal="Draft a 5-paragraph investment memo using comparables.",
        backstory="Ex-Goldman analyst; writes for partner-level readers.",
        tools=[FetchS3Comparables()],
        llm=llm,
        allow_delegation=False,
        verbose=False,
    )
    editor = Agent(
        role="Legal Editor",
        goal="Fact-check, add legal precedents, request cost commentary, finalise.",
        backstory="Ex-DLA Piper M&A counsel; obsessed with precedent + cost.",
        tools=[FetchGcsPrecedents(), AskCostInvestigator()],
        llm=llm,
        allow_delegation=False,
        verbose=False,
    )

    research_task = Task(
        description="Extract revenue, margins, growth, and risk factors for {ticker} from the latest 10-K.",
        expected_output="Markdown bullet list of the 8 most material facts.",
        agent=researcher,
    )
    writing_task = Task(
        description="Write a 5-paragraph investment memo for {ticker} using the research bullets and sector comparables.",
        expected_output="Plain-text memo, 5 paragraphs.",
        agent=writer,
        context=[research_task],
    )
    editing_task = Task(
        description=(
            "Add 1 relevant legal precedent and 1 cross-cloud cost-anomaly note "
            "(ask the cost-investigator agent for the latter). Return the final memo."
        ),
        expected_output="Final memo with `# Headline` on line 1.",
        agent=editor,
        context=[writing_task],
    )

    return Crew(
        agents=[researcher, writer, editor],
        tasks=[research_task, writing_task, editing_task],
        process=Process.hierarchical,
        manager_agent=director,
        verbose=False,
    )


_crew = None


def _get_crew() -> Crew:
    global _crew
    if _crew is None:
        _crew = _build_crew()
    return _crew


# ---------------------------------------------------------------------------
# A2A entrypoint.
# ---------------------------------------------------------------------------

async def handle(message: Message) -> list[Artifact]:
    ticker = (message.text_content() or "NVDA").strip().upper()
    logger.info("investment-memo-crew received ticker: %s", ticker)
    result = _get_crew().kickoff(inputs={"ticker": ticker})
    final = str(result)
    return [
        Artifact(
            artifact_id="investment-memo",
            name=f"{ticker}_memo.md",
            parts=[TextPart(text=final)],
        )
    ]


# ---------------------------------------------------------------------------
# Decorator.
# ---------------------------------------------------------------------------

@hexr.hexr_agent(
    name="investment-memo-crew",
    tenant="globex-azure",
    resources=[
        "azure:storage.blob.read",
        "s3:GetObject",
        "storage.objects.get",
    ],
    regions={"azure": "eastus", "aws": "us-east-1", "gcp": "us-central1"},
    a2a=True,
    description="CrewAI hierarchical investment memo crew with cross-cluster A2A to FinOps.",
    version="1.0.0",
    skills=[
        {
            "id": "investment-memo",
            "name": "Investment memo",
            "description": (
                "Produce a 5-paragraph investment memo on a ticker. Internally "
                "runs a hierarchical CrewAI crew (director + researcher + writer "
                "+ editor) with cross-cloud data sources and a cross-cluster "
                "A2A call to the cost-investigator agent on the AWS data plane."
            ),
        }
    ],
)
class InvestmentMemoCrew:
    def __init__(self) -> None:
        logger.info("InvestmentMemoCrew initialised (CrewAI hierarchical, AzureOpenAI %s)",
                    os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o"))


if __name__ == "__main__":
    bridge = A2ABridge(handler=handle)
    asyncio.run(bridge.start())
