"""One live check that the configured local model answers the Web prompt as C14.

Excluded from the default run (docs/llm-policy.md 7): ``uv run pytest -m llm``
with the configured provider reachable. Everything else about box 14 is tested
with fakes in ``test_web_specialist.py``.
"""

import json

import pytest
from fake_records import fixture_alerts, fixture_events
from specialist_fakes import load

from soc.config import load_config
from soc.contracts import validate_contract
from soc.l1.specialists.web import PROMPT, WEB_AGENT
from soc.llm import create_provider_registry, format_untrusted_data, load_prompt
from soc.llm.base import ProviderRequest

TICKET = load("ticket_web.json")
REQUEST = load("specialist_request.json")
VIEW = ("ticket_id", "handling_type", "priority", "entities")


@pytest.mark.llm
def test_configured_model_answers_the_web_prompt_as_a_specialist_finding():
    settings = load_config(environ={}).llm
    prompt = load_prompt(PROMPT)
    override = settings.agents.get(WEB_AGENT)
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
                model=(override.model if override else None) or settings.model,
                system_prompt=prompt.text,
                user_prompt=format_untrusted_data(data),
                temperature=settings.temperature,
                timeout_seconds=(override.timeout_seconds if override else None)
                or settings.timeout_seconds,
            )
        )
    )

    finding = validate_contract("SpecialistFinding", json.loads(response.content))
    assert finding.evidence
