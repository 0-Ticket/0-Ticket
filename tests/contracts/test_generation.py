import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def snapshot(path):
    return {p.relative_to(path).as_posix(): p.read_bytes() for p in path.rglob("*") if p.is_file()}


def test_generation_reproducible(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    for dest in (first, second):
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/generate_contracts.py"),
                "--output-root",
                str(dest),
            ],
            cwd=ROOT,
            check=True,
        )
    assert snapshot(first) == snapshot(second)
    for path, content in snapshot(first).items():
        assert (ROOT / path).read_bytes() == content
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/generate_contracts.py"), "--check"],
        cwd=ROOT,
        check=True,
    )

    # Check mode must detect modified, missing AND untracked stale outputs without writing.
    changed = first / "src/soc/contracts/generated/__init__.py"
    changed.write_text(changed.read_text() + "# stale\n")
    missing = first / "frontend/src/contracts/generated/raw_record.ts"
    missing.unlink()
    extra = first / "frontend/src/contracts/generated/stale.ts"
    extra.write_text("// stale\n")
    before = snapshot(first)
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/generate_contracts.py"),
            "--check",
            "--output-root",
            str(first),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    for path in (changed, missing, extra):
        assert str(path.relative_to(first)) in result.stderr
    assert snapshot(first) == before


def test_typescript_types():
    command = ["pnpm", "typecheck"]
    if sys.platform == "win32":
        command[:0] = ["cmd", "/c"]
    subprocess.run(command, cwd=ROOT / "tools/contracts", check=True)


def test_all_fixture_types(tmp_path):
    import json

    from test_schemas import NAMES, fixture, schemas

    titles = {name: schemas()[name + ".schema.json"]["title"] for name in NAMES}
    entry = (ROOT / "frontend/src/contracts/index.js").as_posix()
    lines = [f"import type {{ {', '.join(titles.values())} }} from '{entry}';"]
    for name, title in titles.items():
        value = fixture(name)
        lines.append(f"const fixture_{name} = {json.dumps(value)} satisfies {title};")
        for field in value:
            missing = {key: item for key, item in value.items() if key != field}
            lines.append("// @ts-expect-error every field, including nullable, must be present")
            lines.append(f"const fixture_{name}_{field} = {json.dumps(missing)} satisfies {title};")
    test_file = tmp_path / "fixtures.ts"
    test_file.write_text("\n".join(lines) + "\n")
    subprocess.run(
        [
            "node",
            str(ROOT / "tools/contracts/node_modules/typescript/bin/tsc"),
            "--noEmit",
            "--strict",
            "--target",
            "ES2022",
            "--module",
            "NodeNext",
            "--moduleResolution",
            "NodeNext",
            str(test_file),
        ],
        cwd=ROOT,
        check=True,
    )
