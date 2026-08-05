from __future__ import annotations

from pydantic import BaseModel


class PdfDocumentResult(BaseModel):
    id: str
    project_id: str
    filename: str
    sha256: str
    processing_status: str
    duplicate: bool


class PdfEvidenceResult(BaseModel):
    type: str
    page_number: int
    pole_id: str | None
    external_eid: str | None
    from_pole_id: str | None
    to_pole_id: str | None
    span_length_ft: float | None
    raw_text: str
    bbox: tuple[float, float, float, float]
    confidence: float


class PdfAssetMatch(BaseModel):
    pole_id: str
    asset_id: str
    asset_name: str
    confirmed_coordinates: bool


class PdfExtractionSummary(BaseModel):
    pages: int
    pages_with_native_text: int
    pole_ids: int
    spans: int
    anchors: int
    matched: int
    unmatched: int


class PdfPoleDryRunResponse(BaseModel):
    dry_run: bool
    assets_created: int
    document: PdfDocumentResult
    summary: PdfExtractionSummary
    pole_ids: list[str]
    poles: list[PdfEvidenceResult]
    spans: list[PdfEvidenceResult]
    anchors: list[PdfEvidenceResult]
    matched: list[PdfAssetMatch]
    unmatched: list[str]


class PdfWorkspaceEvidence(BaseModel):
    id: str
    type: str
    page_number: int
    pole_id: str | None
    external_eid: str | None
    from_pole_id: str | None
    to_pole_id: str | None
    span_length_ft: float | None
    raw_text: str
    bbox: tuple[float, float, float, float]
    confidence: float
    entity_ids: list[str]
    resolution_status: str
    matched_asset_id: str | None
    coordinates_available: bool
    review_status: str


class PdfWorkspaceResponse(BaseModel):
    document: PdfDocumentResult
    pages: int
    items: list[PdfWorkspaceEvidence]
    total: int
    offset: int
    limit: int
    page_width: float | None
    page_height: float | None


class EvidenceReviewRequest(BaseModel):
    status: str
