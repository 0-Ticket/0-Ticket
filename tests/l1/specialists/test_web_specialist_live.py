"""One live check that the ZT_CONFIG-selected model answers the Web prompt as C14.

Excluded from the default run (docs/llm-policy.md 7): ``uv run pytest -m llm``
with the configured provider reachable. Everything else about the specialist is tested
with fakes in ``test_web_specialist.py``.
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fake_records import fixture_alerts, fixture_events
from specialist_fakes import load

from soc.config import load_config
from soc.contracts import ContractValidationError, validate_contract
from soc.l1.specialists.web import PROMPT, WEB_AGENT
from soc.llm import create_provider_registry, format_untrusted_data, load_prompt
from soc.llm.base import ProviderRequest

ROOT = Path(__file__).resolve().parents[3]
RESULTS_PATH = ROOT / "config/local.issue-80-test-results.json"
TICKET = load("ticket_web.json")
REQUEST = load("specialist_request.json")
VIEW = ("ticket_id", "handling_type", "priority", "entities")


def _record_live_result(
    *,
    model: str,
    provider: str,
    base_url: str,
    api_key_env: str,
    response: str,
    tokens: int | None,
    status: str,
    contract_valid: bool,
    output: dict | None = None,
    evidence_count: int | None = None,
    failure_type: str | None = None,
) -> None:
    """Append one model response to the ignored, local-only experiment record."""
    if RESULTS_PATH.exists():
        state = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    else:
        state = {"issue": 80, "recorded_on": datetime.now(UTC).date().isoformat()}
    state.setdefault("runs", [])
    state["comparison_limit"] = (
        "Earlier user-reported runs have no raw response; compare the captured "
        "attempts under each model."
    )
    state["retention"] = "Local-only ignored test record; API key values are never stored."
    run = next((item for item in state["runs"] if item["model"] == model), None)
    if run is None:
        run = {"model": model, "attempts": []}
        state["runs"].append(run)

    attempt = {
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "provider": provider,
        "base_url": base_url,
        "api_key_env": api_key_env,
        "status": status,
        "contract": "SpecialistFinding",
        "contract_valid": contract_valid,
        "tokens": tokens,
        "raw_response": response,
    }
    if output is not None:
        attempt["output"] = output
    if evidence_count is not None:
        attempt["evidence_count"] = evidence_count
    if failure_type is not None:
        attempt["failure_type"] = failure_type
    run.setdefault("attempts", []).append(attempt)

    temporary_path = RESULTS_PATH.with_name(f"{RESULTS_PATH.name}.tmp")
    temporary_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary_path.replace(RESULTS_PATH)


@pytest.mark.llm
def test_configured_model_answers_the_web_prompt_as_a_specialist_finding():
    settings = load_config(environ=os.environ).llm
    prompt = load_prompt(PROMPT)
    override = settings.agents.get(WEB_AGENT)
    model = (override.model if override else None) or settings.model
    data = {
        "question": REQUEST["params"]["question"],
        "ticket": {field: TICKET[field] for field in VIEW},
        "alerts": [alert.model_dump(mode="json") for alert in fixture_alerts()],
        "events": [event.model_dump(mode="json") for event in fixture_events()],
    }

    response = (
        create_provider_registry()
        .get(settings.provider)()
        .complete(
            ProviderRequest(
                base_url=settings.base_url,
                api_key=os.environ.get(settings.api_key_env) or None,
                model=model,
                system_prompt=prompt.text,
                user_prompt=format_untrusted_data(data),
                temperature=settings.temperature,
                timeout_seconds=(override.timeout_seconds if override else None)
                or settings.timeout_seconds,
            )
        )
    )

    try:
        decoded = json.loads(response.content)
    except json.JSONDecodeError:
        _record_live_result(
            model=model,
            provider=settings.provider,
            base_url=settings.base_url,
            api_key_env=settings.api_key_env,
            response=response.content,
            tokens=response.tokens,
            status="invalid_json",
            contract_valid=False,
            failure_type="json_decode_error",
        )
        raise

    try:
        finding = validate_contract("SpecialistFinding", decoded)
    except ContractValidationError:
        _record_live_result(
            model=model,
            provider=settings.provider,
            base_url=settings.base_url,
            api_key_env=settings.api_key_env,
            response=response.content,
            tokens=response.tokens,
            status="contract_invalid",
            contract_valid=False,
            output=decoded,
            failure_type="contract_validation_error",
        )
        raise

    if not finding.evidence:
        _record_live_result(
            model=model,
            provider=settings.provider,
            base_url=settings.base_url,
            api_key_env=settings.api_key_env,
            response=response.content,
            tokens=response.tokens,
            status="empty_evidence",
            contract_valid=True,
            output=decoded,
            evidence_count=0,
        )
    assert finding.evidence
    _record_live_result(
        model=model,
        provider=settings.provider,
        base_url=settings.base_url,
        api_key_env=settings.api_key_env,
        response=response.content,
        tokens=response.tokens,
        status="passed",
        contract_valid=True,
        output=decoded,
        evidence_count=len(finding.evidence),
    )
    print(f"Configured model Web specialist contract (model={model}): valid")
    print(f"Saved Web specialist response to {RESULTS_PATH.relative_to(ROOT)}")
