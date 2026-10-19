"""Run L1 Alert entity lookup (box 11)."""

import argparse

from soc.config import load_config
from soc.l1.runtime import build_runtime


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run L1 entity lookup for branched Alerts")
    parser.add_argument(
        "--all",
        action="store_true",
        help="process every pending C21 l1_entity_lookup Alert",
    )
    args = parser.parse_args(argv)
    runtime = build_runtime(load_config())
    try:
        processed = runtime.run(all_alerts=args.all)
        print(f"Processed {processed} L1 Alert(s)")
    finally:
        runtime.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
