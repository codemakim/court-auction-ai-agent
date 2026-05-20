import json
import sqlite3
from pathlib import Path

from court_auction_ai_agent.crawler_source import CrawlerSource
from court_auction_ai_agent.db import count_by_status, get_latest_summary, init_db, save_summary
from court_auction_ai_agent.enrichment import build_analysis_input, build_prompt_payload, parse_model_response, response_schema
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


def test_analysis_input_is_structured_and_keeps_risk_facts(tmp_path):
    db = tmp_path / 'crawler.sqlite3'
    make_crawler_db(db)
    candidate = CrawlerSource(db).list_candidates()[0]

    payload = build_analysis_input(candidate)

    dumped = json.dumps(payload, ensure_ascii=False)
    assert payload['document_type'] == 'sale_item_statement_enriched_raw'
    assert payload['case']['case_number'] == '2025타경1'
    assert payload['price']['minimum_sale_price'] == 240000000
    assert '최선순위설정2020.01.01' in dumped
    assert '조사된 임차내역없음' in dumped
    assert '개인정보유출주의' not in dumped


def test_parse_model_response_accepts_investment_analysis_json():
    parsed = parse_model_response(json.dumps({
        'summary': {'overall_risk': 'HIGH', 'overall_merit': 'MEDIUM', 'one_line_opinion': '임차 리스크 확인 전 보수 접근'},
        'critical_risks': [{'category': 'tenant', 'risk': '임차관계 확인 필요', 'reason': '명세서상 점유 문구', 'need_to_check': '전입/배당요구'}],
        'merits': [{'category': 'price', 'merit': '1회 유찰', 'reason': '최저가 하락', 'confidence': 'MEDIUM'}],
        'bid_price_analysis': {'minimum_sale_price': 240000000, 'estimated_extra_costs': ['명도비 확인 필요'], 'safe_bid_logic': '추가 인수금 차감', 'avoid_condition': '대항 임차 확인'},
        'pre_bid_checklist': ['등기부 확인'],
        'final_recommendation': {'action': 'NEED_MORE_DATA', 'reason': '임차관계 확인 필요'}
    }, ensure_ascii=False))

    assert parsed['summary']['overall_risk'] == 'HIGH'
    assert parsed['summary']['overall_merit'] == 'MEDIUM'
    assert parsed['final_recommendation']['action'] == 'NEED_MORE_DATA'
    assert parsed['risk_label'] == 'HIGH'
    assert '임차관계 확인 필요' in parsed['summary_bullets']


def test_response_schema_matches_required_analysis_shape():
    schema = response_schema()
    assert 'summary' in schema['required']
    assert 'critical_risks' in schema['required']
    assert 'final_recommendation' in schema['required']


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
                'risk_label': 'HIGH',
                'risk_comment': '확인 필요',
                'mobile_highlights': ['확인 필요'],
                'summary': {'overall_risk': 'HIGH', 'overall_merit': 'LOW', 'one_line_opinion': '확인 필요'},
                'critical_risks': [],
                'merits': [],
                'bid_price_analysis': {'minimum_sale_price': 240000000, 'estimated_extra_costs': [], 'safe_bid_logic': '확인 필요', 'avoid_condition': '확인 필요'},
                'pre_bid_checklist': [],
                'final_recommendation': {'action': 'NEED_MORE_DATA', 'reason': '확인 필요'},
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


def test_analysis_input_does_not_treat_table_labels_as_occupants(tmp_path):
    db = tmp_path / 'crawler.sqlite3'
    make_crawler_db(db)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE document_texts SET markdown_text = ? WHERE id = 100",
            ('# 매각물건명세서\n\n[점유/임차 관계] 점유자성 명점유부분정보출처구 분점유의권 원임대차기간(점유기간)보 증 금차 임전입신고일자확정일자배당요구여부(배당요구일자)임예성전유부분 전부등기사항전부증명서주거 임차권자2020.10.30.350,000,0002020.10.30.2020.09.24.주택도시보증공사전유부분 전부권리신고주거 임차인2020.10.30.350,000,0002020.10.30.2020.09.24.2025.12.8.',),
        )
    candidate = CrawlerSource(db).list_candidates()[0]

    payload = build_analysis_input(candidate)

    names = [occupant['name_masked'] for occupant in payload['occupants']]
    assert names == ['임OO']


def test_analysis_input_extracts_multiple_occupants_with_dates_and_deposits(tmp_path):
    db = tmp_path / 'crawler.sqlite3'
    make_crawler_db(db)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE document_texts SET markdown_text = ? WHERE id = 100",
            ('# 매각물건명세서\n\n최선순위설정2022.01.10. 근저당권배당요구종기2026. 3. 25.\n[점유/임차 관계] 김철수301호현황조사주거 임차인2021.03.15.180,000,0002021.03.15.2021.03.20.2026.03.01.박영희302호권리신고주거 임차인2023.04.01.50,000,0002023.04.01.2023.04.05.2026.03.02.',),
        )
    candidate = CrawlerSource(db).list_candidates()[0]

    payload = build_analysis_input(candidate)

    assert [o['name_masked'] for o in payload['occupants']] == ['김OO', '박OO']
    assert payload['occupants'][0]['move_in_date'] == '2021-03-15'
    assert payload['occupants'][0]['fixed_date'] == '2021-03-20'
    assert payload['occupants'][0]['deposit'] == 180000000
    assert payload['occupants'][0]['opposability_possible'] is True
    assert payload['occupants'][1]['deposit'] == 50000000
    assert payload['lease_and_distribution']['tenant_move_in_before_standard_right'] is True
