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


def findings_refs(output: Any) -> list[str]:
    """조사가 근거로 고른 SIEM 문서의 저장 키(#382). 발급은 워커가 한다."""
    return list(output["siem_refs"])


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
        cited_refs=findings_refs,
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
    issued_evidence_ids: tuple[str, ...] = (),
    dropped_refs: int = 0,
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
            # 발급하지 못해 버린 근거 수(#382). 값은 넣지 않는다(밖에서 온 문자열).
            # 모델이 왜 그 근거를 인용할 수 없는지 모르면 같은 것을 다시 가리켜 형식 오류로 돈다
            "dropped_refs": dropped_refs,
        },
        output_contract="incident_analysis",
        cited_ids=analysis_citations,
        subject_type="incident",
        subject_id=incident_id,
        # 조사가 인용한 것과, 조사가 고른 SIEM 문서를 워커가 발급한 ID를 더한다(#382)
        allowed_evidence_ids=tuple(_unique(context_evidence, cited, issued_evidence_ids)),
        attempt=attempt,
    )
