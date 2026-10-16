from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.core.security import decode_access_token
from app.db.base import AsyncSessionLocal
from app.db.models import User
from app.ws.manager import ws_manager

router = APIRouter()


@router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket, token: str | None = None):
    """Live event stream. Connect with `wss://<host>/ws?token=<JWT>`.

    Browsers can't set headers on WebSocket connections, so the access
    token from `/auth/login` goes in the query string.
    """
    user_id = decode_access_token(token) if token else None
    if user_id is not None:
        async with AsyncSessionLocal() as session:
            user = await session.get(User, user_id)
            if user is None or not user.is_active:
                user_id = None
    if user_id is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid or missing token")
        return

    await ws_manager.connect(websocket)
    try:
        while True:
            # Clients are receive-only; awaiting keeps the connection open
            # and detects disconnects promptly.
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
