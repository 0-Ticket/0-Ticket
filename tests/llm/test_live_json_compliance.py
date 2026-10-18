"""Small, explicitly selected live compliance check for the configured local model."""

import json
import os
from pathlib import Path

import pytest

from soc.config import load_config
from soc.contracts import validate_contract
from soc.llm import create_provider_registry, format_untrusted_data, load_prompt
from soc.llm.base import ProviderRequest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.llm
def test_configured_model_json_compliance_rate():
    settings = load_config(environ={}).llm
    prompt = load_prompt(ROOT / "tests/fixtures/llm/prompts/sample_verdict.md")
    samples = json.loads(
        (ROOT / "tests/fixtures/llm/evaluation_samples.json").read_text(encoding="utf-8")
    )
    provider = create_provider_registry().get(settings.provider)()
    api_key = os.environ.get(settings.api_key_env) or None
    valid = 0

    for sample in samples:
        response = provider.complete(
            ProviderRequest(
                base_url=settings.base_url,
                api_key=api_key,
                model=settings.model,
                system_prompt=prompt.text,
                user_prompt=format_untrusted_data(sample),
                temperature=settings.temperature,
            )
        )
        try:
            validate_contract("Verdict", json.loads(response.content))
        except (ValueError, TypeError):
            continue
        valid += 1

    print(f"Configured model JSON contract compliance: {valid}/{len(samples)}")
