# Court Auction AI Agent 운영

## 서비스 제어

```bash
sudo systemctl status court-auction-ai-agent.service --no-pager -l
sudo systemctl restart court-auction-ai-agent.service
journalctl -u court-auction-ai-agent.service -f
```

## 요약 진행 상태

```bash
cd /home/jhkim/code/court-auction-ai-agent
. .venv/bin/activate
court-auction-ai-agent status
```

또는 DB 직접 확인:

```bash
sqlite3 /var/lib/court-auction-ai-agent/data/auction_ai.sqlite3 \
  'select status, count(*) from auction_ai_summaries group by status;'
```

## 처리 방식

- 워커는 매각물건명세서가 있는 물건만 처리한다.
- 한 루프에 한 건만 Ollama에 보낸다.
- 요약 성공 건은 같은 명세서 hash와 prompt/schema 버전 기준으로 다시 처리하지 않는다.
- 실패 건은 같은 입력 기준 최대 3회까지 재시도한다.
- 새 수집으로 명세서 hash가 바뀌면 다시 요약 대상이 된다.

## 웹 연동

웹은 아래 DB를 읽어서 목록/상세에 AI 상태와 요약을 표시한다.

```text
/var/lib/court-auction-ai-agent/data/auction_ai.sqlite3
```

웹 서비스 환경에는 다음 값이 필요하다.

```text
CAW_AI_DB_PATH=/var/lib/court-auction-ai-agent/data/auction_ai.sqlite3
```
