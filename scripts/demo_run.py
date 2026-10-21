"""Demo runner (#81): run the AIT demo on a new database, or show a database already run.

Usage (from the repo root, with `docker compose up -d` and `.env` filled):

    uv run python scripts/demo_run.py check
    uv run python scripts/demo_run.py full --db zt_demo81
    uv run python scripts/demo_run.py full --db zt_demo81b --from-template zt_demo81_branched
    uv run python scripts/demo_run.py show --db zt_demo81

- ``check`` only checks what ``full`` needs: PostgreSQL, Qdrant, the LLM and
  embedding models the settings name, the replay files and the Lookup CSVs. It
  lists everything that is missing and exits with 1.
- ``full`` runs ``check``, creates the database, then runs the same commands as
  docs/milestone-l1.md "실행 순서" one by one: migrate, lookup load, ingest,
  normalize, branch, l1. After branch it compares the C21 paths with
  ``expected.csv`` and ``expected_counts.csv`` and keeps a copy of the branched
  database as ``<db>_branched``, so l1 can be run again later from it with
  ``--from-template``. It prints the time each step took.
- ``show`` starts the result API and the screen on a database ``full`` made.
  The presentation uses this mode: l1 takes over an hour on a laptop.

The database names come from ``--db``; the server and accounts come from
DATABASE_URL and DATABASE_READONLY_URL, of which only the database name changes.
Output holds counts, IDs and enum values only: never a log value, a URL or a
password (docs/security-policy.md 1, 3).
"""

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import unquote, urlsplit, urlunsplit
from urllib.request import Request, urlopen

import psycopg
from psycopg import sql

from soc.config import Settings, load_config
from soc.db import connect
from soc.db.connection import DatabaseConnectionError

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "config" / "demo"
URL_ENV = "DATABASE_URL"
READONLY_URL_ENV = "DATABASE_READONLY_URL"
TEMPLATE_SUFFIX = "_branched"
NO_VALUE = "-"
DEDUPLICATED = "deduplicated"
# PostgreSQL identifiers the runner creates: lower case, at most 63 bytes.
NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
HTTP_TIMEOUT_SECONDS = 5


class RunnerError(RuntimeError):
    """A step could not run. The message never holds a URL or a password."""


# --- database URLs and admin connections ------------------------------------------


def check_name(name: str) -> str:
    if not NAME.match(name):
        raise RunnerError(f"database name must match {NAME.pattern}: {name!r}")
    return name


def database_url(url: str, name: str) -> str:
    """``url`` with its database name replaced; host, account and options stay."""
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{check_name(name)}"))


def url_user(url: str) -> str | None:
    try:
        user = urlsplit(url).username
    except ValueError:
        return None
    return unquote(user) if user else None


def admin_connection(url: str) -> psycopg.Connection:
    """An autocommit connection with the database account (redacted errors, #83)."""
    return connect(load_config(environ={}), {URL_ENV: url})


def database_exists(url: str, name: str) -> bool:
    with admin_connection(url) as conn:
        row = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone()
    return row is not None


def create_database(url: str, name: str, template: str | None = None) -> None:
    """CREATE DATABASE, refusing a name that exists: the runner never drops one."""
    check_name(name)
    if database_exists(url, name):
        raise RunnerError(f"database {name} already exists; choose a new --db name")
    statement = sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name))
    if template is not None:
        if not database_exists(url, check_name(template)):
            raise RunnerError(f"template database {template} does not exist")
        statement = sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
            sql.Identifier(name), sql.Identifier(template)
        )
    with admin_connection(url) as conn:
        conn.execute(statement)


def grant_readonly(url: str, readonly_url: str | None, name: str) -> str:
    """Let the read-only account read every table of the new database.

    Skipped when there is no separate read-only account (the same user in both URLs).
    Returns what was done, without the account's password.
    """
    readonly_user = url_user(readonly_url) if readonly_url else None
    if readonly_user is None or readonly_user == url_user(url):
        return "read-only account: same as the database account, grant skipped"
    with admin_connection(database_url(url, name)) as conn:
        conn.execute(
            sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA public TO {}").format(
                sql.Identifier(readonly_user)
            )
        )
    return f"read-only account: granted SELECT on all tables to {readonly_user}"


# --- results and the expected tables ----------------------------------------------

RESULTS_QUERY = """
SELECT a.alert_id,
       a.record::jsonb -> 'raw_ids' ->> 0,
       a.record::jsonb ->> 'rule_id',
       (a.record::jsonb ->> 'count')::int,
       b.path,
       (SELECT d.decision FROM l1_decisions d
         WHERE d.subject_type = 'alert' AND d.subject_id = a.alert_id
         ORDER BY d.created_at DESC, d.seq DESC LIMIT 1),
       t.ticket_id,
       (SELECT d.decision FROM l1_decisions d
         WHERE d.subject_type = 'ticket' AND d.subject_id = t.ticket_id
         ORDER BY d.created_at DESC, d.seq DESC LIMIT 1)
  FROM alert_records a
  LEFT JOIN branch_results b ON b.subject_type = 'alert' AND b.subject_id = a.alert_id
  LEFT JOIN LATERAL (
       SELECT ticket_id FROM tickets WHERE payload -> 'alert_ids' ? a.alert_id
        ORDER BY ticket_id LIMIT 1) t ON true
"""


@dataclass(frozen=True)
class AlertResult:
    """Where one stored alert went: its C21 path, C23 decision and its Ticket's."""

    alert_id: str
    raw_id: str
    rule_id: str | None
    count: int
    path: str | None
    alert_decision: str | None
    ticket_id: str | None
    ticket_decision: str | None


def collect_results(conn: psycopg.Connection) -> dict[str, AlertResult]:
    """Every stored alert keyed by its first raw_id (file name and line: stable)."""
    return {row[1]: AlertResult(*row) for row in conn.execute(RESULTS_QUERY).fetchall()}


def stable(results: Mapping[str, AlertResult]) -> dict[str, tuple]:
    """The results without the random Ticket ID, to compare two runs."""
    return {
        raw_id: (
            row.alert_id,
            row.rule_id,
            row.count,
            row.path,
            row.alert_decision,
            row.ticket_id is not None,
            row.ticket_decision,
        )
        for raw_id, row in results.items()
    }


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def read_expected(path: Path) -> list[dict[str, str]]:
    return _rows(path)


def read_expected_counts(path: Path) -> list[dict[str, str]]:
    return _rows(path)


@dataclass
class Report:
    """The comparison. ``lines`` is what the runner prints."""

    rows: int = 0
    matched: int = 0
    paths_matched: int = 0
    mismatches: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)


def _shown(value: str | None) -> str:
    return NO_VALUE if value is None else value


def compare(
    expected: Sequence[Mapping[str, str]],
    expected_counts: Sequence[Mapping[str, str]],
    results: Mapping[str, AlertResult],
    *,
    decisions: bool = True,
) -> Report:
    """Compare ``results`` with the two expected tables.

    ``decisions=False`` compares the branch only (C21 path and counts), as right
    after ``soc.branch``.
    """
    report = Report(rows=len(expected))
    header = "raw_id | rule_id | path (expected / got)"
    if decisions:
        header += " | alert, ticket decision (expected / got)"
    report.lines.append(header + " | result")
    for row in expected:
        got = results.get(row["raw_id"])
        path = None if got is None else got.path
        wrong = []
        if got is None or got.rule_id != row["rule_id"]:
            wrong.append("alert missing or another rule_id")
        if path != row["expected_path"]:
            wrong.append("path")
        else:
            report.paths_matched += 1
        decision_text = ""
        if decisions:
            alert = _shown(None if got is None else got.alert_decision)
            ticket = _shown(None if got is None else got.ticket_decision)
            if alert != row["expected_alert_decision"]:
                wrong.append("alert decision")
            if ticket != row["expected_ticket_decision"]:
                wrong.append("ticket decision")
            decision_text = (
                f" | {row['expected_alert_decision']}, {row['expected_ticket_decision']}"
                f" / {alert}, {ticket}"
            )
        mark = "ok" if not wrong else "DIFF " + ", ".join(wrong)
        report.lines.append(
            f"{row['raw_id']} | {row['rule_id']} | {row['expected_path']} / {_shown(path)}"
            f"{decision_text} | {mark}"
        )
        if wrong:
            report.mismatches.append(f"{row['raw_id']}: {', '.join(wrong)}")
        else:
            report.matched += 1
    _compare_counts(expected_counts, results, report)
    return report


def _compare_counts(
    expected_counts: Sequence[Mapping[str, str]],
    results: Mapping[str, AlertResult],
    report: Report,
) -> None:
    alerts: Counter[str] = Counter()
    representatives: Counter[str] = Counter()
    duplicates: Counter[str] = Counter()
    counted = 0
    for row in results.values():
        rule = row.rule_id or NO_VALUE
        alerts[rule] += 1
        if row.path == DEDUPLICATED:
            duplicates[rule] += 1
        elif row.path is not None:
            representatives[rule] += 1
            counted += row.count
    got = {rule: (alerts[rule], representatives[rule], duplicates[rule]) for rule in alerts} | {
        "total": (sum(alerts.values()), representatives.total(), duplicates.total())
    }
    report.lines.append("rule_id | alerts, representatives, deduplicated (expected / got)")
    for row in expected_counts:
        rule = row["rule_id"]
        want = (int(row["alerts"]), int(row["representatives"]), int(row["deduplicated"]))
        have = got.get(rule, (0, 0, 0))
        mark = "ok" if want == have else "DIFF"
        report.lines.append(
            f"{rule} | {', '.join(map(str, want))} / {', '.join(map(str, have))} | {mark}"
        )
        if want != have:
            report.mismatches.append(f"counts {rule}: expected {want}, got {have}")
    if counted != sum(alerts.values()):
        report.mismatches.append(
            f"count sum of representatives {counted} != stored alerts {sum(alerts.values())}"
        )
    report.lines.append(f"count sum of representatives: {counted} / alerts {sum(alerts.values())}")


# --- check ------------------------------------------------------------------------

HttpGet = Callable[[str, Mapping[str, str]], tuple[int, bytes]]


def http_get(url: str, headers: Mapping[str, str]) -> tuple[int, bytes]:
    request = Request(url, headers=dict(headers))
    with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:  # noqa: S310 - settings URL
        return response.status, response.read()


def _model_names(body: bytes) -> set[str]:
    """Model IDs of an OpenAI-compatible /models answer, also without ``:latest``."""
    try:
        data = json.loads(body).get("data", [])
    except (ValueError, AttributeError):
        return set()
    names = {item.get("id") for item in data if isinstance(item, dict)} - {None}
    return names | {name.removesuffix(":latest") for name in names}


def check(
    settings: Settings,
    environ: Mapping[str, str],
    files: Sequence[Path],
    *,
    get: HttpGet = http_get,
    connect_db: Callable[[Settings, Mapping[str, str]], Any] = connect,
) -> list[str]:
    """What is missing for ``full``, as one line each. Empty when all is there."""
    problems = []
    for name in (URL_ENV, READONLY_URL_ENV):
        if not environ.get(name):
            problems.append(f"{name} is not set (.env)")
    if environ.get(URL_ENV):
        try:
            connect_db(settings, environ).close()
        except DatabaseConnectionError:
            problems.append(f"PostgreSQL: cannot connect using {URL_ENV} (docker compose up -d)")
    try:
        status, _ = get(f"{settings.vector_store.url}/readyz", {})
        if status != 200:
            raise URLError(f"status {status}")
    except (OSError, URLError):
        problems.append("Qdrant: not reachable at [vector_store] url (docker compose up -d)")
    headers = {}
    key = environ.get(settings.llm.api_key_env)
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        _, body = get(f"{settings.llm.base_url.rstrip('/')}/models", headers)
    except (OSError, URLError):
        problems.append("LLM server: not reachable at [llm] base_url (is Ollama running?)")
    else:
        names = _model_names(body)
        for model in (settings.llm.model, settings.embedder.model):
            if model not in names:
                problems.append(
                    f"model {model} not found on the LLM server "
                    "(ollama pull, or ollama create from config/demo/Modelfile)"
                )
    for entry in settings.siem.direct.files:
        if not (ROOT / entry.path).is_file():
            problems.append(f"replay file missing: {entry.path} (docs/milestone-l1.md 시연 데이터)")
    for path in files:
        if not path.is_file():
            problems.append(f"file missing: {path}")
    return problems


# --- running the steps ------------------------------------------------------------


@dataclass
class Step:
    name: str
    seconds: float


def step_environ(environ: Mapping[str, str], config: Path, name: str) -> dict[str, str]:
    """The environment for one command: the settings file and the new database."""
    env = dict(environ)
    env["ZT_CONFIG"] = str(config)
    env[URL_ENV] = database_url(environ[URL_ENV], name)
    if environ.get(READONLY_URL_ENV):
        env[READONLY_URL_ENV] = database_url(environ[READONLY_URL_ENV], name)
    return env


def run_module(name: str, module: str, args: Sequence[str], env: Mapping[str, str]) -> Step:
    print(f"== {name}", flush=True)
    started = time.perf_counter()
    done = subprocess.run([sys.executable, "-m", module, *args], cwd=ROOT, env=dict(env))
    seconds = time.perf_counter() - started
    if done.returncode != 0:
        raise RunnerError(f"{name} failed with exit code {done.returncode}")
    print(f"   {name}: {seconds:.1f}s", flush=True)
    return Step(name, seconds)


def timed(name: str, action: Callable[[], str | None]) -> Step:
    print(f"== {name}", flush=True)
    started = time.perf_counter()
    message = action()
    seconds = time.perf_counter() - started
    if message:
        print(f"   {message}")
    print(f"   {name}: {seconds:.1f}s", flush=True)
    return Step(name, seconds)


def print_report(title: str, report: Report) -> None:
    print(f"== {title}")
    for line in report.lines:
        print(f"   {line}")
    print(f"   rows matched {report.matched}/{report.rows}, paths {report.paths_matched}")
    for mismatch in report.mismatches:
        print(f"   DIFF {mismatch}")


def report_now(url: str, args: argparse.Namespace, *, decisions: bool) -> Report:
    with admin_connection(url) as conn:
        results = collect_results(conn)
    return compare(
        read_expected(args.expected),
        read_expected_counts(args.expected_counts),
        results,
        decisions=decisions,
    )


def run_full(args: argparse.Namespace, environ: Mapping[str, str]) -> int:
    settings = load_config(args.config, environ=environ)
    problems = check(settings, environ, [args.assets, args.users, *expected_files(args)])
    if problems:
        print_problems(problems)
        return 1
    name = check_name(args.db)
    env = step_environ(environ, args.config, name)
    url = env[URL_ENV]
    steps: list[Step] = []

    steps.append(
        timed(
            "create database",
            lambda: create_database(environ[URL_ENV], name, args.from_template),
        )
    )
    if args.from_template is None:
        steps.append(run_module("migrate", "soc.db.migrate", [], env))
    steps.append(
        timed(
            "grant read-only",
            lambda: grant_readonly(environ[URL_ENV], environ.get(READONLY_URL_ENV), name),
        )
    )
    if args.from_template is None:
        lookup = "soc.normalize.lookup.load"
        steps.append(run_module("lookup assets", lookup, ["assets", str(args.assets)], env))
        steps.append(run_module("lookup users", lookup, ["users", str(args.users)], env))
        steps.append(run_module("ingest", "soc.ingest", ["--all"], env))
        steps.append(run_module("normalize", "soc.normalize", ["--all"], env))
        steps.append(run_module("branch", "soc.branch", ["--all"], env))
        print_report("branch vs expected", report_now(url, args, decisions=False))
        template = check_name(name + TEMPLATE_SUFFIX)
        steps.append(
            timed(
                "keep branched database",
                lambda: (
                    create_database(environ[URL_ENV], template, name)
                    or f"kept as {template} (rerun l1 with --from-template {template})"
                ),
            )
        )
    steps.append(run_module("l1", "soc.l1", ["--all"], env))
    report = report_now(url, args, decisions=True)
    print_report("L1 vs expected (decisions are reference values)", report)
    print("== time")
    for step in steps:
        print(f"   {step.name}: {step.seconds:.1f}s")
    print(f"   total: {sum(step.seconds for step in steps):.1f}s")
    print(f"== show it: uv run python scripts/demo_run.py show --db {name}")
    return 0


def expected_files(args: argparse.Namespace) -> list[Path]:
    return [args.expected, args.expected_counts]


def print_problems(problems: Sequence[str]) -> None:
    print("missing, nothing was run:", file=sys.stderr)
    for problem in problems:
        print(f"  - {problem}", file=sys.stderr)


def run_show(args: argparse.Namespace, environ: Mapping[str, str]) -> int:
    settings = load_config(args.config, environ=environ)
    name = check_name(args.db)
    if not environ.get(URL_ENV) or not environ.get(READONLY_URL_ENV):
        print_problems([f"{URL_ENV} and {READONLY_URL_ENV} must be set (.env)"])
        return 1
    if not database_exists(environ[URL_ENV], name):
        print_problems([f"database {name} does not exist (run full first)"])
        return 1
    env = step_environ(environ, args.config, name)
    api = f"http://{settings.api.host}:{settings.api.port}/api"
    processes = [subprocess.Popen([sys.executable, "-m", "soc.api"], cwd=ROOT, env=env)]
    print(f"== API on {api} reading {name}")
    if not args.api_only:
        screen_env = env | {"VITE_USE_MOCK": "false", "VITE_API_BASE_URL": api}
        processes.append(
            subprocess.Popen(["pnpm", "--dir", "frontend", "dev"], cwd=ROOT, env=screen_env)
        )
        print("== screen: pnpm --dir frontend dev (the screen's API connection is issue H6)")
    print("== Ctrl+C stops both")
    try:
        while all(process.poll() is None for process in processes):
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            process.wait()
    return 0


def run_check(args: argparse.Namespace, environ: Mapping[str, str]) -> int:
    settings = load_config(args.config, environ=environ)
    problems = check(settings, environ, [args.assets, args.users, *expected_files(args)])
    if problems:
        print_problems(problems)
        return 1
    print("everything full needs is there")
    return 0


def parser() -> argparse.ArgumentParser:
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--config", type=Path, default=DEMO / "settings.toml")
    parent.add_argument("--assets", type=Path, default=DEMO / "assets.csv")
    parent.add_argument("--users", type=Path, default=DEMO / "users.csv")
    parent.add_argument("--expected", type=Path, default=DEMO / "expected.csv")
    parent.add_argument("--expected-counts", type=Path, default=DEMO / "expected_counts.csv")
    main_parser = argparse.ArgumentParser(prog="scripts/demo_run.py", description=__doc__)
    commands = main_parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", parents=[parent], help="check what full needs")
    full = commands.add_parser("full", parents=[parent], help="run the demo on a new database")
    full.add_argument("--db", required=True, help="name of the new database")
    full.add_argument(
        "--from-template",
        help="copy this branched database and run only l1 (e.g. <db>_branched)",
    )
    show = commands.add_parser("show", parents=[parent], help="serve a database already run")
    show.add_argument("--db", required=True, help="the database full made")
    show.add_argument("--api-only", action="store_true", help="start the API without the screen")
    return main_parser


def main(argv: Sequence[str] | None = None, environ: Mapping[str, str] | None = None) -> int:
    args = parser().parse_args(argv)
    environ = os.environ if environ is None else environ
    commands = {"check": run_check, "full": run_full, "show": run_show}
    try:
        return commands[args.command](args, environ)
    except (RunnerError, DatabaseConnectionError) as error:
        print(f"stopped: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
