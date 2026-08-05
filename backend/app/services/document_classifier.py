from __future__ import annotations
import re
from pathlib import Path

def extract_revision(filename: str) -> str | None:
    stem = Path(filename).stem
    for pattern in (r"\brev(?:ision)?[-_ ]*([A-Za-z0-9.]+)\b", r"\br([0-9]{1,3})\b", r"\bv([0-9]+(?:\.[0-9]+)*)\b"):
        match = re.search(pattern, stem, flags=re.IGNORECASE)
        if match:
            return match.group(1).upper()
    return None

def classify_document(filename: str, mime_type: str | None = None) -> str:
    name = filename.lower()
    suffix = Path(filename).suffix.lower()
    if suffix == ".kmz": return "KMZ"
    if suffix == ".kml": return "KML"
    if suffix in {".xlsx", ".xls", ".csv"}: return "SPREADSHEET"
    if suffix in {".jpg", ".jpeg", ".png", ".heic", ".webp"}: return "PHOTO"
    if suffix == ".pdf":
        if any(x in name for x in ("ug permit","ug_permit","ugp","encroachment")): return "UG_PERMIT"
        if any(x in name for x in ("make ready","make_ready","makeready")): return "MAKE_READY"
        if "prm" in name: return "PRM"
        if any(x in name for x in ("as-built","as_built","asbuilt")): return "AS_BUILT"
        return "PDF"
    if suffix == ".zip": return "PROJECT_PACKAGE"
    return "UNKNOWN"
