"""격리 키·직렬화는 정해 둔 바이트와 손으로 만든 입력으로 확인한다."""

import base64
import copy
import hashlib
import json
from pathlib import Path

from soc.ingest.quarantine import (
    canonical_json_bytes,
    exceeds_depth,
    quarantine_key,
    serialize_original,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "ingest"


def golden() -> dict:
    return json.loads((FIXTURES / "quarantine_hash_golden.json").read_text(encoding="utf-8"))


def hash_payload(sample: dict) -> dict:
    hit = copy.deepcopy(sample["hit"])
    hit.pop("_score", None)
    if isinstance(hit.get("sort"), list) and hit["sort"]:
        hit["sort"] = hit["sort"][:1]
    return {"source_kind": sample["source_kind"], "source_key": sample["source_key"], "hit": hit}


def test_hash_bytes_and_synthetic_key_match_golden_fixture() -> None:
    sample = golden()
    payload = hash_payload(sample)

    encoded = canonical_json_bytes(payload)

    assert encoded == json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=True,
    ).encode("ascii")
    assert hashlib.sha256(encoded).hexdigest() == sample["expected_sha256"]
    assert (
        quarantine_key(sample["source_kind"], sample["source_key"], sample["hit"])
        == sample["expected_siem_ref"]
    )


def test_hash_ignores_score_and_pit_sort_tail_without_mutating_hit() -> None:
    sample = golden()
    changed = copy.deepcopy(sample["hit"])
    changed["_score"] = -123.0
    changed["sort"][1] = {"_shard_doc": 999}
    before = copy.deepcopy(changed)

    assert (
        quarantine_key(sample["source_kind"], sample["source_key"], changed)
        == sample["expected_siem_ref"]
    )
    assert changed == before

    reordered = dict(reversed(list(sample["hit"].items())))
    reordered["_source"] = dict(reversed(list(reordered["_source"].items())))
    compact = json.loads(json.dumps(reordered, separators=(",", ":")))
    assert (
        quarantine_key(sample["source_kind"], sample["source_key"], compact)
        == sample["expected_siem_ref"]
    )


def test_synthetic_tokens_distinguish_missing_values_and_json_types() -> None:
    missing = quarantine_key("event", "logs-a", {"_index": None, "_id": "", "sort": [False]})
    present = quarantine_key("event", "logs-a", {"_index": "-", "_id": "-", "sort": ["123"]})

    assert missing.startswith("synthetic:v1:n:n:vZmFsc2U:")
    assert present.startswith("synthetic:v1:vIi0i:vIi0i:vIjEyMyI:")
    assert quarantine_key("event", "logs-a", "raw scalar").startswith("synthetic:v1:n:n:n:")


def test_object_sort_token_uses_canonical_json_key_order_and_compact_bytes() -> None:
    sort_value = [{"z": [2, {"b": "x", "a": 1}], "a": True}]
    first = {
        "_index": "logs-a",
        "_id": "doc-1",
        "sort": [sort_value],
    }
    reordered = {
        "sort": [[{"a": True, "z": [2, {"a": 1, "b": "x"}]}]],
        "_id": "doc-1",
        "_index": "logs-a",
    }
    canonical = b'[{"a":true,"z":[2,{"a":1,"b":"x"}]}]'
    expected = "v" + base64.urlsafe_b64encode(canonical).decode("ascii").rstrip("=")

    assert canonical_json_bytes(sort_value) == canonical

    first_key = quarantine_key("event", "logs-a", first)
    reordered_key = quarantine_key("event", "logs-a", reordered)

    assert first_key == reordered_key
    assert first_key.split(":")[4] == expected


def test_each_field_token_hashes_only_when_unpadded_payload_exceeds_128_chars() -> None:
    positions = {"_index": 2, "_id": 3, "sort": 4}
    for field, prefix in positions.items():
        for length, expected_payload_size in ((94, 128), (95, 130)):
            value = "x" * length
            hit = {"_index": "stable-index", "_id": "stable-id", "sort": [0]}
            hit[field] = value if field != "sort" else [value]
            encoded_json = (
                serialize_original(value).encode("ascii")
                if field in ("_index", "_id")
                else canonical_json_bytes(value)
            )
            payload = base64.urlsafe_b64encode(encoded_json).decode("ascii").rstrip("=")
            actual = quarantine_key("event", "logs-a", hit).split(":")[prefix]
            expected = (
                "h" + hashlib.sha256(encoded_json).hexdigest()
                if len(payload) > 128
                else "v" + payload
            )

            assert len(payload) == expected_payload_size
            assert actual == expected


def test_iterative_serializers_handle_depth_beyond_python_recursion_limit() -> None:
    nested = 0
    for _ in range(1200):
        nested = [nested]
    expected = b"[" * 1200 + b"0" + b"]" * 1200

    assert canonical_json_bytes(nested) == expected
    assert serialize_original(nested) == expected.decode("ascii")
    assert exceeds_depth(nested)


def test_depth_limit_counts_containers_without_recursion() -> None:
    at_limit = 0
    for _ in range(100):
        at_limit = [at_limit]
    over_limit = [at_limit]

    assert not exceeds_depth(at_limit)
    assert exceeds_depth(over_limit)


def test_original_serializer_matches_d049_json_text_and_keeps_nonfinite_values() -> None:
    sample = golden()
    hit = sample["hit"]

    assert serialize_original(hit) == json.dumps(hit, ensure_ascii=True)
    assert "NaN" in serialize_original(hit)
    assert "Infinity" in serialize_original(hit)
    assert "\\ud800" in serialize_original(hit)
