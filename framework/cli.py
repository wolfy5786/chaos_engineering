"""CLI: argparse, logging to stderr, short summary on stdout."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from framework.logging_config import setup_logging
from framework.orchestrator import run_pipeline

logger = logging.getLogger(__name__)


def _load_dotenv(env_path: Path) -> int:
    """Best-effort ``.env`` loader (no external dependency).

    Parses ``KEY=VALUE`` lines, ignores blanks and ``#`` comments, strips a
    single pair of surrounding quotes, and only sets variables that are not
    already defined in the process environment. Returns the number of keys
    applied. Silently does nothing if the file is missing or unreadable —
    scenario placeholders like ``${LOGIN_EMAIL}`` will then simply expand to
    whatever is (or isn't) already in ``os.environ``.
    """
    if not env_path.is_file():
        return 0
    applied = 0
    try:
        with env_path.open("r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[len("export "):].lstrip()
                if "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                if not key:
                    continue
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                    value = value[1:-1]
                if key in os.environ:
                    continue
                os.environ[key] = value
                applied += 1
    except OSError as exc:
        logger.debug("cli: unable to read %s: %s", env_path, exc)
        return 0
    return applied


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Security & Chaos Engineering Framework (skeleton runner)")
    p.add_argument(
        "-s",
        "--scenario",
        type=Path,
        required=True,
        help="Path to scenario YAML file",
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Log at DEBUG on stderr",
    )
    p.add_argument(
        "--log-level",
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Override log level (default: INFO, or DEBUG if -v)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.log_level is not None:
        level = getattr(logging, args.log_level)
    elif args.verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO

    setup_logging(level=level)

    # Populate os.environ from the repo-root .env so scenario placeholders like
    # ${LOGIN_EMAIL} / ${LOGIN_PASSWORD} resolve during workload generation.
    # Existing environment variables always win, so CI overrides still apply.
    repo_root = Path(__file__).resolve().parent.parent
    for candidate in (Path.cwd() / ".env", repo_root / ".env"):
        applied = _load_dotenv(candidate)
        if applied:
            logger.info("cli: loaded %d variable(s) from %s", applied, candidate)
            break

    scenario_path = args.scenario.resolve()

    logger.info(
        "cli: invocation scenario=%s log_level=%s (%s)",
        scenario_path,
        logging.getLevelName(level),
        level,
    )

    if not scenario_path.is_file():
        logger.error("cli: scenario file not found: %s", scenario_path)
        print(f"error: scenario not found: {scenario_path}", file=sys.stdout, flush=True)
        return 2

    try:
        result = run_pipeline(scenario_path)
    except Exception:
        logger.exception("cli: pipeline failed")
        print("status: failed", file=sys.stdout, flush=True)
        return 1

    print(f"run_id: {result.run_id}", file=sys.stdout, flush=True)
    print(f"scenario: {result.scenario_path}", file=sys.stdout, flush=True)
    print("status: success", file=sys.stdout, flush=True)
    print(f"report_json: {result.json_report}", file=sys.stdout, flush=True)
    print(f"report_html: {result.html_report}", file=sys.stdout, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
