"""Input checks every L1 decision store applies before reading or writing (boxes 11, 27)."""

from soc.contracts import L1DecisionRecord, validate_contract
from soc.store.paging import check_filter, check_page_limit, decode_cursor

from .base import DECISIONS, REASONS, SUBJECT_TYPES


def check_decision(record: L1DecisionRecord) -> L1DecisionRecord:
    return validate_contract("L1DecisionRecord", record.model_dump(mode="json"))


def check_list_args(
    subject_type: str | None, decision: str | None, reason: str | None, limit: int
) -> None:
    check_filter("subject_type", subject_type, SUBJECT_TYPES)
    check_filter("decision", decision, DECISIONS)
    check_filter("reason", reason, REASONS)
    check_page_limit(limit)


def check_subject_type(subject_type: str) -> None:
    check_filter("subject_type", subject_type, SUBJECT_TYPES)


def decode_decision_cursor(cursor: str | None) -> tuple[int, int] | None:
    """The (created_at, seq) after which the next page starts."""
    return None if cursor is None else decode_cursor(cursor, (int, int))
