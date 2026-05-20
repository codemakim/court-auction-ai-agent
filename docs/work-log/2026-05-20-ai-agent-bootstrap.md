# 2026-05-20 AI 요약 에이전트 분리 구축

## 목표
- 크롤러/웹과 분리된 AI 요약 워커를 만든다.
- Ollama `gemma4:e4b`가 매각물건명세서 있는 물건을 한 건씩 요약한다.
- 결과를 별도 SQLite DB에 저장하고 웹에서 읽어 보여준다.

## 이전 실패를 반영한 설계
- 긴 PDF 원문 전체를 보내지 않고, 크롤러에서 정제된 명세서와 구조화 필드만 보낸다.
- AI DB를 별도 고정 스키마로 만들고 웹이 같은 DB를 직접 읽는다.
- 같은 `source_hash + prompt_version + schema_version` 성공 결과가 있으면 중복 호출하지 않는다.
- 같은 입력 실패는 최대 3회까지만 재시도한다.
- AI 서비스가 실패해도 웹은 `AI 요약 전` 또는 `AI 실패`로 표시하고 목록 조회는 계속 동작한다.

## 운영 경로
- 코드: `/home/jhkim/code/court-auction-ai-agent`
- AI DB: `/var/lib/court-auction-ai-agent/data/auction_ai.sqlite3`
- 환경 파일: `/etc/court-auction-ai-agent.env`
- systemd: `court-auction-ai-agent.service`

## 확인 명령
```bash
court-auction-ai-agent status
journalctl -u court-auction-ai-agent.service -f
sqlite3 /var/lib/court-auction-ai-agent/data/auction_ai.sqlite3 'select status, count(*) from auction_ai_summaries group by status;'
```
