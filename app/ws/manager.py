"""
WebSocket connection manager — the ONLY bridge between backend-internal
events (MQTT-derived DB writes, alerts) and connected dashboard clients.
Frontend components never talk to MQTT directly; they get everything
through this broadcast.
"""
import json
import logging

from fastapi import WebSocket

logger = logging.getLogger("petrotwin.ws")


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.add(ws)
        logger.info("WS client connected (%d total)", len(self._connections))

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.discard(ws)
        logger.info("WS client disconnected (%d total)", len(self._connections))

    async def broadcast(self, message: dict) -> None:
        if not self._connections:
            return
        payload = json.dumps(message)
        dead = []
        for ws in self._connections:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._connections.discard(ws)


ws_manager = ConnectionManager()
