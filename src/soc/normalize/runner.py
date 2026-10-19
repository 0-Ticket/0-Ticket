"""Normalization run (box 4): stored source records -> C5 / C13 / C12, in arrival order.

Each run reads one page of ``kind`` after the saved position, normalizes it,
joins lookups, and saves results, failures and the new position together. A
run that fails saves nothing, and the next run reads the same page again. A
source record is never normalized twice: the position only moves forward and
the store accepts one outcome per source.
"""

from collections.abc import Callable
from dataclasses import dataclass

from soc.contracts import (
    AlertRecord,
    EventRecord,
    NormalizedAlert,
    NormalizeFailure,
    validate_contract,
)
from soc.store.records.base import RecordStore, SourceFailure, SourceKind

from .ids import alert_id_for, event_id_for
from .lookup.enricher import LookupEnricher
from .normalizer import Normalizer

__all__ = ["NormalizeRun", "alert_id_for", "event_id_for", "normalize_once", "normalize_pending"]

KINDS: tuple[SourceKind, ...] = ("alert", "event")


@dataclass(frozen=True)
class NormalizeRun:
    kind: SourceKind
    read: int
    normalized: int
    failed: int
    last_seq: int | None


def normalize_once(
    store: RecordStore,
    normalizer: Normalizer,
    enricher: LookupEnricher,
    kind: SourceKind,
    batch_size: int,
    clock: Callable[[], int],
) -> NormalizeRun:
    """Normalize the next ``batch_size`` sources of ``kind``; save them with the new position."""
    position = store.load_normalize_position(kind)
    sources = store.list_source_records(kind, position, batch_size)
    if not sources:
        return NormalizeRun(kind, 0, 0, 0, position)
    now = clock()
    records: list[AlertRecord | EventRecord] = []
    failures: list[SourceFailure] = []
    for stored in sources:
        source = stored.record
        result = normalizer.normalize(source, now)
        if isinstance(result, NormalizeFailure):
            failures.append(SourceFailure(source.source_record_id, result))
        elif isinstance(result, NormalizedAlert):
            records.append(_alert_record(result, source.source_record_id, enricher))
        else:
            records.append(_event_record(result, enricher))
    last_seq = sources[-1].seq
    store.save_normalize_batch(kind, records, failures, last_seq)
    return NormalizeRun(kind, len(sources), len(records), len(failures), last_seq)


def normalize_pending(
    store: RecordStore,
    normalizer: Normalizer,
    enricher: LookupEnricher,
    batch_size: int,
    clock: Callable[[], int],
) -> list[NormalizeRun]:
    """Run each kind until nothing is left. The last run of each kind reads 0."""
    runs = []
    for kind in KINDS:
        while True:
            run = normalize_once(store, normalizer, enricher, kind, batch_size, clock)
            runs.append(run)
            if run.read == 0:
                break
    return runs


def _alert_record(
    alert: NormalizedAlert, source_record_id: str, enricher: LookupEnricher
) -> AlertRecord:
    found = enricher.enrich(alert.src_ip, alert.dst_ip, alert.user, alert.time)
    return validate_contract(
        "AlertRecord",
        {
            "alert_id": alert_id_for(source_record_id),
            "source_record_id": source_record_id,
            **alert.model_dump(mode="json"),
            "src_asset": _dump(found.src_asset),
            "dst_asset": _dump(found.dst_asset),
            "user_info": _dump(found.user_info),
            "count": 1,
            "first_seen": alert.time,
            "last_seen": alert.time,
        },
    )


def _event_record(event: EventRecord, enricher: LookupEnricher) -> EventRecord:
    found = enricher.enrich(event.src_ip, event.dst_ip, event.user, event.time)
    return validate_contract(
        "EventRecord",
        {
            **event.model_dump(mode="json"),
            "src_asset": _dump(found.src_asset),
            "dst_asset": _dump(found.dst_asset),
            "user_info": _dump(found.user_info),
        },
    )


def _dump(model):
    return None if model is None else model.model_dump(mode="json")
