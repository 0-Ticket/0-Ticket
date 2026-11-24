"""손제작 같은 사건 쌍이 실제 bge-m3 하한에서 빠지지 않는지 확인한다."""

import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from soc.l2.branch.embed import embedding_text
from soc.l2.config import load_config as load_l2_config
from soc.l2.config import read_settings as read_l2_settings
from soc.store import BgeM3Embedder
from soc.store.config import load_config
from soc.store.config import read_settings as read_store_settings

FIXTURE = Path(__file__).parent / "fixtures" / "l2" / "vector_cases.json"


@pytest.mark.embedder
def test_all_same_attack_pairs_retain_candidate() -> None:
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]
    store_settings = read_store_settings(load_config()["store"])
    threshold = read_l2_settings(load_l2_config()["l2"]).min_score
    embedder = BgeM3Embedder(store_settings.embedder)
    vectors = [embedder.embed(embedding_text(SimpleNamespace(**case, hunt=None))) for case in cases]
    for i, first in enumerate(cases):
        for j, second in enumerate(cases[i + 1 :], i + 1):
            if first["same_attack"] and second["same_attack"]:
                score = math.fsum(a * b for a, b in zip(vectors[i], vectors[j], strict=True))
                assert score >= threshold, (first["name"], second["name"], score)
