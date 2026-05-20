from __future__ import annotations

import json
import re
from typing import Any

import requests

from .models import AuctionCandidate

OVERALL_RISKS = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
OVERALL_MERITS = {"LOW", "MEDIUM", "HIGH"}
ACTIONS = {"PASS", "CONSERVATIVE_BID", "AGGRESSIVE_BID_NOT_RECOMMENDED", "NEED_MORE_DATA"}
PROMPT_SYSTEM = """너는 한국 부동산 경매 물건의 위험도와 투자 메리트를 분석하는 보조 AI다.

아래 JSON은 매각물건명세서, 현황조사서, 등기부, 감정평가서 등에서 추린 로우데이터다.
너의 임무는 이 데이터를 바탕으로 낙찰자가 주의해야 할 위험 요소와 메리트를 구조적으로 분석하는 것이다.

중요 규칙:
1. JSON에 없는 사실을 단정하지 마라.
2. 불확실한 값은 반드시 "확인 필요"로 표시하라.
3. 임차인 대항력, 배당요구, 보증금 인수 가능성을 최우선으로 분석하라.
4. 말소기준권리보다 앞서는 권리 또는 점유자가 있는지 확인하라.
5. 낙찰가 판단 시 최소매각가뿐 아니라 추가 인수 가능 금액, 수리비, 세금, 명도 리스크를 함께 고려하라.
6. 재개발/모아타운 정보는 메리트이지만, 진행 단계와 분담금이 불확실하면 리스크로도 평가하라.
7. 법률 자문처럼 단정하지 말고, 실무 체크리스트와 보수적 판단을 제시하라.

출력은 지정된 JSON schema만 사용하라."""


def _collapse(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text).strip()


def _trim(text: str | None, limit: int) -> str | None:
    if not text:
        return None
    collapsed = _collapse(text)
    return collapsed if len(collapsed) <= limit else collapsed[:limit].rstrip() + "…"


def _to_int(value: str | None) -> int | None:
    if not value:
        return None
    digits = re.sub(r"[^0-9]", "", value)
    return int(digits) if digits else None


def _parse_date(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"(\d{4})[.\-/]\s*(\d{1,2})[.\-/]\s*(\d{1,2})", value)
    if not match:
        return None
    y, m, d = match.groups()
    return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"


def _compact_sale_spec(markdown: str, limit: int = 5200) -> str:
    text = re.sub(r"^#\s*매각물건명세서\s*", "", markdown.strip())
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


def _extract_occupants(sale_spec: str) -> list[dict[str, Any]]:
    text = _compact_sale_spec(sale_spec, limit=4000)
    if "조사된 임차내역없음" in text:
        return []
    occupants: list[dict[str, Any]] = []
    # Text extraction often collapses table cells. Keep this deliberately conservative.
    section = text.split("[점유/임차 관계]", 1)[1] if "[점유/임차 관계]" in text else text
    money_values = re.findall(r"(\d{1,3}(?:,\d{3})+|\d{7,})", section)
    dates = [_parse_date(match.group(0)) for match in re.finditer(r"\d{4}[.\-/]\s*\d{1,2}[.\-/]\s*\d{1,2}", section)]
    label_stopwords = {
        "점유자", "점유부분", "정보출처", "보증금", "전유부분", "전부", "등기사항", "전부증명서",
        "주거", "임차권자", "임차인", "권리신고", "현황조사", "전입", "확정일자", "배당요구",
        "주택도시", "보증공사", "주택도시보증공사",
    }
    names = []
    for raw_name in re.findall(r"([가-힣]{2,4})(?=(?:전유부분|[0-9]+호|미상|현황조사|권리신고|등기사항))", section):
        if raw_name in label_stopwords:
            continue
        if raw_name.endswith(("부분", "전부", "사항", "증서", "보증", "공사")):
            continue
        names.append(raw_name)
    for idx, name in enumerate(dict.fromkeys(names)):
        occupants.append(
            {
                "name_masked": name[0] + "OO" if len(name) >= 2 else "확인 필요",
                "type": "tenant" if "임차" in section else "unknown",
                "occupies_property": True if "점유" in section or "전유부분" in section else None,
                "move_in_date": dates[0] if dates else None,
                "fixed_date": dates[1] if len(dates) > 1 else None,
                "distribution_request": "confirmed" if "배당요구" in section and any(dates) else "unknown",
                "deposit": _to_int(money_values[0]) if money_values else None,
                "monthly_rent": 0 if "차임" in section else None,
                "opposability_possible": None,
                "priority_status": "확인 필요",
            }
        )
    if not occupants and any(keyword in section for keyword in ("임차", "점유", "전입", "보증금")):
        occupants.append(
            {
                "name_masked": "확인 필요",
                "type": "tenant_or_occupant",
                "occupies_property": True,
                "move_in_date": dates[0] if dates else None,
                "fixed_date": dates[1] if len(dates) > 1 else None,
                "distribution_request": "unknown",
                "deposit": _to_int(money_values[0]) if money_values else None,
                "monthly_rent": None,
                "opposability_possible": None,
                "priority_status": "확인 필요",
            }
        )
    return occupants[:5]


def build_analysis_input(candidate: AuctionCandidate) -> dict[str, Any]:
    sale_spec = _compact_sale_spec(candidate.sale_spec_markdown)
    standard_match = re.search(r"최선순위설정\s*([0-9.\-/\s]+)\s*([^\n배당]+)?", sale_spec)
    deadline_match = re.search(r"배당요구종기\s*([0-9.\-/\s]+)", sale_spec)
    exclusive_area = None
    area_match = re.search(r"전유(?:부분|면적)?[^0-9]{0,20}(\d+(?:\.\d+)?)\s*㎡", candidate.appraisal_summary or "")
    if area_match:
        exclusive_area = float(area_match.group(1))
    floor_match = re.search(r"(\d+)층(?:\s*제?\d+호|\d+호|[\s,])", candidate.address)
    total_floors_match = re.search(r"(\d+)층\s*건물", candidate.appraisal_summary or "")
    approval_match = re.search(r"사용승인일\s*[:：]?\s*(\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2})", candidate.appraisal_summary or "")
    known_red_flags = []
    if "임차" in sale_spec or "점유" in sale_spec:
        known_red_flags.append("occupant or tenant text exists")
    if "배당" in sale_spec and "배당요구" in sale_spec:
        known_red_flags.append("distribution request needs confirmation")
    if "인수" in sale_spec:
        known_red_flags.append("possible inherited right or deposit text exists")
    if "지분매각" in sale_spec or "공유자" in sale_spec:
        known_red_flags.append("share sale or co-owner right text exists")
    return {
        "document_type": "sale_item_statement_enriched_raw",
        "case": {
            "court": None,
            "case_number": candidate.case_number,
            "sale_date": candidate.sale_date,
            "property_type": candidate.residential_subtype or candidate.property_category,
        },
        "property": {
            "address": candidate.address,
            "building_name": None,
            "exclusive_area_m2": exclusive_area,
            "land_share_m2": None,
            "approval_date": _parse_date(approval_match.group(1)) if approval_match else None,
            "floor": int(floor_match.group(1)) if floor_match else None,
            "total_floors": int(total_floors_match.group(1)) if total_floors_match else None,
            "elevator": "승강기" in (candidate.appraisal_summary or "") or None,
            "parking_available": "주차" in (candidate.appraisal_summary or "") or None,
        },
        "price": {
            "appraisal_price": candidate.appraisal_value,
            "minimum_sale_price": candidate.minimum_sale_price,
            "previous_failed_count": candidate.failed_auction_count,
        },
        "occupants": _extract_occupants(candidate.sale_spec_markdown),
        "rights": {
            "standard_extinguishing_right": {
                "type": _collapse(standard_match.group(2) or "확인 필요") if standard_match else "확인 필요",
                "registered_at": _parse_date(standard_match.group(1)) if standard_match else None,
                "holder": None,
                "claim_max_amount": None,
            },
            "registered_rights": [],
        },
        "lease_and_distribution": {
            "tenant_move_in_before_standard_right": None,
            "tenant_fixed_date_before_standard_right": None,
            "distribution_demand_deadline": _parse_date(deadline_match.group(1)) if deadline_match else None,
            "distribution_request_confirmed": None,
            "possible_deposit_inheritance": "possible" if "인수" in sale_spec else "unknown",
            "known_red_flags": known_red_flags,
        },
        "redevelopment": {
            "possible_area": None,
            "project_type": None,
            "zone": None,
            "constructor": None,
            "status": "unverified",
            "expected_additional_charge_risk": "unknown",
        },
        "raw_notes": [line for line in sale_spec.splitlines() if line][:20],
    }


def build_prompt_payload(candidate: AuctionCandidate) -> dict[str, Any]:
    return build_analysis_input(candidate)


def response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "summary": {
                "type": "object",
                "properties": {
                    "overall_risk": {"type": "string"},
                    "overall_merit": {"type": "string"},
                    "one_line_opinion": {"type": "string"},
                },
                "required": ["overall_risk", "overall_merit", "one_line_opinion"],
            },
            "critical_risks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string"},
                        "risk": {"type": "string"},
                        "reason": {"type": "string"},
                        "need_to_check": {"type": "string"},
                    },
                    "required": ["category", "risk", "reason", "need_to_check"],
                },
            },
            "merits": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string"},
                        "merit": {"type": "string"},
                        "reason": {"type": "string"},
                        "confidence": {"type": "string"},
                    },
                    "required": ["category", "merit", "reason", "confidence"],
                },
            },
            "bid_price_analysis": {
                "type": "object",
                "properties": {
                    "minimum_sale_price": {"type": ["number", "null"]},
                    "estimated_extra_costs": {"type": "array", "items": {"type": "string"}},
                    "safe_bid_logic": {"type": "string"},
                    "avoid_condition": {"type": "string"},
                },
                "required": ["minimum_sale_price", "estimated_extra_costs", "safe_bid_logic", "avoid_condition"],
            },
            "pre_bid_checklist": {"type": "array", "items": {"type": "string"}},
            "final_recommendation": {
                "type": "object",
                "properties": {"action": {"type": "string"}, "reason": {"type": "string"}},
                "required": ["action", "reason"],
            },
        },
        "required": ["summary", "critical_risks", "merits", "bid_price_analysis", "pre_bid_checklist", "final_recommendation"],
    }


def _sanitize(value: Any) -> Any:
    if isinstance(value, str):
        return _collapse(re.sub(r"</?[^>]+>", "", value))
    if isinstance(value, list):
        return [_sanitize(item) for item in value if item is not None]
    if isinstance(value, dict):
        return {str(key): _sanitize(item) for key, item in value.items()}
    return value


def _ensure_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def parse_model_response(content: str) -> dict[str, Any]:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.DOTALL)
        if not match:
            raise
        payload = json.loads(match.group(0))
    payload = _sanitize(payload)
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    overall_risk = str(summary.get("overall_risk") or "HIGH").upper()
    if overall_risk not in OVERALL_RISKS:
        overall_risk = "HIGH"
    overall_merit = str(summary.get("overall_merit") or "LOW").upper()
    if overall_merit not in OVERALL_MERITS:
        overall_merit = "LOW"
    recommendation = payload.get("final_recommendation") if isinstance(payload.get("final_recommendation"), dict) else {}
    action = str(recommendation.get("action") or "NEED_MORE_DATA").upper()
    if action not in ACTIONS:
        action = "NEED_MORE_DATA"
    normalized = {
        "summary": {
            "overall_risk": overall_risk,
            "overall_merit": overall_merit,
            "one_line_opinion": str(summary.get("one_line_opinion") or "확인 필요"),
        },
        "critical_risks": _ensure_list(payload.get("critical_risks"))[:8],
        "merits": _ensure_list(payload.get("merits"))[:8],
        "bid_price_analysis": payload.get("bid_price_analysis") if isinstance(payload.get("bid_price_analysis"), dict) else {
            "minimum_sale_price": None,
            "estimated_extra_costs": [],
            "safe_bid_logic": "확인 필요",
            "avoid_condition": "확인 필요",
        },
        "pre_bid_checklist": [str(item) for item in _ensure_list(payload.get("pre_bid_checklist"))][:10],
        "final_recommendation": {"action": action, "reason": str(recommendation.get("reason") or "확인 필요")},
    }
    # Compatibility fields used by the current web UI.
    normalized["summary_title"] = normalized["summary"]["one_line_opinion"]
    normalized["summary_bullets"] = [
        *(str(item.get("risk") or item) if isinstance(item, dict) else str(item) for item in normalized["critical_risks"][:3]),
        *(str(item.get("merit") or item) if isinstance(item, dict) else str(item) for item in normalized["merits"][:2]),
    ][:6]
    normalized["risk_label"] = normalized["summary"]["overall_risk"]
    normalized["risk_comment"] = normalized["final_recommendation"]["reason"]
    normalized["mobile_highlights"] = [
        f"위험도 {normalized['summary']['overall_risk']}",
        f"메리트 {normalized['summary']['overall_merit']}",
        f"권고 {normalized['final_recommendation']['action']}",
    ]
    return normalized


class OllamaClient:
    def __init__(self, base_url: str, model_name: str, *, timeout_seconds: int = 900):
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds

    def enrich(self, candidate: AuctionCandidate) -> dict[str, Any]:
        analysis_input = build_analysis_input(candidate)
        user_content = (
            "분석 대상 JSON:\n"
            f"{json.dumps(analysis_input, ensure_ascii=False)}"
        )
        response = requests.post(
            f"{self.base_url}/api/chat",
            json={
                "model": self.model_name,
                "stream": False,
                "format": response_schema(),
                "messages": [
                    {"role": "system", "content": PROMPT_SYSTEM},
                    {"role": "user", "content": user_content},
                ],
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return parse_model_response(response.json()["message"]["content"])
