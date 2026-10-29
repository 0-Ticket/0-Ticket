"""Offline formatting checks and an opt-in live L1 model comparison (#80)."""

import hashlib
import json
import os
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path

import pytest

from soc.config import load_config
from soc.contracts import ContractValidationError, validate_contract
from soc.llm import create_provider_registry, format_untrusted_data, load_prompt
from soc.llm.base import ProviderError, ProviderRequest

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "tests/fixtures/llm/entity_lookup_comparison_samples.json"
PROMPT = ROOT / "src/soc/l1/prompts/l1_entity_lookup.md"
MODELS_ENV = "L1_COMPARE_MODELS"
CHECKPOINT_VERSION = 1
CHECKPOINT_PATH = ROOT / "config/local.l1-entity-lookup-checkpoint.json"


def test_parse_model_ids_trims_two_distinct_names():
    assert _parse_model_ids(" model-one , model-two ") == ("model-one", "model-two")


@pytest.mark.parametrize(
    "value",
    [None, "", "model-one", "model-one,model-two,model-three", "same,same", "model-one,"],
)
def test_parse_model_ids_rejects_missing_or_invalid_pair(value):
    with pytest.raises(ValueError):
        _parse_model_ids(value)


def test_comparison_record_includes_full_outputs_and_changed_fields():
    outputs = [
        {
            "model": "model-one",
            "contract_valid": True,
            "output": {
                "verdict": "unknown",
                "confidence": 0.4,
                "summary": "Insufficient evidence.",
                "evidence": [{"ref_type": "alert", "ref_id": "al_1", "note": "One alert"}],
                "recommended_action": "Gather more evidence.",
                "needs_human": False,
                "human_reason": None,
            },
        },
        {
            "model": "model-two",
            "contract_valid": True,
            "output": {
                "verdict": "fp",
                "confidence": 0.8,
                "summary": "A benign health check.",
                "evidence": [{"ref_type": "alert", "ref_id": "al_1", "note": "Health check"}],
                "recommended_action": "Close as benign.",
                "needs_human": False,
                "human_reason": None,
            },
        },
    ]

    record = _comparison_record("sample-1", outputs)

    assert record == {
        "sample_id": "sample-1",
        "models": outputs,
        "different_fields": [
            "confidence",
            "evidence",
            "recommended_action",
            "summary",
            "verdict",
        ],
        "complete": True,
    }
    serialized = _json_line(record)
    assert "\n" not in serialized
    assert json.loads(serialized) == record


def test_comparison_record_reports_contract_and_raw_response_differences():
    outputs = [
        {"model": "model-one", "contract_valid": False, "raw_response": "not json"},
        {"model": "model-two", "contract_valid": True, "output": {"verdict": "unknown"}},
    ]

    record = _comparison_record("sample-2", outputs)

    assert record["different_fields"] == ["contract_valid", "output", "raw_response"]
    assert record["models"] == outputs


def test_pending_models_skips_model_responses_already_in_checkpoint():
    checkpoint_results = {
        "sample-1": {
            "model-one": {
                "model": "model-one",
                "contract_valid": True,
                "output": {"verdict": "unknown"},
            }
        }
    }

    assert _pending_models("sample-1", ("model-one", "model-two"), checkpoint_results) == (
        "model-two",
    )


def test_checkpoint_round_trip_preserves_full_model_outputs(tmp_path):
    path = tmp_path / "comparison.json"
    identity = {"digest": "fixture-prompt-config-hash"}
    results = {
        "sample-1": {
            "model-one": {
                "model": "model-one",
                "contract_valid": True,
                "output": {"verdict": "unknown", "summary": "No corroboration."},
            }
        }
    }

    _save_checkpoint(path, identity, results)

    assert (
        _load_checkpoint(
            path,
            identity,
            sample_ids={"sample-1"},
            models=("model-one", "model-two"),
        )
        == results
    )


def test_checkpoint_rejects_different_run_identity(tmp_path):
    path = tmp_path / "comparison.json"
    _save_checkpoint(path, {"digest": "old"}, {"sample-1": {}})

    with pytest.raises(ValueError, match="does not match"):
        _load_checkpoint(
            path,
            {"digest": "new"},
            sample_ids={"sample-1"},
            models=("model-one", "model-two"),
        )


def _parse_model_ids(value: str | None) -> tuple[str, str]:
    """Parse exactly two distinct model IDs from the test-only environment setting."""
    if value is None:
        raise ValueError(f"{MODELS_ENV} must contain exactly two comma-separated model IDs")
    models = tuple(model.strip() for model in value.split(","))
    if len(models) != 2 or any(not model for model in models) or models[0] == models[1]:
        raise ValueError(f"{MODELS_ENV} must contain exactly two distinct model IDs")
    return models


def _pending_models(
    sample_id: str, models: tuple[str, str], checkpoint_results: dict[str, dict[str, dict]]
) -> tuple[str, ...]:
    """Return only model calls that have no completed response in the checkpoint."""
    completed = checkpoint_results.get(sample_id, {})
    return tuple(model for model in models if model not in completed)


def _comparison_identity(
    models: tuple[str, str],
    prompt_text: str,
    samples: list[dict],
    *,
    provider: str,
    base_url: str,
    temperature: float,
) -> dict:
    """Fingerprint every input that would make saved model responses incomparable."""
    material = {
        "models": list(models),
        "prompt": prompt_text,
        "samples": samples,
        "provider": provider,
        "base_url": base_url,
        "temperature": temperature,
    }
    canonical = json.dumps(material, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return {
        "models": list(models),
        "fingerprint": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }


def _is_completed_model_output(model: str, result: object) -> bool:
    if not isinstance(result, dict) or result.get("model") != model:
        return False
    if not isinstance(result.get("contract_valid"), bool):
        return False
    if result["contract_valid"]:
        return isinstance(result.get("output"), dict) and "raw_response" not in result
    return ("output" in result) != ("raw_response" in result)


def _load_checkpoint(
    path: Path,
    identity: dict,
    *,
    sample_ids: set[str],
    models: tuple[str, str],
) -> dict[str, dict[str, dict]]:
    """Load completed model outputs and reject stale or malformed checkpoint files."""
    if not path.exists():
        return {}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise ValueError(
            "comparison checkpoint is unreadable; remove it to start a fresh run"
        ) from None
    if (
        not isinstance(state, dict)
        or state.get("version") != CHECKPOINT_VERSION
        or state.get("identity") != identity
    ):
        raise ValueError(
            "comparison checkpoint does not match the current prompt, samples, models, "
            "or provider settings; remove it to start a fresh run"
        )
    results = state.get("results")
    if not isinstance(results, dict):
        raise ValueError("comparison checkpoint has an invalid results section")
    for sample_id, model_results in results.items():
        if sample_id not in sample_ids or not isinstance(model_results, dict):
            raise ValueError("comparison checkpoint contains an unknown sample")
        for model, result in model_results.items():
            if model not in models or not _is_completed_model_output(model, result):
                raise ValueError("comparison checkpoint contains an invalid model result")
    return results


def _save_checkpoint(path: Path, identity: dict, results: dict[str, dict[str, dict]]) -> None:
    """Atomically save completed outputs after each provider response."""
    path.parent.mkdir(parents=True, exist_ok=True)
    state = {"version": CHECKPOINT_VERSION, "identity": identity, "results": results}
    serialized = json.dumps(state, ensure_ascii=True, sort_keys=True, indent=2) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as temporary_file:
            temporary_file.write(serialized)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def _comparison_record(sample_id: str, outputs: list[dict]) -> dict:
    """Build a complete row with full outputs and the differing Verdict fields."""
    if len(outputs) != 2:
        raise ValueError("a complete comparison requires two model outputs")
    left, right = outputs
    different_fields = []
    if left.get("contract_valid") != right.get("contract_valid"):
        different_fields.append("contract_valid")

    left_output = left.get("output")
    right_output = right.get("output")
    if isinstance(left_output, Mapping) and isinstance(right_output, Mapping):
        sentinel = object()
        different_fields.extend(
            field
            for field in sorted(left_output.keys() | right_output.keys())
            if left_output.get(field, sentinel) != right_output.get(field, sentinel)
        )
    elif left_output != right_output:
        different_fields.append("output")

    if left.get("raw_response") != right.get("raw_response") and (
        "raw_response" in left or "raw_response" in right
    ):
        different_fields.append("raw_response")
    return {
        "sample_id": sample_id,
        "models": outputs,
        "different_fields": different_fields,
        "complete": True,
    }


def _json_line(record: dict) -> str:
    """Serialize one output row as a single escaped JSONL line."""
    return json.dumps(record, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _model_output(model: str, content: str) -> dict:
    """Keep the complete valid Verdict, parsed JSON, or safely escaped raw response."""
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return {"model": model, "contract_valid": False, "raw_response": content}
    try:
        verdict = validate_contract("Verdict", parsed)
    except ContractValidationError:
        return {"model": model, "contract_valid": False, "output": parsed}
    return {
        "model": model,
        "contract_valid": True,
        "output": verdict.model_dump(mode="json"),
    }


def test_model_output_keeps_complete_contract_valid_verdict():
    content = json.dumps(
        {
            "verdict": "unknown",
            "confidence": 0.4,
            "summary": "Only one alert is shown.",
            "evidence": [{"ref_type": "alert", "ref_id": "al_1", "note": "One observation"}],
            "recommended_action": "Gather more evidence.",
            "needs_human": False,
            "human_reason": None,
        }
    )

    result = _model_output("model-one", content)

    assert result["contract_valid"] is True
    assert set(result["output"]) == {
        "verdict",
        "confidence",
        "summary",
        "evidence",
        "recommended_action",
        "needs_human",
        "human_reason",
    }


def test_model_output_preserves_malformed_response_for_escaped_jsonl():
    content = "not JSON\nsecond line"

    result = _model_output("model-one", content)

    assert result == {"model": "model-one", "contract_valid": False, "raw_response": content}
    assert json.loads(_json_line(result))["raw_response"] == content


def test_model_output_preserves_parsed_json_that_fails_contract():
    result = _model_output("model-one", '{"verdict":"unexpected"}')

    assert result == {
        "model": "model-one",
        "contract_valid": False,
        "output": {"verdict": "unexpected"},
    }


def _incomplete_record(sample_id: str, outputs: list[dict]) -> dict:
    """Represent provider failure without response bodies or partial comparisons."""
    return {
        "sample_id": sample_id,
        "models": outputs,
        "different_fields": None,
        "complete": False,
    }


@pytest.mark.llm
def test_compare_configured_models_on_entity_lookup():
    """Call both configured models on each fresh sample and emit comparable JSONL."""
    try:
        models = _parse_model_ids(os.environ.get(MODELS_ENV))
    except ValueError as error:
        pytest.fail(str(error), pytrace=False)

    app_settings = load_config(environ=os.environ)
    settings = app_settings.llm
    api_key = os.environ.get(settings.api_key_env) or None
    if not api_key:
        pytest.fail("the configured LLM API key is missing from the environment", pytrace=False)

    agent_settings = settings.agents.get("l1")
    timeout_seconds = (
        agent_settings.timeout_seconds if agent_settings else None
    ) or settings.timeout_seconds
    prompt = load_prompt(PROMPT)
    samples = json.loads(SAMPLES.read_text(encoding="utf-8"))
    provider = create_provider_registry().get(settings.provider)()
    identity = _comparison_identity(
        models,
        prompt.text,
        samples,
        provider=settings.provider,
        base_url=settings.base_url,
        temperature=settings.temperature,
    )
    sample_ids = {sample["sample_id"] for sample in samples}
    try:
        checkpoint_results = _load_checkpoint(
            CHECKPOINT_PATH,
            identity,
            sample_ids=sample_ids,
            models=models,
        )
    except ValueError as error:
        pytest.fail(str(error), pytrace=False)

    completed = sum(len(model_results) for model_results in checkpoint_results.values())
    total = len(samples) * len(models)
    print(
        f"L1 comparison checkpoint: {completed}/{total} model responses saved at {CHECKPOINT_PATH}",
        file=sys.stderr,
        flush=True,
    )

    for sample in samples:
        sample_id = sample["sample_id"]
        model_results = checkpoint_results.setdefault(sample_id, {})
        user_prompt = format_untrusted_data(sample["input"])
        for model in _pending_models(sample_id, models, checkpoint_results):
            try:
                response = provider.complete(
                    ProviderRequest(
                        base_url=settings.base_url,
                        api_key=api_key,
                        model=model,
                        system_prompt=prompt.text,
                        user_prompt=user_prompt,
                        temperature=settings.temperature,
                        timeout_seconds=timeout_seconds,
                    )
                )
            except ProviderError as error:
                outputs = []
                for pending_model in models:
                    if pending_model in model_results:
                        outputs.append(model_results[pending_model])
                    elif pending_model == model:
                        outputs.append(
                            {
                                "model": model,
                                "status": "provider_error",
                                "code": error.code,
                                "retry_after_seconds": error.retry_after_seconds,
                            }
                        )
                    else:
                        outputs.append({"model": pending_model, "status": "not_run"})
                print(_json_line(_incomplete_record(sample_id, outputs)), flush=True)
                pytest.fail(
                    "model comparison incomplete: "
                    f"sample={sample_id} model={model} code={error.code} "
                    f"retry_after_seconds={error.retry_after_seconds}",
                    pytrace=False,
                )
            model_results[model] = _model_output(model, response.content)
            try:
                _save_checkpoint(CHECKPOINT_PATH, identity, checkpoint_results)
            except OSError:
                pytest.fail(
                    "could not save the local L1 comparison checkpoint; "
                    "check that the ignored config/local.* path is writable",
                    pytrace=False,
                )
            print(
                f"L1 comparison saved: sample={sample_id} model={model}",
                file=sys.stderr,
                flush=True,
            )

    for sample in samples:
        sample_id = sample["sample_id"]
        outputs = [checkpoint_results[sample_id][model] for model in models]
        print(_json_line(_comparison_record(sample_id, outputs)), flush=True)
