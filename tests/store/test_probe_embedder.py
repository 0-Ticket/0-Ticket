"""#114 (C-08a): the embedding smoke probe (scripts/probe_embedder.py).

Only fake embedders and a fake Ollama answer are reached here. The probe report
must hold sizes and safe codes only: no vector values and no ``base_url``.
"""

import importlib.util
import json
import sys
from io import BytesIO
from pathlib import Path
from urllib.error import URLError

import pytest

from soc.plugins import PluginRegistry
from soc.store.embedders.ollama import EmbeddingError, create_ollama_embedder

ROOT = Path(__file__).resolve().parents[2]
SECRET_HOST = "embed-secret.example.com"
# A value that would show up in the output if a vector were printed.
MARKER = 0.123456789


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "probe_embedder", ROOT / "scripts" / "probe_embedder.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


probe = _load_script()


class FakeEmbedder:
    def __init__(self, vector=None, error=None):
        self._vector = vector
        self._error = error
        self.texts = []

    def embed(self, text):
        self.texts.append(text)
        if self._error is not None:
            raise self._error
        return list(self._vector)


def _registry(embedder):
    registry = PluginRegistry("embedders")
    registry.register("fake", lambda _settings: embedder)
    return registry


def _org_config(tmp_path, provider="fake", dimensions=4):
    path = tmp_path / "local.toml"
    path.write_text(
        "[embedder]\n"
        f'provider = "{provider}"\n'
        f'base_url = "http://{SECRET_HOST}:11434"\n'
        f"dimensions = {dimensions}\n",
        encoding="utf-8",
    )
    return path


def _run(tmp_path, capsys, registry, **config):
    code = probe.main(
        ["--config", str(_org_config(tmp_path, **config))], environ={}, registry=registry
    )
    out, err = capsys.readouterr()
    return code, out, err


def test_success_reports_sizes_and_never_vector_values(tmp_path, capsys):
    embedder = FakeEmbedder(vector=[MARKER] * 4)

    code, out, err = _run(tmp_path, capsys, _registry(embedder))

    assert code == 0
    report = json.loads(out)
    assert report["ok"] is True
    assert report["provider"] == "fake"
    assert report["dimensions"] == 4
    assert len(embedder.texts) == len(probe.SAMPLES)
    for sample in report["samples"]:
        assert sample["outcome"] == "ok"
        assert sample["length"] == 4
        assert sample["finite"] is True
        assert sample["norm"] == pytest.approx(MARKER * 2, abs=1e-4)
        assert sample["latency_ms"] >= 0
    assert str(MARKER) not in out + err
    assert "embeddings" not in out


def test_embedding_error_is_reported_as_its_safe_code_with_exit_1(tmp_path, capsys):
    embedder = FakeEmbedder(error=EmbeddingError("embedder_unavailable"))

    code, out, _ = _run(tmp_path, capsys, _registry(embedder))

    assert code == 1
    report = json.loads(out)
    assert report["ok"] is False
    assert {sample["outcome"] for sample in report["samples"]} == {"embedder_unavailable"}
    assert all("length" not in sample for sample in report["samples"])


def test_wrong_dimension_from_any_provider_is_a_mismatch(tmp_path, capsys):
    embedder = FakeEmbedder(vector=[MARKER] * 3)

    code, out, _ = _run(tmp_path, capsys, _registry(embedder))

    assert code == 1
    outcomes = {sample["outcome"] for sample in json.loads(out)["samples"]}
    assert outcomes == {"embedding_dimension_mismatch"}


def test_unexpected_provider_error_text_is_not_printed(tmp_path, capsys):
    embedder = FakeEmbedder(error=RuntimeError(f"cannot reach {SECRET_HOST}"))

    code, out, err = _run(tmp_path, capsys, _registry(embedder))

    assert code == 1
    outcomes = {sample["outcome"] for sample in json.loads(out)["samples"]}
    assert outcomes == {"unexpected_error"}
    assert SECRET_HOST not in out + err


def test_base_url_never_reaches_output_from_the_real_ollama_embedder(tmp_path, capsys, monkeypatch):
    def unreachable(*_args, **_kwargs):
        raise URLError(f"connection refused by {SECRET_HOST}")

    monkeypatch.setattr("soc.store.embedders.ollama.urlopen", unreachable)
    registry = PluginRegistry("embedders")
    registry.register("ollama", create_ollama_embedder)

    code, out, err = _run(tmp_path, capsys, registry, provider="ollama")

    assert code == 1
    assert SECRET_HOST not in out + err
    outcomes = {sample["outcome"] for sample in json.loads(out)["samples"]}
    assert outcomes == {"embedder_unavailable"}


def test_real_ollama_embedder_answer_is_checked_without_printing_it(tmp_path, capsys, monkeypatch):
    class FakeResponse(BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_):
            self.close()

    body = json.dumps({"embeddings": [[MARKER] * 4]}).encode()
    monkeypatch.setattr("soc.store.embedders.ollama.urlopen", lambda *_a, **_k: FakeResponse(body))
    registry = PluginRegistry("embedders")
    registry.register("ollama", create_ollama_embedder)

    code, out, err = _run(tmp_path, capsys, registry, provider="ollama")

    assert code == 0
    assert str(MARKER) not in out + err
    assert SECRET_HOST not in out + err


def test_unknown_provider_is_a_setup_error_with_no_request(tmp_path, capsys):
    code, out, err = _run(tmp_path, capsys, PluginRegistry("embedders"))

    assert code == 2
    assert out == ""
    assert SECRET_HOST not in err


def test_missing_settings_file_is_a_setup_error(tmp_path, capsys):
    missing = tmp_path / SECRET_HOST / "local.toml"

    code = probe.main(["--config", str(missing)], environ={}, registry=PluginRegistry("embedders"))
    out, err = capsys.readouterr()

    assert code == 2
    assert out == ""
    assert SECRET_HOST not in err
