"""
MQTT subscriber for PetroTwin.

PROTECTED FILE per docs/ai-workflow-rules.md — once this connection loop is
stable, only modify it with explicit instruction.

Hard invariants (docs/architecture.md):
- paho-mqtt's network loop runs on its own background thread and never
  blocks the FastAPI asyncio event loop. Messages are validated on that
  thread (cheap, pure) and handed to the event loop with
  `asyncio.run_coroutine_threadsafe`.
- Subscribe only. The backend never publishes to device topics.

Connection behaviour:
- `connect_async` + `loop_start`: a broker that is down at startup doesn't
  crash the app; paho keeps retrying with backoff.
- Stable client ID + `clean_session=False` + QoS 1: the broker queues
  messages while the backend is briefly disconnected (e.g. a Render cold
  start), and replays them on reconnect.
- TLS (port 8883) when MQTT_TLS=true, using the certifi CA bundle.
"""
import asyncio
import json
import logging
import ssl
from concurrent.futures import Future

import certifi
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
from pydantic import BaseModel, ValidationError

from app.config import settings
from app.mqtt.schemas import EventPayload, StatusPayload, TelemetryPayload
from app.services.ingestion import handle_event, handle_status, handle_telemetry

logger = logging.getLogger("petrotwin.mqtt")

TOPIC_PREFIX = "petrotwin"
TELEMETRY_TOPIC_FILTER = f"{TOPIC_PREFIX}/+/telemetry"
STATUS_TOPIC_FILTER = f"{TOPIC_PREFIX}/+/status"
EVENT_TOPIC_FILTER = f"{TOPIC_PREFIX}/+/event"


class MQTTSubscriber:
    def __init__(self) -> None:
        self._client = mqtt.Client(
            CallbackAPIVersion.VERSION2,
            client_id=settings.mqtt_client_id,
            clean_session=False,
            protocol=mqtt.MQTTv311,
        )
        if settings.mqtt_username:
            self._client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
        if settings.mqtt_tls:
            self._client.tls_set(ca_certs=certifi.where(), tls_version=ssl.PROTOCOL_TLS_CLIENT)
        self._client.reconnect_delay_set(min_delay=1, max_delay=60)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.on_disconnect = self._on_disconnect
        self._loop: asyncio.AbstractEventLoop | None = None
        self.connected = False

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        """Call once, from FastAPI's lifespan startup, with the running event loop."""
        self._loop = loop
        self._client.connect_async(settings.mqtt_host, settings.mqtt_port, keepalive=60)
        self._client.loop_start()  # paho's own network thread; retries until the broker is up
        logger.info("MQTT subscriber starting (%s:%s, tls=%s)", settings.mqtt_host, settings.mqtt_port,
                    settings.mqtt_tls)

    def stop(self) -> None:
        self._client.disconnect()
        self._client.loop_stop()
        self.connected = False
        logger.info("MQTT subscriber stopped")

    # --- paho callbacks: run on paho's background thread, keep these fast ---

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            logger.error("MQTT connect failed: %s", reason_code)
            return
        self.connected = True
        client.subscribe([(TELEMETRY_TOPIC_FILTER, 1), (STATUS_TOPIC_FILTER, 1), (EVENT_TOPIC_FILTER, 1)])
        logger.info("MQTT connected; subscribed to %s, %s and %s (session present=%s)",
                    TELEMETRY_TOPIC_FILTER, STATUS_TOPIC_FILTER, EVENT_TOPIC_FILTER, flags.session_present)

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        self.connected = False
        logger.warning("MQTT disconnected (%s) — paho will reconnect", reason_code)

    def _on_message(self, client, userdata, msg):
        if self._loop is None:
            logger.error("Received MQTT message before event loop was set — dropping")
            return

        topic_parts = msg.topic.split("/")  # petrotwin/{truck_id}/{telemetry|status}
        if len(topic_parts) != 3 or topic_parts[0] != TOPIC_PREFIX:
            logger.warning("Rejected malformed topic: %s", msg.topic)
            return
        _, truck_id, kind = topic_parts

        try:
            raw = json.loads(msg.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            logger.warning("Rejected non-JSON payload on %s", msg.topic)
            return

        if kind == "telemetry":
            self._validate_and_dispatch(raw, TelemetryPayload, handle_telemetry, msg.topic, truck_id)
        elif kind == "status":
            self._validate_and_dispatch(raw, StatusPayload, handle_status, msg.topic, truck_id)
        elif kind == "event":
            self._validate_and_dispatch(raw, EventPayload, handle_event, msg.topic, truck_id)
        else:
            logger.warning("Rejected unknown topic kind '%s' on %s", kind, msg.topic)

    def _validate_and_dispatch(self, raw, schema_cls: type[BaseModel], handler, topic: str, truck_id: str) -> None:
        try:
            payload = schema_cls.model_validate(raw)
        except ValidationError as e:
            # Reject and log — NEVER guess or coerce missing/invalid fields.
            logger.warning("Rejected invalid payload on %s: %s", topic, e.errors(include_url=False))
            return

        if payload.truck_id != truck_id:
            logger.warning("Rejected payload on %s: body truck_id '%s' != topic truck_id '%s'",
                           topic, payload.truck_id, truck_id)
            return

        future = asyncio.run_coroutine_threadsafe(handler(payload), self._loop)
        future.add_done_callback(lambda f, t=topic: self._log_failure(f, t))

    @staticmethod
    def _log_failure(future: Future, topic: str) -> None:
        exc = future.exception()
        if exc is not None:
            logger.error("Processing message on %s failed", topic, exc_info=exc)


mqtt_subscriber = MQTTSubscriber()
