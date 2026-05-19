from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .db import count_attempts, has_terminal_success, save_summary


@dataclass(frozen=True)
class WorkerResult:
    auction_id: int | None
    external_key: str | None
    status: str


class EnrichmentWorker:
    def __init__(
        self,
        crawler_source,
        db_path: Path,
        ollama_client,
        *,
        model_name: str,
        prompt_version: str,
        schema_version: str,
        max_attempts: int = 3,
    ):
        self.crawler_source = crawler_source
        self.db_path = Path(db_path)
        self.ollama_client = ollama_client
        self.model_name = model_name
        self.prompt_version = prompt_version
        self.schema_version = schema_version
        self.max_attempts = max_attempts

    def run_once(self) -> WorkerResult:
        for candidate in self.crawler_source.list_candidates():
            if has_terminal_success(
                self.db_path,
                auction_id=candidate.auction_id,
                source_hash=candidate.source_hash,
                prompt_version=self.prompt_version,
                schema_version=self.schema_version,
            ):
                continue
            attempts = count_attempts(
                self.db_path,
                auction_id=candidate.auction_id,
                source_hash=candidate.source_hash,
                prompt_version=self.prompt_version,
                schema_version=self.schema_version,
            )
            if attempts >= self.max_attempts:
                continue
            print({"event": "processing", "auction_id": candidate.auction_id, "external_key": candidate.external_key}, flush=True)
            try:
                payload = self.ollama_client.enrich(candidate)
            except Exception as exc:
                save_summary(
                    self.db_path,
                    auction_id=candidate.auction_id,
                    external_key=candidate.external_key,
                    source_document_id=candidate.document_id,
                    source_text_id=candidate.text_id,
                    source_hash=candidate.source_hash,
                    model_name=self.model_name,
                    prompt_version=self.prompt_version,
                    schema_version=self.schema_version,
                    status="failed",
                    error_message=str(exc),
                )
                print({"event": "failed", "auction_id": candidate.auction_id, "external_key": candidate.external_key, "error": str(exc)}, flush=True)
                return WorkerResult(candidate.auction_id, candidate.external_key, "failed")
            save_summary(
                self.db_path,
                auction_id=candidate.auction_id,
                external_key=candidate.external_key,
                source_document_id=candidate.document_id,
                source_text_id=candidate.text_id,
                source_hash=candidate.source_hash,
                model_name=self.model_name,
                prompt_version=self.prompt_version,
                schema_version=self.schema_version,
                status="success",
                summary_title=payload["summary_title"],
                summary_bullets=payload["summary_bullets"],
                risk_label=payload["risk_label"],
                risk_comment=payload["risk_comment"],
                mobile_highlights=payload["mobile_highlights"],
                raw_response=payload,
            )
            print({"event": "success", "auction_id": candidate.auction_id, "external_key": candidate.external_key}, flush=True)
            return WorkerResult(candidate.auction_id, candidate.external_key, "success")
        return WorkerResult(None, None, "idle")
