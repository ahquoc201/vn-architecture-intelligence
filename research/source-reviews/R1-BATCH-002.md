# R1 Batch 002 — site-orientation foundation and edition review queue

**Status: ENGINEERING FOUNDATION ONLY, not reviewed feng shui formulas.**

## Outputs

- `src/vnai/site_orientation.py`: deterministic, pure geometry to compute clockwise azimuth from two explicit drawing-space vectors; vector origin is arbitrary. Does **not** use household birth year or provide lucky/unlucky directions.
- `knowledge/fengshui/orientation-input.schema.json`: schema for true north and **outward vector from building to street**. A frontage line tangent alone cannot determine facing direction.
- `research/editions/r1-batch002.yaml`: unresolved edition/source questions for Bát Trạch Minh Kính and Dương Trạch Tam Yếu. Refer to source IDs in `sources/bibliography.yaml`; **no numerical rules are approved**.
- `examples/townhouse_orientation.json`: an illustration in drawing coordinates, **not a measured survey**.

## Coordinate contract

- `north_vector_drawing_xy`: vector in the CAD drawing XY plane pointing to **true north**.
- `frontage_outward_vector_drawing_xy`: vector pointing **from the building outward toward the street**; not the direction of the road, facade line or boundary polyline.
- Both vectors may have any non-zero scale. Azimuth is clockwise relative to true north: 0° N, 90° E, 180° S, 270° W.
- Input uncertainty is in degrees. At a boundary or when the stated uncertainty overlaps the boundary of two 45° sectors, output both sectors with `AMBIGUOUS_BOUNDARY` rather than one definitive label. A zero uncertainty is a numerical idealization, not proof of survey precision.
- Magnetic north and grid north are not automatically converted. Missing/unsupported reference or ambiguous facing yields `NEEDS_DATA`.

## Research gates

The matrix does not validate book contents. Before Bát Trạch/Dương Trạch logic is implemented, collect a legally accessed full edition, verify edition/translator/chapter/page, document disputed conventions and test oracles reviewed by the relevant specialists. Feng shui remains traditional cultural interpretation; it does not override structural safety, technical standards or legal review.

## CLI

```bash
vnai fengshui orientation examples/townhouse_orientation.json
vnai fengshui orientation examples/townhouse_orientation.json --out outputs/orientation.json
```

No CAD changes are performed; output explicitly says `cad_writes_permitted: false`.
