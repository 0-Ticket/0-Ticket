import pytest

from soc.store.vectors.fusion import (
    FUSION_FUNCTIONS,
    VectorSearchHit,
    fuse_dbsf,
    fuse_keyword_first,
    fuse_rrf,
    fuse_weighted_rrf,
    fuse_weighted_score,
)


def test_all_fusion_methods_are_available_by_name():
    assert set(FUSION_FUNCTIONS) == {
        "keyword_first",
        "rrf",
        "weighted_rrf",
        "dbsf",
        "weighted_score",
    }


@pytest.mark.parametrize(
    "fusion",
    [fuse_keyword_first, fuse_rrf, fuse_weighted_rrf, fuse_dbsf, fuse_weighted_score],
)
def test_fusion_methods_deduplicate_results_and_apply_top_k(fusion):
    keyword_hits = [
        VectorSearchHit("tk_a", 2.0, ("203.0.113.10", "web-01")),
        VectorSearchHit("tk_b", 1.0, ("203.0.113.10",)),
        VectorSearchHit("tk_a", 1.0, ("203.0.113.10",)),
    ]
    vector_hits = [
        VectorSearchHit("tk_b", 0.91),
        VectorSearchHit("tk_c", 0.72),
    ]

    result = fusion(keyword_hits, vector_hits, k=2)

    assert len(result) == 2
    assert len({ticket_id for ticket_id, _ in result}) == 2
    assert all(isinstance(score, float) for _, score in result)


def test_keyword_first_puts_exact_matches_before_vector_only_results():
    keyword_hits = [VectorSearchHit("tk_exact", 1.0, ("203.0.113.10",))]
    vector_hits = [VectorSearchHit("tk_semantic", 0.99)]

    assert [ticket_id for ticket_id, _ in fuse_keyword_first(keyword_hits, vector_hits, k=2)] == [
        "tk_exact",
        "tk_semantic",
    ]


def test_rrf_promotes_a_ticket_ranked_by_both_sources():
    keyword_hits = [VectorSearchHit("tk_shared", 1.0), VectorSearchHit("tk_keyword", 1.0)]
    vector_hits = [VectorSearchHit("tk_shared", 0.4), VectorSearchHit("tk_vector", 0.9)]

    result = fuse_rrf(keyword_hits, vector_hits, k=1)

    assert result[0][0] == "tk_shared"
    assert result[0][1] == pytest.approx(2 / 60)


def test_weighted_rrf_can_prioritize_keyword_rank():
    keyword_hits = [VectorSearchHit("tk_exact", 1.0)]
    vector_hits = [VectorSearchHit("tk_semantic", 1.0)]

    result = fuse_weighted_rrf(
        keyword_hits,
        vector_hits,
        k=1,
        keyword_weight=2.0,
        vector_weight=1.0,
    )

    assert result[0][0] == "tk_exact"


def test_dbsf_and_weighted_score_use_candidate_scores():
    keyword_hits = [VectorSearchHit("tk_a", 5.0), VectorSearchHit("tk_b", 1.0)]
    vector_hits = [VectorSearchHit("tk_b", 0.99), VectorSearchHit("tk_a", 0.1)]

    dbsf = fuse_dbsf(keyword_hits, vector_hits, k=2)
    weighted = fuse_weighted_score(
        keyword_hits,
        vector_hits,
        k=2,
        keyword_weight=3.0,
        vector_weight=1.0,
    )

    assert dbsf[0][0] in {"tk_a", "tk_b"}
    assert weighted[0][0] == "tk_a"


def test_empty_and_single_result_lists_are_supported():
    assert fuse_rrf([], [], k=3) == []
    assert fuse_dbsf([VectorSearchHit("tk_only", 1.0)], [], k=3) == [("tk_only", 0.5)]
