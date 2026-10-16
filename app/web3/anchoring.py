"""
Web3 anchoring service — STUB for now.

Per docs/architecture.md: only a hash digest of the alert record is ever
anchored on-chain, never raw telemetry or PII. Anchoring is async and
queued so a slow/failed chain write never blocks ingestion.

Current state: an in-memory queue + background worker that logs what it
WOULD anchor. Critical alerts are enqueued with the SHA-256 digest already
stored on the alert row (`Alert.digest`, see app/services/alerts.py).
Swap the body of `_anchor` for a real web3.py transaction once a contract
is deployed to a testnet — see Open Questions in docs/progress-tracker.md.

Hard rule: never put a private key in this file or anywhere in the repo.
The signing key is injected via env at deploy time only.
"""
import asyncio
import logging

logger = logging.getLogger("petrotwin.web3")


class AnchoringQueue:
    def __init__(self) -> None:
        self._queue: asyncio.Queue | None = None
        self._worker_task: asyncio.Task | None = None

    def start(self) -> None:
        self._queue = asyncio.Queue()
        self._worker_task = asyncio.create_task(self._worker())
        logger.info("Anchoring queue worker started (stub — no real chain write yet)")

    def stop(self) -> None:
        if self._worker_task:
            self._worker_task.cancel()

    async def enqueue(self, alert_id: str, digest: str) -> None:
        if self._queue is None:  # not started (e.g. tests)
            return
        await self._queue.put({"alert_id": alert_id, "digest": digest})

    async def _worker(self) -> None:
        assert self._queue is not None
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
        logger.info("[STUB] Would anchor alert %s with digest %s — no real tx sent",
                    item["alert_id"], item["digest"])
        # TODO(web3): submit the digest to the deployed contract, then store
        # the tx hash on Alert.onchain_tx_hash.


anchoring_queue = AnchoringQueue()
