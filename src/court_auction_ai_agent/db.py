from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def init_db(path: Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS auction_ai_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                auction_id INTEGER NOT NULL,
                external_key TEXT NOT NULL,
                source_document_id INTEGER,
                source_text_id INTEGER,
                source_hash TEXT NOT NULL,
                model_name TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                schema_version TEXT NOT NULL,
                status TEXT NOT NULL,
                summary_title TEXT,
                summary_bullets_json TEXT,
                risk_label TEXT,
                risk_comment TEXT,
                mobile_highlights_json TEXT,
                raw_response_json TEXT,
                error_message TEXT,
                generated_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ai_summary_auction ON auction_ai_summaries(auction_id, id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ai_summary_source ON auction_ai_summaries(auction_id, source_hash, prompt_version, schema_version, status)")


def save_summary(
    path: Path,
    *,
    auction_id: int,
    external_key: str,
    source_document_id: int | None,
    source_text_id: int | None,
    source_hash: str,
    model_name: str,
    prompt_version: str,
    schema_version: str,
    status: str,
    summary_title: str | None = None,
    summary_bullets: list[str] | None = None,
    risk_label: str | None = None,
    risk_comment: str | None = None,
    mobile_highlights: list[str] | None = None,
    raw_response: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            INSERT INTO auction_ai_summaries (
                auction_id, external_key, source_document_id, source_text_id, source_hash,
                model_name, prompt_version, schema_version, status,
                summary_title, summary_bullets_json, risk_label, risk_comment,
                mobile_highlights_json, raw_response_json, error_message, generated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                auction_id,
                external_key,
                source_document_id,
                source_text_id,
                source_hash,
                model_name,
                prompt_version,
                schema_version,
                status,
                summary_title,
                json.dumps(summary_bullets or [], ensure_ascii=False),
                risk_label,
                risk_comment,
                json.dumps(mobile_highlights or [], ensure_ascii=False),
                json.dumps(raw_response or {}, ensure_ascii=False),
                error_message,
                datetime.now(UTC).isoformat(),
            ),
        )


def get_latest_summary(path: Path, auction_id: int):
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute("SELECT * FROM auction_ai_summaries WHERE auction_id = ? ORDER BY id DESC LIMIT 1", (auction_id,)).fetchone()


def count_attempts(path: Path, *, auction_id: int, source_hash: str, prompt_version: str, schema_version: str) -> int:
    with sqlite3.connect(path) as conn:
        return conn.execute(
            """
            SELECT count(*) FROM auction_ai_summaries
            WHERE auction_id = ? AND source_hash = ? AND prompt_version = ? AND schema_version = ?
              AND status = 'failed'
            """,
            (auction_id, source_hash, prompt_version, schema_version),
        ).fetchone()[0]


def has_terminal_success(path: Path, *, auction_id: int, source_hash: str, prompt_version: str, schema_version: str) -> bool:
    with sqlite3.connect(path) as conn:
        return conn.execute(
            """
            SELECT 1 FROM auction_ai_summaries
            WHERE auction_id = ? AND source_hash = ? AND prompt_version = ? AND schema_version = ?
              AND status = 'success'
            ORDER BY id DESC LIMIT 1
            """,
            (auction_id, source_hash, prompt_version, schema_version),
        ).fetchone() is not None


def count_by_status(path: Path) -> dict[str, int]:
    if not Path(path).exists():
        return {}
    with sqlite3.connect(path) as conn:
        rows = conn.execute("SELECT status, count(*) FROM auction_ai_summaries GROUP BY status").fetchall()
    return {row[0]: row[1] for row in rows}
