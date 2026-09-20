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
import multiprocessing
import os
import random
import sys
import time
from dataclasses import dataclass, field

import hexr
from hexr import hexr_agent, hexr_llm, hexr_tool

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-22s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("globex.hr")

TENANT = os.getenv("HEXR_TENANT_ID", "globex-azure")
VAULT_TENANT = os.getenv("HEXR_TENANT", "globex-azure")  # the identity's tenant, as the Vault scopes it


def touch_candidate_store(purpose: str) -> str:
    """Reach the candidate record store through Hexr.

    This is what makes the demo real rather than a print statement. hexr_tool()
    exchanges THIS PROCESS's SVID for short-lived cloud credentials and emits a
    signed evidence row either way — `tool_call_allowed` if the exchange
    succeeds, `tool_call_denied` if policy refuses it.

    The store is a GCS bucket, reached from an Azure-hosted process: the
    credential-injector federates the process's identity into GCP through the
    tenant's workload-identity provider (hexr-globex-azure), so the agent
    holds no key for either cloud. It was `azure_storage` until 2026-09-19;
    the injector federates to AWS and GCP only, so that call was refused by
    policy on every run, and the demo's "allowed" path had never once
    happened.

    A denial is not a failure of the demo. It is the demo: the row names the
    process that asked, what it asked for, and that it was refused. The
    pipeline continues regardless, because a screening run that dies when a
    storage call is denied would teach the operator to turn the control off.
    """
    try:
        client = hexr_tool("gcp_storage")
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

_llm_state: dict = {}


def _llm():
    """The model client for THIS process, built on first use.

    The key comes from Hexr Vault, released only to a process that proves its
    identity — so this cannot run at import, when the process has none. If
    the Vault has no key for this tenant the scorer works without a model
    and says so in its reason; nothing is faked.
    """
    if "client" not in _llm_state:
        _llm_state["client"] = None
        try:
            import openai
            from hexr.vault.client import VaultClient
            # Secret paths are scoped by the tenant in the process's identity
            # (globex-azure), not by the namespace (tenant-globex-azure).
            key = VaultClient().get(f"{VAULT_TENANT}/api-keys/deepseek")
            if key:
                _llm_state["client"] = hexr_llm(openai.OpenAI(api_key=key, base_url="https://api.deepseek.com"))
                log.info("  model key released by the Vault to this process")
        except Exception as exc:  # noqa: BLE001 — evidence, not a crash
            log.info("  no model key for this process: %s", type(exc).__name__)
    return _llm_state["client"]


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
    client = _llm()
    decisions = []
    for c, score in ranked:
        if score < threshold:
            outcome, reason = "hold", f"ranking {score:.3f} below threshold {threshold:.2f}"
        else:
            outcome, reason = "advance", f"ranking {score:.3f} meets threshold"
        # One model call per candidate above threshold: a one-line interview
        # focus. Every call is a signed evidence row from this process.
        if client is not None and outcome == "advance":
            try:
                r = client.chat.completions.create(
                    model="deepseek-chat", max_tokens=40, temperature=0.2,
                    messages=[{"role": "user", "content": f"In one sentence, what should an interviewer probe for a {c.role} candidate with {c.years_experience} years and skills {', '.join(c.skills)}? No names."}],
                )
                reason += " · focus: " + (r.choices[0].message.content or "").strip()
            except Exception as exc:  # noqa: BLE001
                reason += f" · model unavailable ({type(exc).__name__})"
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
# simply nobody. When it reaches the store through hexr_tool() the SDK refuses
# it credentials and records a `tool_call_denied` row under `local-dev` — the
# one trace it leaves, and it is a refusal, not an action.
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

# ── Each stage runs in its OWN process ───────────────────────────────────────
#
# This is not a stylistic choice, and getting it wrong invalidates the whole
# demo.
#
# A Hexr identity is per-PROCESS. The SDK writes
# /tmp/hexr-context/hexr-agent-<PID>-<role>.json and the attestor reads it,
# keyed on the PID the kernel reports for the caller. Two decorated functions
# running in ONE interpreter therefore share a PID — so they register two
# roles, the later one wins, and every evidence row is attributed to whichever
# decorator ran last.
#
# We shipped exactly that mistake and it showed up as 234 evidence rows over
# two hours, every one signed by `interview-scorer`, while `resume-ranker`
# demonstrably made the same call and produced none. The claim "two processes,
# two identities" was false while the page asserted it.
#
# So each stage is spawned as a real subprocess. Separate PIDs, separate
# context files, separate SVIDs, and evidence that attributes to the stage that
# actually made the call. It also happens to be how a real screening pipeline
# would be built — stages that can fail and be retried independently.

def _stage_worker(fn_name: str, payload, conn) -> None:
    """Run one stage in this (fresh) process and send the result back.

    The decorator runs on import in the child, so registration happens against
    the CHILD's PID. That is the entire point of spawning rather than calling.
    """
    fn = {"resume_ranker": resume_ranker, "interview_scorer": interview_scorer}[fn_name]
    try:
        conn.send(("ok", fn(*payload)))
    except Exception as exc:  # noqa: BLE001 — surfaced to the parent, not swallowed
        conn.send(("err", f"{type(exc).__name__}: {exc}"))
    finally:
        conn.close()


# SPAWN, not fork.
#
# The default start method on Linux is fork(), and a forked child inherits the
# parent's memory — including the SDK's already-resolved identity. The child
# therefore never re-registers, and its evidence is signed with the PARENT's
# SVID. We measured exactly that: distinct OS PIDs, one shared proc-<pid> in
# every SPIFFE ID.
#
# spawn starts a fresh interpreter that re-imports this module, so the
# @hexr_agent decorators run again and register against the CHILD's pid. It is
# slower per stage, and the slowness is the correct trade for an identity that
# actually names the process that did the work.
_MP = multiprocessing.get_context("spawn")


def run_stage(fn_name: str, *payload):
    """Spawn a stage in a fresh interpreter, wait for it, return its result."""
    parent, child = _MP.Pipe()
    proc = _MP.Process(
        target=_stage_worker, args=(fn_name, payload, child), name=fn_name
    )
    proc.start()
    status, value = parent.recv()
    proc.join(timeout=60)
    log.info("  %s ran as pid %s", fn_name, proc.pid)
    if status == "err":
        raise RuntimeError(f"{fn_name} failed: {value}")
    return value


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

    ranked = run_stage("resume_ranker", applications, required)
    decisions = run_stage("interview_scorer", ranked)

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
