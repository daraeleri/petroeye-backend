"""
Orchestration layer: takes a validated MQTT payload, persists it, runs it
through the rule engine, and broadcasts results over WebSocket. This is
where the MQTT, DB, AI, and WS boundaries meet — none of those modules call
each other directly, they all go through here.
"""
import logging

from sqlalchemy import select

from app.ai.rule_engine import evaluate_reading
from app.db.base import AsyncSessionLocal
from app.db.models import Alert, Telemetry, Truck, TruckStatus
from app.mqtt.schemas import StatusPayload, TelemetryPayload
from app.ws.manager import ws_manager

logger = logging.getLogger("petrotwin.handlers")


async def handle_telemetry(payload: TelemetryPayload) -> None:
    async with AsyncSessionLocal() as session:
        # Ensure the truck row exists (auto-register on first-ever message).
        truck = await session.get(Truck, payload.truck_id)
        if truck is None:
            truck = Truck(truck_id=payload.truck_id, status=TruckStatus.in_transit)
            session.add(truck)

        truck.last_seen_at = payload.ts

        # Look up the truck's most recent prior reading, needed for rate-of-change
        # rules (e.g. fuel dropping too fast) — the rule engine itself stays a
        # pure function; this is just fetching its second input.
        prev_result = await session.execute(
            select(Telemetry)
            .where(Telemetry.truck_id == payload.truck_id)
            .order_by(Telemetry.ts.desc())
            .limit(1)
        )
        previous = prev_result.scalar_one_or_none()

        reading = Telemetry(
            truck_id=payload.truck_id,
            ts=payload.ts,
            fuel_level_pct=payload.fuel_level_pct,
            temperature_c=payload.temperature_c,
            pressure_kpa=payload.pressure_kpa,
            lat=payload.lat,
            lon=payload.lon,
            tilt_deg=payload.tilt_deg,
            flow_rate_lpm=payload.flow_rate_lpm,
            hatch_open=payload.hatch_open,
            schema_version=payload.schema_version,
        )
        session.add(reading)

        anomalies = evaluate_reading(current=payload, previous=previous)

        created_alerts = []
        for anomaly in anomalies:
            alert = Alert(
                truck_id=payload.truck_id,
                type=anomaly.type,
                severity=anomaly.severity,
                message=anomaly.message,
                triggered_by=anomaly.triggered_by,
            )
            session.add(alert)
            created_alerts.append(alert)
            truck.status = TruckStatus.alert

        await session.commit()

        # Broadcast AFTER commit, so anything a client fetches via REST
        # immediately after the WS message is guaranteed to see it.
        await ws_manager.broadcast({
            "type": "telemetry",
            "truck_id": payload.truck_id,
            "data": payload.model_dump(mode="json"),
        })
        for alert in created_alerts:
            logger.warning("Alert created: %s [%s] on %s", alert.type, alert.severity, alert.truck_id)
            await ws_manager.broadcast({
                "type": "alert",
                "truck_id": payload.truck_id,
                "data": {
                    "id": str(alert.id),
                    "alert_type": alert.type,
                    "severity": alert.severity,
                    "message": alert.message,
                    "triggered_by": alert.triggered_by,
                },
            })
            # Web3 anchoring is intentionally NOT awaited inline here — it's
            # queued asynchronously so a slow/failed chain write can never
            # delay ingestion or the dashboard update. See app/web3/anchoring.py.
            from app.web3.anchoring import anchoring_queue
            await anchoring_queue.enqueue(alert_id=str(alert.id), alert_type=alert.type)


async def handle_status(payload: StatusPayload) -> None:
    async with AsyncSessionLocal() as session:
        truck = await session.get(Truck, payload.truck_id)
        if truck is None:
            truck = Truck(truck_id=payload.truck_id)
            session.add(truck)

        truck.last_seen_at = payload.ts
        if not payload.online and truck.status != TruckStatus.alert:
            truck.status = TruckStatus.offline

        await session.commit()

        await ws_manager.broadcast({
            "type": "status",
            "truck_id": payload.truck_id,
            "data": payload.model_dump(mode="json"),
        })
