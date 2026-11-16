"""Measured site azimuth ONLY: no Bát Trạch, Kua, or auspicious direction rules.

Coordinates use an arbitrary 2D CAD XY frame. north_vector points *toward true north*
expressed in that frame; frontage_outward_vector points from the building toward the
street, not along the frontage line. Both vectors must be supplied by the designer.
"""

import math

from vnai.orientation import OCTANTS, azimuth_octant

BOUNDARY_EPSILON = 1e-9  # numerical boundary detection, not measurement accuracy
REQUIRED = (
    "north_reference",
    "north_vector_drawing_xy",
    "frontage_outward_vector_drawing_xy",
    "facing_definition",
    "measurement_uncertainty_degrees",
)


def _vector(value: object, name: str) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{name} must be a pair of finite numbers")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in value):
        raise ValueError(f"{name} must be numeric, not booleans")
    x, y = (float(value[0]), float(value[1]))
    if not math.isfinite(x) or not math.isfinite(y):
        raise ValueError(f"{name} must be finite")
    length = math.hypot(x, y)
    if length == 0 or not math.isfinite(length):
        raise ValueError(f"{name} must be nonzero and finite")
    return x / length, y / length


def bearing_from_vectors(north_vector: object, outward_vector: object) -> float:
    """Clockwise azimuth 0..360 from drawing-coordinate true north to outward facing.

    The 2D convention is right-handed: +90 degrees is clockwise when viewed from above.
    If north=(0,1), east=(1,0), then outward=(1,0) is 90 degrees.
    """
    nx, ny = _vector(north_vector, "north_vector_drawing_xy")
    fx, fy = _vector(outward_vector, "frontage_outward_vector_drawing_xy")
    east_projection = fx * ny - fy * nx
    north_projection = fx * nx + fy * ny
    return math.degrees(math.atan2(east_projection, north_projection)) % 360.0


def direction_with_uncertainty(bearing: float, uncertainty: float) -> dict:
    """Return 8-way label, or both neighbor labels when a sector boundary is possible.

    This only classifies compass sectors. Half-open octants in `azimuth_octant` are
    deterministic, but near-boundary measurements must not falsely imply certainty.
    """
    if isinstance(uncertainty, bool) or not isinstance(uncertainty, (int, float)):
        raise ValueError("measurement_uncertainty_degrees must be numeric")
    uncertainty = float(uncertainty)
    if not math.isfinite(uncertainty) or not 0 <= uncertainty < 22.5:
        raise ValueError("measurement_uncertainty_degrees must be in [0, 22.5)")
    if isinstance(bearing, bool) or not isinstance(bearing, (int, float)):
        raise ValueError("bearing must be numeric")
    bearing = float(bearing)
    if not math.isfinite(bearing):
        raise ValueError("bearing must be finite")
    angle = bearing % 360.0
    nearest = min(range(8), key=lambda i: abs(((angle - (22.5 + 45 * i) + 180) % 360) - 180))
    boundary = (22.5 + nearest * 45) % 360
    distance = abs(((angle - boundary + 180) % 360) - 180)
    if distance <= uncertainty + BOUNDARY_EPSILON:
        return {
            "status": "AMBIGUOUS_BOUNDARY",
            "direction": None,
            "possible_directions": [OCTANTS[nearest], OCTANTS[(nearest + 1) % 8]],
            "nearest_boundary_degrees": boundary,
            "distance_to_boundary_degrees": round(distance, 6),
        }
    label = azimuth_octant(angle)
    return {
        "status": "UNAMBIGUOUS",
        "direction": label,
        "possible_directions": [label],
        "nearest_boundary_degrees": boundary,
        "distance_to_boundary_degrees": round(distance, 6),
    }


def review_site_orientation(payload: object) -> dict:
    """Non-executable cultural review: report geometry; block unverified feng shui rules."""
    if not isinstance(payload, dict):
        raise ValueError("Orientation input must be a JSON object")
    if payload.get("schema_version") != 1 or isinstance(payload.get("schema_version"), bool):
        raise ValueError("schema_version must be 1")
    site_id = payload.get("site_id")
    if not isinstance(site_id, str) or not site_id.strip():
        raise ValueError("site_id must be a nonempty string")
    extra = sorted(set(payload) - set(REQUIRED) - {"site_id", "schema_version"})
    if extra:
        raise ValueError(f"Unknown orientation fields: {', '.join(extra)}")
    missing = [name for name in REQUIRED if payload.get(name) is None]
    if payload.get("north_reference") not in (None, "true_north"):
        # Magnetic/grid north requires a verified conversion, not a silent assumption.
        missing.append("verified_true_north_conversion")
    if payload.get("facing_definition") not in (None, "building_to_street"):
        missing.append("confirmed_frontage_outward_direction")
    if missing:
        return {
            "site_id": site_id,
            "status": "NEEDS_DATA",
            "missing_or_unconfirmed": list(dict.fromkeys(missing)),
            "fengshui": {"status": "NEEDS_SOURCE_REVIEW", "rules_applied": []},
            "technical_standards": {"status": "NOT_EVALUATED"},
            "cad_writes_permitted": False,
        }
    azimuth = bearing_from_vectors(
        payload["north_vector_drawing_xy"], payload["frontage_outward_vector_drawing_xy"]
    )
    sector = direction_with_uncertainty(azimuth, payload["measurement_uncertainty_degrees"])
    return {
        "site_id": site_id,
        "status": "COMPUTED" if sector["status"] == "UNAMBIGUOUS" else "NEEDS_REVIEW",
        "bearing_degrees_clockwise_from_true_north": round(azimuth, 6),
        "sector": sector,
        "measurement_uncertainty_degrees": float(payload["measurement_uncertainty_degrees"]),
        "fengshui": {
            "status": "NEEDS_SOURCE_REVIEW",
            "rules_applied": [],
            "note": "Compass geometry only; no Bát Trạch, Kua, or Môn–Chủ–Táo inference.",
        },
        "technical_standards": {"status": "NOT_EVALUATED"},
        "cad_writes_permitted": False,
    }
