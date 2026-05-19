from __future__ import annotations

import json
import re
from typing import Any

import requests

from .models import AuctionCandidate

RISK_LABELS = {"low", "review_recommended", "high", "unknown"}
PROMPT_SYSTEM = (
    "너는 법률 판단을 대신하지 않는 보수적인 한국 부동산 경매 검토 보조자다. "
    "투자 권유나 법률 단정은 하지 말고, 매각물건명세서와 감정요약에서 확인 가능한 사실만 근거로 요약하라. "
    "특히 지분매각, 특별매각조건, 공유자 우선매수권, 임차인/점유자, 대항력, 배당요구, 전입일, 확정일자, 보증금, 최선순위설정을 우선 확인하라. "
    "불확실하거나 원문 근거가 부족하면 반드시 사람 검토 필요라고 적어라. "
    "반복 양식 문구는 요약하지 말고 실제 물건 판단에 필요한 내용만 남겨라."
)


def _collapse(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text).strip()


def _trim(text: str | None, limit: int) -> str | None:
    if not text:
        return None
    collapsed = _collapse(text)
    return collapsed if len(collapsed) <= limit else collapsed[:limit].rstrip() + "…"


def _compact_sale_spec(markdown: str, limit: int = 4200) -> str:
    text = re.sub(r"^#\s*매각물건명세서\s*", "", markdown.strip())
    # Crawler normalization already removes form boilerplate. Keep this as defense-in-depth.
    for pattern in (
        r"개인정보유출주의[^\n]*",
        r"※\s*1:.*?기재한다\.",
        r"※\s*최선순위 설정일자보다.*?주의하시기 바랍니다\.",
        r"부동산의\s*표시.*$",
    ):
        text = re.sub(pattern, " ", text, flags=re.DOTALL)
    lines = [_collapse(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    compact = "\n".join(lines)
    return compact if len(compact) <= limit else compact[:limit].rstrip() + "…"


def build_prompt_payload(candidate: AuctionCandidate) -> dict[str, Any]:
    return {
        "기본정보": {
            "수집키": candidate.external_key,
            "사건번호": candidate.case_number,
            "물건번호": candidate.item_number,
            "주소": candidate.address,
            "종류": candidate.property_category,
            "주거세부유형": candidate.residential_subtype,
        },
        "가격_일정": {
            "감정가": candidate.appraisal_value,
            "최저매각가": candidate.minimum_sale_price,
            "유찰횟수": candidate.failed_auction_count,
            "매각기일": candidate.sale_date,
            "현재상태": candidate.current_status,
        },
        "감정평가_요약": _trim(candidate.appraisal_summary, 1400),
        "매각물건명세서_정제본문": _compact_sale_spec(candidate.sale_spec_markdown),
    }


def _sanitize(value: Any) -> Any:
    if isinstance(value, str):
        return _collapse(re.sub(r"</?[^>]+>", "", value))
    if isinstance(value, list):
        return [_sanitize(item) for item in value if item is not None]
    if isinstance(value, dict):
        return {str(key): _sanitize(item) for key, item in value.items()}
    return value


def parse_model_response(content: str) -> dict[str, Any]:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.DOTALL)
        if not match:
            raise
        payload = json.loads(match.group(0))
    payload = _sanitize(payload)
    bullets = payload.get("summary_bullets") or []
    highlights = payload.get("mobile_highlights") or []
    if isinstance(bullets, str):
        bullets = [bullets]
    if isinstance(highlights, str):
        highlights = [highlights]
    risk_label = payload.get("risk_label") or "unknown"
    if risk_label not in RISK_LABELS:
        risk_label = "unknown"
    return {
        "summary_title": str(payload.get("summary_title") or "AI 요약"),
        "summary_bullets": [str(item) for item in bullets][:6],
        "risk_label": risk_label,
        "risk_comment": str(payload.get("risk_comment") or "사람 검토 필요"),
        "mobile_highlights": [str(item) for item in highlights][:5],
    }


class OllamaClient:
    def __init__(self, base_url: str, model_name: str, *, timeout_seconds: int = 900):
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds

    def enrich(self, candidate: AuctionCandidate) -> dict[str, Any]:
        schema = {
            "type": "object",
            "properties": {
                "summary_title": {"type": "string"},
                "summary_bullets": {"type": "array", "items": {"type": "string"}},
                "risk_label": {"type": "string"},
                "risk_comment": {"type": "string"},
                "mobile_highlights": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["summary_title", "summary_bullets", "risk_label", "risk_comment", "mobile_highlights"],
        }
        user_content = (
            "다음 경매 물건을 모바일 화면에서 바로 1차 판단 보조로 볼 수 있게 한국어 JSON으로 요약해줘.\n"
            "원문을 반복하지 말고 확인 가능한 사실, 리스크, 추가 확인 포인트를 분리해줘.\n"
            "risk_label은 low / review_recommended / high / unknown 중 하나만 사용해.\n"
            "명세서에 없거나 불확실한 내용은 단정하지 말고 확인 필요라고 써.\n\n"
            f"입력:\n{json.dumps(build_prompt_payload(candidate), ensure_ascii=False)}"
        )
        response = requests.post(
            f"{self.base_url}/api/chat",
            json={
                "model": self.model_name,
                "stream": False,
                "format": schema,
                "messages": [
                    {"role": "system", "content": PROMPT_SYSTEM},
                    {"role": "user", "content": user_content},
                ],
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return parse_model_response(response.json()["message"]["content"])
