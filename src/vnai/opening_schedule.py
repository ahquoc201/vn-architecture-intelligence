"""Explicit dimensions and content-equivalent marks; unknowns remain null."""

from vnai.contracts import canonical_digest


def schedule(rows: list[dict], records: list[dict], units: str, problem) -> list[dict]:
    def equivalent(value):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return 0.0 if value == 0 else float(value)
        if isinstance(value, dict):
            return {k: equivalent(v) for k, v in value.items()}
        if isinstance(value, list):
            return [equivalent(v) for v in value]
        return value

    groups = {}
    marks = {}
    by_id = {r["id"]: r for r in records}
    fields = (
        "type",
        "kind",
        "rough_width",
        "rough_height",
        "bottom",
        "sill",
        "head",
        "clear_width",
        "clear_height",
        "clear_start_offset",
        "frame_inner_width",
        "frame",
        "leaf",
        "mount_side",
        "mount_offset",
        "swing",
        "slide",
        "operation",
        "operating_state",
        "material_reference",
    )
    for row in sorted(rows, key=lambda r: r["id"]):
        # Space identity is placement, while handing/rotation/angle remain schedule properties.
        declared = {k: row.get(k) for k in fields}
        for k in ("swing", "slide"):
            if declared[k]:
                declared[k] = {n: v for n, v in declared[k].items() if n != "opens_into"}
        digest = canonical_digest(equivalent(declared))
        if row["mark"] in marks and marks[row["mark"]] != digest:
            problem(
                "conflict",
                "CONFLICTING_OPENING_MARK",
                row["id"],
                "Identical mark labels incompatible declared dimensions/type/handing/assembly.",
            )
        marks[row["mark"]] = digest
        r = by_id[row["id"]]
        key = (row["mark"], row["floor_id"], r["host_wall_id"], digest)
        if key not in groups:
            groups[key] = {
                "mark": row["mark"],
                "type": row["type"],
                "floor_id": row["floor_id"],
                "host_wall_id": r["host_wall_id"],
                "rough_width_m": r.get("rough_width_m"),
                "rough_height_m": r.get("rough_height_m"),
                "frame_inner_width_m": r.get("frame_inner_width_m"),
                "leaf_width_m": r.get("primitives", {}).get(
                    "leaf_width_m",
                    row.get("leaf", {}).get("width") * (1.0 if units == "m" else 0.001)
                    if row.get("leaf")
                    else None,
                ),
                "clear_width_m": r.get("clear_width_m"),
                "clear_height_m": r.get("clear_height_m"),
                "sill_m": r.get("sill_m"),
                "head_m": r.get("head_m"),
                "material_reference": row.get("material_reference"),
                "declared_specification": declared,
                "declared_units": units,
                "quantity": 0,
                "opening_ids": [],
                "provenance": [],
                "review_state": "PROPOSED",
                "unresolved_specifications": [],
                "specification_digest": digest,
            }
        g = groups[key]
        g["quantity"] += 1
        g["opening_ids"].append(row["id"])
        g["provenance"].append(row["provenance"])
        g["unresolved_specifications"] += r["issues"]
    for g in groups.values():
        g["provenance"] = sorted(set(g["provenance"]))
        g["unresolved_specifications"] = sorted(set(g["unresolved_specifications"]))
    return [groups[k] for k in sorted(groups, key=lambda k: tuple(str(v) for v in k))]
