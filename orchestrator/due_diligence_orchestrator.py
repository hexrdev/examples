"""
A2A Due Diligence Orchestrator — HEXR A2A Example
==================================================

Demonstrates agent-to-agent communication by orchestrating two independent
deep-agent pods:

1. CrewAI Content Crew (crewaai_a2a) — researches a topic and produces content
2. LangChain Financial Analysis (langchain_a2a) — runs a 5-agent analysis pipeline

This orchestrator:
    - Receives a company/topic via A2A message
    - Sends parallel A2A requests to both worker agents
    - Collects artifacts from both
    - Synthesizes a combined due-diligence brief
    - Returns the brief as an A2A artifact

Architecture:
    External caller -> Envoy -> Orchestrator sidecar :8090 -> Bridge :8080
    -> handle_diligence_request()
        |-- A2AClient -> content-crew (crewaai_a2a pod)   \\ parallel
        |-- A2AClient -> financial-analysis (langchain_a2a pod) / via asyncio.gather
    -> synthesize -> artifact -> back

Service URLs (static K8s DNS — known at deploy time, namespace from HEXR_TENANT_ID env var):
    - content-creation-crew-a2a.tenant-YOUR_TENANT.svc.cluster.local
    - financial-analysis-agents-a2a.tenant-YOUR_TENANT.svc.cluster.local
"""

import asyncio
import logging
import os

import hexr
from hexr import hexr_llm
import openai
from hexr.a2a.bridge import A2ABridge
from hexr.a2a.client import A2AClient
from hexr.a2a.models import Message, Artifact, TextPart
from hexr.vault import VaultClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _get_openai_key() -> str | None:
    """Fetch OpenAI API key from Hexr Vault, fallback to env var for local dev."""
    # Production path: fetch from Hexr Vault (SPIFFE-authenticated)
    try:
        vault = VaultClient()
        key = vault.get("api-keys/openai")
        logger.info("✅ OpenAI API key fetched from Hexr Vault")
        return key
    except Exception as e:
        logger.debug(f"Vault unavailable ({e}), trying env var fallback")
    # Fallback for local development
    return os.environ.get("OPENAI_API_KEY")


# ── hexr_llm: wrap the OpenAI client for automatic OTel instrumentation ──
# Every call through this client gets a span with gen_ai.* attributes.
_api_key = _get_openai_key()
_llm_client = hexr_llm(openai.OpenAI(api_key=_api_key)) if _api_key else None

# ---------------------------------------------------------------------------
# Static A2A target URLs (K8s service DNS)
# Override via env vars for flexibility in different environments
# ---------------------------------------------------------------------------
_NS = os.environ.get("HEXR_TENANT_ID", "tenant-hexr-internal")
CONTENT_CREW_URL = os.getenv(
    "A2A_CONTENT_CREW_URL",
    f"http://content-creation-crew-a2a.{_NS}.svc.cluster.local",
)
FINANCIAL_ANALYSIS_URL = os.getenv(
    "A2A_FINANCIAL_ANALYSIS_URL",
    f"http://financial-analysis-agents-a2a.{_NS}.svc.cluster.local",
)


@hexr.hexr_agent(
    name="due-diligence-orchestrator",
    role="orchestrator",
    tenant="demo",
    a2a=True,
    skills=[
        {
            "id": "due-diligence",
            "name": "Due Diligence",
            "description": (
                "Orchestrate comprehensive company due diligence by invoking "
                "a content research crew and a financial analysis team in parallel, "
                "then synthesizing results into a combined brief."
            ),
        },
    ],
    description=(
        "A2A orchestrator that delegates work to two deep-agent pods "
        "(CrewAI content crew + LangChain financial analysis) via the A2A protocol, "
        "collects their results in parallel, and returns a unified due-diligence report."
    ),
)
def due_diligence_orchestrator():
    """Placeholder — the real work happens in handle_diligence_request."""
    pass


# ---------------------------------------------------------------------------
# A2A Handler — the core orchestration logic
# ---------------------------------------------------------------------------

async def handle_diligence_request(message: Message) -> str:
    """A2A handler: fan-out to CrewAI + LangChain agents, fan-in results.

    Called by the Go A2A sidecar via Bridge :8080 /execute.

    Args:
        message: Inbound A2A message — text is the company/topic to research.

    Returns:
        Combined due-diligence brief as plain text (auto-wrapped in Artifact).
    """
    subject = message.text_content().strip() or "Anthropic"
    logger.info(f"A2A due-diligence request received — subject: {subject}")

    # -----------------------------------------------------------------------
    # Fan-out: send parallel A2A requests to both worker agents
    # -----------------------------------------------------------------------
    async with (
        A2AClient(CONTENT_CREW_URL, timeout=120.0) as content_client,
        A2AClient(FINANCIAL_ANALYSIS_URL, timeout=120.0) as finance_client,
    ):
        logger.info(f"Sending parallel A2A requests for: {subject}")

        content_task, finance_task = await asyncio.gather(
            content_client.send(
                Message.user(f"Create comprehensive content about: {subject}"),
            ),
            finance_client.send(
                Message.user(f"Run financial analysis for: {subject}"),
            ),
            return_exceptions=True,
        )

    # -----------------------------------------------------------------------
    # Collect results (handle errors gracefully)
    # -----------------------------------------------------------------------
    if isinstance(content_task, Exception):
        content_result = f"[Content Crew Error] {content_task}"
        logger.error(f"Content crew failed: {content_task}")
    else:
        content_result = content_task.text_result() or "[No content artifacts]"
        logger.info(f"Content crew completed — task {content_task.id} ({content_task.state.value})")

    if isinstance(finance_task, Exception):
        finance_result = f"[Financial Analysis Error] {finance_task}"
        logger.error(f"Financial analysis failed: {finance_task}")
    else:
        finance_result = finance_task.text_result() or "[No financial artifacts]"
        logger.info(f"Financial analysis completed — task {finance_task.id} ({finance_task.state.value})")

    # -----------------------------------------------------------------------
    # Fan-in: synthesize combined due-diligence brief
    # -----------------------------------------------------------------------
    # Use hexr_llm() to produce an LLM-powered synthesis when available
    llm_synthesis = ""
    if _llm_client is not None:
        try:
            resp = _llm_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a senior due-diligence analyst. Given content research and "
                            "financial analysis from two independent teams, write a concise 4-5 "
                            "sentence executive synthesis highlighting key findings, risks, and "
                            "a clear investment recommendation."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Subject: {subject}\n\n"
                            f"--- Content Research ---\n{content_result[:1500]}\n\n"
                            f"--- Financial Analysis ---\n{finance_result[:1500]}"
                        ),
                    },
                ],
                max_tokens=300,
                temperature=0.3,
            )
            llm_synthesis = resp.choices[0].message.content
            tokens_in = getattr(resp.usage, "prompt_tokens", "?")
            tokens_out = getattr(resp.usage, "completion_tokens", "?")
            logger.info(f"\u2705 hexr_llm synthesis: {tokens_in} in / {tokens_out} out tokens")
        except Exception as e:
            logger.warning(f"hexr_llm synthesis failed, using static summary: {e}")

    synthesis_text = (
        llm_synthesis
        if llm_synthesis
        else (
            f"This due-diligence report was produced by the Hexr A2A orchestrator.\n"
            f"Two independent deep-agent pods were invoked in parallel:\n"
            f"  1. CrewAI Content Crew \u2014 {len(content_result)} chars of research content\n"
            f"  2. LangChain Financial Analysis \u2014 {len(finance_result)} chars of financial data\n\n"
            f"Both agents authenticated via SPIFFE mTLS through the Envoy mesh,\n"
            f"authorized by OPA policy, and traced end-to-end via OpenTelemetry.\n"
        )
    )

    brief = (
        f"{'=' * 60}\n"
        f"DUE DILIGENCE REPORT: {subject}\n"
        f"{'=' * 60}\n\n"
        f"--- SECTION 1: Content Research (CrewAI) ---\n\n"
        f"{content_result}\n\n"
        f"--- SECTION 2: Financial Analysis (LangChain) ---\n\n"
        f"{finance_result}\n\n"
        f"{'=' * 60}\n"
        f"EXECUTIVE SYNTHESIS"
        f"{' (LLM-powered)' if llm_synthesis else ''}\n"
        f"{'=' * 60}\n\n"
        f"{synthesis_text}\n"
    )

    logger.info(f"Due diligence complete for {subject} — brief is {len(brief)} chars")
    return brief


# ---------------------------------------------------------------------------
# Main — start the A2A Bridge
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("A2A Due Diligence Orchestrator - Starting")
    logger.info("=" * 60)
    logger.info(f"Content Crew target:       {CONTENT_CREW_URL}")
    logger.info(f"Financial Analysis target: {FINANCIAL_ANALYSIS_URL}")

    # Start the A2A bridge — blocks forever, waiting for sidecar requests
    bridge = A2ABridge(handle_diligence_request)
    logger.info("A2A Bridge starting on 127.0.0.1:8080")
    asyncio.run(bridge.start())
