# 2026-05-21 구조화 JSON 분석 전환 및 전체 재요약 준비

## 변경
- AI 입력을 `sale_item_statement_enriched_raw` 구조화 JSON으로 확정했다.
- 임차인/점유자 파서를 보강했다.
  - 여러 점유자 행을 분리한다.
  - 이름, 전입일자, 확정일자, 배당요구일, 보증금을 구분해 넣는다.
  - `전유부분`, `보증금` 같은 표 라벨을 사람 이름으로 오인하지 않는다.
  - `주택도시보증공사` 같은 보증/권리승계 기관은 occupant로 넣지 않고 raw_notes에 남긴다.
- `최선순위설정 ... 개시결정`은 저당권/말소기준권리로 단정하지 않고 `auction_start_decision_or_unknown`으로 보낸다.
- 빈 `[법정지상권]`, `[비고]` 같은 섹션 제목만 있는 라인은 raw_notes에서 제외한다.
- prompt/schema version을 `investment-risk-v2`로 올려 기존 결과도 새 방식으로 다시 처리되게 했다.

## 검증
- AI agent tests: `8 passed`
- web tests/build는 web repo 작업 로그에 별도 기록.
