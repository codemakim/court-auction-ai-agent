from dataclasses import dataclass


@dataclass(frozen=True)
class AuctionCandidate:
    auction_id: int
    external_key: str
    case_number: str
    item_number: str
    address: str
    property_category: str | None
    residential_subtype: str | None
    appraisal_value: int | None
    minimum_sale_price: int | None
    failed_auction_count: int | None
    sale_date: str | None
    current_status: str | None
    appraisal_summary: str | None
    document_id: int
    document_content_hash: str | None
    text_id: int
    sale_spec_markdown: str
    source_hash: str
