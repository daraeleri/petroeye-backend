"""
MQTT subscriber for PetroTwin.

PROTECTED FILE per docs/ai-workflow-rules.md — once this connection loop is
stable, only modify it with explicit instruction.

Hard invariant (docs/architecture.md): this client runs paho-mqtt's network
loop on its own background thread and must never block the FastAPI asyncio
event loop. Incoming messages are validated synchronously (cheap, pure) and
then handed off to the event loop via `asyncio.run_coroutine_threadsafe` so
the actual DB write / broadcast / rule evaluation happens as a normal async
task, not inside paho-mqtt's callback thread.
"""
import asyncio
import json
import logging

import paho.mqtt.client as mqtt
from pydantic import ValidationError

from app.config import settings
from app.mqtt.handlers import handle_status, handle_telemetry
from app.mqtt.schemas import StatusPayload, TelemetryPayload

logger = logging.getLogger("petrotwin.mqtt")

TELEMETRY_TOPIC_FILTER = "petrotwin/+/telemetry"
STATUS_TOPIC_FILTER = "petrotwin/+/status"


class MQTTSubscriber:
    def __init__(self) -> None:
        self._client = mqtt.Client(client_id="petrotwin-backend", protocol=mqtt.MQTTv311)
        if settings.mqtt_username:
            self._client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.on_disconnect = self._on_disconnect
        self._loop: asyncio.AbstractEventLoop | None = None

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        """Call once, from FastAPI's lifespan startup, with the running event loop."""
        self._loop = loop
        self._client.connect(settings.mqtt_host, settings.mqtt_port, keepalive=60)
        self._client.loop_start()  # spins up paho's own network thread
        logger.info("MQTT subscriber started (%s:%s)", settings.mqtt_host, settings.mqtt_port)

    def stop(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()
        logger.info("MQTT subscriber stopped")

    # --- paho callbacks: run on paho's background thread, keep these fast ---

    def _on_connect(self, client, userdata, flags, rc):
        if rc != 0:
            logger.error("MQTT connect failed with rc=%s", rc)
            return
        client.subscribe([(TELEMETRY_TOPIC_FILTER, 1), (STATUS_TOPIC_FILTER, 1)])
        logger.info("Subscribed to %s and %s", TELEMETRY_TOPIC_FILTER, STATUS_TOPIC_FILTER)

    def _on_disconnect(self, client, userdata, rc):
        logger.warning("MQTT disconnected (rc=%s) — paho will auto-reconnect", rc)

    def _on_message(self, client, userdata, msg):
        if self._loop is None:
            logger.error("Received MQTT message before event loop was set — dropping")
            return

        try:
            raw = json.loads(msg.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            logger.warning("Rejected non-JSON payload on %s", msg.topic)
            return

        topic_parts = msg.topic.split("/")  # petrotwin/{truck_id}/{telemetry|status}
        if len(topic_parts) != 3:
            logger.warning("Rejected malformed topic: %s", msg.topic)
            return
        _, truck_id, kind = topic_parts

        if kind == "telemetry":
            self._validate_and_dispatch(raw, TelemetryPayload, handle_telemetry, msg.topic, truck_id)
        elif kind == "status":
            self._validate_and_dispatch(raw, StatusPayload, handle_status, msg.topic, truck_id)
        else:
            logger.warning("Rejected unknown topic kind '%s' on %s", kind, msg.topic)

    def _validate_and_dispatch(self, raw: dict, schema_cls, handler, topic: str, truck_id: str) -> None:
        try:
            payload = schema_cls.model_validate(raw)
        except ValidationError as e:
            # Reject and log — NEVER guess or coerce missing/invalid fields.
            logger.warning("Rejected invalid payload on %s: %s", topic, e)
            return

        if payload.truck_id != truck_id:
            logger.warning(
                "Rejected payload on %s: body truck_id '%s' != topic truck_id '%s'",
                topic, payload.truck_id, truck_id,
            )
            return

        asyncio.run_coroutine_threadsafe(handler(payload), self._loop)


mqtt_subscriber = MQTTSubscriber()
