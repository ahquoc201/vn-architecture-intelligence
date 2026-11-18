"""Validated immutable candidate context shared by circulation review tools."""

from copy import deepcopy
from dataclasses import dataclass, field
import math
from typing import Any

from shapely.geometry import Polygon

from vnai.contracts import canonical_digest, finish, issue, new_report, schema_check
from vnai.spatial import validate_geometry
from vnai.space_program import build_space_program


def candidate_digest(candidate: dict) -> str:
    return canonical_digest(candidate)


def design_digest(spec: dict) -> str:
    return canonical_digest({k: v for k, v in spec.items() if k != "decisions"})


@dataclass
class Space:
    id: str
    kind: str
    floor: str
    geometry_id: str | None
    shape: Polygon | None

    def record(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "floor_id": self.floor,
            "geometry_id": self.geometry_id,
        }


@dataclass
class ReviewContext:
    spec: dict
    report: dict
    geometry: dict = field(default_factory=dict)
    scale: float = 1
    tolerance: float = 0
    area_tolerance: float = 0
    spaces: dict[str, Space] = field(default_factory=dict)
    rows: dict[str, dict] = field(default_factory=dict)
    shapes: dict[str, Polygon] = field(default_factory=dict)
    obstacles: list[tuple[str, str, Polygon]] = field(default_factory=list)
    clearances: dict[str, Polygon] = field(default_factory=dict)
    floors: set[str] = field(default_factory=set)
    geometry_status: str = "NOT_EVALUATED"

    def xy(self, value: list[float]) -> tuple[float, float]:
        return (value[0] * self.scale, value[1] * self.scale)

    def polygon(self, row: dict) -> Polygon:
        return Polygon(
            [self.xy(p) for p in row["exterior"]],
            [[self.xy(p) for p in ring] for ring in row.get("holes", [])],
        )

    def envelope(self, floor: str) -> Polygon:
        outline = next(
            (
                r
                for r in self.rows.values()
                if r["role"] == "floor_outline" and r.get("floor_id") == floor
            ),
            None,
        )
        if outline is None:
            outline = next((r for r in self.rows.values() if r["role"] == "footprint"), None)
        if outline is None:
            outline = next(r for r in self.rows.values() if r["role"] == "site")
        return self.shapes[outline["id"]]


def stage_report(ctx: ReviewContext, kind: str, **fields: Any) -> dict:
    result = new_report(kind)
    for bucket in ("errors", "warnings", "missing_information", "diagnostics"):
        result[bucket] = deepcopy(ctx.report[bucket])
    result.update(
        {key: ctx.report.get(key) for key in ("candidate_id", "candidate_digest", "design_digest")}
    )
    result.update(fields)
    return finish(result)


def near_covers(container: Any, target: Any, tolerance: float) -> bool:
    return container.covers(target) or (
        tolerance > 0 and container.buffer(tolerance).covers(target)
    )


def valid_frame(ctx: ReviewContext, row: dict, report: dict, path: str) -> bool:
    valid = row["units"] == ctx.geometry["units"] and row["frame_id"] == ctx.geometry["frame"]["id"]
    if not valid:
        issue(
            report,
            "errors",
            "COORDINATE_MISMATCH",
            path,
            "Use the candidate frame and units; no transform is inferred.",
        )
    return valid


def build_context(value: Any) -> ReviewContext:
    report = new_report("review-context-v1")
    report.update(candidate_id=None, candidate_digest=None, design_digest=None)
    ctx = ReviewContext(value if isinstance(value, dict) else {}, report)
    if not schema_check(value, "candidate-review.schema.json", report):
        return ctx
    candidate = value["candidate"]
    ctx.geometry = geometry = candidate["geometry"]
    ctx.scale = 1 if geometry["units"] == "m" else 0.001
    ctx.tolerance = geometry["tolerances"]["boundary_m"]
    ctx.area_tolerance = geometry["tolerances"]["overlap_m2"]
    report.update(
        candidate_id=candidate["candidate_id"],
        candidate_digest=candidate_digest(candidate),
        design_digest=design_digest(value),
    )
    selection = value.get("selection")
    if selection and (
        selection["candidate_id"] != report["candidate_id"]
        or selection["candidate_digest"] != report["candidate_digest"]
    ):
        issue(
            report,
            "errors",
            "CANDIDATE_SELECTION_MISMATCH",
            "selection",
            "Selected ID/content digest does not match the candidate.",
        )
        return ctx
    spatial = validate_geometry(geometry)
    ctx.geometry_status = spatial["status"]
    if spatial["status"] != "VALID":
        issue(
            report,
            "errors" if spatial["errors"] else "missing_information",
            "CANDIDATE_GEOMETRY",
            "candidate.geometry",
            "Candidate geometry must pass current spatial validation.",
        )
        return ctx
    ctx.floors = {f["id"] for f in geometry["floors"]}
    if (
        set(candidate["floor_ids"]) != ctx.floors
        or len(candidate["floor_ids"]) != len(ctx.floors)
        or candidate["floor_id"] != (next(iter(ctx.floors)) if len(ctx.floors) == 1 else None)
    ):
        issue(
            report,
            "errors",
            "CANDIDATE_FLOOR_METADATA",
            "candidate",
            "Candidate floor metadata differs from its geometry.",
        )
    ctx.rows = {row["id"]: row for row in geometry["polygons"]}
    ctx.shapes = {key: ctx.polygon(row) for key, row in ctx.rows.items()}
    requirements = {
        r["id"] for r in geometry.get("zoning", {}).get("brief", {}).get("requirements", [])
    }
    if "zoning" in geometry:
        program = build_space_program(geometry["zoning"]["brief"])
        rooms = {r["id"]: r for r in program["rooms"]}
    else:
        rooms = {}
    measured = {}
    for row in ctx.rows.values():
        if row["role"] == "room":
            key = row["room_id"]
            measured[key] = ctx.shapes[row["id"]].area
            ctx.spaces[key] = Space(key, "room", row["floor_id"], row["id"], ctx.shapes[row["id"]])
            area = rooms.get(key, {}).get("requested_area_m2")
            if area and (
                (
                    "min" in area
                    and measured[key] < area["min"]
                    and not math.isclose(measured[key], area["min"], abs_tol=1e-12, rel_tol=1e-12)
                )
                or (
                    "max" in area
                    and measured[key] > area["max"]
                    and not math.isclose(measured[key], area["max"], abs_tol=1e-12, rel_tol=1e-12)
                )
            ):
                issue(
                    report,
                    "errors",
                    "CANDIDATE_AREA_BOUNDS",
                    key,
                    "Candidate violates source hard room-area bounds.",
                )
        elif row["role"] == "reservation":
            if row["reservation_kind"] in {"circulation", "stairwell"}:
                ctx.spaces[row["id"]] = Space(
                    row["id"],
                    row["reservation_kind"],
                    row["floor_id"],
                    row["id"],
                    ctx.shapes[row["id"]],
                )
            if row["reservation_kind"] != "circulation":
                ctx.obstacles.append((row["id"], row["floor_id"], ctx.shapes[row["id"]]))
    if set(candidate["room_areas_m2"]) != set(measured) or any(
        not math.isclose(candidate["room_areas_m2"][key], area, rel_tol=1e-12, abs_tol=1e-12)
        for key, area in measured.items()
        if key in candidate["room_areas_m2"]
    ):
        issue(
            report,
            "errors",
            "CANDIDATE_MEASUREMENT_MISMATCH",
            "candidate.room_areas_m2",
            "Recomputed room areas differ from the candidate's stored measurements.",
        )
    identifiers = set(ctx.rows) | ctx.floors | {geometry["project_id"], geometry["frame"]["id"]}
    identifiers |= {p["id"] for p in geometry["points"]} | {s["id"] for s in geometry["segments"]}
    for bucket in ("fixed_obstacles", "clearance_regions"):
        for row in value.get(bucket, []):
            path = bucket + "." + row["id"]
            if row["id"] in identifiers:
                issue(
                    report,
                    "errors",
                    "DUPLICATE_REVIEW_GEOMETRY",
                    path,
                    "Sidecar geometry IDs must be unique.",
                )
            identifiers.add(row["id"])
            valid_frame(ctx, row, report, path)
            if (
                row["role"] != "reservation"
                or row.get("floor_id") not in ctx.floors
                or row["owner_id"] != row.get("floor_id")
                or not row.get("provenance")
                or row.get("requirement_id") not in requirements
            ):
                issue(
                    report,
                    "errors",
                    "REVIEW_GEOMETRY_METADATA",
                    path,
                    "Use a floor-owned reservation with source requirement and provenance.",
                )
            shape = ctx.polygon(row)
            if (
                not shape.is_valid
                or not math.isfinite(shape.area)
                or shape.area <= geometry["tolerances"]["min_area_m2"]
            ):
                issue(
                    report,
                    "errors",
                    "INVALID_REVIEW_POLYGON",
                    path,
                    "Sidecar polygon is invalid or below the declared area threshold; no repair applied.",
                )
                continue
            if bucket == "fixed_obstacles":
                if row.get("reservation_kind") not in {"service_shaft", "other"}:
                    issue(
                        report,
                        "errors",
                        "OBSTACLE_KIND",
                        path,
                        "Fixed obstacles use other/service_shaft, not circulation or stairwell.",
                    )
                if row.get("floor_id") in ctx.floors and not near_covers(
                    ctx.envelope(row["floor_id"]), shape, ctx.tolerance
                ):
                    issue(
                        report,
                        "errors",
                        "OBSTACLE_OUTSIDE_ENVELOPE",
                        path,
                        "Obstacle lies outside its floor envelope.",
                    )
                ctx.obstacles.append((row["id"], row.get("floor_id", ""), shape))
            else:
                ctx.clearances[row["id"]] = shape
                ctx.rows[row["id"]] = row
    for external in value.get("exteriors", []):
        key, boundary = external["id"], ctx.rows.get(external["boundary_id"])
        if key in identifiers or key in ctx.spaces:
            issue(
                report,
                "errors",
                "DUPLICATE_SPACE_ID",
                key,
                "Exterior ID conflicts with existing geometry/space.",
            )
        identifiers.add(key)
        if (
            external["floor_id"] not in ctx.floors
            or not boundary
            or boundary["role"] not in {"site", "footprint", "floor_outline"}
            or (
                boundary.get("floor_id") is not None
                and boundary["floor_id"] != external["floor_id"]
            )
        ):
            issue(
                report,
                "errors",
                "EXTERIOR_BOUNDARY",
                key,
                "Exterior access must reference a compatible floor envelope boundary.",
            )
        approach = ctx.clearances.get(external.get("approach_id", ""))
        if external.get("approach_id") and approach is None:
            issue(
                report,
                "errors",
                "EXTERIOR_APPROACH_REFERENCE",
                key,
                "Unknown supplied approach polygon.",
            )
        if approach is not None and external["floor_id"] in ctx.floors:
            if ctx.rows[external["approach_id"]].get("floor_id") != external["floor_id"]:
                issue(
                    report,
                    "errors",
                    "EXTERIOR_APPROACH_FLOOR",
                    key,
                    "Approach and exterior floor IDs differ.",
                )
            if approach.intersection(ctx.envelope(external["floor_id"])).area > ctx.area_tolerance:
                issue(
                    report,
                    "errors",
                    "EXTERIOR_APPROACH_INSIDE",
                    key,
                    "Exterior approach cannot overlap the building envelope interior.",
                )
        ctx.spaces[key] = Space(
            key, "exterior", external["floor_id"], external["boundary_id"], approach
        )
    finish(report)
    return ctx
