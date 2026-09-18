"""
Globex People — candidate screening pipeline
============================================

The second flagship demo tenant. Runs on AKS in trust domain
``globex-azure.agents.hexr.cloud``, alongside Craneware Health on EKS in
``agents.hexr.cloud``.

WHY HIRING

New York City **Local Law 144** has been enforced since 5 July 2023. Any
employer using an Automated Employment Decision Tool on a candidate for an NYC
role must commission an independent bias audit **annually**, publish a summary,
and give candidates ten business days' notice. Penalties run $500 for a first
violation and $500–$1,500 after — and *every day* a tool runs without a valid
audit is a separate violation. An unaudited screening agent running a quarter
is ninety violations, not one.

In December 2025 the New York State Comptroller audited DCWP's enforcement of
the law and called it **ineffective**. A regulator publicly told it is not
enforcing does not stay that way.

WHAT THIS DEMONSTRATES

Three processes. **Two are instrumented. One deliberately is not.**

    resume-ranker      @hexr_agent  -> gets an identity, signs evidence
    interview-scorer   @hexr_agent  -> gets an identity, signs evidence
    candidate-dedupe   NOT decorated -> runs happily, is nobody

The third is the entire argument. It is written the way such a thing actually
appears: one engineer needed to clean duplicate applications out of a pipeline,
wrote forty lines, and shipped it. It reads candidate records and makes
decisions about them, which makes it an AEDT under LL144 — and nobody knows it
exists, so nobody has audited it.

Agentless discovery finds it. It can say the process exists and give you its
binary SHA-256. It **cannot** say what it did, because it never had an identity
to sign anything with. That is not a gap in the product; it is the honest shape
of the free tier, and the reason the SDK matters.

WHAT WE DO NOT CLAIM

Hexr does not perform bias audits and this file does not pretend to. The
screening logic here is deliberately trivial — keyword matching, no model, no
scoring of protected attributes — because the demo is about *which processes
are running and what they touched*, not about fairness metrics. Bias-audit
vendors are partners: we tell them what to audit.

RUN

    python globex_hr_screening.py            # all three, as in the demo
    python globex_hr_screening.py --no-dark  # only the instrumented two
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
import time
from dataclasses import dataclass, field

import hexr
from hexr import hexr_agent, hexr_tool

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-22s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("globex.hr")

TENANT = os.getenv("HEXR_TENANT_ID", "globex-azure")


def touch_candidate_store(purpose: str) -> str:
    """Reach the candidate record store through Hexr.

    This is what makes the demo real rather than a print statement. hexr_tool()
    exchanges THIS PROCESS's SVID for short-lived Azure credentials and emits a
    signed evidence row either way — `tool_call_allowed` if the exchange
    succeeds, `tool_call_denied` if policy refuses it.

    A denial is not a failure of the demo. It is the demo: the row names the
    process that asked, what it asked for, and that it was refused. The
    pipeline continues regardless, because a screening run that dies when a
    storage call is denied would teach the operator to turn the control off.
    """
    try:
        client = hexr_tool("azure_storage")
        log.info("  [%s] candidate store reached via %s", purpose, type(client).__name__)
        return "allowed"
    except Exception as exc:  # noqa: BLE001 — any failure is evidence, not a crash
        log.info("  [%s] candidate store refused: %s", purpose, type(exc).__name__)
        return "denied"


# ── The candidates ───────────────────────────────────────────────────────────
# Synthetic, and obviously so. Real applicant data has no business in a demo
# tenant, and a reviewer who spots plausible-looking PII stops trusting
# everything else on the page.

@dataclass
class Candidate:
    ref: str
    role: str
    years_experience: int
    skills: list[str]
    source: str
    notes: list[str] = field(default_factory=list)


def load_applications() -> list[Candidate]:
    return [
        Candidate("APP-2026-0001", "backend-engineer", 6, ["python", "kubernetes", "postgres"], "careers-site"),
        Candidate("APP-2026-0002", "backend-engineer", 2, ["python", "django"], "referral"),
        Candidate("APP-2026-0003", "data-engineer", 9, ["spark", "python", "airflow"], "agency"),
        Candidate("APP-2026-0004", "backend-engineer", 6, ["python", "kubernetes", "postgres"], "agency"),
        Candidate("APP-2026-0005", "sre", 4, ["terraform", "kubernetes", "go"], "careers-site"),
    ]


# ── 1. resume-ranker — instrumented ──────────────────────────────────────────

@hexr_agent(
    name="resume-ranker",
    tenant=TENANT,
    subprocess_support=True,
    description="Scores applications against a role's required skills.",
)
def resume_ranker(candidates: list[Candidate], required: list[str]) -> list[tuple[Candidate, float]]:
    """Rank candidates by skill overlap.

    Deliberately simple and deliberately explainable: the score is the fraction
    of required skills present, plus a small bounded weight for experience. No
    model, no embeddings, nothing that could be mistaken for a fairness claim.
    What matters for the demo is that every call this process makes is signed
    by ITS identity, not the pod's.
    """
    log.info("resume-ranker: scoring %d applications against %s", len(candidates), required)
    touch_candidate_store("read applications")
    ranked: list[tuple[Candidate, float]] = []
    for c in candidates:
        overlap = len(set(required) & set(c.skills)) / max(len(required), 1)
        experience = min(c.years_experience, 10) / 10.0
        score = round(0.8 * overlap + 0.2 * experience, 3)
        ranked.append((c, score))
        log.info("  %s  %-18s  skills=%.2f  exp=%.2f  -> %.3f",
                 c.ref, c.role, overlap, experience, score)
    ranked.sort(key=lambda t: t[1], reverse=True)
    return ranked


# ── 2. interview-scorer — instrumented ───────────────────────────────────────

@hexr_agent(
    name="interview-scorer",
    tenant=TENANT,
    subprocess_support=True,
    description="Turns structured interview feedback into a recommendation.",
)
def interview_scorer(ranked: list[tuple[Candidate, float]], threshold: float = 0.55) -> list[dict]:
    """Recommend advance/hold for candidates above the ranking threshold.

    A second identity, not a second function on the first one. Under stock
    SPIRE this and resume-ranker would share the pod's identity and you could
    not tell which of them touched a given application. Here they are two
    SPIFFE IDs differing in process_role.
    """
    log.info("interview-scorer: reviewing candidates above %.2f", threshold)
    touch_candidate_store("write decisions")
    decisions = []
    for c, score in ranked:
        if score < threshold:
            outcome, reason = "hold", f"ranking {score:.3f} below threshold {threshold:.2f}"
        else:
            outcome, reason = "advance", f"ranking {score:.3f} meets threshold"
        decisions.append({"ref": c.ref, "role": c.role, "outcome": outcome, "reason": reason})
        log.info("  %s  %-8s  %s", c.ref, outcome, reason)
    return decisions


# ── 3. candidate-dedupe — DELIBERATELY NOT INSTRUMENTED ──────────────────────
#
# No decorator. No import of anything Hexr. This is the point.
#
# It is written the way this actually happens: someone needed duplicate
# applications removed, wrote the obvious thing, and shipped it. It never
# occurred to them that a script which reads candidate records and decides
# which ones survive is an automated employment decision tool.
#
# Because it never called @hexr_agent, it writes no context file. The enhanced
# attestor therefore emits no hexr: selectors for its PID, no registration
# entry matches, and SPIRE issues it nothing. It runs perfectly well. It is
# simply nobody.
#
# Do NOT "fix" this by decorating it. The dark row is the demo.

def candidate_dedupe(candidates: list[Candidate]) -> list[Candidate]:
    """Drop applications that look like duplicates of an earlier one."""
    log.info("candidate-dedupe: scanning %d applications", len(candidates))
    # It reaches the same candidate store as the instrumented agents. Note what
    # does NOT happen: no SVID exchange, no evidence row, no record anywhere
    # that this process read candidate data at all. It uses whatever ambient
    # credentials the pod happens to carry, which is exactly the posture Hexr
    # exists to replace.
    touch_candidate_store("dedupe scan")
    seen: dict[tuple, Candidate] = {}
    kept: list[Candidate] = []
    for c in candidates:
        fingerprint = (c.role, c.years_experience, tuple(sorted(c.skills)))
        if fingerprint in seen:
            original = seen[fingerprint]
            log.info("  %s dropped as duplicate of %s", c.ref, original.ref)
            continue
        seen[fingerprint] = c
        kept.append(c)
    log.info("candidate-dedupe: %d -> %d applications", len(candidates), len(kept))
    return kept


# ── Pipeline ─────────────────────────────────────────────────────────────────

def run_once(include_dark: bool) -> dict:
    applications = load_applications()
    required = ["python", "kubernetes", "postgres"]

    if include_dark:
        # The dark process runs FIRST and removes a candidate. By the time the
        # instrumented agents see the list, APP-2026-0004 is gone — and no
        # signed evidence anywhere explains why. That absence is the finding.
        applications = candidate_dedupe(applications)
    else:
        log.info("candidate-dedupe: skipped (--no-dark)")

    ranked = resume_ranker(applications, required)
    decisions = interview_scorer(ranked)

    advanced = sum(1 for d in decisions if d["outcome"] == "advance")
    log.info("pipeline complete: %d reviewed, %d advanced", len(decisions), advanced)
    return {"reviewed": len(decisions), "advanced": advanced, "decisions": decisions}


def main() -> int:
    ap = argparse.ArgumentParser(description="Globex People candidate screening")
    ap.add_argument("--no-dark", action="store_true",
                    help="skip the uninstrumented candidate-dedupe process")
    ap.add_argument("--loop", type=int, default=0,
                    help="run continuously, sleeping N seconds between passes")
    args = ap.parse_args()

    log.info("Globex People screening — tenant=%s", TENANT)
    log.info("SDK identity: %s", getattr(hexr, "__version__", "unknown"))

    while True:
        result = run_once(include_dark=not args.no_dark)
        print(json.dumps(result, indent=2))
        if args.loop <= 0:
            return 0
        # Jitter so successive passes do not land on the same second, which
        # makes evidence timelines easier to read.
        time.sleep(args.loop + random.uniform(0, 3))


if __name__ == "__main__":
    sys.exit(main())
