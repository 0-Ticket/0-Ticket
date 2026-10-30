"""IDs boxes 10-13 take from the alert, so running branching again names the same things.

A scenario Ticket ID has the shape of a random one (``tk_`` + 32 hex), so C6
checks and the Ticket store treat it the same way.
"""

import hashlib


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def branch_id_for(subject_type: str, subject_id: str) -> str:
    return "br_" + _digest(f"branch:{subject_type}:{subject_id}")


def scenario_ticket_id_for(alert_id: str) -> str:
    return "tk_" + _digest(f"scenario_ticket:{alert_id}")
