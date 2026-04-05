"""
Content Creation Pipeline - HEXR A2A Enhanced
==============================================

A content creation system with specialized agents:
- Research Agent: Investigates topics and gathers information
- Writer Agent: Creates engaging content based on research
- Editor Agent: Reviews and refines content for quality

Pattern: Sequential pipeline with hexr_llm for LLM calls

Hexr Concepts Demonstrated:
  - @hexr_agent    → Register agent classes, discovered by `hexr build` (docs.hexr.dev/sdk/hexr-agent)
  - hexr_tool()    → Cloud credentials via SPIFFE identity (docs.hexr.dev/sdk/hexr-tool)
  - hexr_llm()     → LLM client wrapper with OTel + LLM Guard (docs.hexr.dev/sdk/hexr-llm)
  - A2ABridge      → Expose agent over A2A protocol (docs.hexr.dev/sdk/hexr-a2a)
  - VaultClient    → Fetch secrets via SPIFFE identity (docs.hexr.dev/sdk/vault)
  - LLM Guard      → Automatic prompt/output scanning (docs.hexr.dev/security/llm-guard)

A2A Flow:
    External caller -> Envoy -> A2A Sidecar :8090 -> Bridge :8080 /execute
    -> handle_content_request() -> 3-stage pipeline -> artifacts -> back
"""

import asyncio
import logging
import os
import hexr
from hexr import hexr_llm
import openai
from hexr.a2a.bridge import A2ABridge
from hexr.a2a.models import Message, Artifact, TextPart
from hexr.vault import VaultClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _get_openai_key() -> str | None:
    """Fetch OpenAI API key from Hexr Vault, fallback to env var for local dev."""
    try:
        vault = VaultClient()
        key = vault.get("api-keys/openai")
        logger.info("✅ OpenAI API key fetched from Hexr Vault")
        return key
    except Exception as e:
        logger.debug(f"Vault unavailable ({e}), trying env var fallback")
    return os.environ.get("OPENAI_API_KEY")


# ── hexr_llm: wrap the OpenAI client for automatic OTel tracing + LLM Guard ──
_api_key = _get_openai_key()
_llm_client = hexr_llm(openai.OpenAI(api_key=_api_key)) if _api_key else None


# NOTE: tenant= is a source-code default. It's overridden at build time by:
#   hexr build content_creation_crew_a2a.py --tenant YOUR_TENANT

@hexr.hexr_agent(
    name="research_agent",
    role="researcher",
    tenant="demo"
)
class ResearchAgent:
    """Research agent that gathers information using cloud tools"""

    def __init__(self):
        logger.info("🔬 Initializing Research Agent")
        # hexr_tool: request AWS S3 credentials via SPIFFE identity (no API keys needed)
        self.s3 = hexr.hexr_tool('aws_s3')

    def research(self, topic: str) -> str:
        """Research a topic using S3 for data storage + hexr_llm for LLM calls."""
        logger.info(f"📚 Researching topic: {topic}")

        try:
            buckets = self.s3.list_buckets()
            logger.info(f"✅ S3 access verified: {len(buckets)} buckets found")
        except Exception as e:
            logger.error(f"❌ S3 access failed: {e}")

        if _llm_client is not None:
            try:
                resp = _llm_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "You are a research analyst. Provide 3 concise bullet points."},
                        {"role": "user", "content": f"Research key facts about: {topic}"},
                    ],
                    max_tokens=200,
                    temperature=0.4,
                )
                result = resp.choices[0].message.content
                tokens_in = getattr(resp.usage, "prompt_tokens", "?")
                tokens_out = getattr(resp.usage, "completion_tokens", "?")
                logger.info(f"✅ hexr_llm research: {tokens_in} in / {tokens_out} out tokens")
                return f"Research findings (LLM):\n{result}"
            except Exception as e:
                logger.warning(f"hexr_llm call failed, falling back to static: {e}")

        return f"Research findings on {topic}"


@hexr.hexr_agent(
    name="writer_agent",
    role="writer",
    tenant="demo"
)
class WriterAgent:
    """Writer agent that creates content"""

    def __init__(self):
        logger.info("✍️ Initializing Writer Agent")
        self.s3 = hexr.hexr_tool('aws_s3')

    def write(self, research: str) -> str:
        """Write content based on research."""
        logger.info("📝 Writing content")

        try:
            buckets = self.s3.list_buckets()
            logger.info(f"✅ S3 access verified: {len(buckets)} buckets found")
        except Exception as e:
            logger.error(f"❌ S3 access failed: {e}")

        if _llm_client is not None:
            try:
                resp = _llm_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "You are a professional content writer. Write a concise, engaging 2-paragraph article based on the research provided."},
                        {"role": "user", "content": f"Write an article based on this research:\n{research}"},
                    ],
                    max_tokens=300,
                    temperature=0.7,
                )
                result = resp.choices[0].message.content
                tokens_in = getattr(resp.usage, "prompt_tokens", "?")
                tokens_out = getattr(resp.usage, "completion_tokens", "?")
                logger.info(f"✅ hexr_llm write: {tokens_in} in / {tokens_out} out tokens")
                return f"Draft (LLM):\n{result}"
            except Exception as e:
                logger.warning(f"hexr_llm call failed, falling back to static: {e}")

        return f"Draft content based on: {research}"


@hexr.hexr_agent(
    name="editor_agent",
    role="editor",
    tenant="demo"
)
class EditorAgent:
    """Editor agent that reviews and refines content"""

    def __init__(self):
        logger.info("📋 Initializing Editor Agent")
        self.s3 = hexr.hexr_tool('aws_s3')

    def edit(self, draft: str) -> str:
        """Edit and refine content."""
        logger.info("✏️ Editing content")

        try:
            buckets = self.s3.list_buckets()
            logger.info(f"✅ S3 access verified: {len(buckets)} buckets found")
        except Exception as e:
            logger.error(f"❌ S3 access failed: {e}")

        if _llm_client is not None:
            try:
                resp = _llm_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "You are a senior editor. Polish this draft for clarity and impact. Return only the improved text."},
                        {"role": "user", "content": f"Edit this draft:\n{draft}"},
                    ],
                    max_tokens=350,
                    temperature=0.3,
                )
                result = resp.choices[0].message.content
                tokens_in = getattr(resp.usage, "prompt_tokens", "?")
                tokens_out = getattr(resp.usage, "completion_tokens", "?")
                logger.info(f"✅ hexr_llm edit: {tokens_in} in / {tokens_out} out tokens")
                return f"Final (LLM):\n{result}"
            except Exception as e:
                logger.warning(f"hexr_llm call failed, falling back to static: {e}")

        return f"Polished content: {draft}"


@hexr.hexr_agent(
    name="content-crew-orchestrator",
    role="orchestrator",
    tenant="demo",
    a2a=True,
    skills=[
        {
            "id": "content-creation",
            "name": "Content Creation",
            "description": "Research a topic and produce polished, publication-ready content using a crew of research, writing, and editing agents.",
        },
    ],
    description="Content creation pipeline. Send a topic and receive a researched, written, and edited article.",
)
class ContentCreationPipeline:
    """Main orchestrator for content creation pipeline"""

    def __init__(self):
        logger.info("🎯 Initializing Content Creation Pipeline")
        self.s3 = hexr.hexr_tool('aws_s3')

    def run(self, topic: str) -> str:
        """Execute the full content creation pipeline."""
        logger.info(f"🚀 Starting content creation for: {topic}")

        try:
            buckets = self.s3.list_buckets()
            logger.info(f"✅ Pipeline S3 access verified: {len(buckets)} buckets found")
        except Exception as e:
            logger.error(f"❌ Pipeline S3 access failed: {e}")

        research_agent = ResearchAgent()
        writer_agent = WriterAgent()
        editor_agent = EditorAgent()

        research_result = research_agent.research(topic)
        write_result = writer_agent.write(research_result)
        final_result = editor_agent.edit(write_result)

        logger.info(f"✅ Content creation complete for: {topic}")
        return (
            f"=== Content Creation Report ===\n"
            f"Topic: {topic}\n\n"
            f"Research:\n{research_result}\n\n"
            f"Draft:\n{write_result}\n\n"
            f"Final:\n{final_result}"
        )


# ---------------------------------------------------------------------------
# A2A Handler — receives messages from the A2A sidecar, runs the pipeline
# ---------------------------------------------------------------------------

def handle_content_request(message: Message) -> str:
    """A2A handler: extract topic from message, run the pipeline, return result."""
    topic = message.text_content().strip() or "AI in healthcare"
    logger.info(f"A2A request received — topic: {topic}")

    pipeline = ContentCreationPipeline()
    return pipeline.run(topic)


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("Content Creation Pipeline (A2A) - Starting")
    logger.info("=" * 60)

    bridge = A2ABridge(handle_content_request)
    logger.info("A2A Bridge starting on 127.0.0.1:8080")
    asyncio.run(bridge.start())
