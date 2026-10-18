"""Generate both languages from contracts/; --check never changes tracked files."""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
PY_OUTPUT = Path("src/soc/contracts/generated")
TS_OUTPUT = Path("frontend/src/contracts/generated")
HEADER = "자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py"


def run(*args):
    subprocess.run(args, cwd=ROOT, check=True)


def normalize_line_endings(directory: Path):
    """Make generated source bytes independent of the host operating system."""
    for path in directory.rglob("*"):
        if path.is_file():
            content = path.read_bytes()
            normalized = content.replace(b"\r\n", b"\n")
            if normalized != content:
                path.write_bytes(normalized)


def type_projection(value):
    """Keep field types; conditional validation remains in the authoritative schemas.

    Generators do not faithfully translate object-level if/then/anyOf checks.
    Only our root-level allOf condition list and documentation are omitted.
    Nullable anyOf references and field-level constraints remain intact.
    """
    result = {k: v for k, v in value.items() if k not in {"allOf", "description"}}
    result["properties"] = {
        name: {k: v for k, v in prop.items() if k != "description"}
        for name, prop in result["properties"].items()
    }
    return result


def generate(destination):
    py_dir, ts_dir = destination / PY_OUTPUT, destination / TS_OUTPUT
    py_dir.mkdir(parents=True, exist_ok=True)
    ts_dir.mkdir(parents=True, exist_ok=True)
    source = destination / "schema-input"
    source.mkdir()
    schemas = [
        json.loads(p.read_text()) for p in sorted((ROOT / "contracts").glob("*.schema.json"))
    ]
    for schema in schemas:
        (source / schema["$id"]).write_text(json.dumps(type_projection(schema), indent=2) + "\n")
    run(
        sys.executable,
        "-m",
        "datamodel_code_generator",
        "--input",
        str(source),
        "--input-file-type",
        "jsonschema",
        "--output",
        str(py_dir),
        "--output-model-type",
        "pydantic_v2.BaseModel",
        "--target-python-version",
        "3.12",
        "--disable-timestamp",
        "--use-standard-collections",
        "--collapse-root-models",
        "--use-union-operator",
        "--enum-field-as-literal",
        "all",
        "--use-title-as-name",
        "--strict-types",
        "str",
        "int",
        "float",
        "bool",
        "--formatters",
        "builtin",
        "--custom-file-header",
        "# " + HEADER,
    )
    run("node", str(ROOT / "tools/contracts/generate.mjs"), str(ts_dir), str(source))
    # Public exports are generated from schema titles, never a handwritten model list.
    schemas = [
        json.loads(p.read_text()) for p in sorted((ROOT / "contracts").glob("*.schema.json"))
    ]
    exports = "\n".join(
        f"from .{s['$id'].removesuffix('.schema.json')}_schema import {s['title']}" for s in schemas
    )
    names = ",\n".join("    " + repr(s["title"]) for s in schemas)
    (py_dir / "__init__.py").write_text(f"# {HEADER}\n{exports}\n\n__all__ = [\n{names}\n]\n")
    run(
        sys.executable,
        "-m",
        "ruff",
        "format",
        "--config",
        str(ROOT / "pyproject.toml"),
        str(py_dir),
    )
    run(
        sys.executable,
        "-m",
        "ruff",
        "check",
        "--fix",
        "--config",
        str(ROOT / "pyproject.toml"),
        str(py_dir),
    )
    normalize_line_endings(py_dir)
    normalize_line_endings(ts_dir)
    for path in source.iterdir():
        path.unlink()
    source.rmdir()


def files(folder):
    return {
        p.relative_to(folder): p.read_bytes()
        for p in folder.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=ROOT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    with TemporaryDirectory(prefix="soc-contracts-") as temp:
        stage = Path(temp)
        generate(stage)
        differences = []
        for relative in (PY_OUTPUT, TS_OUTPUT):
            actual, expected = files(args.output_root / relative), files(stage / relative)
            differences.extend(
                str(relative / p)
                for p in actual.keys() | expected.keys()
                if actual.get(p) != expected.get(p)
            )
            if not args.check:
                target = args.output_root / relative
                target.mkdir(parents=True, exist_ok=True)
                for stale in actual.keys() - expected.keys():
                    (target / stale).unlink()
                for path, content in expected.items():
                    (target / path).parent.mkdir(parents=True, exist_ok=True)
                    (target / path).write_bytes(content)
        if args.check and differences:
            parser.exit(1, "Generated contracts differ:\n" + "\n".join(sorted(differences)) + "\n")


if __name__ == "__main__":
    main()
