"""
Web3 anchoring service — STUB for now.

Per docs/architecture.md: only a hash digest of the alert/event payload is
ever anchored on-chain, never raw telemetry or PII. Anchoring is async and
queued so a slow/failed chain write never blocks ingestion.

Current state: this is an in-memory queue + background worker that logs
what WOULD be anchored, so the rest of the system (alerts, dashboard) can
be built and demoed without a live contract deployment. Swap the body of
`_anchor` for a real web3.py transaction once contracts/ is deployed to a
testnet — see docs/progress-tracker.md's Open Questions for which network.

Hard rule: never put a private key in this file or anywhere in the repo.
The signing key is injected via secret manager/env at deploy time only.
"""
import asyncio
import hashlib
import logging

logger = logging.getLogger("petrotwin.web3")


class AnchoringQueue:
    def __init__(self) -> None:
        self._queue: asyncio.Queue = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None

    def start(self) -> None:
        self._worker_task = asyncio.create_task(self._worker())
        logger.info("Anchoring queue worker started (stub — no real chain write yet)")

    def stop(self) -> None:
        if self._worker_task:
            self._worker_task.cancel()

    async def enqueue(self, alert_id: str, alert_type: str) -> None:
        await self._queue.put({"alert_id": alert_id, "alert_type": alert_type})

    async def _worker(self) -> None:
        while True:
            item = await self._queue.get()
            try:
                await self._anchor(item)
            except Exception:
                logger.exception("Anchoring failed for alert %s — re-queueing", item["alert_id"])
                await asyncio.sleep(2)  # basic backoff
                await self._queue.put(item)
            finally:
                self._queue.task_done()

    async def _anchor(self, item: dict) -> None:
        # Digest is a stand-in for "hash of the full alert payload" — once
        # real anchoring is wired up, hash the canonical alert record
        # fetched from the DB, not just the id/type shown here.
        digest = hashlib.sha256(f"{item['alert_id']}:{item['alert_type']}".encode()).hexdigest()
        logger.info(
            "[STUB] Would anchor alert %s (type=%s) with digest %s — no real tx sent",
            item["alert_id"], item["alert_type"], digest,
        )
        # TODO(web3-blockchain agent): replace with a real web3.py call to
        # the deployed contract once contracts/ has an address, e.g.:
        #   tx_hash = await submit_anchor_tx(alert_id=item["alert_id"], digest=digest)
        #   await update_alert_onchain_hash(item["alert_id"], tx_hash)


anchoring_queue = AnchoringQueue()
