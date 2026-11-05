"""L2 Incident 조사·보고 AgentTask를 만든다."""

import hashlib
from pathlib import Path
from typing import Any

from soc.agent import AgentTask, TaskPrompt

PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"


def _prompt(name: str) -> TaskPrompt:
    text = (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")
    return TaskPrompt(text=text, version=hashlib.sha256(text.encode("utf-8")).hexdigest())


def _unique(*groups: list[str] | tuple[str, ...]) -> list[str]:
    return list(dict.fromkeys(item for group in groups for item in group))


def findings_citations(output: Any) -> list[str]:
    """최상위·timeline·entity 근거를 장부 검사 순서로 평탄화한다."""
    return _unique(
        output["evidence_ids"],
        *[item["evidence_ids"] for item in output["timeline"]],
        *[item["evidence_ids"] for item in output["entities"]],
    )


def analysis_citations(output: Any) -> list[str]:
    """최상위·ATT&CK 기법 근거를 장부 검사 순서로 평탄화한다."""
    return _unique(
        output["evidence_ids"],
        *[item["evidence_ids"] for item in output["techniques"]],
    )


def make_investigate_task(
    incident_id: str,
    *,
    attempt: int,
    data: dict[str, Any],
    allowed_evidence_ids: tuple[str, ...],
) -> AgentTask:
    return AgentTask(
        stage="l2",
        task="l2_investigate",
        prompt=_prompt("l2_investigate"),
        data=data,
        output_contract="incident_findings",
        cited_ids=findings_citations,
        subject_type="incident",
        subject_id=incident_id,
        allowed_evidence_ids=allowed_evidence_ids,
        attempt=attempt,
    )


def make_report_task(
    incident_id: str,
    *,
    attempt: int,
    findings: dict[str, Any],
    incident: dict[str, Any],
    assets: list[dict[str, Any]],
    previous_artifact: dict[str, Any] | None,
    asset_lookup_failed: bool,
    context_evidence: tuple[str, ...],
) -> AgentTask:
    cited = tuple(findings_citations(findings))
    return AgentTask(
        stage="l2",
        task="l2_report",
        prompt=_prompt("l2_report"),
        data={
            "findings": findings,
            "incident": {"id": incident["id"], "summary": incident["summary"]},
            "assets": assets,
            "previous_artifact": previous_artifact,
            "asset_lookup_failed": asset_lookup_failed,
        },
        output_contract="incident_analysis",
        cited_ids=analysis_citations,
        subject_type="incident",
        subject_id=incident_id,
        allowed_evidence_ids=tuple(_unique(context_evidence, cited)),
        attempt=attempt,
    )
