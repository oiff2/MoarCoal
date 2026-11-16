"""Die feste Grundkarte von Deutschland (Natural Earth, gemeinfrei) und ihre Projektion (#114).

`germany_map.json` erzeugt `scripts/make_germany_map.py` einmal zur Entwicklungszeit; die App holt
nie Kacheln oder Geodaten. Umriss und Landesgrenzen sind SVG-Pfade in Karteneinheiten; `project`
rechnet eine Lage in dieselben Einheiten um.
"""

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

MAP_FILE = Path(__file__).with_name("germany_map.json")


@dataclass(frozen=True)
class GermanyMap:
    min_lon: float
    max_lat: float
    scale_x: float
    scale_y: float
    width: float
    height: float
    outline: str
    borders: str

    def project(self, latitude: float, longitude: float) -> tuple[float, float] | None:
        """Karteneinheiten einer Lage; `None`, wenn sie außerhalb der Karte liegt."""
        x = (longitude - self.min_lon) * self.scale_x
        y = (self.max_lat - latitude) * self.scale_y
        inside = 0 <= x <= self.width and 0 <= y <= self.height
        return (round(x, 1), round(y, 1)) if inside else None


@cache
def germany_map() -> GermanyMap:
    data = json.loads(MAP_FILE.read_text(encoding="utf-8"))
    return GermanyMap(**{name: data[name] for name in GermanyMap.__dataclass_fields__})
