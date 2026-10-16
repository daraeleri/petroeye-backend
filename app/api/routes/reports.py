import csv
import io
import json
from datetime import datetime
from enum import Enum
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from app.api.deps import DB, CurrentUser
from app.core.time import utcnow
from app.db.models import UserRole
from app.schemas.operations import ActivityEntry, ReportSummary
from app.services import audit, reports

router = APIRouter(prefix="/reports", tags=["Reports"])


class ReportKind(str, Enum):
    activity = "activity"
    discharges = "discharges"
    alerts = "alerts"
    telemetry = "telemetry"
    audit = "audit"


class ExportFormat(str, Enum):
    csv = "csv"
    json = "json"


Start = Annotated[datetime | None, Query(description="From (inclusive, ISO 8601). Omit for no lower bound.")]
End = Annotated[datetime | None, Query(description="Until (inclusive, ISO 8601). Omit for no upper bound.")]
TruckFilter = Annotated[str | None, Query(description="Only this truck.")]


@router.get("/summary", response_model=ReportSummary, summary="Activity summary")
async def report_summary(db: DB, _: CurrentUser, start: Start = None, end: End = None,
                         truck_id: TruckFilter = None) -> ReportSummary:
    """Totals for a period: discharges (authorized vs unauthorized), litres
    discharged, alerts by severity and type, unacknowledged alerts, and how
    many telemetry readings were stored."""
    return await reports.summary(db, start, end, truck_id)


@router.get("/activity", response_model=list[ActivityEntry], summary="Activity timeline")
async def activity(db: DB, _: CurrentUser, start: Start = None, end: End = None,
                   truck_id: TruckFilter = None) -> list[ActivityEntry]:
    """Chronological log of what happened: valve opened/closed (inside or
    outside a geofence, litres), alerts, acknowledgements, device
    online/offline, and configuration changes by users."""
    return await reports.activity_entries(db, start, end, truck_id)


def _to_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    if rows:
        writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v) if isinstance(v, dict | list) else v for k, v in row.items()})
    return buf.getvalue()


@router.get(
    "/export/{kind}",
    summary="Export a report as CSV or JSON",
    response_class=Response,
    responses={
        200: {
            "description": "The report file (downloaded as an attachment).",
            "content": {"text/csv": {}, "application/json": {}},
        },
        403: {"description": "`audit` export is admin-only."},
    },
)
async def export_report(
    kind: ReportKind,
    db: DB,
    user: CurrentUser,
    format: Annotated[ExportFormat, Query(description="`csv` (opens in Excel) or `json`.")] = ExportFormat.csv,
    start: Start = None,
    end: End = None,
    truck_id: TruckFilter = None,
) -> Response:
    """Download stored data for a period as a file:

    - `activity` — the combined timeline (same as `GET /reports/activity`)
    - `discharges` — every valve session with location, geofence, litres
    - `alerts` — alerts with acknowledgement details
    - `telemetry` — raw + derived readings (max 100,000 rows; narrow the dates for more)
    - `audit` — full audit log incl. logins (**admin only**)

    Every export is itself recorded in the audit log.
    """
    if kind is ReportKind.audit and user.role != UserRole.admin.value:
        raise HTTPException(status_code=403, detail="Audit export requires the admin role")

    if kind is ReportKind.activity:
        rows = [e.model_dump(mode="json") for e in await reports.activity_entries(db, start, end, truck_id)]
    else:
        builder = {
            ReportKind.discharges: reports.discharge_rows,
            ReportKind.alerts: reports.alert_rows,
            ReportKind.telemetry: reports.telemetry_rows,
            ReportKind.audit: reports.audit_rows,
        }[kind]
        rows = await builder(db, start, end, truck_id)

    audit.record(db, "report.export", user_id=user.id, entity_type="report", entity_id=kind.value,
                 truck_id=truck_id, details={"format": format.value, "rows": len(rows),
                                             "start": start.isoformat() if start else None,
                                             "end": end.isoformat() if end else None})
    await db.commit()

    stamp = utcnow().strftime("%Y%m%d-%H%M%S")
    scope = f"-{truck_id}" if truck_id else ""
    filename = f"petrotwin-{kind.value}{scope}-{stamp}.{format.value}"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    if format is ExportFormat.csv:
        # BOM so Excel detects UTF-8.
        return Response("﻿" + _to_csv(rows), media_type="text/csv; charset=utf-8", headers=headers)
    return Response(json.dumps(rows, indent=2, default=str), media_type="application/json", headers=headers)
