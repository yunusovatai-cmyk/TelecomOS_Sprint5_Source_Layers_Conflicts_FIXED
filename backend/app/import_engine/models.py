from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ImportFeature:
    name: str
    geometry_type: str
    coordinates: object
    folder: str | None = None
    style_url: str | None = None
    description: str | None = None
    extended_data: dict[str, str] = field(default_factory=dict)


@dataclass
class ImportResult:
    project_name: str
    features: list[ImportFeature]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
