"""Export compact Pulse jurisdiction artwork without importing native geometry into JS."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO.parent / "pulse-gov-native"
STATE_CODES = (
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO "
    "MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY"
).split()
MAX_SOURCE_BYTES = 1024 * 1024
SOURCE_FILES = (
    "SSANative/Views/StateSeal.swift",
    "SSANative/Views/VerificationArtworkStyle.swift",
    "SSANative/Design/SealDrawing.swift",
    "SSANative/Design/SealGeography.swift",
    "SSANative/Design/Theme.swift",
    "SSANative/Design/Tokens.generated.swift",
)


def digest(path: Path) -> str:
    if path.stat().st_size > MAX_SOURCE_BYTES:
        raise ValueError("Artwork input exceeds its size budget")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def finite_point(point: list) -> bool:
    return len(point) == 2 and all(
        isinstance(value, (int, float)) and math.isfinite(value) and 0 <= value <= 1
        for value in point
    )


def read_geography(path: Path, code: str) -> dict:
    if path.stat().st_size > MAX_SOURCE_BYTES:
        raise ValueError("Geography exceeds its size budget")
    geography = json.loads(path.read_bytes())
    if geography["version"] != 1 or geography["code"] != code:
        raise ValueError("Unexpected geography identity")
    if not finite_point(geography["centroid"]) or not all(
        math.isfinite(geography[key]) and geography[key] > 0 for key in ("area", "reach")
    ):
        raise ValueError("Invalid geography fit")
    rings = [ring for polygon in geography["polygons"] for ring in polygon]
    if not rings or sum(len(ring) for ring in rings) > 100_000:
        raise ValueError("Invalid geography point budget")
    if not all(len(ring) >= 3 and all(finite_point(point) for point in ring) for ring in rings):
        raise ValueError("Invalid geography coordinates")
    return geography


def plate() -> list[str]:
    """Quantize the native 135-degree blue/sand gradient into circular caps.

    Each cap lies entirely inside the plate. No clipping, paint servers, raster
    images, external references or SVG definitions are required.
    """
    layers = ['<circle cx="40" cy="40" r="40" fill="#e4d5bd"/>']
    for band in range(31, -1, -1):
        distance = (band / 32 - 0.5) * 80
        tangent = math.sqrt(40**2 - distance**2)
        x1 = 40 + (distance + tangent) / math.sqrt(2)
        y1 = 40 + (distance - tangent) / math.sqrt(2)
        x2, y2 = y1, x1
        # Native gradient endpoints are centered at +/- 40 along its diagonal.
        rgb = tuple(
            round(a + (b - a) * band / 32)
            for a, b in zip((183, 206, 224), (228, 213, 189), strict=True)
        )
        color = "#" + "".join(f"{v:02x}" for v in rgb)
        layers.append(
            f'<path d="M{x1:.2f} {y1:.2f}A40 40 0 {int(distance > 0)} 0 '
            f'{x2:.2f} {y2:.2f}Z" fill="{color}"/>'
        )
    layers.append(
        '<circle cx="40" cy="40" r="39.5" fill="none" stroke="#617e99" stroke-width="1"/>'
    )
    return layers


def geography_path(geography: dict) -> str:
    scale = 39.6 * min(math.sqrt(0.5 * math.pi / geography["area"]), 0.92 / geography["reach"])
    cx, cy = geography["centroid"]
    paths = []
    for polygon in geography["polygons"]:
        for ring in polygon:
            points = [(40 + (x - cx) * scale, 40 + (y - cy) * scale) for x, y in ring]
            assert all(math.isfinite(x) and math.isfinite(y) for x, y in points)
            paths.append("M" + "L".join(f"{x:.2f} {y:.2f}" for x, y in points) + "Z")
    return "".join(paths)


def export() -> dict:
    destination = REPO / "web/public/artwork/states"
    destination.mkdir(parents=True, exist_ok=True)
    assets = []
    for code in sorted(STATE_CODES):
        input_path = SOURCE_ROOT / f"SSANative/Resources/SealGeography/seal-geography-{code}.json"
        geography = read_geography(input_path, code)
        land = (
            f'<path d="{geography_path(geography)}" fill="#647e92" fill-opacity="0.439216" '
            'fill-rule="evenodd" stroke="#17232f" stroke-opacity="0.45" '
            'stroke-width="0.5" stroke-linejoin="round"/>'
        )
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="80" height="80" '
            'viewBox="0 0 80 80" data-cadastre-diagram="independent">'
            + "".join(plate())
            + land
            + "</svg>\n"
        )
        output = destination / f"{code}.svg"
        output.write_text(svg)
        assets.append(
            {
                "code": code,
                "source": str(input_path.relative_to(SOURCE_ROOT)),
                "source_sha256": digest(input_path),
                "asset": str(output.relative_to(REPO)),
                "asset_sha256": digest(output),
                "bytes": output.stat().st_size,
            }
        )
    return {
        "schema_version": 1,
        "source_repository": "pulse-gov-native",
        "source_revision": subprocess.check_output(
            ["git", "-C", str(SOURCE_ROOT), "rev-parse", "HEAD"], text=True
        ).strip(),
        "source_checkout_dirty": bool(
            subprocess.check_output(
                ["git", "-C", str(SOURCE_ROOT), "status", "--porcelain"], text=True
            ).strip()
        ),
        "source_files": [
            {"path": name, "sha256": digest(SOURCE_ROOT / name)} for name in SOURCE_FILES
        ],
        "description": "Decorative jurisdiction artwork; not official seals or identity evidence.",
        "rendering": {
            "size": 80,
            "compact_disc": 0.99,
            "area_target": "0.5*pi",
            "reach_limit": 0.92,
            "native_gradient_degrees": 135,
            "native_gradient_stops": ["#b7cee0", "#e4d5bd"],
            "plate_approximation": "32 diagonal circular caps; no SVG paint servers",
            "geography": "All native rings retained; coordinates rounded to 0.01 SVG units",
            "legend": False,
            "location_marker": False,
        },
        "assets": assets,
    }


if __name__ == "__main__":
    provenance = export()
    record = REPO / "docs/artwork/state-badges.json"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(json.dumps(provenance, indent=2) + "\n")
    total_bytes = sum(a["bytes"] for a in provenance["assets"])
    print(f"Exported {len(provenance['assets'])} state badges ({total_bytes:,} bytes)")
