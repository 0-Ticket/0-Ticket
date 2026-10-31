import logging
import traceback
from types import SimpleNamespace

import httpx
import pytest
from qdrant_client import models
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

from soc.config import load_config
from soc.store.vectors.base import (
    VectorStoreInitializationCleanupError,
    VectorStoreUnavailableError,
)
from soc.store.vectors.qdrant import QdrantVectorStore, create_qdrant_vector_store

_SECRET = "synthetic-secret-marker"
_ADDRESS = "https://203.0.113.77:6333/private-path"


def unexpected_response(status_code: int, content: str = _SECRET) -> UnexpectedResponse:
    return UnexpectedResponse(
        status_code=status_code,
        reason_phrase="Synthetic Service Failure",
        content=content.encode(),
        headers=httpx.Headers({"x-synthetic-secret": _SECRET}),
    )


class FakeQdrantClient:
    def __init__(self, *, errors=None, close_error=None, collection_exists=False):
        self.errors = errors or {}
        self.close_error = close_error
        self.collection_exists_result = collection_exists
        self.calls = []

    def _call(self, name):
        self.calls.append(name)
        error = self.errors.get(name)
        if error is not None:
            raise error

    def collection_exists(self, collection):
        self._call("collection_exists")
        return self.collection_exists_result

    def create_collection(self, **kwargs):
        self._call("create_collection")

    def get_collection(self, collection):
        self._call("get_collection")
        vectors = models.VectorParams(size=3, distance=models.Distance.COSINE)
        return SimpleNamespace(config=SimpleNamespace(params=SimpleNamespace(vectors=vectors)))

    def create_payload_index(self, **kwargs):
        self._call("create_payload_index")

    def query_points(self, **kwargs):
        self._call("query_points")
        return SimpleNamespace(points=[])

    def upsert(self, **kwargs):
        self._call("upsert")

    def scroll(self, **kwargs):
        self._call("scroll")
        return [], None

    def close(self):
        self._call("close")
        if self.close_error is not None:
            raise self.close_error


def settings():
    return load_config(environ={})


@pytest.mark.parametrize(
    "error, expected_type",
    [
        (httpx.ConnectError(f"connect failed at {_ADDRESS}; {_SECRET}"), "ConnectError"),
        (httpx.ReadTimeout(f"timed out at {_ADDRESS}; {_SECRET}"), "ReadTimeout"),
        (
            ResponseHandlingException(httpx.ConnectError(f"wrapped failure at {_ADDRESS}")),
            "ConnectError",
        ),
        (unexpected_response(503), "UnexpectedResponse"),
        (unexpected_response(429), "UnexpectedResponse"),
    ],
)
def test_transient_qdrant_initialization_failures_are_neutral_and_clean_up(
    monkeypatch, error, expected_type
):
    client = FakeQdrantClient(errors={"collection_exists": error})
    monkeypatch.setattr(
        "soc.store.vectors.qdrant.QdrantClient",
        lambda **kwargs: client,
    )

    with pytest.raises(VectorStoreUnavailableError) as raised:
        create_qdrant_vector_store(settings())

    assert str(raised.value) == "vector_store_unavailable"
    assert raised.value.dependency_error_type == expected_type
    assert client.calls.count("close") == 1
    output = "".join(traceback.format_exception(raised.value))
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__
    assert str(error) not in output
    assert _SECRET not in output
    assert _ADDRESS not in output


@pytest.mark.parametrize(
    "error",
    [
        ValueError(f"invalid collection configuration: {_SECRET}"),
        unexpected_response(401),
        unexpected_response(403),
        unexpected_response(404),
        KeyError(f"implementation failure: {_SECRET}"),
    ],
)
def test_non_transient_qdrant_initialization_errors_remain_unchanged(monkeypatch, error):
    client = FakeQdrantClient(errors={"collection_exists": error})
    monkeypatch.setattr("soc.store.vectors.qdrant.QdrantClient", lambda **kwargs: client)

    with pytest.raises(type(error)) as raised:
        create_qdrant_vector_store(settings())

    assert raised.value is error
    assert not isinstance(raised.value, VectorStoreUnavailableError)
    assert client.calls.count("close") == 1


def test_transient_qdrant_client_construction_error_is_mapped(monkeypatch):
    error = httpx.ConnectError(f"connect failed at {_ADDRESS}; {_SECRET}")

    def fail_client_construction(**kwargs):
        raise error

    monkeypatch.setattr(
        "soc.store.vectors.qdrant.QdrantClient",
        fail_client_construction,
    )

    with pytest.raises(VectorStoreUnavailableError) as raised:
        create_qdrant_vector_store(settings())

    assert raised.value.dependency_error_type == "ConnectError"
    output = "".join(traceback.format_exception(raised.value))
    assert str(error) not in output
    assert _SECRET not in output
    assert _ADDRESS not in output


def test_invalid_url_error_from_qdrant_client_construction_is_not_mapped(monkeypatch):
    error = ValueError(f"invalid URL {_ADDRESS}; {_SECRET}")

    def fail_client_construction(**kwargs):
        raise error

    monkeypatch.setattr(
        "soc.store.vectors.qdrant.QdrantClient",
        fail_client_construction,
    )

    with pytest.raises(ValueError) as raised:
        create_qdrant_vector_store(settings())

    assert raised.value is error
    assert not isinstance(raised.value, VectorStoreUnavailableError)


def test_unsupported_protocol_error_is_not_mapped(monkeypatch):
    error = httpx.UnsupportedProtocol(f"unsupported URL scheme at {_ADDRESS}; {_SECRET}")
    client = FakeQdrantClient(errors={"collection_exists": error})
    monkeypatch.setattr("soc.store.vectors.qdrant.QdrantClient", lambda **kwargs: client)

    with pytest.raises(httpx.UnsupportedProtocol) as raised:
        create_qdrant_vector_store(settings())

    assert raised.value is error
    assert not isinstance(raised.value, VectorStoreUnavailableError)
    assert client.calls.count("close") == 1


def test_transient_runtime_qdrant_call_is_mapped_to_backend_neutral_error():
    error = unexpected_response(502)
    client = FakeQdrantClient(errors={"query_points": error})
    store = QdrantVectorStore(client, collection="closed_tickets", dimensions=3)

    with pytest.raises(VectorStoreUnavailableError) as raised:
        store.search_by_vector([1.0, 0.0, 0.0], limit=1)

    assert str(raised.value) == "vector_store_unavailable"
    assert raised.value.dependency_error_type == "UnexpectedResponse"
    assert not isinstance(raised.value, UnexpectedResponse)
    assert str(error) not in "".join(traceback.format_exception(raised.value))


@pytest.mark.parametrize("status_code", [401, 403, 404, 422])
def test_non_transient_runtime_qdrant_response_is_not_mapped(status_code):
    error = unexpected_response(status_code)
    client = FakeQdrantClient(errors={"query_points": error})
    store = QdrantVectorStore(client, collection="closed_tickets", dimensions=3)

    with pytest.raises(UnexpectedResponse) as raised:
        store.search_by_vector([1.0, 0.0, 0.0], limit=1)

    assert raised.value is error


def test_invalid_collection_configuration_closes_acquired_client(monkeypatch):
    client = FakeQdrantClient()
    monkeypatch.setattr("soc.store.vectors.qdrant.QdrantClient", lambda **kwargs: client)
    configured = settings()
    configured = configured.model_copy(
        update={"vector_store": configured.vector_store.model_copy(update={"collection": ""})}
    )

    with pytest.raises(ValueError, match="qdrant_collection_required"):
        create_qdrant_vector_store(configured)

    assert client.calls == ["close"]


def test_collection_schema_mismatch_closes_store_without_becoming_unavailable(monkeypatch):
    client = FakeQdrantClient(collection_exists=True)
    client.get_collection = lambda collection: SimpleNamespace(
        config=SimpleNamespace(params=SimpleNamespace(vectors={"size": 3}))
    )
    monkeypatch.setattr("soc.store.vectors.qdrant.QdrantClient", lambda **kwargs: client)

    with pytest.raises(ValueError, match="qdrant_collection_dimension_mismatch"):
        create_qdrant_vector_store(settings())

    assert client.calls.count("close") == 1


@pytest.mark.parametrize(
    "initialization_error, expected_initialization_type",
    [
        (unexpected_response(503, f"{_SECRET} at {_ADDRESS}"), "VectorStoreUnavailableError"),
        (ValueError(f"invalid setup at {_ADDRESS}; {_SECRET}"), "ValueError"),
    ],
)
def test_cleanup_failure_during_initialization_is_fatal_and_sanitized(
    monkeypatch, caplog, initialization_error, expected_initialization_type
):
    cleanup_error = OSError(f"cleanup failed at {_ADDRESS}; {_SECRET}")
    client = FakeQdrantClient(
        errors={"collection_exists": initialization_error},
        close_error=cleanup_error,
    )
    monkeypatch.setattr("soc.store.vectors.qdrant.QdrantClient", lambda **kwargs: client)

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(VectorStoreInitializationCleanupError) as raised:
            create_qdrant_vector_store(settings())

    assert str(raised.value) == "vector_store_initialization_cleanup_failed"
    assert raised.value.initialization_error_type == expected_initialization_type
    assert raised.value.cleanup_error_type == "OSError"
    assert not isinstance(raised.value, VectorStoreUnavailableError)
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__
    assert client.calls.count("close") == 1
    output = "".join(traceback.format_exception(raised.value)) + caplog.text
    assert str(initialization_error) not in output
    assert str(cleanup_error) not in output
    assert _SECRET not in output
    assert _ADDRESS not in output
