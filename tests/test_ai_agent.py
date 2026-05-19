import json
import sqlite3
from pathlib import Path

from court_auction_ai_agent.crawler_source import CrawlerSource
from court_auction_ai_agent.db import count_by_status, get_latest_summary, init_db, save_summary
from court_auction_ai_agent.enrichment import build_prompt_payload, parse_model_response
from court_auction_ai_agent.worker import EnrichmentWorker


def make_crawler_db(path: Path):
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE auctions (
              id INTEGER PRIMARY KEY,
              external_key TEXT,
              case_number TEXT,
              item_number TEXT,
              address TEXT,
              property_category TEXT,
              residential_subtype TEXT,
              appraisal_value INTEGER,
              minimum_sale_price INTEGER,
              failed_auction_count INTEGER,
              sale_date TEXT,
              current_status TEXT,
              appraisal_summary TEXT,
              last_seen_at TEXT
            );
            CREATE TABLE documents (
              id INTEGER PRIMARY KEY,
              auction_id INTEGER,
              document_type TEXT,
              available INTEGER,
              download_status TEXT,
              content_hash TEXT
            );
            CREATE TABLE document_texts (
              id INTEGER PRIMARY KEY,
              document_id INTEGER,
              extraction_status TEXT,
              markdown_text TEXT,
              processed_at TEXT,
              processor_version TEXT
            );
            """
        )
        conn.execute("INSERT INTO auctions VALUES (1,'2025타경1-1','2025타경1','1','서울특별시 금천구 가산동 테스트아파트 9층908호','건물','아파트',300000000,240000000,1,'2026-06-01','매각기일','전유면적 38.56㎡', '2026-05-20')")
        conn.execute("INSERT INTO documents VALUES (10,1,'sale_spec',1,'downloaded','hash-a')")
        conn.execute("INSERT INTO document_texts VALUES (100,10,'extracted','# 매각물건명세서\n\n최선순위설정2020.01.01. 근저당권\n[점유/임차 관계] 조사된 임차내역없음','2026-05-20','v3')")


def test_crawler_source_returns_downloaded_sale_specs(tmp_path):
    db = tmp_path / 'crawler.sqlite3'
    make_crawler_db(db)

    items = CrawlerSource(db).list_candidates()

    assert len(items) == 1
    assert items[0].auction_id == 1
    assert items[0].document_id == 10
    assert items[0].source_hash.startswith('hash-a:')
    assert '조사된 임차내역없음' in items[0].sale_spec_markdown


def test_prompt_payload_is_compact_and_keeps_risk_facts(tmp_path):
    db = tmp_path / 'crawler.sqlite3'
    make_crawler_db(db)
    candidate = CrawlerSource(db).list_candidates()[0]

    payload = build_prompt_payload(candidate)

    dumped = json.dumps(payload, ensure_ascii=False)
    assert '최선순위설정2020.01.01' in dumped
    assert '조사된 임차내역없음' in dumped
    assert '개인정보유출주의' not in dumped


def test_parse_model_response_accepts_json_object():
    parsed = parse_model_response(json.dumps({
        'summary_title': '가산동 아파트 1차 검토',
        'summary_bullets': ['명세서상 임차내역 없음'],
        'risk_label': 'review_recommended',
        'risk_comment': '권리관계 확인 필요',
        'mobile_highlights': ['최저가 2.4억']
    }, ensure_ascii=False))

    assert parsed['risk_label'] == 'review_recommended'
    assert parsed['summary_bullets'] == ['명세서상 임차내역 없음']


def test_worker_skips_success_and_retries_failed_until_limit(tmp_path):
    crawler_db = tmp_path / 'crawler.sqlite3'
    ai_db = tmp_path / 'ai.sqlite3'
    make_crawler_db(crawler_db)
    init_db(ai_db)

    class Client:
        calls = 0
        def enrich(self, candidate):
            self.calls += 1
            return {
                'summary_title': '요약',
                'summary_bullets': ['핵심'],
                'risk_label': 'unknown',
                'risk_comment': '확인 필요',
                'mobile_highlights': ['확인 필요'],
            }

    client = Client()
    worker = EnrichmentWorker(CrawlerSource(crawler_db), ai_db, client, model_name='m', prompt_version='p', schema_version='s', max_attempts=3)

    assert worker.run_once().status == 'success'
    assert worker.run_once().status == 'idle'
    assert client.calls == 1
    assert get_latest_summary(ai_db, 1)['summary_title'] == '요약'


def test_worker_retries_failed_input_only_three_times(tmp_path):
    crawler_db = tmp_path / 'crawler.sqlite3'
    ai_db = tmp_path / 'ai.sqlite3'
    make_crawler_db(crawler_db)
    init_db(ai_db)

    class FailingClient:
        def enrich(self, candidate):
            raise RuntimeError('ollama down')

    worker = EnrichmentWorker(CrawlerSource(crawler_db), ai_db, FailingClient(), model_name='m', prompt_version='p', schema_version='s', max_attempts=3)

    assert worker.run_once().status == 'failed'
    assert worker.run_once().status == 'failed'
    assert worker.run_once().status == 'failed'
    assert worker.run_once().status == 'idle'
    assert count_by_status(ai_db)['failed'] == 3
