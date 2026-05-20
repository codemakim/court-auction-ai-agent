# 2026-05-21 투자 리스크 분석 프롬프트 전환

## 변경
- 기본 모델을 `gemma4:e4b`로 변경했다.
- 단순 요약 프롬프트에서 투자 리스크/메리트 분석 프롬프트로 전환했다.
- 입력은 PDF 원문 전체가 아니라 `sale_item_statement_enriched_raw` 형태의 분석용 JSON으로 재구성한다.
- 출력은 `summary`, `critical_risks`, `merits`, `bid_price_analysis`, `pre_bid_checklist`, `final_recommendation` 구조를 요구한다.

## 주의
- 현 단계의 JSON 파싱은 crawler DB와 정제된 매각물건명세서 텍스트에서 보수적으로 추출한다.
- 현황조사서/등기부/외부 재개발 데이터가 아직 별도 구조화되어 있지 않은 값은 `null` 또는 `확인 필요`로 둔다.
- 웹 호환을 위해 기존 `summary_title`, `summary_bullets`, `risk_label`, `risk_comment`, `mobile_highlights` 필드도 파생 저장한다.
