"""Finite grid rectangle search. All sizes originate in the supplied constraints."""

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from typing import Callable

from shapely.geometry import Polygon, box


class SearchLimit(Exception):
    """Deterministic operation budget exhausted, not proof of infeasibility."""


@dataclass
class Budget:
    limit: int
    steps: int = 0

    def tick(self) -> None:
        if self.steps >= self.limit:
            raise SearchLimit
        self.steps += 1


@dataclass(frozen=True)
class Placement:
    shape: Polygon
    mask: int
    area_m2: float
    width: float
    depth: float


def placements(
    room: dict,
    envelope: Polygon,
    reserved: list[Polygon],
    step: Decimal,
    scale: Decimal,
    budget: Budget,
) -> list[Placement]:
    """Enumerate rectangles on the envelope-origin grid, with no implicit rotation."""
    x0, y0, x1, y1 = map(lambda value: Decimal(str(value)), envelope.bounds)
    nx = int(((x1 - x0) / step).to_integral_value(rounding=ROUND_FLOOR))
    ny = int(((y1 - y0) / step).to_integral_value(rounding=ROUND_FLOOR))
    dims = room["dimensions"]
    wmin = max(
        1,
        int((Decimal(str(dims["width"]["min"])) / step).to_integral_value(rounding=ROUND_CEILING)),
    )
    wmax = min(
        nx, int((Decimal(str(dims["width"]["max"])) / step).to_integral_value(rounding=ROUND_FLOOR))
    )
    hmin = max(
        1,
        int((Decimal(str(dims["depth"]["min"])) / step).to_integral_value(rounding=ROUND_CEILING)),
    )
    hmax = min(
        ny, int((Decimal(str(dims["depth"]["max"])) / step).to_integral_value(rounding=ROUND_FLOOR))
    )
    low, high = (Decimal(str(room["area"][key])) for key in ("min", "max"))
    result = []
    for w in range(wmin, wmax + 1):
        for h in range(hmin, hmax + 1):
            budget.tick()
            area = Decimal(w * h) * step * step * scale * scale
            if not low <= area <= high:
                continue
            for y in range(ny - h + 1):
                for x in range(nx - w + 1):
                    budget.tick()
                    shape = box(
                        float(x0 + x * step),
                        float(y0 + y * step),
                        float(x0 + (x + w) * step),
                        float(y0 + (y + h) * step),
                    )
                    if not envelope.covers(shape) or any(
                        shape.intersection(r).area > 0 for r in reserved
                    ):
                        continue
                    mask = sum(((1 << w) - 1) << ((y + row) * nx + x) for row in range(h))
                    result.append(
                        Placement(shape, mask, float(area), float(w * step), float(h * step))
                    )
    target = room["area"].get("target")
    return sorted(result, key=lambda p: (abs(p.area_m2 - target) if target else 0, p.shape.bounds))


def adjacent(left: Placement, right: Placement) -> bool:
    return left.shape.boundary.intersection(right.shape.boundary).length > 0


def search(
    rooms: list[dict],
    domains: dict[str, list[Placement]],
    hard_pairs: list[tuple[str, str]],
    budget: Budget,
    accept: Callable[[dict[str, Placement]], None],
    stop: Callable[[], bool],
) -> None:
    ordered = sorted(rooms, key=lambda r: (len(domains[r["id"]]), r["floor_id"], r["id"]))
    placed: dict[str, Placement] = {}
    occupied: dict[str, int] = {}

    def visit(index: int) -> None:
        if stop():
            return
        budget.tick()
        if index == len(ordered):
            accept(dict(placed))
            return
        room = ordered[index]
        key, floor = room["id"], room["floor_id"]
        mask = occupied.get(floor, 0)
        for choice in domains[key]:
            if stop():
                return
            budget.tick()
            if choice.mask & mask:
                continue
            if any(
                not adjacent(choice, placed[other])
                for a, b in hard_pairs
                for other in ([b] if a == key else [a] if b == key else [])
                if other in placed
            ):
                continue
            placed[key] = choice
            occupied[floor] = mask | choice.mask
            visit(index + 1)
            del placed[key]
            occupied[floor] = mask

    visit(0)
