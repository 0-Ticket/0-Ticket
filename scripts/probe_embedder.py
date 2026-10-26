"""#114 (C-08a): embedding smoke probe for the configured box 8 embedder.

Not box 8 search. It opens the embedder named by ``[embedder].provider`` through
the ``embedders`` registry (by default the local Ollama bge-m3, D-010), embeds a
few fixed synthetic sentences and reports per sentence:

- ``outcome``: ``ok`` or a safe code (``embedder_unavailable``,
  ``embedder_invalid_response``, ``embedding_dimension_mismatch``,
  ``unexpected_error``)
- ``length``, ``finite``, ``norm`` (L2, rounded) and ``latency_ms`` when ok

Nothing is written to a vector store and no collection is touched. The report
holds no vector values, no ``base_url`` and no error text from the provider:
the address is organization setting (docs/security-policy.md 1).

    ZT_CONFIG=config/local.toml uv run python scripts/probe_embedder.py

Exit code: 0 every sentence ok, 1 some sentence failed, 2 setup error (no request sent).
"""

import argparse
import json
import math
import os
import sys
import time
from collections.abc import Mapping, Sequence

from soc.config import ConfigError, Settings, load_config
from soc.plugins import PluginNotFoundError, PluginRegistry
from soc.store.embedders import EMBEDDERS, open_embedder
from soc.store.embedders.ollama import EmbeddingError

REPORT_VERSION = 1
# Synthetic sentences only (documentation IP range, example.com). No log content.
SAMPLES = (
    ("ticket_en", "Web scan from 192.0.2.10 against www.example.com rule 31151 closed as noise"),
    ("ticket_ko", "192.0.2.20에서 www.example.com 로그인 페이지로 반복 요청, L1 보류"),
    ("entities", "src_ip 198.51.100.7 dst_host www.example.com user alice"),
)


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Embedding smoke probe (#114).")
    parser.add_argument(
        "--config", help="organization settings file (default: the file named by ZT_CONFIG)"
    )
    return parser.parse_args(argv)


def probe_sample(embedder, text: str, dimensions: int) -> dict:
    started = time.perf_counter()
    try:
        vector = embedder.embed(text)
    except EmbeddingError as error:
        return {"outcome": str(error)}
    except Exception:  # noqa: BLE001 - any provider failure becomes one safe code
        return {"outcome": "unexpected_error"}
    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    if not isinstance(vector, list) or len(vector) != dimensions:
        return {"outcome": "embedding_dimension_mismatch"}
    finite = all(
        isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)
        for value in vector
    )
    return {
        "outcome": "ok",
        "length": len(vector),
        "finite": finite,
        "norm": round(math.sqrt(sum(value * value for value in vector)), 4) if finite else None,
        "latency_ms": latency_ms,
    }


def run(settings: Settings, registry: PluginRegistry) -> dict:
    embedder = open_embedder(settings, registry)
    dimensions = settings.embedder.dimensions
    samples = [{"name": name, **probe_sample(embedder, text, dimensions)} for name, text in SAMPLES]
    return {
        "report_version": REPORT_VERSION,
        "provider": settings.embedder.provider,
        "model": settings.embedder.model,
        "dimensions": dimensions,
        "ok": all(sample["outcome"] == "ok" and sample["finite"] for sample in samples),
        "samples": samples,
    }


def main(
    argv: Sequence[str] | None = None,
    environ: Mapping[str, str] | None = None,
    registry: PluginRegistry | None = None,
) -> int:
    args = parse_args(argv)
    environ = os.environ if environ is None else environ
    try:
        settings = load_config(args.config, environ)
    except ConfigError:
        # The message may name the file or a rejected value; keep it out of the output.
        print("Settings could not be loaded (check ZT_CONFIG or --config)", file=sys.stderr)
        return 2
    try:
        report = run(settings, EMBEDDERS if registry is None else registry)
    except PluginNotFoundError:
        print("No embedder is registered under [embedder].provider", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, ensure_ascii=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
