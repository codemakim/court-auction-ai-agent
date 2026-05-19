from __future__ import annotations

import hashlib
import html
import sqlite3
from pathlib import Path

from .models import AuctionCandidate


class CrawlerSource:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    def _connect(self):
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def list_candidates(self) -> list[AuctionCandidate]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                  a.id AS auction_id,
                  a.external_key,
                  a.case_number,
                  a.item_number,
                  a.address,
                  a.property_category,
                  a.residential_subtype,
                  a.appraisal_value,
                  a.minimum_sale_price,
                  a.failed_auction_count,
                  a.sale_date,
                  a.current_status,
                  a.appraisal_summary,
                  d.id AS document_id,
                  d.content_hash AS document_content_hash,
                  latest.id AS text_id,
                  latest.markdown_text AS sale_spec_markdown
                FROM auctions a
                JOIN documents d ON d.auction_id = a.id AND d.document_type = 'sale_spec'
                JOIN document_texts latest ON latest.id = (
                  SELECT max(id) FROM document_texts WHERE document_id = d.id
                )
                WHERE d.available = 1
                  AND d.download_status = 'downloaded'
                  AND latest.extraction_status = 'extracted'
                  AND latest.markdown_text IS NOT NULL
                  AND length(trim(latest.markdown_text)) > 0
                ORDER BY a.sale_date IS NULL, a.sale_date ASC, a.id ASC
                """
            ).fetchall()
        return [self._candidate(row) for row in rows]

    def _candidate(self, row: sqlite3.Row) -> AuctionCandidate:
        markdown = row["sale_spec_markdown"] or ""
        content_hash = row["document_content_hash"] or "no-content-hash"
        text_hash = hashlib.sha256(markdown.encode("utf-8")).hexdigest()[:16]
        return AuctionCandidate(
            auction_id=row["auction_id"],
            external_key=row["external_key"],
            case_number=row["case_number"],
            item_number=row["item_number"],
            address=html.unescape(row["address"] or ""),
            property_category=row["property_category"],
            residential_subtype=row["residential_subtype"],
            appraisal_value=row["appraisal_value"],
            minimum_sale_price=row["minimum_sale_price"],
            failed_auction_count=row["failed_auction_count"],
            sale_date=row["sale_date"],
            current_status=row["current_status"],
            appraisal_summary=html.unescape(row["appraisal_summary"] or "") or None,
            document_id=row["document_id"],
            document_content_hash=row["document_content_hash"],
            text_id=row["text_id"],
            sale_spec_markdown=markdown,
            source_hash=f"{content_hash}:{text_hash}",
        )
