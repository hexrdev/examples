"""
Denial-Review Crew — HEXR A2A Enhanced (Craneware / Trisus-aligned demo)
=========================================================================

A HIPAA-aware claims-denial appeal pipeline modelled on the customer profile
of The Craneware Group (Trisus Unified Healthcare Financial Intelligence).

This is a purpose-built variant of `content_creation_crew_a2a.py` that
demonstrates the enterprise pitch to healthcare-finance buyers:

  * Three specialised agents — ClaimsAnalyst, PolicyReviewer, DenialWriter
  * All ePHI-adjacent inputs are SYNTHETIC / MOCK; the pipeline never touches
    real patient data. The demo is safe to run against any test cluster.
  * Every tool call is mediated by SPIFFE + credential-injector + OPA and
    emits `compliance_evidence` rows tagged with HIPAA §164.308/§164.312
    controls, ready for `hexr audit --framework hipaa`.
  * Final artifact (redacted denial-appeal draft) is written to the tenant
    S3 bucket via `hexr_tool('aws_s3')` — auditor can trace the exact bytes
    that left the cluster.

Hexr Concepts Demonstrated:
  - @hexr_agent    → Register agent classes, discovered by `hexr build`
  - hexr_tool()    → Cloud credentials via SPIFFE identity (no boto3 in agent code)
  - hexr_llm()     → LLM client wrapper with OTel + LLM Guard (PII redaction)
  - A2ABridge      → Expose agent over A2A protocol
  - VaultClient    → Fetch secrets via SPIFFE identity

A2A Flow:
    External caller -> Envoy -> A2A Sidecar :8090 -> Bridge :8080 /execute
    -> handle_denial_request() -> 3-stage pipeline -> artifact -> back
"""

import asyncio
import hashlib
import json
import logging
import os
import time

import hexr
import openai
from hexr import hexr_llm
from hexr.a2a.bridge import A2ABridge
from hexr.a2a.models import Message
from hexr.vault import VaultClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Tenant-scoped S3 bucket. Terraform (deployment/terraform/aws/tenants/) provisions
# hexr-<tenant>-artifacts-<account>; tenant-bootstrap can inject as HEXR_TENANT_S3_BUCKET.
# Falls back to the pivot-demo bucket for local runs.
_TENANT_S3_BUCKET = os.environ.get(
    "HEXR_TENANT_S3_BUCKET", "hexr-pivot-demo-artifacts-697675504955"
)

# SYNTHETIC claim used when the A2A caller does not supply one. All fields are
# fabricated — no real patient data, no real payer identifiers.
_SYNTHETIC_CLAIM = {
    "claim_id": "SYN-CLM-2026-000042",
    "patient_pseudonym": "PATIENT-A",   # never a real name
    "dob_year": 1958,                    # year only, no month/day
    "service_date": "2026-05-14",
    "cpt_codes": ["99223", "93010"],
    "drg": "291",                        # heart failure w/ MCC
    "denial_code": "CO-197",             # precert/authorization absent
    "billed_amount_usd": 8420.00,
    "payer_class": "MEDICARE_ADVANTAGE",
}


def _verify_s3(s3, label: str) -> None:
    """Tenant-scoped S3 auth probe. Uses head_bucket (allowed by the tenant IAM policy)
    instead of list_buckets (a wildcard-resource op that AWS correctly rejects under
    least-privilege tenant scoping)."""
    try:
        s3.head_bucket(Bucket=_TENANT_S3_BUCKET)
        logger.info(f"✅ {label} S3 access verified on bucket={_TENANT_S3_BUCKET}")
    except Exception as e:
        logger.error(f"❌ {label} S3 access failed: {e}")


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
#   hexr build denial_review_crew_a2a.py --tenant YOUR_TENANT


@hexr.hexr_agent(
    name="claims_analyst",
    role="analyst",
    tenant="pivot-demo",
)
class ClaimsAnalyst:
    """Parses the (synthetic) claim payload and extracts denial-relevant facts."""

    def __init__(self):
        logger.info("🩺 Initializing Claims Analyst")
        self.s3 = hexr.hexr_tool("aws_s3")

    def analyze(self, claim: dict) -> str:
        logger.info(f"🔍 Analyzing claim {claim.get('claim_id')}")
        _verify_s3(self.s3, "claims_analyst")

        summary_prompt = (
            "You are a healthcare revenue-integrity analyst. Read the (synthetic) "
            "claim record below and summarise, in three bullets:\n"
            "  * the clinical service delivered,\n"
            "  * the denial reason inferred from the denial_code, and\n"
            "  * one revenue-integrity concern.\n"
            "Do NOT invent patient identifiers, dates of birth, or provider names.\n\n"
            f"{json.dumps(claim, indent=2)}"
        )

        if _llm_client is not None:
            try:
                resp = _llm_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": summary_prompt}],
                    max_tokens=220,
                    temperature=0.2,
                )
                out = resp.choices[0].message.content
                logger.info("✅ hexr_llm claim-analysis complete")
                return f"Claim analysis:\n{out}"
            except Exception as e:
                logger.warning(f"hexr_llm call failed, falling back to static: {e}")

        return (
            f"Claim analysis (fallback): "
            f"CPT {claim.get('cpt_codes')} DRG {claim.get('drg')} denied with "
            f"{claim.get('denial_code')} — likely missing prior authorization."
        )


@hexr.hexr_agent(
    name="policy_reviewer",
    role="reviewer",
    tenant="pivot-demo",
)
class PolicyReviewer:
    """Cites the (mock) payer policy sections that govern the denial and appeal."""

    def __init__(self):
        logger.info("📚 Initializing Policy Reviewer")
        self.s3 = hexr.hexr_tool("aws_s3")

    def review(self, claim: dict, analysis: str) -> str:
        logger.info("📖 Reviewing applicable payer policy")
        _verify_s3(self.s3, "policy_reviewer")

        prompt = (
            "You are a payer-policy specialist. Given the claim analysis below, "
            "cite THREE mock (fabricated) payer policy references — invent them "
            "with clear 'MOCK-' prefix so no real payer is implicated — that would "
            "support an appeal argument. Keep it under 180 words.\n\n"
            f"Denial code: {claim.get('denial_code')}\n"
            f"Analysis:\n{analysis}"
        )

        if _llm_client is not None:
            try:
                resp = _llm_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=280,
                    temperature=0.3,
                )
                out = resp.choices[0].message.content
                logger.info("✅ hexr_llm policy-review complete")
                return f"Policy review:\n{out}"
            except Exception as e:
                logger.warning(f"hexr_llm call failed, falling back to static: {e}")

        return (
            "Policy review (fallback): MOCK-PAY-POLICY-101 §3.2 permits retro-authorization "
            "for emergent inpatient admissions when medical-necessity documentation is "
            "supplied within 30 days of discharge."
        )


@hexr.hexr_agent(
    name="denial_writer",
    role="writer",
    tenant="pivot-demo",
)
class DenialWriter:
    """Drafts the audit-ready denial-appeal letter."""

    def __init__(self):
        logger.info("✍️ Initializing Denial Writer")
        self.s3 = hexr.hexr_tool("aws_s3")

    def draft(self, claim: dict, analysis: str, policy: str) -> str:
        logger.info("📝 Drafting denial-appeal letter")
        _verify_s3(self.s3, "denial_writer")

        prompt = (
            "You are a healthcare-finance appeals writer. Compose a concise "
            "denial-appeal letter body (no letterhead, no signature block) "
            "that references the claim number, denial code, clinical summary, "
            "and the cited mock policy sections. Do NOT include any patient "
            "name, SSN, MRN, DOB month/day, phone, address, or email. Use only "
            "the pseudonymous identifier already in the input. Under 300 words.\n\n"
            f"Claim: {claim.get('claim_id')} (patient {claim.get('patient_pseudonym')})\n"
            f"Analysis:\n{analysis}\n\n"
            f"Policy:\n{policy}"
        )

        if _llm_client is not None:
            try:
                resp = _llm_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=380,
                    temperature=0.4,
                )
                out = resp.choices[0].message.content
                logger.info("✅ hexr_llm draft complete")
                return out
            except Exception as e:
                logger.warning(f"hexr_llm call failed, falling back to static: {e}")

        return (
            f"Appeal (fallback): Re {claim.get('claim_id')} — request retro-authorization "
            "review per MOCK-PAY-POLICY-101 §3.2. Clinical documentation attached."
        )


@hexr.hexr_agent(
    name="denial-review-orchestrator",
    role="orchestrator",
    tenant="pivot-demo",
    a2a=True,
    skills=[
        {
            "id": "denial-review",
            "name": "Denial Review",
            "description": (
                "HIPAA-aware three-agent pipeline that analyzes a synthetic claim, "
                "cites payer policy, and drafts an audit-ready denial-appeal letter. "
                "Every step emits signed compliance_evidence rows for the auditor."
            ),
        },
    ],
    description="Denial-review pipeline. Send a (synthetic) claim JSON and receive an appeal draft written to the tenant S3 bucket.",
)
class DenialReviewPipeline:
    """Orchestrator for the denial-review crew."""

    def __init__(self):
        logger.info("🎯 Initializing Denial-Review Pipeline")
        self.s3 = hexr.hexr_tool("aws_s3")

    def run(self, claim: dict | None = None) -> str:
        claim = claim or _SYNTHETIC_CLAIM
        logger.info(f"🚀 Denial-review start for claim={claim.get('claim_id')}")

        _verify_s3(self.s3, "pipeline")

        analyst = ClaimsAnalyst()
        reviewer = PolicyReviewer()
        writer = DenialWriter()

        analysis = analyst.analyze(claim)
        policy = reviewer.review(claim, analysis)
        appeal = writer.draft(claim, analysis, policy)

        report = (
            "=== Denial-Review Appeal Draft ===\n"
            f"Claim ID: {claim.get('claim_id')}\n"
            f"Patient (pseudonym): {claim.get('patient_pseudonym')}\n"
            f"Denial code: {claim.get('denial_code')}\n\n"
            f"--- Analysis ---\n{analysis}\n\n"
            f"--- Policy citations ---\n{policy}\n\n"
            f"--- Appeal draft ---\n{appeal}\n"
        )

        # End-to-end enterprise proof: upload to the tenant S3 bucket.
        key = f"denial-reviews/{int(time.time())}-{hashlib.sha1(claim.get('claim_id','').encode()).hexdigest()[:12]}.txt"
        try:
            self.s3.put_object(
                Bucket=_TENANT_S3_BUCKET,
                Key=key,
                Body=report.encode("utf-8"),
                ContentType="text/plain; charset=utf-8",
                Metadata={
                    "hexr-framework": "hipaa",
                    "hexr-controls": "164.308-a-6-ii,164.312-b,164.312-c-1",
                    "hexr-claim-id": claim.get("claim_id", ""),
                    "hexr-synthetic": "true",
                },
            )
            logger.info(f"✅ Uploaded appeal to s3://{_TENANT_S3_BUCKET}/{key}")
            report += f"\n\nUploaded: s3://{_TENANT_S3_BUCKET}/{key}"
        except Exception as e:
            logger.error(f"❌ S3 put_object failed: {e}")
            report += f"\n\nS3 upload FAILED: {e}"

        logger.info(f"✅ Denial-review complete for claim={claim.get('claim_id')}")
        return report


# ---------------------------------------------------------------------------
# A2A Handler — receives messages from the A2A sidecar, runs the pipeline
# ---------------------------------------------------------------------------

def handle_denial_request(message: Message) -> str:
    """A2A handler: parse message body as claim JSON (or use synthetic default)."""
    body = message.text_content().strip()
    claim: dict | None = None
    if body:
        try:
            claim = json.loads(body)
            logger.info(f"A2A request received — parsed claim {claim.get('claim_id')}")
        except json.JSONDecodeError:
            logger.info("A2A request received — non-JSON body, using synthetic claim")
    else:
        logger.info("A2A request received — empty body, using synthetic claim")

    pipeline = DenialReviewPipeline()
    return pipeline.run(claim)


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("Denial-Review Pipeline (A2A) — Craneware demo variant — Starting")
    logger.info("=" * 60)

    bridge = A2ABridge(handle_denial_request)
    logger.info("A2A Bridge starting on 127.0.0.1:8080")
    asyncio.run(bridge.start())
