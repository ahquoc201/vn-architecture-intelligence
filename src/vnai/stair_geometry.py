"""Exact decimal-rational elevations and orthogonal staircase primitives."""

from decimal import Decimal, localcontext
from fractions import Fraction
from math import fsum
from shapely.geometry import Polygon, LineString, Point
from shapely.ops import unary_union
from vnai.wall_topology import encode
from vnai.opening_hosts import shape_set
from vnai.review_common import near_covers

DIRECTIONS = {"E": (1, 0), "N": (0, 1), "W": (-1, 0), "S": (0, -1)}


def exact(value, scale=Fraction(1)):
    return Fraction(str(value)) * scale


def pitch(rise, going):
    """Deterministic atan through Decimal half-angle reduction, no platform libm."""
    with localcontext() as c:
        c.prec = 50
        x = Decimal(rise.numerator) / Decimal(rise.denominator)
        x /= Decimal(going.numerator) / Decimal(going.denominator)
        multiplier = 1
        while x > Decimal(".2"):
            x = x / (1 + (1 + x * x).sqrt())
            multiplier *= 2
        power = x
        total = x
        for n in range(1, 100):
            power *= -x * x
            total += power / (2 * n + 1)
        pi = Decimal("3.1415926535897932384626433832795028841971693993751")
        return float(multiplier * total * 180 / pi)


def exact_path_length(points, scale):
    with localcontext() as context:
        context.prec = 50
        terms = []
        for a, b in zip(points, points[1:]):
            square = sum((exact(q, scale) - exact(p, scale)) ** 2 for p, q in zip(a, b))
            terms.append((Decimal(square.numerator) / Decimal(square.denominator)).sqrt())
        return float(sum(terms, Decimal(0)))


def rectangle(points, bad, key):
    p = shape_set(points)
    if p.is_empty or not p.is_valid or p.area <= 0 or not p.equals(Polygon.from_bounds(*p.bounds)):
        bad(
            "invalid",
            "RECTANGULAR_REGION_REQUIRED",
            key,
            "Supply one valid axis-aligned rectangle, without holes or repair.",
        )
        return None
    return p


def construct(row, levels, scale, tolerance, area_tolerance, bad):
    key = row["id"]
    typ = row["type"]
    if typ not in {"straight", "L", "U"}:
        bad(
            "unsupported",
            "STAIR_TYPE_UNSUPPORTED",
            key,
            "Only straight, orthogonal L and parallel-return U stairs are constructed.",
        )
        return None
    if row["counting"] != "arrival_surface":
        bad(
            "unsupported",
            "STAIR_COUNTING_UNSUPPORTED",
            key,
            "Each flight uses n risers, n-1 ordinary treads and a separate arrival surface.",
        )
        return None
    a, b = levels.get(row["source_floor"]), levels.get(row["destination_floor"])
    if a is None or b is None:
        bad(
            "missing",
            "FLOOR_ELEVATION_REQUIRED",
            key,
            "Confirmed finished floor elevations are required.",
        )
        return None
    if a >= b or row["source_floor"] == row["destination_floor"]:
        bad(
            "invalid",
            "STAIR_FLOOR_RISE",
            key,
            "Specify distinct source/destination floors with positive rise.",
        )
        return None
    wanted = 1 if typ == "straight" else 2
    if len(row["flights"]) != wanted or len(row["landings"]) != wanted - 1:
        bad(
            "invalid",
            "STAIR_COMPONENT_COUNT",
            key,
            "Flight/landing counts must match the declared configuration.",
        )
        return None
    envelope = rectangle(row["envelope"], bad, key)
    if envelope is None:
        return None
    count = sum(f["risers"] for f in row["flights"])
    h = (b - a) / count
    current = a
    flights = []
    surfaces = []
    risers = []
    sections = []
    developed = Fraction(0)
    for f in row["flights"]:
        fid = f["id"]
        n = f["risers"]
        d = exact(f["tread_depth"], scale)
        width = exact(f["width"], scale)
        if n < 2:
            bad(
                "unsupported",
                "SINGLE_RISER_FLIGHT",
                fid,
                "At least two risers are required for the current flight footprint model.",
            )
            return None
        if "tread_count" in f and f["tread_count"] != n - 1:
            bad(
                "conflict",
                "TREAD_RISER_CONVENTION",
                fid,
                "Ordinary tread count must be n-1 under arrival_surface.",
            )
        rh = exact(f["riser_height"], scale) if "riser_height" in f else h
        last = (
            exact(f.get("last_riser_height", float(rh / scale)), scale)
            if "last_riser_height" in f
            else rh
        )
        if last != rh:
            bad(
                "warning",
                "NONUNIFORM_FINAL_RISER",
                fid,
                "Explicit final riser differs; it is retained, never redistributed.",
            )
        origin = [exact(v, scale) for v in f["origin"]]
        u = DIRECTIONS[f["direction"]]
        v = (-u[1], u[0])
        run = (n - 1) * d

        def xy(t, w=Fraction(0)):
            return [float(origin[i] + u[i] * t + v[i] * w) for i in (0, 1)]

        def edge(t):
            return [xy(t), xy(t, width)]

        def box(start, end):
            return Polygon([xy(start), xy(end), xy(end, width), xy(start, width)])

        nosing = exact(f.get("nosing", 0), scale)
        if nosing >= d:
            bad(
                "conflict",
                "NOSING_EXCEEDS_GOING",
                fid,
                "Nosing must be smaller than declared going.",
            )
        footprint = box(-nosing, run)
        if not footprint.is_valid or footprint.is_empty or footprint.area <= 0:
            bad(
                "invalid",
                "DEGENERATE_STAIR_FLIGHT",
                fid,
                "Declared dimensions do not produce a valid positive representable flight polygon.",
            )
            return None
        if not near_covers(envelope, footprint, tolerance):
            bad(
                "conflict",
                "STAIR_OUTSIDE_ENVELOPE",
                fid,
                "Flight or supplied nosing lies outside the explicit stair envelope.",
            )
        start = current
        treads = []
        refs = []
        profile = [[float(developed), float(current)]]
        for j in range(n):
            before = current
            current = start + (j + 1) * rh if j < n - 1 else start + (n - 1) * rh + last
            line = edge(j * d)
            rr = {
                "id": fid + "-R" + str(j + 1),
                "line": line,
                "bottom_m": float(before),
                "top_m": float(current),
            }
            refs.append(rr)
            risers.append(rr)
            profile.append([float(developed + j * d), float(current)])
            if j < n - 1:
                g = box(j * d - nosing, (j + 1) * d)
                tread = {
                    "id": fid + "-T" + str(j + 1),
                    "kind": "tread",
                    "flight_id": fid,
                    "geometry": encode(g),
                    "elevation_m": float(current),
                    "nosing_line": edge(j * d - nosing) if "nosing" in f else None,
                }
                treads.append(tread)
                surfaces.append(tread)
                profile.append([float(developed + (j + 1) * d), float(current)])
        fresult = {
            "id": fid,
            "direction": list(u),
            "width_m": float(width),
            "risers": n,
            "ordinary_treads": n - 1,
            "riser_height_m": float(rh),
            "last_riser_height_m": float(last),
            "riser_height_origin": "supplied"
            if "riser_height" in f
            else "derived_exact_total_rise_over_total_risers",
            "tread_depth_m": float(d),
            "run_m": float(run),
            "pitch_degrees": pitch(rh, d),
            "start_elevation_m": float(start),
            "arrival_elevation_m": float(current),
            "geometry": encode(footprint),
            "entry_edge": edge(0),
            "exit_edge": edge(run),
            "risers_geometry": refs,
            "treads": treads,
            "walking_line": [xy(0, width / 2), xy(run, width / 2)],
            "section_profile": profile,
        }
        flights.append(fresult)
        sections.append({"kind": "flight", "id": fid, "profile": profile})
        developed += run
        index = len(flights) - 1
        if index < len(row["landings"]):
            record_item = row["landings"][index]
            lp = rectangle(record_item["geometry"], bad, record_item["id"])
            if lp is None:
                return None
            if (
                "elevation" in record_item
                and abs(float(exact(record_item["elevation"], scale) - current)) > tolerance
            ):
                bad(
                    "conflict",
                    "LANDING_ELEVATION",
                    record_item["id"],
                    "Landing elevation differs from actual flight arrival.",
                )
            if not near_covers(envelope, lp, tolerance):
                bad(
                    "conflict",
                    "LANDING_OUTSIDE_ENVELOPE",
                    record_item["id"],
                    "Landing leaves the stair envelope.",
                )
            if not near_covers(lp.boundary, LineString(fresult["exit_edge"]), tolerance):
                bad(
                    "conflict",
                    "LANDING_FLIGHT_CONNECTION",
                    record_item["id"],
                    "Landing boundary must contain the complete flight exit edge.",
                )
            line = LineString(
                [
                    [float(exact(x, scale)), float(exact(y, scale))]
                    for x, y in record_item["walking_line"]
                ]
            )
            midpoint = LineString(fresult["exit_edge"]).interpolate(0.5, normalized=True)
            if (
                not near_covers(lp, line, tolerance)
                or midpoint.distance(Point(line.coords[0])) > tolerance
            ):
                bad(
                    "conflict",
                    "LANDING_WALKING_LINE",
                    record_item["id"],
                    "Explicit landing walking line must start at flight exit centre and remain in the landing.",
                )
            length = exact_path_length(record_item["walking_line"], scale)
            lr = {
                "id": record_item["id"],
                "kind": "landing",
                "flight_id": fid,
                "geometry": encode(lp),
                "elevation_m": float(current),
                "walking_line": list(map(list, line.coords)),
                "developed_length_m": length,
                "dimensions_m": [lp.bounds[2] - lp.bounds[0], lp.bounds[3] - lp.bounds[1]],
                "elevation_origin": "supplied"
                if "elevation" in record_item
                else "derived_flight_arrival",
            }
            surfaces.append(lr)
            next_developed = developed + Fraction(str(length))
            sections.append(
                {
                    "kind": "landing",
                    "id": record_item["id"],
                    "profile": [
                        [float(developed), float(current)],
                        [float(next_developed), float(current)],
                    ],
                }
            )
            developed = next_developed
    if abs(float(current - b)) > tolerance:
        bad(
            "conflict",
            "STAIR_FINAL_ELEVATION",
            key,
            "Cumulative declared rise misses destination; no last-step adjustment or redistribution.",
        )
    elif current != b:
        bad(
            "warning",
            "STAIR_LEVEL_RESIDUAL",
            key,
            "Nonzero declared closure residual is retained within source boundary tolerance.",
        )
    if len(flights) == 2:
        first, second = flights
        if first["riser_height_m"] != second["riser_height_m"]:
            bad(
                "warning",
                "NONUNIFORM_FLIGHT_RISERS",
                key,
                "Explicit flight riser heights differ; they are preserved and require architect/technical review, not automatically certified.",
            )
        u, v = first["direction"], second["direction"]
        cross = u[0] * v[1] - u[1] * v[0]
        dot = u[0] * v[0] + u[1] * v[1]
        expected = 1 if row.get("turn") == "left" else -1
        if "turn" not in row:
            bad("missing", "STAIR_TURN_REQUIRED", key, "Declare turning direction.")
        elif typ == "L" and (dot != 0 or cross != expected):
            bad(
                "conflict",
                "STAIR_TURN_GEOMETRY",
                key,
                "Flight directions contradict the declared orthogonal turn.",
            )
        elif typ == "U":
            lateral = (second["entry_edge"][0][0] - first["entry_edge"][0][0]) * (-u[1]) + (
                second["entry_edge"][0][1] - first["entry_edge"][0][1]
            ) * u[0]
            if dot != -1 or lateral * expected <= 0:
                bad(
                    "conflict",
                    "STAIR_RETURN_GEOMETRY",
                    key,
                    "Return flight must be parallel/opposite on the declared side.",
                )
            if "flight_separation" not in row:
                bad(
                    "missing",
                    "STAIR_WELL_SEPARATION_REQUIRED",
                    key,
                    "Supply explicit return-flight separation.",
                )
            else:
                lateral_exact = sum(
                    (
                        exact(row["flights"][1]["origin"][i], scale)
                        - exact(row["flights"][0]["origin"][i], scale)
                    )
                    * (-u[1], u[0])[i]
                    for i in (0, 1)
                )
                first_width = exact(row["flights"][0]["width"], scale)
                second_width = exact(row["flights"][1]["width"], scale)
                gap = max(Fraction(0), lateral_exact - second_width - first_width, -lateral_exact)
                if abs(float(gap - exact(row["flight_separation"], scale))) > tolerance:
                    bad(
                        "conflict",
                        "STAIR_FLIGHT_SEPARATION",
                        key,
                        "Declared separation differs from actual flight polygons.",
                    )
        landing = next(s for s in surfaces if s["kind"] == "landing")
        p = shape_set(landing["geometry"])
        edge = LineString(second["entry_edge"])
        if (
            not near_covers(p.boundary, edge, tolerance)
            or edge.interpolate(0.5, normalized=True).distance(Point(landing["walking_line"][-1]))
            > tolerance
        ):
            bad(
                "conflict",
                "LANDING_NEXT_FLIGHT",
                landing["id"],
                "Full next-flight entry edge and walking-line end must connect.",
            )
        if abs(first["width_m"] - second["width_m"]) > tolerance:
            bad(
                "conflict",
                "INCONSISTENT_FLIGHT_WIDTHS",
                key,
                "Current supported flights must have consistent explicit widths.",
            )
    components = [shape_set(f["geometry"]) for f in flights] + [
        shape_set(s["geometry"]) for s in surfaces if s["kind"] == "landing"
    ]
    for i, p in enumerate(components):
        for q in components[i + 1 :]:
            if p.intersection(q).area > area_tolerance:
                bad(
                    "conflict",
                    "STAIR_COMPONENT_OVERLAP",
                    key,
                    "Flights and intermediate landings unintentionally overlap in plan.",
                )
    exit_edge = flights[-1]["exit_edge"]
    exit_point = LineString(exit_edge).interpolate(0.5, normalized=True)
    if "arrival" in row:
        ar = rectangle(row["arrival"]["geometry"], bad, key + ".arrival")
        if ar is not None:
            point = [float(exact(v, scale)) for v in row["arrival"]["exit_point"]]
            if (
                not near_covers(ar.boundary, LineString(exit_edge), tolerance)
                or not near_covers(ar.boundary, LineString([point, point]), tolerance)
                or not near_covers(envelope, ar, tolerance)
            ):
                bad(
                    "conflict",
                    "ARRIVAL_SURFACE_CONNECTION",
                    key,
                    "Explicit upper-floor arrival surface must connect the full flight edge and exit point within envelope.",
                )
            surfaces.append(
                {
                    "id": key + "-ARRIVAL",
                    "kind": "arrival",
                    "flight_id": flights[-1]["id"],
                    "geometry": encode(ar),
                    "elevation_m": float(current),
                }
            )
            exit_point = Point(point)
            u = flights[-1]["direction"]
            v = (-u[1], u[0])
            width = flights[-1]["width_m"]
            portal_edge = [[point[i] + v[i] * w for i in (0, 1)] for w in (-width / 2, width / 2)]
            if not near_covers(ar.boundary, LineString(portal_edge), tolerance):
                bad(
                    "conflict",
                    "ARRIVAL_EXIT_WIDTH",
                    key,
                    "Arrival exit edge of the declared flight width must fit its supplied rectangle boundary.",
                )
            arrival_midpoint = LineString(flights[-1]["exit_edge"]).interpolate(
                0.5, normalized=True
            )
            dx, dy = point[0] - arrival_midpoint.x, point[1] - arrival_midpoint.y
            along, across = dx * u[0] + dy * u[1], dx * v[0] + dy * v[1]
            if abs(across) > tolerance or along < 0:
                bad(
                    "unsupported",
                    "ARRIVAL_SECTION_PATH_REQUIRED",
                    key,
                    "Current arrival section needs an explicit collinear rectangular arrival, not an invented turning path.",
                )
            else:
                sections.append(
                    {
                        "kind": "arrival",
                        "id": key + "-ARRIVAL",
                        "profile": [
                            [float(developed), float(current)],
                            [fsum((float(developed), along)), float(current)],
                        ],
                    }
                )
            exit_edge = portal_edge
    return {
        "id": key,
        "mark": row.get("mark"),
        "type": typ,
        "source_floor": row["source_floor"],
        "destination_floor": row["destination_floor"],
        "stairwell_ids": row["stairwell_ids"],
        "envelope": encode(envelope),
        "flights": flights,
        "surfaces": surfaces,
        "rise_m": float(b - a),
        "source_elevation_m": float(a),
        "destination_elevation_m": float(b),
        "final_elevation_m": float(current),
        "closure_residual_m": float(current - b),
        "entry_edge": flights[0]["entry_edge"],
        "exit_edge": exit_edge,
        "entry_point": list(
            LineString(flights[0]["entry_edge"]).interpolate(0.5, normalized=True).coords[0]
        ),
        "exit_point": list(exit_point.coords[0]),
        "section_kind": "TRUE_LONGITUDINAL"
        if typ == "straight"
        else "DEVELOPED_EXPLICIT_WALKING_LINE",
        "sections": sections,
        "footprint": encode(
            unary_union(
                [
                    *components,
                    *[shape_set(s["geometry"]) for s in surfaces if s["kind"] == "arrival"],
                ]
            )
        ),
        "risers_geometry": risers,
        "review_status": "PROPOSED",
        "provenance": row["provenance"],
        "requirement_ids": row["requirement_ids"],
    }
