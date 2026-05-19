from __future__ import annotations

import argparse
import json
import time

from .config import Settings
from .crawler_source import CrawlerSource
from .db import count_by_status, init_db
from .enrichment import OllamaClient
from .worker import EnrichmentWorker


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="court-auction-ai-agent")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db")
    sub.add_parser("status")
    sub.add_parser("worker-once")
    loop = sub.add_parser("worker-loop")
    loop.add_argument("--interval-seconds", type=int, default=None)
    loop.add_argument("--stop-when-idle", action="store_true")
    return parser


def build_worker(settings: Settings) -> EnrichmentWorker:
    init_db(settings.db_path)
    return EnrichmentWorker(
        CrawlerSource(settings.crawler_db_path),
        settings.db_path,
        OllamaClient(settings.ollama_base_url, settings.ollama_model, timeout_seconds=settings.ollama_timeout_seconds),
        model_name=settings.ollama_model,
        prompt_version=settings.prompt_version,
        schema_version=settings.schema_version,
        max_attempts=settings.max_attempts,
    )


def main() -> None:
    args = build_parser().parse_args()
    settings = Settings()
    if args.command == "init-db":
        init_db(settings.db_path)
        print(json.dumps({"status": "initialized", "db_path": str(settings.db_path)}, ensure_ascii=False))
        return
    if args.command == "status":
        init_db(settings.db_path)
        candidates = CrawlerSource(settings.crawler_db_path).list_candidates()
        print(json.dumps({"candidate_count": len(candidates), "summary_counts": count_by_status(settings.db_path)}, ensure_ascii=False))
        return
    worker = build_worker(settings)
    if args.command == "worker-once":
        print(json.dumps(worker.run_once().__dict__, ensure_ascii=False), flush=True)
        return
    interval = args.interval_seconds if args.interval_seconds is not None else settings.worker_interval_seconds
    while True:
        result = worker.run_once()
        print(json.dumps(result.__dict__, ensure_ascii=False), flush=True)
        if args.stop_when_idle and result.status == "idle":
            return
        time.sleep(interval)
