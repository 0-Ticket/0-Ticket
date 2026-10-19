"""#79: the script that cuts the demo window out of the AIT dataset (scripts/demo_slice_ait.py).

The fixtures are hand-made in the AIT formats; the dataset itself is never read here.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "demo"


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "demo_slice_ait", ROOT / "scripts" / "demo_slice_ait.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


slicer = _load_script()

WINDOW = "2022-01-18T10:00:00+00:00/2022-01-18T10:30:00+00:00"


def test_window_is_start_inclusive_end_exclusive():
    start, end = slicer.parse_window(WINDOW)
    assert end - start == 30 * 60 * 1000
    assert slicer.in_windows(start, [(start, end)])
    assert not slicer.in_windows(end, [(start, end)])


@pytest.mark.parametrize(
    "text",
    [
        "2022-01-18T10:00:00+00:00",  # no end
        "2022-01-18T10:00:00/2022-01-18T10:30:00",  # no time zone
        "2022-01-18T10:30:00+00:00/2022-01-18T10:00:00+00:00",  # end before start
    ],
)
def test_bad_window_is_rejected(text):
    with pytest.raises(ValueError):
        slicer.parse_window(text)


def test_slice_keeps_only_alert_lines_in_window(tmp_path):
    out = tmp_path / "suricata_alert.jsonl"
    count = slicer.slice_eve(FIXTURES / "eve_mixed.jsonl", out, [slicer.parse_window(WINDOW)])
    lines = out.read_text(encoding="utf-8").splitlines()
    kept = [json.loads(line) for line in lines]
    assert [line["timestamp"][11:19] for line in kept] == ["10:00:00", "10:04:00", "10:20:00"]
    assert all(line["event_type"] == "alert" for line in kept)
    assert (count.kept, count.bad) == (3, 1)
    # Lines are copied byte for byte, not re-serialized.
    source = (FIXTURES / "eve_mixed.jsonl").read_text(encoding="utf-8").splitlines()
    assert set(lines) <= set(source)


def test_slice_apache_keeps_lines_in_window(tmp_path):
    out = tmp_path / "access.log"
    count = slicer.slice_apache(FIXTURES / "apache_access.log", out, [slicer.parse_window(WINDOW)])
    times = [line.split("[")[1][12:20] for line in out.read_text(encoding="utf-8").splitlines()]
    assert times == ["10:00:00", "10:29:59"]
    assert (count.kept, count.bad) == (2, 1)


def test_several_windows_are_joined(tmp_path):
    windows = [
        slicer.parse_window("2022-01-18T10:00:00+00:00/2022-01-18T10:01:00+00:00"),
        slicer.parse_window("2022-01-18T10:30:00+00:00/2022-01-18T10:31:00+00:00"),
    ]
    out = tmp_path / "suricata_alert.jsonl"
    assert slicer.slice_eve(FIXTURES / "eve_mixed.jsonl", out, windows).kept == 2


def test_summary_groups_repeats_like_box25_dedup():
    rows = slicer.summarize(FIXTURES / "eve_mixed.jsonl", [], dedup_minutes=10)
    by_id = {row.signature_id: row for row in rows}
    # 09:59:59.999, 10:00, 10:04 fall in one 10-minute window from the first alert; 10:20 starts
    # a new one. So 4 alerts become 2 representatives and 2 duplicates.
    wpscan = by_id["2008983"]
    assert (wpscan.alerts, wpscan.representatives, wpscan.duplicates) == (4, 2, 2)
    assert by_id["2009999"].duplicates == 0


def test_summary_prints_ids_and_counts_only(capsys):
    assert slicer.main(["summary", "--eve", str(FIXTURES / "eve_mixed.jsonl")]) == 0
    out = capsys.readouterr().out
    assert "2008983" in out
    # Signature text, URLs and user agents never reach the output.
    for text in ("WPScan", "webshell", "ET SCAN", "Mozilla"):
        assert text not in out


def test_slice_command_writes_the_configured_file_names(tmp_path, capsys):
    code = slicer.main(
        [
            "slice",
            "--eve",
            str(FIXTURES / "eve_mixed.jsonl"),
            "--apache",
            str(FIXTURES / "apache_access.log"),
            "--window",
            WINDOW,
            "--out",
            str(tmp_path),
        ]
    )
    assert code == 0
    assert (tmp_path / "suricata_alert.jsonl").is_file()
    assert (tmp_path / "apache_access.log").is_file()
    assert "Mozilla" not in capsys.readouterr().out
