"""Drawing units, scale conversions, CAD layer policies and drawing styles."""

from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
import re
from typing import Any

LAYER_POLICY_VERSION = "vnai-cad-layers-v1"
LAYER_POLICY_AUTHORITY = "project_convention_not_mandatory_standard"
VALID_LINETYPES = frozenset({"CONTINUOUS", "DASHED", "DASHDOT", "CENTER", "DOTTED"})
_ILLEGAL_CAD_LAYER_RE = re.compile(r'[<>/\\":;?*|=]')

UNIT_TO_MM: dict[str, Decimal] = {
    "mm": Decimal("1"),
    "m": Decimal("1000"),
}

DEFAULT_LAYERS: tuple[dict[str, Any], ...] = (
    {
        "name": "A-WALL-EXT",
        "entity_category": "exterior_wall",
        "aci_color": 7,
        "svg_color": "#111827",
        "linetype": "CONTINUOUS",
        "lineweight_mm": 0.35,
        "visible": True,
        "plottable": True,
    },
    {
        "name": "A-WALL-INT",
        "entity_category": "interior_wall",
        "aci_color": 8,
        "svg_color": "#374151",
        "linetype": "CONTINUOUS",
        "lineweight_mm": 0.25,
        "visible": True,
        "plottable": True,
    },
    {
        "name": "A-DOOR",
        "entity_category": "door",
        "aci_color": 3,
        "svg_color": "#1f2937",
        "linetype": "CONTINUOUS",
        "lineweight_mm": 0.20,
        "visible": True,
        "plottable": True,
    },
    {
        "name": "A-DOOR-SWING",
        "entity_category": "door_swing",
        "aci_color": 9,
        "svg_color": "#4b5563",
        "linetype": "DASHED",
        "lineweight_mm": 0.13,
        "visible": True,
        "plottable": True,
    },
    {
        "name": "A-WIND",
        "entity_category": "window",
        "aci_color": 4,
        "svg_color": "#1f2937",
        "linetype": "CONTINUOUS",
        "lineweight_mm": 0.18,
        "visible": True,
        "plottable": True,
    },
    {
        "name": "A-STAIR",
        "entity_category": "stair",
        "aci_color": 5,
        "svg_color": "#1f2937",
        "linetype": "CONTINUOUS",
        "lineweight_mm": 0.20,
        "visible": True,
        "plottable": True,
    },
    {
        "name": "A-STAIR-ABOVE",
        "entity_category": "stair_above_cut",
        "aci_color": 9,
        "svg_color": "#6b7280",
        "linetype": "DASHED",
        "lineweight_mm": 0.13,
        "visible": True,
        "plottable": True,
    },
    {
        "name": "A-ROOM-TEXT",
        "entity_category": "room_annotation",
        "aci_color": 7,
        "svg_color": "#111827",
        "linetype": "CONTINUOUS",
        "lineweight_mm": 0.18,
        "visible": True,
        "plottable": True,
    },
    {
        "name": "A-OPENING-TAG",
        "entity_category": "opening_tag",
        "aci_color": 2,
        "svg_color": "#111827",
        "linetype": "CONTINUOUS",
        "lineweight_mm": 0.15,
        "visible": True,
        "plottable": True,
    },
    {
        "name": "A-DIMS",
        "entity_category": "dimension",
        "aci_color": 1,
        "svg_color": "#374151",
        "linetype": "CONTINUOUS",
        "lineweight_mm": 0.13,
        "visible": True,
        "plottable": True,
    },
    {
        "name": "A-GRID",
        "entity_category": "reference_grid",
        "aci_color": 8,
        "svg_color": "#6b7280",
        "linetype": "DASHDOT",
        "lineweight_mm": 0.13,
        "visible": True,
        "plottable": True,
    },
    {
        "name": "A-LEVEL",
        "entity_category": "level_mark",
        "aci_color": 6,
        "svg_color": "#1f2937",
        "linetype": "CONTINUOUS",
        "lineweight_mm": 0.18,
        "visible": True,
        "plottable": True,
    },
    {
        "name": "A-SECT",
        "entity_category": "section_marker",
        "aci_color": 6,
        "svg_color": "#111827",
        "linetype": "DASHDOT",
        "lineweight_mm": 0.25,
        "visible": True,
        "plottable": True,
    },
    {
        "name": "A-HATCH",
        "entity_category": "hatch",
        "aci_color": 253,
        "svg_color": "#d1d5db",
        "linetype": "CONTINUOUS",
        "lineweight_mm": 0.09,
        "visible": True,
        "plottable": True,
    },
    {
        "name": "A-REVIEW",
        "entity_category": "review_overlay",
        "aci_color": 1,
        "svg_color": "#b91c1c",
        "linetype": "DASHED",
        "lineweight_mm": 0.18,
        "visible": True,
        "plottable": False,
    },
)

COLOR_OVERRIDES: dict[str, str] = {
    "A-WALL-EXT": "#111827",
    "A-WALL-INT": "#374151",
    "A-DOOR": "#92400e",
    "A-DOOR-SWING": "#b45309",
    "A-WIND": "#0284c7",
    "A-STAIR": "#1d4ed8",
    "A-STAIR-ABOVE": "#6366f1",
    "A-ROOM-TEXT": "#111827",
    "A-OPENING-TAG": "#0f766e",
    "A-DIMS": "#334155",
    "A-GRID": "#64748b",
    "A-LEVEL": "#0369a1",
    "A-SECT": "#7c2d12",
    "A-HATCH": "#cbd5e1",
    "A-REVIEW": "#b91c1c",
}

STYLE_DEFAULTS: dict[str, Any] = {
    "name": "arch-mono-v1",
    "text_style_ref": "STANDARD-VN-UNICODE",
    "font_family": "Noto Sans, Segoe UI, Arial, sans-serif",
    "proprietary_font_bundled": False,
    "paper_text_height_mm": 2.4,
    "paper_dim_text_height_mm": 2.0,
    "paper_arrow_size_mm": 1.6,
    "paper_dim_offset_mm": 8.0,
    "paper_chain_spacing_mm": 7.5,
    "paper_extension_offset_mm": 1.5,
    "paper_extension_overshoot_mm": 1.5,
    "paper_grid_bubble_radius_mm": 3.5,
    "tick_style": "slash",
    "hatch_enabled": True,
    "hatch_presentation": "solid_light_fill_with_45deg_pattern",
}


def dec(value: int | float | str | Decimal) -> Decimal:
    """Parse finite numeric scalar to Decimal deterministically."""
    if isinstance(value, bool):
        raise ValueError("Boolean is not a valid numeric measurement.")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    return Decimal(str(value))


def zero_float(value: Decimal | float | int) -> float:
    """Convert Decimal or numeric to float with -0.0 normalized to 0.0."""
    out = float(value)
    return 0.0 if out == 0.0 else out


def convert_length(
    value: int | float | Decimal,
    from_unit: str,
    to_unit: str,
) -> Decimal:
    """Convert a linear length using exact Decimal arithmetic."""
    if from_unit not in UNIT_TO_MM or to_unit not in UNIT_TO_MM:
        raise ValueError(f"Unsupported unit conversion: {from_unit} -> {to_unit}")
    val = dec(value)
    if from_unit == to_unit:
        return val
    return (val * UNIT_TO_MM[from_unit]) / UNIT_TO_MM[to_unit]


def convert_point(
    point: tuple[float, float] | list[float],
    from_unit: str,
    to_unit: str,
) -> list[float]:
    """Convert a 2D coordinate pair exactly once between source and drawing units."""
    return [
        zero_float(convert_length(point[0], from_unit, to_unit)),
        zero_float(convert_length(point[1], from_unit, to_unit)),
    ]


def convert_points(
    points: list[tuple[float, float] | list[float]],
    from_unit: str,
    to_unit: str,
) -> list[list[float]]:
    """Convert a sequence of 2D points cleanly."""
    return [convert_point(p, from_unit, to_unit) for p in points]


def format_measurement(value_dec: Decimal, precision: int) -> tuple[str, Decimal, Decimal]:
    """Format a measurement with ROUND_HALF_UP while preserving exact discrepancy."""
    q = Decimal("1") if precision == 0 else Decimal("1e-" + str(precision))
    displayed = value_dec.quantize(q, rounding=ROUND_HALF_UP)
    if displayed == 0:
        displayed = Decimal("0")
    text = f"{displayed:.{precision}f}" if precision > 0 else f"{int(displayed)}"
    discrepancy = displayed - value_dec
    return text, displayed, discrepancy


def paper_to_model(
    paper_mm: int | float | Decimal,
    scale_denominator: int | float | Decimal,
    drawing_units: str,
) -> float:
    """Convert paper-space millimetres into model-space drawing units at the active scale."""
    model_mm = dec(paper_mm) * dec(scale_denominator)
    return zero_float(convert_length(model_mm, "mm", drawing_units))


def build_unit_policy(
    source_units: str,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build explicit unit policy preventing double conversion."""
    cfg = cfg or {}
    drawing_units = cfg.get("drawing_units", "mm")
    if drawing_units not in UNIT_TO_MM:
        raise ValueError(f"Unsupported drawing_units: {drawing_units}")
    if source_units not in UNIT_TO_MM:
        raise ValueError(f"Unsupported source_units: {source_units}")
    precision = (
        int(cfg.get("display_precision_mm", 0))
        if drawing_units == "mm"
        else int(cfg.get("display_precision_m", 3))
    )
    return {
        "source_units": source_units,
        "drawing_units": drawing_units,
        "conversion_factor_source_to_drawing": zero_float(
            UNIT_TO_MM[source_units] / UNIT_TO_MM[drawing_units]
        ),
        "unit_conversion_applied": source_units != drawing_units,
        "double_conversion_guard": "EXPLICIT_SOURCE_TO_DRAWING_ONCE",
        "display_precision": precision,
        "display_precision_mm": int(cfg.get("display_precision_mm", 0)),
        "display_precision_m": int(cfg.get("display_precision_m", 3)),
        "display_precision_m2": int(cfg.get("display_precision_m2", 2)),
    }


def _ezdxf_mapping(layer: dict[str, Any]) -> dict[str, Any]:
    # DXF lineweight uses integer hundredths of mm (e.g. 0.35 mm -> 35).
    return {
        "name": layer["name"],
        "color": int(layer["aci_color"]),
        "linetype": layer["linetype"],
        "lineweight": int(round(layer["lineweight_mm"] * 100)),
        "plot": bool(layer["plottable"]),
        "on": bool(layer["visible"]),
    }


def build_layer_policy(
    overrides: list[dict[str, Any]] | None = None,
    *,
    style_name: str = "arch-mono-v1",
) -> dict[str, Any]:
    """Build configurable, versioned CAD layer policy with ezdxf-ready mappings."""
    layers = [deepcopy(row) for row in DEFAULT_LAYERS]
    if style_name == "arch-color-v1":
        for row in layers:
            if row["name"] in COLOR_OVERRIDES:
                row["svg_color"] = COLOR_OVERRIDES[row["name"]]
    by_name = {row["name"]: row for row in layers}
    for override in overrides or []:
        name = override["name"]
        if name in by_name:
            target = by_name[name]
            for key in (
                "entity_category",
                "aci_color",
                "svg_color",
                "linetype",
                "lineweight_mm",
                "visible",
                "plottable",
            ):
                if key in override:
                    target[key] = override[key]
        else:
            new_row = {
                "name": name,
                "entity_category": override.get("entity_category", "custom"),
                "aci_color": int(override.get("aci_color", 7)),
                "svg_color": override.get("svg_color", "#111827"),
                "linetype": override.get("linetype", "CONTINUOUS"),
                "lineweight_mm": float(override.get("lineweight_mm", 0.18)),
                "visible": bool(override.get("visible", True)),
                "plottable": bool(override.get("plottable", True)),
            }
            layers.append(new_row)
            by_name[name] = new_row
    for row in layers:
        row["ezdxf_mapping"] = _ezdxf_mapping(row)
    return {
        "policy_version": LAYER_POLICY_VERSION,
        "authority": LAYER_POLICY_AUTHORITY,
        "layers": layers,
        "category_to_layer": {row["entity_category"]: row["name"] for row in layers},
    }


def validate_layer_policy(policy: dict[str, Any]) -> list[str]:
    """Validate CAD layer names, colors, linetypes and lineweights."""
    issues: list[str] = []
    seen: set[str] = set()
    layers = policy.get("layers", [])
    if not isinstance(layers, list) or not layers:
        return ["Layer policy must contain a non-empty layers list."]
    for row in layers:
        name = row.get("name", "")
        if not isinstance(name, str) or not name.strip() or _ILLEGAL_CAD_LAYER_RE.search(name):
            issues.append(f"Invalid CAD layer name: {name!r}")
        if name in seen:
            issues.append(f"Duplicate CAD layer name: {name}")
        seen.add(name)
        aci = row.get("aci_color")
        if not isinstance(aci, int) or isinstance(aci, bool) or not (1 <= aci <= 255):
            issues.append(f"Invalid ACI color on layer {name}: {aci!r}")
        lt = row.get("linetype")
        if lt not in VALID_LINETYPES:
            issues.append(f"Unsupported linetype on layer {name}: {lt!r}")
        lw = row.get("lineweight_mm")
        if not isinstance(lw, (int, float)) or isinstance(lw, bool) or lw <= 0:
            issues.append(f"Lineweight must be positive on layer {name}: {lw!r}")
    return issues


def build_drawing_style(
    cfg: dict[str, Any] | None = None,
    *,
    scale_denominator: int | float = 100,
    drawing_units: str = "mm",
    precision: int = 0,
) -> dict[str, Any]:
    """Construct reusable style policy with separated paper-space and model-space sizing."""
    cfg = cfg or {}
    style = deepcopy(STYLE_DEFAULTS)
    for key in (
        "name",
        "font_family",
        "paper_text_height_mm",
        "paper_dim_text_height_mm",
        "paper_arrow_size_mm",
        "paper_dim_offset_mm",
        "paper_chain_spacing_mm",
        "paper_extension_offset_mm",
        "paper_extension_overshoot_mm",
        "paper_grid_bubble_radius_mm",
        "tick_style",
        "hatch_enabled",
    ):
        if key in cfg:
            style[key] = cfg[key]
    style["scale_denominator"] = zero_float(dec(scale_denominator))
    style["measurement_precision"] = int(precision)
    style["model_sizing"] = {
        "text_height": paper_to_model(
            style["paper_text_height_mm"], scale_denominator, drawing_units
        ),
        "dim_text_height": paper_to_model(
            style["paper_dim_text_height_mm"], scale_denominator, drawing_units
        ),
        "arrow_size": paper_to_model(
            style["paper_arrow_size_mm"], scale_denominator, drawing_units
        ),
        "dim_offset": paper_to_model(
            style["paper_dim_offset_mm"], scale_denominator, drawing_units
        ),
        "chain_spacing": paper_to_model(
            style["paper_chain_spacing_mm"], scale_denominator, drawing_units
        ),
        "extension_offset": paper_to_model(
            style["paper_extension_offset_mm"], scale_denominator, drawing_units
        ),
        "extension_overshoot": paper_to_model(
            style["paper_extension_overshoot_mm"], scale_denominator, drawing_units
        ),
        "grid_bubble_radius": paper_to_model(
            style["paper_grid_bubble_radius_mm"], scale_denominator, drawing_units
        ),
        "units": drawing_units,
    }
    return style
