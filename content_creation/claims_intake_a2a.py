"""
Claims intake — the caller side of the denial-review demo (healthtech tenant).

One identified process that, every few minutes, hands a synthetic denied claim
to the denial-review crew over A2A. The call is agent-to-agent mTLS: this
process presents ITS OWN X.509-SVID, the crew's inbound proxy verifies it
against the tenant trust root, and the crew's own processes run the review.

Why it exists
  - The crew is a callee. With nobody calling it, an AWS runtime reports
    "agents running, no evidence" — which is exactly what fleet-watch flagged
    on 2026-09-19. A caller makes the plane live, continuously.
  - Every cycle is an A2A round trip on current SDK, so "A2A works" is a fact
    re-established every few minutes rather than remembered from July.

What it does NOT do
  - No PHI. The claim is synthetic and says so in its own metadata.
  - No keys. The mTLS client certificate comes from the identity plane; the
    process holds nothing that could be copied.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time

import hexr
from hexr.a2a.client import A2AClient
from hexr.a2a.models import Message

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("healthtech.intake")

CREW_URL = os.getenv("HEXR_A2A_CREW_URL", "https://denial-review-crew-a2a.tenant-pivot-demo.svc.cluster.local:8443")
SPIFFE_SOCKET = os.getenv("SPIFFE_ENDPOINT_SOCKET", "unix:///run/spire/sockets/agent.sock").replace("unix://", "")
INTERVAL = int(os.getenv("HEXR_INTAKE_INTERVAL", "180"))

DENIAL_CODES = ["CO-16", "CO-97", "PR-204", "CO-4", "CO-50"]


def synthetic_claim(n: int) -> dict:
    return {
        "claim_id": f"SYN-CLM-2026-{n:06d}",
        "patient_pseudonym": f"P-{random.randint(10000, 99999)}",
        "denial_code": random.choice(DENIAL_CODES),
        "amount_usd": round(random.uniform(180, 4200), 2),
        "service_date": "2026-09-01",
        "synthetic": True,
    }


@hexr.hexr_agent(name="claims_intake", role="intake", tenant="pivot-demo")
class ClaimsIntake:
    """Hands one claim to the crew and reports the outcome."""

    async def submit(self, claim: dict) -> str:
        async with A2AClient(CREW_URL, spiffe_socket=SPIFFE_SOCKET, timeout=240) as client:
            card = await client.discover()
            log.info("crew card: %s", getattr(card, "name", "?"))
            task = await client.send(Message.user(json.dumps(claim)), metadata={"synthetic": "true"})
            state = getattr(getattr(task, "status", None), "state", None) or getattr(task, "state", "?")
            log.info("claim %s → task %s state=%s", claim["claim_id"], getattr(task, "id", "?"), state)
            return str(state)


async def main() -> None:
    intake = ClaimsIntake()
    n = int(time.time()) % 100000
    while True:
        n += 1
        claim = synthetic_claim(n)
        try:
            await intake.submit(claim)
        except Exception as exc:  # noqa: BLE001 — a failed hop is evidence, and the loop continues
            log.warning("claim %s: A2A call failed: %s: %s", claim["claim_id"], type(exc).__name__, exc)
        await asyncio.sleep(INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
