"""
FastAPI entrypoint. Wires together the REST API, WebSocket relay, MQTT
subscriber, and Web3 anchoring queue via the app lifespan — this is the
only place all four boundaries are allowed to appear together.
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import alerts, telemetry, trucks
from app.config import settings
from app.db.base import init_db
from app.mqtt.client import mqtt_subscriber
from app.web3.anchoring import anchoring_queue
from app.ws.routes import router as ws_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("petrotwin.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    loop = asyncio.get_running_loop()
    mqtt_subscriber.start(loop)
    anchoring_queue.start()
    logger.info("PetroTwin backend started")
    yield
    mqtt_subscriber.stop()
    anchoring_queue.stop()
    logger.info("PetroTwin backend stopped")


app = FastAPI(title="PetroTwin API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(trucks.router)
app.include_router(telemetry.router)
app.include_router(alerts.router)
app.include_router(ws_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
