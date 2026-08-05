from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Iterable

import pdfplumber


POLE_ID = r"(?<!\d)\d{9}(?!\d)"
RELATION_RE = re.compile(
    rf"(?:FROM\s+)?(?:POLE\s*)?#?({POLE_ID})\s+TO\s+(?:POLE\s*)?#?({POLE_ID})"
    r"(?:\s*\(\s*(\d+(?:\.\d+)?)\s*(?:FT|FEET|['’])?\s*\))?",
    re.IGNORECASE,
)
POLE_RE = re.compile(rf"(?:POLE\s*(?:ID|NO\.?|NUMBER)?\s*#?\s*)({POLE_ID})", re.IGNORECASE)
EID_RE = re.compile(r"\bEID\s*(?:ID|NO\.?|#|:)?\s*([A-Z0-9][A-Z0-9_-]{2,63})\b", re.IGNORECASE)
ANCHOR_RE = re.compile(
    rf"(?:NEW\s+)?ANCHOR(?:\s+(?:AT|ON))?\s+(?:EXIST(?:ING|\.)?\s+)?(?:POLE\s*)?#?({POLE_ID})",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TextLine:
    text: str
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True)
class ExtractedPage:
    page_number: int
    raw_text: str
    lines: tuple[TextLine, ...]
    page_width: float = 0.0
    page_height: float = 0.0


@dataclass(frozen=True)
class PoleEvidence:
    page_number: int
    evidence_type: str
    raw_text: str
    bbox: tuple[float, float, float, float]
    confidence: float
    pole_id: str | None = None
    from_pole_id: str | None = None
    to_pole_id: str | None = None
    span_length_ft: float | None = None
    external_eid: str | None = None


def _lines_from_words(words: list[dict]) -> tuple[TextLine, ...]:
    rows: list[list[dict]] = []
    for word in sorted(words, key=lambda item: (round(float(item["top"]), 1), float(item["x0"]))):
        top = float(word["top"])
        row = next((candidate for candidate in reversed(rows[-3:]) if abs(float(candidate[0]["top"]) - top) <= 3), None)
        if row is None:
            row = []
            rows.append(row)
        row.append(word)

    lines = []
    for row in rows:
        ordered = sorted(row, key=lambda item: float(item["x0"]))
        text = " ".join(str(item["text"]) for item in ordered).strip()
        if text:
            lines.append(TextLine(text, (
                min(float(item["x0"]) for item in ordered),
                min(float(item["top"]) for item in ordered),
                max(float(item["x1"]) for item in ordered),
                max(float(item["bottom"]) for item in ordered),
            )))
    return tuple(lines)


def extract_native_pages(
    content: bytes,
    *,
    max_pages: int = 500,
    max_words: int = 1_000_000,
) -> list[ExtractedPage]:
    pages: list[ExtractedPage] = []
    total_words = 0
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        if len(pdf.pages) > max_pages:
            raise ValueError(f"PDF contains more than {max_pages} pages.")
        for page_number, page in enumerate(pdf.pages, start=1):
            raw_text = page.extract_text(x_tolerance=2, y_tolerance=2) or ""
            words = page.extract_words(x_tolerance=2, y_tolerance=2, keep_blank_chars=False)
            total_words += len(words)
            if total_words > max_words:
                raise ValueError(f"PDF contains more than {max_words} extracted words.")
            pages.append(ExtractedPage(
                page_number,
                raw_text,
                _lines_from_words(words),
                float(page.width),
                float(page.height),
            ))
    return pages


def extract_evidence(pages: Iterable[ExtractedPage], *, max_evidence: int = 50_000) -> list[PoleEvidence]:
    evidence: list[PoleEvidence] = []
    seen: set[tuple] = set()
    for page in pages:
        for line in page.lines:
            relations = list(RELATION_RE.finditer(line.text))
            for match in relations:
                length = float(match.group(3)) if match.group(3) else None
                item = PoleEvidence(
                    page_number=page.page_number,
                    evidence_type="SPAN",
                    from_pole_id=match.group(1),
                    to_pole_id=match.group(2),
                    span_length_ft=length,
                    raw_text=line.text,
                    bbox=line.bbox,
                    confidence=0.98 if length is not None else 0.94,
                )
                key = (item.page_number, item.evidence_type, item.from_pole_id, item.to_pole_id, item.raw_text)
                if key not in seen:
                    seen.add(key)
                    evidence.append(item)

            for match in ANCHOR_RE.finditer(line.text):
                item = PoleEvidence(
                    page_number=page.page_number,
                    evidence_type="ANCHOR",
                    pole_id=match.group(1),
                    raw_text=line.text,
                    bbox=line.bbox,
                    confidence=0.96,
                )
                key = (item.page_number, item.evidence_type, item.pole_id, item.raw_text)
                if key not in seen:
                    seen.add(key)
                    evidence.append(item)

            relation_ids = {value for match in relations for value in match.groups()[:2]}
            eids = [match.group(1).upper() for match in EID_RE.finditer(line.text)]
            for match in POLE_RE.finditer(line.text):
                pole_id = match.group(1)
                if pole_id in relation_ids:
                    continue
                item = PoleEvidence(
                    page_number=page.page_number,
                    evidence_type="POLE_ID",
                    pole_id=pole_id,
                    raw_text=line.text,
                    bbox=line.bbox,
                    confidence=0.92,
                    external_eid=eids[0] if len(eids) == 1 else None,
                )
                key = (item.page_number, item.evidence_type, item.pole_id, item.raw_text)
                if key not in seen:
                    seen.add(key)
                    evidence.append(item)
            if not list(POLE_RE.finditer(line.text)):
                for eid in eids:
                    item = PoleEvidence(
                        page_number=page.page_number,
                        evidence_type="POLE_ID",
                        external_eid=eid,
                        raw_text=line.text,
                        bbox=line.bbox,
                        confidence=0.9,
                    )
                    key = (item.page_number, item.evidence_type, item.external_eid, item.raw_text)
                    if key not in seen:
                        seen.add(key)
                        evidence.append(item)
            if len(evidence) > max_evidence:
                raise ValueError(f"PDF contains more than {max_evidence} evidence records.")
    return evidence
