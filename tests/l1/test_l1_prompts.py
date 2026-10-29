"""L1 prompts state the C7 Verdict output format (#91).

Without it the model guessed the shape and every call failed contract validation
(required, type) on the demo data.
"""

import json
import re
from pathlib import Path

import pytest

from soc.contracts import validate_contract
from soc.l1 import runtime, ticket_triage
from soc.llm.prompts import load_prompt

ROOT = Path(__file__).resolve().parents[2]
VERDICT_FIELDS = json.loads(
    (ROOT / "contracts" / "verdict.schema.json").read_text(encoding="utf-8")
)["required"]
PROMPTS = [runtime.PROMPT, ticket_triage.PROMPT]


@pytest.mark.parametrize("prompt_path", PROMPTS, ids=["entity_lookup", "ticket_triage"])
def test_prompt_example_is_a_valid_verdict(prompt_path):
    text = load_prompt(prompt_path).text
    example = re.search(r"```json\n(.*?)\n```", text, re.DOTALL)

    assert example is not None
    validate_contract("Verdict", json.loads(example.group(1)))


@pytest.mark.parametrize("prompt_path", PROMPTS, ids=["entity_lookup", "ticket_triage"])
def test_prompt_names_every_verdict_field(prompt_path):
    section = load_prompt(prompt_path).text.split("## Output format", 1)[1]

    assert all(f"`{name}`" in section for name in VERDICT_FIELDS)
