"""US National CAD Standard layer-name parsing.

NCS layer names are dash-delimited fields:

    <discipline>-<major>-<minor>-<modifier>-<status>

Only the first two are required; trailing fields are optional. The
discipline is a single letter (``A`` for architecture, ``S`` for
structural, etc.); the rest are 4-character codes.

Examples this module handles correctly:

    A-WALL                       discipline + major
    A-WALL-EXTR                  + minor
    A-WALL-EXTR-FULL             + modifier
    A-WALL-EXTR-FULL-N           + status (new)
    S-COLS                       structural columns
    A-DOOR                       doors
    A-FLOR-FIXT                  floor fixtures
    a-wall-extr                  case-insensitive

We don't validate against an authoritative NCS code list — the spec
is large and clients use extensions. We *do* surface a structural
``is_well_formed`` flag so downstream code knows whether to trust
the parsed groups vs. fall back to the raw layer string.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from atlas_core import ElementKind

# NCS discipline codes (single uppercase letter at field 0).
DISCIPLINES: dict[str, str] = {
    "A": "Architecture",
    "C": "Civil",
    "E": "Electrical",
    "F": "Fire Protection",
    "G": "General",
    "H": "Hazardous Materials",
    "I": "Interiors",
    "L": "Landscape",
    "M": "Mechanical",
    "P": "Plumbing",
    "Q": "Equipment",
    "R": "Resource",
    "S": "Structural",
    "T": "Telecommunications",
    "V": "Survey / Mapping",
    "X": "Other Disciplines",
    "Z": "Contractor / Shop Drawings",
}

# Common Major-group codes from the NCS / AIA Layer Guidelines.
# Maps to ``ElementKind`` where Atlas has a first-class element type.
# Codes not in this map fall through to ``ElementKind.OTHER``.
MAJOR_GROUP_TO_KIND: dict[str, ElementKind] = {
    "WALL": ElementKind.WALL,
    "DOOR": ElementKind.DOOR,
    "WIND": ElementKind.WINDOW,
    "GLAZ": ElementKind.WINDOW,  # glazing — usually windows on architectural
    "COLS": ElementKind.COLUMN,
    "COLU": ElementKind.COLUMN,
    "STRS": ElementKind.STAIR,
    "STAR": ElementKind.STAIR,
    "ROOM": ElementKind.ROOM,
    "AREA": ElementKind.ROOM,
    "SPCE": ElementKind.ROOM,
    "DIMS": ElementKind.DIMENSION,
    "DIME": ElementKind.DIMENSION,
    "ANNO": ElementKind.ANNOTATION,
    "IDEN": ElementKind.ANNOTATION,
    "TEXT": ElementKind.ANNOTATION,
    "SYMB": ElementKind.SYMBOL,
}

# Field constraints for the well-formedness check.
_DISCIPLINE_RE = re.compile(r"^[A-Z]$")
_GROUP_RE = re.compile(r"^[A-Z0-9]{1,4}$")


@dataclass(frozen=True, slots=True)
class NcsLayer:
    """Parsed result of a single layer name.

    All group fields are uppercased even when the input was lowercase.
    ``is_well_formed`` is True when the discipline character is one of
    the canonical NCS letters and every present group fits the
    1-4 alphanumeric constraint.
    """

    raw: str
    discipline: str | None
    major_group: str | None
    minor_group: str | None
    modifier: str | None
    status: str | None

    @property
    def discipline_name(self) -> str | None:
        """Human-readable discipline (``"Architecture"``) or None."""
        return DISCIPLINES.get(self.discipline) if self.discipline else None

    @property
    def is_well_formed(self) -> bool:
        """True when the layer parses cleanly per NCS field shape."""
        if not self.discipline or not _DISCIPLINE_RE.match(self.discipline):
            return False
        if self.discipline not in DISCIPLINES:
            return False
        if not self.major_group:
            return False
        for field in (self.major_group, self.minor_group, self.modifier, self.status):
            if field is not None and not _GROUP_RE.match(field):
                return False
        return True

    @property
    def element_kind(self) -> ElementKind | None:
        """Map the Major group to an ElementKind, if known.

        Returns None when the layer is malformed; returns
        ``ElementKind.OTHER`` when the major group is structurally
        valid but isn't in the mapping table.
        """
        if not self.is_well_formed or not self.major_group:
            return None
        return MAJOR_GROUP_TO_KIND.get(self.major_group, ElementKind.OTHER)


def parse_layer(name: str) -> NcsLayer:
    """Parse a single layer name into its NCS fields.

    Always returns an :class:`NcsLayer` — never raises. Use
    :attr:`NcsLayer.is_well_formed` and :attr:`NcsLayer.element_kind`
    to decide how much to trust the result.
    """
    cleaned = (name or "").strip().upper()
    if not cleaned:
        return NcsLayer(raw=name, discipline=None, major_group=None,
                        minor_group=None, modifier=None, status=None)

    parts = cleaned.split("-")
    fields: list[str | None] = list(parts) + [None] * (5 - len(parts))
    discipline, major, minor, modifier, status = fields[:5]

    return NcsLayer(
        raw=name,
        discipline=discipline,
        major_group=major,
        minor_group=minor,
        modifier=modifier,
        status=status,
    )


def parse_layers(names: list[str]) -> list[NcsLayer]:
    """Convenience: parse a batch."""
    return [parse_layer(n) for n in names]
