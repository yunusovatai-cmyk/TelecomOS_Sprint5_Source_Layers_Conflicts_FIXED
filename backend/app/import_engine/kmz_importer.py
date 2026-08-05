from __future__ import annotations

import io
import zipfile

from app.import_engine.models import ImportResult
from app.import_engine.parsers.kml_parser import parse_kml


def parse_kmz(content: bytes) -> ImportResult:
    try:
        with zipfile.ZipFile(io.BytesIO(content), "r") as archive:
            kml_files = [
                name for name in archive.namelist()
                if name.lower().endswith(".kml")
            ]
            if not kml_files:
                raise ValueError("KMZ archive does not contain a KML document.")
            return parse_kml(archive.read(kml_files[0]))
    except zipfile.BadZipFile as exc:
        raise ValueError("Uploaded file is not a valid KMZ archive.") from exc


def parse_kml_content(content: bytes) -> ImportResult:
    return parse_kml(content)
