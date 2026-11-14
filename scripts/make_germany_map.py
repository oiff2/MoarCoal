# /// script
# requires-python = ">=3.13"
# dependencies = ["shapely>=2.0"]
# ///
"""Build `src/moarcoal/modules/work/germany_map.json`, the base map of the Dienstreisen page (#114).

Dev-time only, run once: the app itself never fetches geodata. Input is Natural Earth (public
domain), `ne_10m_admin_1_states_provinces.geojson` from
https://github.com/nvkelso/natural-earth-vector, downloaded into a folder of its own:

    uv run scripts/make_germany_map.py <path to the geojson> [<output json>]

Projection: equirectangular with the longitude scaled by cos(51.2 degrees), 100 units per degree of
latitude; `moarcoal.modules.work.germany_map` projects a position the same way from the constants
stored in the output.
"""

import json
import math
import sys
from pathlib import Path

from shapely.geometry import MultiPolygon, Polygon, shape
from shapely.ops import unary_union

MID_LATITUDE = 51.2
UNITS_PER_DEGREE = 100
TOLERANCE_DEGREES = 0.012


def main(source: Path, target: Path) -> None:
    features = json.loads(source.read_text(encoding="utf-8"))["features"]
    states = [shape(f["geometry"]) for f in features if f["properties"].get("admin") == "Germany"]
    if len(states) != 16:
        raise SystemExit(f"expected 16 Bundesländer, found {len(states)}")
    states = [s.simplify(TOLERANCE_DEGREES, preserve_topology=True) for s in states]
    outline = (
        unary_union([s.buffer(0.002) for s in states]).buffer(-0.002).simplify(TOLERANCE_DEGREES)
    )
    min_lon, min_lat, max_lon, max_lat = outline.bounds
    scale_x = math.cos(math.radians(MID_LATITUDE)) * UNITS_PER_DEGREE

    def project(lon: float, lat: float) -> tuple[float, float]:
        return (lon - min_lon) * scale_x, (max_lat - lat) * UNITS_PER_DEGREE

    def ring_path(ring) -> str:
        points = [project(x, y) for x, y in ring.coords]
        return "M" + "L".join(f"{x:.1f} {y:.1f}" for x, y in points[:-1]) + "Z"

    def path(geometry) -> str:
        polygons = geometry.geoms if isinstance(geometry, MultiPolygon) else [geometry]
        assert all(isinstance(p, Polygon) for p in polygons)
        return "".join(ring_path(p.exterior) for p in polygons if p.area > 0.004)

    width, height = project(max_lon, min_lat)
    document = {
        "source": "Natural Earth 1:10m Admin 1 (public domain), simplified",
        "min_lon": round(min_lon, 4),
        "max_lat": round(max_lat, 4),
        "scale_x": round(scale_x, 4),
        "scale_y": UNITS_PER_DEGREE,
        "width": round(width, 1),
        "height": round(height, 1),
        "outline": path(outline),
        "borders": "".join(path(s) for s in states),
    }
    target.write_text(json.dumps(document, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{target}: {target.stat().st_size} bytes, {document['width']} x {document['height']}")


if __name__ == "__main__":
    main(
        Path(sys.argv[1]),
        Path(sys.argv[2] if len(sys.argv) > 2 else "src/moarcoal/modules/work/germany_map.json"),
    )
