"""contracts/의 JSON Schema로 Python(Pydantic v2) 모델을 만든다.

    uv run python scripts/generate_contracts.py          # generated/를 다시 만든다
    uv run python scripts/generate_contracts.py --check  # 커밋된 코드와 다르면 실패한다

생성 결과는 직접 고치지 않는다. schema를 고친 뒤 이 스크립트를 다시 실행한다.
도구 버전은 uv.lock으로 고정되어 있어 누가 실행해도 같은 결과가 나온다.
TypeScript 생성(json-schema-to-typescript)은 첫 화면 이슈에서 붙인다(데이터 계약, D-003).
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = ROOT / "contracts"
OUTPUT_DIR = ROOT / "src" / "soc" / "contracts" / "generated"
PYPROJECT = ROOT / "pyproject.toml"

HEADER = (
    "# 생성 코드. 직접 고치지 않는다.\n"
    "# contracts/의 JSON Schema를 고치고 scripts/generate_contracts.py를 실행한다."
)

CODEGEN_OPTIONS = [
    "--input-file-type=jsonschema",
    "--output-model-type=pydantic_v2.BaseModel",
    "--target-python-version=3.13",
    "--disable-timestamp",  # 생성 시각이 들어가면 --check가 늘 실패한다
    "--formatters=builtin",  # 정리는 아래에서 프로젝트 ruff로 한다
    "--use-title-as-name",
    "--use-annotated",
    "--use-type-alias",  # ID·숫자를 RootModel 대신 str·int로 쓰게 한다
    "--collapse-root-models",
    "--enum-field-as-literal=all",
    f"--custom-file-header={HEADER}",
]


def run(*args: str) -> None:
    subprocess.run([sys.executable, *args], check=True, cwd=ROOT)


def generate(destination: Path) -> None:
    run(
        "-m",
        "datamodel_code_generator",
        f"--input={SCHEMA_DIR}",
        f"--output={destination}",
        *CODEGEN_OPTIONS,
    )
    # 임시 폴더에는 레포 설정이 적용되지 않으므로 pyproject.toml을 직접 준다.
    # E501은 생성 폴더에서만 끈 규칙이라(D-038), 여기서는 남은 위반을 무시하고
    # 고칠 수 있는 것만 고친다.
    config = f"--config={PYPROJECT}"
    run("-m", "ruff", "check", config, "--fix", "--exit-zero", "--silent", str(destination))
    run("-m", "ruff", "format", config, "--quiet", str(destination))


def snapshot(directory: Path) -> dict[str, bytes]:
    if not directory.is_dir():
        return {}
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in sorted(directory.rglob("*.py"))
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="다시 만들어 차이만 검사한다")
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory() as tmp:
        fresh = Path(tmp) / "generated"
        generate(fresh)

        if args.check:
            expected, actual = snapshot(fresh), snapshot(OUTPUT_DIR)
            changed = sorted(
                name
                for name in expected.keys() | actual.keys()
                if expected.get(name) != actual.get(name)
            )
            if changed:
                print("생성 코드가 contracts/와 다르다. 아래를 실행하고 커밋한다.", file=sys.stderr)
                print("  uv run python scripts/generate_contracts.py", file=sys.stderr)
                for name in changed:
                    print(f"  다른 파일: {name}", file=sys.stderr)
                return 1
            print("생성 코드가 contracts/와 같다.")
            return 0

        shutil.rmtree(OUTPUT_DIR, ignore_errors=True)
        shutil.copytree(fresh, OUTPUT_DIR)
    print(f"생성했다: {OUTPUT_DIR.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
