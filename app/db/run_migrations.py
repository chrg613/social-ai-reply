"""Run SQL migration files against Supabase during deploy/startup.

Requires ``DATABASE_URL`` (direct Postgres connection string) in the environment.
Set this in your ``.env`` or Railway dashboard.

All migration SQL must be idempotent (``IF NOT EXISTS`` / ``DO $$ … END $$``).
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_MIGRATION_DIRS = [
    Path(__file__).resolve().parent / "migrations",
    Path(__file__).resolve().parent.parent.parent / "supabase" / "migrations",
]


def _sort_key(path: Path) -> tuple[int, str]:
    stem = path.stem
    m = re.match(r"^(\d+)[_-]?(.*)", stem)
    return (int(m.group(1)) if m else 0, m.group(2) if m else stem)


def _collect_migrations() -> list[Path]:
    files: list[Path] = []
    for d in _MIGRATION_DIRS:
        if d.is_dir():
            files.extend(sorted(d.glob("*.sql"), key=_sort_key))
    return files


def run_migrations() -> list[str]:
    """Execute all pending migration files.

    Returns names of successfully applied migrations (empty = nothing to do).
    Silent no-op when ``DATABASE_URL`` is not set.
    """
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        logger.info(
            "DATABASE_URL not set — skipping auto-migration. "
            "To enable, add DATABASE_URL=postgresql://... to your .env or Railway dashboard. "
            "You can also apply migrations manually via Supabase SQL Editor."
        )
        return []

    import psycopg2  # type: ignore[import-untyped]

    files = _collect_migrations()
    if not files:
        logger.info("No migration files found in %s", [str(d) for d in _MIGRATION_DIRS])
        return []

    applied: list[str] = []
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            for path in files:
                name = f"{path.parent.name}/{path.name}"
                content = path.read_text(encoding="utf-8").strip()
                if not content:
                    continue

                statements = [s.strip() for s in content.split(";") if s.strip()]
                try:
                    for stmt in statements:
                        if stmt.upper().startswith("NOTIFY"):
                            continue
                        cur.execute(stmt)
                    conn.commit()
                    logger.info("Migration applied: %s", name)
                    applied.append(name)
                except Exception:
                    conn.rollback()
                    logger.exception("Migration FAILED: %s — continuing", name)
    finally:
        conn.close()

    return applied


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_migrations()
