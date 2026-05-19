# Court Auction AI Agent

법원 경매 수집 데이터에 대해 Ollama `gemma4:26b`를 한 건씩 호출해 모바일에서 보기 쉬운 요약/리스크 코멘트를 생성하는 독립 워커입니다.

## 책임 범위

- `court-auction-crawler` DB를 읽기 전용으로 조회합니다.
- 매각물건명세서가 다운로드/텍스트 추출된 물건만 요약합니다.
- 결과는 별도 SQLite DB에 저장합니다.
- 같은 명세서/같은 프롬프트 버전은 중복 요약하지 않습니다.
- 실패한 건은 같은 입력 기준 최대 3회까지 재시도합니다.

## 기본 경로

```text
crawler DB: /var/lib/court-auction-collector/data/court_auction.sqlite3
AI DB:      /var/lib/court-auction-ai-agent/data/auction_ai.sqlite3
Ollama:     http://127.0.0.1:11434
Model:      gemma4:26b
```

## 로컬 실행

```bash
cd /home/jhkim/code/court-auction-ai-agent
python3 -m venv .venv
. .venv/bin/activate
pip install -e .[dev]
cp .env.example .env
court-auction-ai-agent init-db
court-auction-ai-agent worker-once
```

백로그를 계속 처리하려면:

```bash
court-auction-ai-agent worker-loop --interval-seconds 5
```

상태 확인:

```bash
court-auction-ai-agent status
```

## 운영

systemd 서비스 파일 예시는 `systemd/court-auction-ai-agent.service`에 있습니다.

로그:

```bash
journalctl -u court-auction-ai-agent.service -f
```

## 데이터 보안

`.env`, `.venv`, SQLite DB, 런타임 데이터는 커밋하지 않습니다.
이 repo는 코드와 문서만 공개해도 되도록 구성합니다.
