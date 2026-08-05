from __future__ import annotations

from xml.etree import ElementTree as ET

from app.import_engine.models import ImportFeature, ImportResult

KML_NS = {"kml": "http://www.opengis.net/kml/2.2"}


def _parse_coordinates(text: str | None) -> list[list[float]]:
    values: list[list[float]] = []
    for chunk in (text or "").strip().split():
        parts = chunk.split(",")
        if len(parts) < 2:
            continue
        values.append([float(parts[0]), float(parts[1])])
    return values


def _folder_name(placemark: ET.Element, parent_map: dict[ET.Element, ET.Element]) -> str | None:
    node = parent_map.get(placemark)
    while node is not None:
        if node.tag.endswith("Folder"):
            name = node.findtext("kml:name", default="", namespaces=KML_NS).strip()
            return name or None
        node = parent_map.get(node)
    return None


def parse_kml(kml_bytes: bytes) -> ImportResult:
    root = ET.fromstring(kml_bytes)
    parent_map = {child: parent for parent in root.iter() for child in parent}

    project_name = (
        root.findtext(".//kml:Document/kml:name", default="", namespaces=KML_NS).strip()
        or "Imported KMZ Project"
    )

    features: list[ImportFeature] = []
    warnings: list[str] = []

    for placemark in root.findall(".//kml:Placemark", KML_NS):
        name = placemark.findtext("kml:name", default="Unnamed feature", namespaces=KML_NS).strip()
        style_url = placemark.findtext("kml:styleUrl", default="", namespaces=KML_NS).strip() or None
        description = placemark.findtext("kml:description", default="", namespaces=KML_NS).strip() or None

        extended: dict[str, str] = {}
        for data in placemark.findall(".//kml:ExtendedData/kml:Data", KML_NS):
            key = data.attrib.get("name")
            value = data.findtext("kml:value", default="", namespaces=KML_NS)
            if key:
                extended[key] = value

        point_text = placemark.findtext(".//kml:Point/kml:coordinates", default="", namespaces=KML_NS)
        line_text = placemark.findtext(".//kml:LineString/kml:coordinates", default="", namespaces=KML_NS)

        if point_text.strip():
            coordinates = _parse_coordinates(point_text)
            if not coordinates:
                warnings.append(f"{name}: invalid Point coordinates")
                continue
            geometry_type = "Point"
            geometry_coordinates: object = coordinates[0]
        elif line_text.strip():
            coordinates = _parse_coordinates(line_text)
            if len(coordinates) < 2:
                warnings.append(f"{name}: invalid LineString coordinates")
                continue
            geometry_type = "LineString"
            geometry_coordinates = coordinates
        else:
            warnings.append(f"{name}: unsupported or missing geometry")
            continue

        features.append(
            ImportFeature(
                name=name,
                geometry_type=geometry_type,
                coordinates=geometry_coordinates,
                folder=_folder_name(placemark, parent_map),
                style_url=style_url,
                description=description,
                extended_data=extended,
            )
        )

    return ImportResult(
        project_name=project_name,
        features=features,
        warnings=warnings,
    )
