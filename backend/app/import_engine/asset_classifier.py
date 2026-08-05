from __future__ import annotations

from app.import_engine.models import ImportFeature


def classify_asset(feature: ImportFeature) -> str:
    text = " ".join(
        value for value in [
            feature.name,
            feature.folder or "",
            feature.style_url or "",
        ]
    ).lower()

    if feature.geometry_type == "Point":
        if any(token in text for token in ("handhole", "hand hole", "hh-", "vault")):
            return "HANDHOLE"
        return "POLE"

    if any(token in text for token in ("aerial", "overlash", "span")):
        return "AERIAL_SPAN"
    return "UG_SEGMENT"


def infer_status(feature: ImportFeature) -> tuple[str, str | None]:
    text = " ".join(
        value for value in [
            feature.folder or "",
            feature.style_url or "",
            feature.description or "",
        ]
    ).lower()

    if "not approved" in text or "notapproved" in text or "missing" in text:
        return "REVIEW", "Approval not found"
    if "approved" in text:
        return "VERIFIED", None
    return "REVIEW", "Imported object requires engineering review"
