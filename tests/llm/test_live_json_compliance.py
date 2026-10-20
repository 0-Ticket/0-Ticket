"""Live JSON compliance checks for both Box 11 Verdict prompts."""

import json
import os
from pathlib import Path

import pytest

from soc.config import load_config
from soc.contracts import validate_contract
from soc.llm import create_provider_registry, format_untrusted_data, load_prompt
from soc.llm.base import ProviderRequest

ROOT = Path(__file__).resolve().parents[2]
EVALUATION_SAMPLES = ROOT / "tests/fixtures/llm/evaluation_samples.json"
PROMPTS = (
    ("l1_entity_lookup", ROOT / "src/soc/l1/prompts/l1_entity_lookup.md"),
    ("l1_ticket_triage", ROOT / "src/soc/l1/prompts/l1_ticket_triage.md"),
)


@pytest.mark.llm
@pytest.mark.parametrize(("prompt_name", "prompt_path"), PROMPTS, ids=[name for name, _ in PROMPTS])
def test_configured_model_json_compliance_rate(prompt_name, prompt_path):
    app_settings = load_config(environ=os.environ)
    settings = app_settings.llm
    agent_settings = settings.agents.get("l1")
    model = (agent_settings.model if agent_settings else None) or settings.model
    timeout_seconds = (
        agent_settings.timeout_seconds if agent_settings else None
    ) or settings.timeout_seconds
    prompt = load_prompt(prompt_path)
    samples = json.loads(EVALUATION_SAMPLES.read_text(encoding="utf-8"))
    provider = create_provider_registry().get(settings.provider)()
    api_key = os.environ.get(settings.api_key_env) or None
    valid = 0

    for sample in samples:
        response = provider.complete(
            ProviderRequest(
                base_url=settings.base_url,
                api_key=api_key,
                model=model,
                system_prompt=prompt.text,
                user_prompt=format_untrusted_data(sample),
                temperature=settings.temperature,
                timeout_seconds=timeout_seconds,
            )
        )
        try:
            validate_contract("Verdict", json.loads(response.content))
        except (ValueError, TypeError):
            continue
        valid += 1

    print(
        f"Configured model JSON contract compliance "
        f"(model={model}, prompt={prompt_name}, contract=Verdict): "
        f"{valid}/{len(samples)} ({valid / len(samples):.0%})"
    )
