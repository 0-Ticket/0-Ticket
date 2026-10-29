"""Test doubles for the demo flow integration test (#81).

Everything here is registered by name in a plugin registry and selected by the
settings in tests/fixtures/flow/settings.toml, the way an organization's plugin
would be. No core code knows these names.

- ``FakeLLMProvider`` answers from tests/fixtures/flow/fake_llm.json by the rule_id
  of the alert in its input. It tells the three calls apart by the shape of the
  input data, never by prompt wording, so prompt changes do not break it.
- ``MemoryVectorStore`` and ``FixedEmbedder`` stand in for Qdrant and Ollama.
- ``FlowFakeSiem`` and ``FlowFakeSiemMcp`` are a SIEM that holds a fixed list of
  C2 contents, for the step that swaps the SIEM by setting only (K66).
"""

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from soc.ingest.siem.base import FetchBatch, HealthStatus, InvalidCursorError
from soc.l1.mcp.siem.base import SiemQuery
from soc.llm.base import ProviderRequest, ProviderResponse
from soc.plugins import PluginRegistry
from soc.store.vectors.base import VectorSearchHit

FLOW = Path(__file__).resolve().parents[1] / "fixtures" / "flow"
SCRIPT = json.loads((FLOW / "fake_llm.json").read_text(encoding="utf-8"))
FAKE = "fake"
DATA_START = "<untrusted_data>"
DATA_END = "</untrusted_data>"


def input_data(user_prompt: str) -> dict[str, Any]:
    """The JSON the LLM call wrapped: the line after the wrapper's notice line."""
    start = user_prompt.index(DATA_START)
    end = user_prompt.index(DATA_END, start)
    body = user_prompt[start + len(DATA_START) : end].strip().split("\n", 1)[1]
    return json.loads(body)


def _answer(kind: str, rule_id: str | None) -> dict[str, Any]:
    script = SCRIPT[kind]
    return dict(script["by_rule"].get(rule_id or "", script["default"]))


def _first_record(summary: Mapping[str, Any]) -> Mapping[str, Any]:
    return summary["records"][0]


def _evidence(ref_type: str, ref_id: str) -> list[dict[str, str]]:
    return [{"ref_type": ref_type, "ref_id": ref_id, "note": "Scripted test evidence"}]


def _verdict(answer: Mapping[str, Any], alert_id: str) -> dict[str, Any]:
    return {
        "verdict": answer["verdict"],
        "confidence": answer["confidence"],
        "summary": "Scripted test verdict.",
        "evidence": _evidence("alert", alert_id),
        "recommended_action": "None: test fake.",
        "needs_human": False,
        "human_reason": None,
    }


def _finding(answer: Mapping[str, Any], data: Mapping[str, Any]) -> dict[str, Any]:
    evidence = _evidence("alert", _first_record(data["alerts"])["alert_id"])
    wanted = answer.get("cite_url_contains")
    if wanted:
        for flow in data["flows"]:
            url = flow["columns"].index("http_url")
            row = next((row for row in flow["rows"] if wanted in (row[url] or "")), None)
            if row is not None:
                evidence = _evidence("event", row[0])
                break
    return {
        "ticket_id": data["ticket"]["ticket_id"],
        "specialist": "web",
        "question": data["question"],
        "summary": "Scripted test finding.",
        "attack_type": answer["attack_type"],
        "succeeded": answer["succeeded"],
        "confidence": answer["confidence"],
        "evidence": evidence,
        "details": {},
        "needs_human": False,
        "human_reason": None,
        "created_at": 0,
    }


class FakeLLMProvider:
    """Scripted provider. ``calls`` counts the calls per kind of input."""

    def __init__(self):
        self.calls: dict[str, int] = {}

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        data = input_data(request.user_prompt)
        if "flows" in data and "question" in data:
            kind = "web_specialist"
            output = _finding(_answer(kind, _first_record(data["alerts"])["rule_id"]), data)
        elif "ticket" in data:
            kind = "ticket_triage"
            alert = _first_record(data["alerts"])
            output = _verdict(_answer(kind, alert["rule_id"]), alert["alert_id"])
        else:
            kind = "entity_lookup"
            alert = data["alert"]
            output = _verdict(_answer(kind, alert["rule_id"]), alert["alert_id"])
        self.calls[kind] = self.calls.get(kind, 0) + 1
        return ProviderResponse(content=json.dumps(output), tokens=1)


class MemoryVectorStore:
    """Keeps upserted documents; searches find nothing, so no similar Ticket is shown."""

    def __init__(self):
        self.documents: dict[str, Mapping[str, Any]] = {}

    def upsert(self, document: Mapping[str, Any], vector: Sequence[float]) -> None:
        self.documents[str(document.get("doc_id"))] = document

    def search_by_vector(self, vector: Sequence[float], *, limit: int) -> list[VectorSearchHit]:
        return []

    def search_by_keywords(self, keywords: Sequence[str], *, limit: int) -> list[VectorSearchHit]:
        return []

    def close(self) -> None:
        pass


class FixedEmbedder:
    def embed(self, text: str) -> list[float]:
        return [1.0, 0.0]


def l1_registries(provider: FakeLLMProvider) -> dict[str, PluginRegistry]:
    """The keyword arguments ``soc.l1`` main takes for the fakes the settings name."""
    providers = PluginRegistry("llm_providers")
    providers.register(FAKE, provider)
    vectors = PluginRegistry("vector_stores")
    vectors.register(FAKE, lambda _settings: MemoryVectorStore())
    embedders = PluginRegistry("embedders")
    embedders.register(FAKE, lambda _settings: FixedEmbedder())
    return {"providers": providers, "vectors": vectors, "embedders": embedders}


class FlowFakeSiem:
    """A SIEM connector over a fixed list of C2 contents, read in pages."""

    def __init__(self, items: Sequence[Mapping[str, Any]]):
        self._items = tuple(dict(item) for item in items)

    def fetch(self, cursor: str | None, limit: int) -> FetchBatch:
        if cursor is not None and not cursor.isdigit():
            raise InvalidCursorError("fake cursor must be a number")
        start = int(cursor or 0)
        items = self._items[start : start + limit]
        return FetchBatch(items=items, next_cursor=str(start + len(items)) if items else cursor)

    def health_check(self) -> HealthStatus:
        return HealthStatus(ok=True, detail="fake SIEM")


class FlowFakeSiemMcp:
    """Answers a SiemQuery from the same list. ``index`` gives each item's time and IPs:
    how a SIEM finds them is the adapter's own business."""

    def __init__(self, items: Sequence[Mapping[str, Any]], index: Sequence[tuple[int, set[str]]]):
        self._records = tuple(zip(items, index, strict=True))
        self.queries: list[SiemQuery] = []

    def query(self, query: SiemQuery) -> tuple[Mapping[str, Any], ...]:
        self.queries.append(query)
        if query.entity.type != "ip":
            return ()
        matched = [
            (time, item)
            for item, (time, ips) in self._records
            if item["kind"] == query.kind
            and query.start_at <= time <= query.end_at
            and query.entity.value in ips
        ]
        matched.sort(key=lambda pair: pair[0])
        return tuple(dict(item) for _time, item in matched[: query.limit])

    def health_check(self) -> HealthStatus:
        return HealthStatus(ok=True, detail="fake SIEM MCP")


def fake_siem_registries(
    items: Sequence[Mapping[str, Any]], index: Sequence[tuple[int, set[str]]]
) -> tuple[PluginRegistry, PluginRegistry, FlowFakeSiemMcp]:
    """The ``siem`` (connector) and ``siem_mcp_adapters`` registries with ``fake``."""
    mcp = FlowFakeSiemMcp(items, index)
    connectors = PluginRegistry("siem")
    connectors.register(FAKE, lambda _settings, _environ: FlowFakeSiem(items))
    adapters = PluginRegistry("siem_mcp_adapters")
    adapters.register(FAKE, lambda _settings, _environ: mcp)
    return connectors, adapters, mcp


def toml_string(value: str) -> str:
    """Quote ``value`` as a TOML basic string, for the settings file a test writes.

    TOML takes the same escapes as JSON, so this covers a Windows path's
    backslashes, a quote in a folder name and control characters such as a
    newline. ``ensure_ascii=False`` is what keeps a character outside the BMP
    (an emoji in a path) working: escaped, it becomes a surrogate pair, which
    TOML rejects as not a Unicode scalar value.
    """
    return json.dumps(value, ensure_ascii=False)


__all__ = [
    "FAKE",
    "FakeLLMProvider",
    "FixedEmbedder",
    "FlowFakeSiem",
    "FlowFakeSiemMcp",
    "MemoryVectorStore",
    "fake_siem_registries",
    "input_data",
    "l1_registries",
    "toml_string",
]
