"""Cut the demo window out of the AIT Log Data Set V2.0 (D-004) for the direct adapter (#79).

The dataset itself is never committed: download it into data/ait/ and cut the
window into data/demo/ (both ignored by git). docs/milestone-l1.md has the
download steps and the window the demo uses.

    uv run python scripts/demo_slice_ait.py summary --eve <eve.json> [--window S/E]
    uv run python scripts/demo_slice_ait.py slice --eve <eve.json> --apache <access.log> \
        --window S/E [--window S/E ...] --out data/demo

``slice`` keeps Suricata lines whose event_type is "alert" and Apache lines whose
time falls in any window (start included, end excluded), copied byte for byte.
The Suricata output is always ``suricata_alert.jsonl``; Apache files keep their
names. ``summary`` lists, per signature_id, how many alerts there are and how
many box 25 would fold as duplicates (same rule and entities within the dedup
window from the first alert), to help pick the window.

Log lines may hold attacker-made text, so the output carries only IDs, counts
and times, never a signature name, URL or user agent (docs/security-policy.md 3).
"""

import argparse
import json
import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

Window = tuple[int, int]

EVE_OUTPUT = "suricata_alert.jsonl"
# Same layout as the default ait_apache_access alias table: the first [...] is the time.
APACHE_TIME = re.compile(rb"\[([^\]]{1,64})\]")
APACHE_TIME_FORMAT = "%d/%b/%Y:%H:%M:%S %z"


@dataclass
class SliceCount:
    kept: int = 0
    dropped: int = 0
    bad: int = 0


@dataclass(frozen=True)
class SignatureSummary:
    signature_id: str
    alerts: int
    representatives: int
    duplicates: int
    first_at: int
    last_at: int


def _ms(moment: datetime) -> int:
    if moment.tzinfo is None:
        raise ValueError("time needs a time zone")
    return int(moment.timestamp() * 1000)


def parse_window(text: str) -> Window:
    """``START/END`` in ISO 8601 with a time zone -> epoch ms, start before end."""
    parts = text.split("/")
    if len(parts) != 2:
        raise ValueError("window must be START/END")
    start, end = (_ms(datetime.fromisoformat(part)) for part in parts)
    if start >= end:
        raise ValueError("window start must be before its end")
    return start, end


def in_windows(at: int, windows: Sequence[Window]) -> bool:
    return any(start <= at < end for start, end in windows)


def _eve_alert(line: bytes) -> dict | None:
    """The parsed line if it is a Suricata alert, else None. Raises ValueError if unreadable."""
    try:
        record = json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("not JSON") from error
    if not isinstance(record, dict):
        raise ValueError("not a JSON object")
    if record.get("event_type") != "alert":
        return None
    return record


def _eve_time(record: dict) -> int:
    return _ms(datetime.fromisoformat(str(record["timestamp"])))


def _lines(path: Path):
    with path.open("rb") as handle:
        for raw in handle:
            line = raw.rstrip(b"\r\n")
            if line.strip():
                yield line


def slice_eve(source: Path, target: Path, windows: Sequence[Window]) -> SliceCount:
    count = SliceCount()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as out:
        for line in _lines(source):
            # Cheap check first: most of eve.json is flow, dns and http records.
            if b'"alert"' not in line:
                count.dropped += 1
                continue
            try:
                record = _eve_alert(line)
                keep = record is not None and in_windows(_eve_time(record), windows)
            except (ValueError, KeyError):
                count.bad += 1
                continue
            if keep:
                out.write(line + b"\n")
                count.kept += 1
            else:
                count.dropped += 1
    return count


def slice_apache(source: Path, target: Path, windows: Sequence[Window]) -> SliceCount:
    count = SliceCount()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as out:
        for line in _lines(source):
            match = APACHE_TIME.search(line)
            try:
                if match is None:
                    raise ValueError("no time")
                at = _ms(datetime.strptime(match.group(1).decode("ascii"), APACHE_TIME_FORMAT))
            except (ValueError, UnicodeDecodeError):
                count.bad += 1
                continue
            if in_windows(at, windows):
                out.write(line + b"\n")
                count.kept += 1
            else:
                count.dropped += 1
    return count


def summarize(
    source: Path, windows: Sequence[Window], dedup_minutes: int
) -> list[SignatureSummary]:
    """Per signature_id: alerts, and how box 25 would fold them (fixed window from the first)."""
    alerts: dict[str, list[tuple[int, frozenset[str]]]] = defaultdict(list)
    for line in _lines(source):
        if b'"alert"' not in line:
            continue
        try:
            record = _eve_alert(line)
            if record is None:
                continue
            at = _eve_time(record)
            signature_id = str(record["alert"]["signature_id"])
        except (ValueError, KeyError, TypeError):
            continue
        if windows and not in_windows(at, windows):
            continue
        entities = frozenset(
            str(value) for value in (record.get("src_ip"), record.get("dest_ip")) if value
        )
        alerts[signature_id].append((at, entities))

    span = dedup_minutes * 60 * 1000
    rows = []
    for signature_id, items in alerts.items():
        items.sort(key=lambda item: item[0])
        window_start: dict[frozenset[str], int] = {}
        representatives = 0
        for at, entities in items:
            first = window_start.get(entities)
            if first is None or at - first >= span:
                window_start[entities] = at
                representatives += 1
        rows.append(
            SignatureSummary(
                signature_id,
                len(items),
                representatives,
                len(items) - representatives,
                items[0][0],
                items[-1][0],
            )
        )
    return sorted(rows, key=lambda row: (row.first_at, row.signature_id))


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000).astimezone().isoformat(timespec="seconds")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="demo_slice_ait.py", description="Cut the AIT demo window for the direct adapter."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    summary = commands.add_parser("summary", help="count alerts and duplicates per signature_id")
    summary.add_argument("--eve", type=Path, required=True)
    summary.add_argument("--window", action="append", default=[], type=parse_window)
    summary.add_argument("--dedup-minutes", type=int, default=10)

    cut = commands.add_parser("slice", help="write the window to the output folder")
    cut.add_argument("--eve", type=Path)
    cut.add_argument("--apache", type=Path, action="append", default=[])
    cut.add_argument("--window", action="append", required=True, type=parse_window)
    cut.add_argument("--out", type=Path, required=True)

    args = parser.parse_args(argv)
    if args.command == "summary":
        print("signature_id\talerts\tafter_dedup\tduplicates\tfirst\tlast")
        for row in summarize(args.eve, args.window, args.dedup_minutes):
            print(
                f"{row.signature_id}\t{row.alerts}\t{row.representatives}\t{row.duplicates}"
                f"\t{_iso(row.first_at)}\t{_iso(row.last_at)}"
            )
        return 0

    outputs = []
    if args.eve:
        outputs.append((args.eve, args.out / EVE_OUTPUT, slice_eve))
    outputs += [(path, args.out / path.name, slice_apache) for path in args.apache]
    names = [target.name for _, target, _ in outputs]
    if len(names) != len(set(names)):
        parser.error("output file names must be unique (the direct adapter keys on them)")
    for source, target, cut_file in outputs:
        count = cut_file(source, target, args.window)
        print(f"{target}: kept {count.kept}, dropped {count.dropped}, unreadable {count.bad}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
