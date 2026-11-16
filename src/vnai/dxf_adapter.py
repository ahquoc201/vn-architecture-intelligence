"""Optional DXF export of schematic input geometry. NOT production architectural drafting."""

from pathlib import Path

from vnai.geometry import polygon_mm, validate_plan_structure


def export_schematic_dxf(plan: dict, out: str | Path) -> Path:
    try:
        import ezdxf
    except ImportError as exc:
        raise RuntimeError('Install CAD extra: pip install -e ".[cad]"') from exc

    validate_plan_structure(plan)
    output = Path(out)
    output.parent.mkdir(parents=True, exist_ok=True)
    doc = ezdxf.new(setup=True)
    doc.header["$INSUNITS"] = 4  # mm
    for layer, color in (("SITE_BOUNDARY", 2), ("SCHEMATIC_ROOMS", 3), ("ROOM_LABELS", 7)):
        doc.layers.new(layer, dxfattribs={"color": color})
    msp = doc.modelspace()
    msp.add_lwpolyline(plan["site"]["outline_mm"], close=True, dxfattribs={"layer": "SITE_BOUNDARY"})
    # A separate layer name per level; geometry itself is 2D, not a 3D stack.
    for level in plan["levels"]:
        layer_name = f"ROOMS_{level['id']}"[:255]
        if layer_name not in doc.layers:
            doc.layers.new(layer_name, dxfattribs={"color": 4})
        for room in level["rooms"]:
            shape = polygon_mm(room["polygon_mm"], room["id"])
            msp.add_lwpolyline(room["polygon_mm"], close=True, dxfattribs={"layer": layer_name})
            p = shape.representative_point()
            # Stick to ASCII in this demo because DXF CAD fonts may not render Vietnamese.
            msp.add_text(
                room["id"],
                dxfattribs={"layer": "ROOM_LABELS", "height": 200, "insert": (p.x, p.y)},
            )
    doc.saveas(output)
    return output
