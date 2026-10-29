"""One ingest run: SIEM connector (box 3) -> source records (boxes 6, 7), resuming at the cursor.

The batch and the cursor after it are saved together, so a run that fails
stores nothing and the next run fetches the same batch again. Saving is
idempotent, so a batch fetched twice is stored once.
"""

from dataclasses import dataclass

from soc.ingest.connector import SiemIngest

from .records.base import RecordStore


@dataclass(frozen=True)
class IngestRun:
    fetched: int
    inserted: int
    duplicates: int
    skipped: int
    next_cursor: str | None


def ingest_once(ingest: SiemIngest, store: RecordStore, cursor_key: str) -> IngestRun:
    """Fetch one batch after the cursor saved under ``cursor_key`` and store it.

    ``cursor_key`` names the SIEM the cursor belongs to; callers pass ``[siem] adapter``.
    """
    batch = ingest.fetch(store.load_cursor(cursor_key))
    saved = store.save_source_records(batch.items, cursor_key, batch.next_cursor)
    return IngestRun(
        fetched=len(batch.items),
        inserted=saved.inserted,
        duplicates=saved.duplicates,
        skipped=batch.skipped,
        next_cursor=batch.next_cursor,
    )
