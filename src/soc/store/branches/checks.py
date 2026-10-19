"""Input checks every branch store applies before reading or writing (box 25)."""

from soc.contracts import BranchResult, validate_contract
from soc.store.records.checks import check_limit

from .base import PATHS, SUBJECT_TYPES

__all__ = ["check_branch", "check_limit", "check_path", "check_subject_type"]


def check_branch(record: BranchResult) -> BranchResult:
    return validate_contract("BranchResult", record.model_dump(mode="json"))


def check_path(path: str) -> None:
    if path not in PATHS:
        raise ValueError(f"path must be one of {', '.join(sorted(PATHS))}")


def check_subject_type(subject_type: str) -> None:
    if subject_type not in SUBJECT_TYPES:
        raise ValueError(f"subject_type must be one of {', '.join(sorted(SUBJECT_TYPES))}")
