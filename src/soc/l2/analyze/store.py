"""L2 Incident 분석 결과와 실패 라운드를 원자적으로 저장한다."""

from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from soc.contracts import to_datetime, validate_contract
from soc.entities import normalize_entity_value
from soc.ids import new_id
from soc.l2.analyze.tasks import analysis_citations, findings_citations
from soc.l2.branch.read import _contract_row


@dataclass(frozen=True)
class SaveResult:
    saved: bool
    dropped_techniques: int = 0


def build_records(
    incident_id: str,
    *,
    analysis_round: int,
    findings: dict[str, Any],
    analysis: dict[str, Any],
    attack_names: dict[str, str],
    now_ms: int,
) -> tuple[dict[str, Any], list[dict[str, Any]], int]:
    techniques = [
        {**item, "name": attack_names[item["id"]]}
        for item in analysis["techniques"]
        if item["id"] in attack_names
    ]
    dropped = len(analysis["techniques"]) - len(techniques)
    artifact_id = new_id("art")
    artifact = {
        "id": artifact_id,
        "incident_id": incident_id,
        "analysis_round": analysis_round,
        "verdict": analysis["verdict"],
        "summary": analysis["summary"],
        "assessed_severity": analysis["assessed_severity"],
        "timeline": findings["timeline"],
        "techniques": techniques,
        "impact": analysis["impact"],
        "cause": analysis["cause"],
        "further_risk": analysis["further_risk"],
        "evidence_ids": list(
            dict.fromkeys([*findings_citations(findings), *analysis_citations(analysis)])
        ),
        "created_at": now_ms,
    }
    proposals = []
    for kind, field in (
        ("detection_rule", "detection_rules"),
        ("response_action", "response_actions"),
    ):
        proposals.extend(
            {
                "id": new_id("prp"),
                "artifact_id": artifact_id,
                "kind": kind,
                "seq": seq,
                "body": body,
                "created_at": now_ms,
            }
            for seq, body in enumerate(analysis[field], 1)
        )
    validate_contract("incident_artifact", artifact)
    for proposal in proposals:
        validate_contract("incident_proposal", proposal)
    return artifact, proposals, dropped


def save_success(
    conn: psycopg.Connection,
    incident_id: str,
    *,
    expected_round: int,
    findings: dict[str, Any],
    analysis: dict[str, Any],
    attack_names: dict[str, str],
    asset_lookup_failed: bool,
    now_ms: int,
) -> SaveResult:
    """상태와 라운드가 읽은 값 그대로일 때 Artifact·Proposal·Incident를 저장한다."""
    with conn.transaction():
        incident = _locked_incident(conn, incident_id)
        if (
            incident is None
            or incident["status"] != "analyzing"
            or incident["analysis_round"] != expected_round
        ):
            return SaveResult(False)
        next_round = expected_round + 1
        artifact, proposals, dropped = build_records(
            incident_id,
            analysis_round=next_round,
            findings=findings,
            analysis=analysis,
            attack_names=attack_names,
            now_ms=now_ms,
        )
        details = _diagnostics(
            incident["details"],
            asset_lookup_failed=asset_lookup_failed,
            dropped_techniques=dropped,
        )
        updated = {
            **incident,
            "summary": analysis["summary"],
            "status": "dismissed" if analysis["verdict"] == "not_threat" else "awaiting_review",
            "entities": _merge_entities(
                incident["entities"], [item["entity"] for item in findings["entities"]]
            ),
            "assessed_severity": analysis["assessed_severity"],
            "analysis_round": next_round,
            "updated_at": now_ms,
            "details": details,
        }
        validate_contract("incident", updated)
        _insert_artifact(conn, artifact)
        for proposal in proposals:
            _insert_proposal(conn, proposal)
        _update_incident(conn, updated)
        return SaveResult(True, dropped)


def save_failure(
    conn: psycopg.Connection,
    incident_id: str,
    *,
    expected_round: int,
    failure: str,
    run_id: str,
    asset_lookup_failed: bool,
    now_ms: int,
) -> bool:
    with conn.transaction():
        incident = _locked_incident(conn, incident_id)
        if (
            incident is None
            or incident["status"] != "analyzing"
            or incident["analysis_round"] != expected_round
        ):
            return False
        next_round = expected_round + 1
        l2 = dict(incident["details"].get("l2_analyze", {}))
        l2["asset_lookup_failed"] = asset_lookup_failed
        l2["failures"] = [
            *l2.get("failures", []),
            {"attempt": next_round, "failure": failure, "run_id": run_id},
        ]
        updated = {
            **incident,
            "analysis_round": next_round,
            "updated_at": now_ms,
            "details": {**incident["details"], "l2_analyze": l2},
        }
        validate_contract("incident", updated)
        _update_incident(conn, updated)
        return True


def mark_stopped(
    conn: psycopg.Connection,
    incident_id: str,
    *,
    expected_round: int,
    now_ms: int,
) -> bool:
    with conn.transaction():
        incident = _locked_incident(conn, incident_id)
        if (
            incident is None
            or incident["status"] != "analyzing"
            or incident["analysis_round"] != expected_round
        ):
            return False
        l2 = {**incident["details"].get("l2_analyze", {}), "stopped": "round_limit"}
        updated = {
            **incident,
            "updated_at": now_ms,
            "details": {**incident["details"], "l2_analyze": l2},
        }
        validate_contract("incident", updated)
        _update_incident(conn, updated)
        return True


def _diagnostics(
    details: dict[str, Any], *, asset_lookup_failed: bool, dropped_techniques: int
) -> dict[str, Any]:
    l2 = dict(details.get("l2_analyze", {}))
    l2.pop("stopped", None)
    l2.update(
        asset_lookup_failed=asset_lookup_failed,
        dropped_techniques=dropped_techniques,
    )
    return {**details, "l2_analyze": l2}


def _merge_entities(
    existing: list[dict[str, Any]], added: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    out = list(existing)
    seen = {(item["type"], normalize_entity_value(item["type"], item["value"])) for item in out}
    for entity in added:
        key = (entity["type"], normalize_entity_value(entity["type"], entity["value"]))
        if key not in seen:
            seen.add(key)
            out.append(entity)
    return out


def _locked_incident(conn: psycopg.Connection, incident_id: str) -> dict[str, Any] | None:
    with conn.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            "SELECT * FROM incidents WHERE id = %s FOR UPDATE", (incident_id,)
        ).fetchone()
    return None if row is None else _contract_row("incident", row)


def _insert_artifact(conn: psycopg.Connection, artifact: dict[str, Any]) -> None:
    conn.execute(
        "INSERT INTO incident_artifacts "
        "(id, incident_id, analysis_round, verdict, summary, assessed_severity, timeline, "
        "techniques, impact, cause, further_risk, evidence_ids, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            artifact["id"],
            artifact["incident_id"],
            artifact["analysis_round"],
            artifact["verdict"],
            artifact["summary"],
            artifact["assessed_severity"],
            Jsonb(artifact["timeline"]),
            Jsonb(artifact["techniques"]),
            artifact["impact"],
            artifact["cause"],
            artifact["further_risk"],
            artifact["evidence_ids"],
            to_datetime(artifact["created_at"]),
        ),
    )


def _insert_proposal(conn: psycopg.Connection, proposal: dict[str, Any]) -> None:
    conn.execute(
        "INSERT INTO incident_proposals (id, artifact_id, kind, seq, body, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (
            proposal["id"],
            proposal["artifact_id"],
            proposal["kind"],
            proposal["seq"],
            proposal["body"],
            to_datetime(proposal["created_at"]),
        ),
    )


def _update_incident(conn: psycopg.Connection, incident: dict[str, Any]) -> None:
    conn.execute(
        "UPDATE incidents SET summary = %s, status = %s, entities = %s, "
        "assessed_severity = %s, analysis_round = %s, updated_at = %s, details = %s "
        "WHERE id = %s",
        (
            incident["summary"],
            incident["status"],
            Jsonb(incident["entities"]),
            incident["assessed_severity"],
            incident["analysis_round"],
            to_datetime(incident["updated_at"]),
            Jsonb(incident["details"]),
            incident["id"],
        ),
    )
