"""GET /api/hunts, GET /api/hunts/{hunt_id}(#239). 읽기만 한다.

목록은 id 내림차순(UUIDv7이라 만든 순서, ID 형식 D-034)이고 cursor는 이전 페이지 마지막 id다.
상세의 runs는 Agent Log를 run_id로 묶은 요약이고 input·output 컬럼은 읽지 않는다.
"""

import re
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Query, Request
from psycopg import sql

from soc.api import db
from soc.api.errors import NotFound
from soc.api.models import HuntDetail, HuntPage, HuntStatus, RunSummary, Technique
from soc.contracts import to_epoch_ms

router = APIRouter()

_UUID7 = "[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
HUNT_ID = re.compile(f"^hnt_{_UUID7}$")
HUNT_ID_PATTERN = f"^hnt_{_UUID7}$"
HUNT_RUN_ID_PATTERN = f"^hrn_{_UUID7}$"

DEFAULT_LIMIT = 50
MAX_LIMIT = 200

_LIST_COLUMNS = (
    "id",
    "hunt_run_id",
    "status",
    "hypothesis",
    "attack_techniques",
    "confidence",
    "attempts",
    "verified_at",
    "created_at",
    "updated_at",
)
_DETAIL_COLUMNS = (
    *_LIST_COLUMNS[:6],
    "reason",
    "evidence_ids",
    "entities",
    *_LIST_COLUMNS[6:],
    "details",
)
_TIMES = ("verified_at", "created_at", "updated_at")


@router.get("/hunts", response_model=HuntPage)
def list_hunts(
    request: Request,
    status: Annotated[HuntStatus | None, Query()] = None,
    hunt_run_id: Annotated[str | None, Query(pattern=HUNT_RUN_ID_PATTERN)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    cursor: Annotated[str | None, Query(pattern=HUNT_ID_PATTERN)] = None,
) -> dict[str, Any]:
    with db.connect(request.app.state.settings) as conn:
        rows = read_hunt_page(conn, status, hunt_run_id, cursor, limit + 1)
    items = [_times(row) for row in rows[:limit]]
    next_cursor = items[-1]["id"] if len(rows) > limit else None
    return {"items": items, "next_cursor": next_cursor}


@router.get("/hunts/{hunt_id}", response_model=HuntDetail)
def get_hunt(request: Request, hunt_id: str) -> dict[str, Any]:
    if not HUNT_ID.match(hunt_id):
        raise NotFound
    settings = request.app.state.settings
    with db.connect(settings) as conn:
        row = conn.execute(
            sql.SQL("SELECT {} FROM hunts WHERE id = %s").format(_columns(_DETAIL_COLUMNS)),
            (hunt_id,),
        ).fetchone()
        if row is None:
            raise NotFound
        names = {
            r["technique_id"]: r["name"]
            for r in conn.execute(
                "SELECT technique_id, name FROM attack_techniques"
                " WHERE attack_version = %s AND technique_id = ANY(%s)",
                (settings.attack_version, row["attack_techniques"]),
            )
        }
        ticket = conn.execute("SELECT id FROM tickets WHERE hunt_id = %s", (hunt_id,)).fetchone()
        log_rows = conn.execute(
            "SELECT run_id, seq, kind, outcome, tokens_in, tokens_out, started_at, duration_ms,"
            " details -> 'task' AS task, details -> 'attempt' AS attempt,"
            " details -> 'failure' AS failure"
            " FROM agent_logs"
            " WHERE subject_type = 'hunt' AND subject_id = ANY(%s)"
            " ORDER BY run_id, seq",
            ([row["id"], row["hunt_run_id"]],),
        ).fetchall()
    hunt = _times(row)
    return {
        "hunt": hunt,
        "techniques": [Technique(id=t, name=names.get(t)) for t in hunt["attack_techniques"]],
        "ticket_id": ticket["id"] if ticket is not None else None,
        "runs": summarize_runs(log_rows),
    }


def read_hunt_page(
    conn: psycopg.Connection,
    status: str | None,
    hunt_run_id: str | None,
    cursor: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    where: list[sql.Composable] = []
    params: list[Any] = []
    for column, value, op in (
        ("status", status, "="),
        ("hunt_run_id", hunt_run_id, "="),
        ("id", cursor, "<"),
    ):
        if value is not None:
            where.append(sql.SQL("{} {} %s").format(sql.Identifier(column), sql.SQL(op)))
            params.append(value)
    query = sql.SQL("SELECT {} FROM hunts {} ORDER BY id DESC LIMIT %s").format(
        _columns(_LIST_COLUMNS),
        sql.SQL("WHERE ") + sql.SQL(" AND ").join(where) if where else sql.SQL(""),
    )
    return conn.execute(query, [*params, limit]).fetchall()


def summarize_runs(rows: list[dict[str, Any]]) -> list[RunSummary]:
    """줄을 run_id로 묶는다. 결과·실패는 마지막 model 줄(없으면 마지막 줄) 기준이다.

    tool 줄의 실패는 정상 흐름에서도 생기므로 run 결과로 보지 않는다.
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(row["run_id"], []).append(row)
    runs = []
    for run_id, lines in groups.items():
        models = [line for line in lines if line["kind"] == "model"]
        last = (models or lines)[-1]
        first = lines[0]
        started = min(to_epoch_ms(line["started_at"]) for line in lines)
        ended = max(to_epoch_ms(line["started_at"]) + line["duration_ms"] for line in lines)
        runs.append(
            RunSummary(
                run_id=run_id,
                task=_text(first["task"]),
                attempt=first["attempt"] if type(first["attempt"]) is int else None,
                outcome=last["outcome"],
                failure=_text(last["failure"]),
                tokens_in=_sum(lines, "tokens_in"),
                tokens_out=_sum(lines, "tokens_out"),
                started_at=started,
                duration_ms=ended - started,
            )
        )
    runs.sort(key=lambda run: (run.started_at, run.run_id))
    return runs


def _sum(lines: list[dict[str, Any]], key: str) -> int | None:
    values = [line[key] for line in lines if line[key] is not None]
    return sum(values) if values else None


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _times(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    for key in _TIMES:
        if key in out and out[key] is not None:
            out[key] = to_epoch_ms(out[key])
    return out


def _columns(names: tuple[str, ...]) -> sql.Composable:
    return sql.SQL(", ").join(map(sql.Identifier, names))
