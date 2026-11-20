# Vietnam Architecture Intelligence (VNAI)

**Phiên bản 0.1.14 — nền tảng nghiên cứu có thể chạy, không phải hệ thống tự thiết kế hoặc phê duyệt hồ sơ thi công.**

Repo mã nguồn mở phục vụ **Claude Code là một agent duy nhất**, với ba nhiệm vụ tách biệt:

1. **Kiến trúc**: tổ chức brief, hình học khu đất/phòng, kiểm tra diện tích cơ bản, chuẩn bị dữ liệu CAD.
2. **Phong thủy Việt Nam**: tìm và đối chiếu các trường phái được gia chủ lựa chọn; **không đưa kết luận dự báo như bằng chứng khoa học**. Chỉ áp dụng quy tắc sau khi kiểm chứng đúng ấn bản, phép tính và có bài test.
3. **Tiêu chuẩn và xây dựng**: **chỉ báo cáo** quy chuẩn/tiêu chuẩn liên quan, điều khoản và dữ liệu thiếu; không tự sửa bản vẽ. Các vấn đề an toàn hoặc pháp lý phải được xử lý trước khi đưa hồ sơ vào thi công.

## Hiện đã làm được

- Danh mục nguồn ban đầu có URL, xuất xứ, mức độ đọc nội dung và trạng thái thẩm định.
- Kiểm tra tính toàn vẹn của source registry, tránh nâng nguồn chưa được đọc thành rule đã duyệt.
- **R1/BATCH-001:** 5 nhận định nghiên cứu có dẫn nguồn (`knowledge/insights.yaml`), phân biệt nghiên cứu trường hợp, ý kiến tác giả và phạm vi tiêu chuẩn; chưa cái nào được duyệt thành rule thực thi.
- **R1/BATCH-003:** 6 biểu ghi sách/bản in từ catalog công khai, 8 thuật ngữ làm rõ đầu vào, 4 câu hỏi quy tắc chưa kiểm chứng; phát hiện mâu thuẫn số trang, validator bảo đảm không có công thức chưa duyệt được thực thi.
- **R1/BATCH-002:** có schema và CLI tính hướng Bắc thực từ vector CAD, báo hướng mơ hồ gần ranh giới; bảng câu hỏi ấn bản Bát Trạch/Dương Trạch chưa được kiểm chứng.
- Kiểm tra hình học mặt bằng JSON (đa giác hợp lệ, diện tích phòng, sai lệch mục tiêu, phòng chồng lấn/vượt ranh). Chỉ đo vùng phòng do người dùng khai báo; **không nhận dạng phòng tự động từ DWG**.
- Tính hướng từ góc phương vị hoặc từ vector Bắc thực và hướng mặt tiền đi từ nhà ra đường; cảnh báo vùng ranh giới, không suy luận cung mệnh/phong thủy khi chưa có engine được duyệt.
- Báo cáo JSON/Markdown có các trạng thái `MEASURED`, `WARNING`, `NEEDS_DATA`, `NOT_EVALUATED`.
- Xuất DXF **sơ đồ hình học** tùy chọn, không phải bản vẽ kiến trúc thi công đầy đủ.
- Ba skill mẫu cho Claude Code và CI kiểm thử.

## R2 Batch 004 - Design Brief & Space Program

Versioned JSON Schema v1 and Python validation preserve requirement provenance and
confirmation. The deterministic program expands room instances and client-supplied
hard/soft relationships without inventing floor assignments, dimensions or layouts.

```powershell
vnai design brief validate examples/townhouse_4x20_brief.json
vnai design brief report examples/townhouse_4x20_brief.json
vnai design program build examples/townhouse_4x20_brief.json
```

All commands emit JSON to stdout. Exit codes: `0` VALID, `1` INVALID,
`2` input/read/parse failure, `3` INCOMPLETE. This example intentionally returns `3`:
80 m2 declared rectangular lot, seven rooms, unresolved room areas, floors and footprint.
VALID means data-ready for the supported workflow, still subject to architect approval.
See [the data contract](docs/DESIGN_BRIEF_CONTRACT.md) for field semantics and limits.

## R2 Batch 005 - Zoning and Geometry Contract

Floor zoning preserves source room instances and explicit architect review records.
The 2D contract validates polygons, holes, ownership, units, tolerances, envelopes and
same-floor overlaps without repairing geometry or generating a layout.

```powershell
vnai design zoning validate examples/batch005/zoning-proposed.json
vnai design zoning report examples/batch005/zoning-approved.json
vnai geometry validate examples/batch005/geometry-valid.json
vnai geometry report examples/batch005/geometry-linked-approved.json
python scripts/smoke_wheel.py
```

The proposal intentionally returns exit 3 (INCOMPLETE); approved **synthetic fixture**
and valid geometry examples return 0. Exit 1 means INVALID; exit 2 means an input error.
No example is a real architect approval or a client-confirmed layout.
See [the zoning/geometry contract](docs/ZONING_GEOMETRY_CONTRACT.md).
The wheel bundles authored runtime data; the smoke script installs it in a fresh venv
outside the checkout and exercises old and new commands with isolated Python.

## R2 Batch 006-A - Deterministic preliminary floorplans

The generator searches rectangular room polygons on an explicit finite grid. It uses
approved source zoning, supplied footprints/reservations and hard area/dimension bounds.
Every proposal passes the spatial validator and remains PROPOSED, with CAD writes disabled.

```powershell
vnai design floorplan generate examples/batch006a/alternatives.json --candidates 3
vnai design floorplan generate examples/batch006a/fixed-stair.json
vnai design floorplan generate examples/batch006a/missing-footprint.json
```

Fixtures and their approval records are synthetic. The first example yields three distinct
proposals; the missing-footprint example is INCOMPLETE (exit 3). Search exhaustion is not
proof of continuous infeasibility. No circulation connectivity or buildability is claimed.
See [the generation contract](docs/FLOORPLAN_CONTRACT.md) for inputs, statuses and limits.

## R2 Batch 006-B - Circulation, openings and stair connectivity

Candidate selection/review uses exact content digests. Explicit boundary-hosted doors
produce a graph; supplied walking routes, widths and clearance envelopes provide a
separate bounded 2D check. Stair envelopes/entry points do not certify staircase design.

```powershell
vnai design candidate review examples/batch006b/selected-only.json
vnai design openings validate examples/batch006b/corridor-clearance.json
vnai design circulation analyze examples/batch006b/corridor-graph-only.json
vnai design stairs validate examples/batch006b/stairs-connected.json
vnai design architectural-review examples/batch006b/corridor-clearance.json
```

All examples and actors are synthetic. GRAPH_CONNECTED is distinct from verified
walking clearance. Missing information remains INCOMPLETE (exit 3), known errors INVALID
(exit 1). VALID (exit 0) applies only to the stated check scope; technical compliance
remains NOT_EVALUATED and CAD writes remain disabled. See
[the circulation review contract](docs/CIRCULATION_CONTRACT.md).

## Chưa làm và không được tuyên bố đã làm

- Chưa đọc toàn văn các giáo trình/sách phong thủy thương mại; chưa có công thức Bát Trạch/Dương Trạch được chuyên gia thẩm định.
- Chưa tính kết cấu, PCCC, điện nước, chống thấm hay xác nhận tuân thủ pháp lý.
- Chưa tạo bản vẽ kiến trúc hoàn chỉnh (tường, cửa, cầu thang, nội thất, dim, mặt cắt, 3D); chưa kết nối AutoCAD MCP trực tiếp.
- Chưa có crawler tự động tìm ấn phẩm mới; có sổ theo dõi nguồn và script kiểm tra khả năng truy cập URL để phát triển tiếp.

## Chạy thử (Python 3.11+)

```powershell
cd vn-architecture-intelligence
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,cad]"
python -m pytest -q
vnai sources validate
vnai knowledge validate
vnai fengshui orientation examples/townhouse_orientation.json
vnai fengshui knowledge validate
vnai fengshui knowledge report --out outputs/fengshui_research_queue.json
vnai review examples/townhouse_sample.json --out outputs/review.json --markdown outputs/review.md
vnai dxf examples/townhouse_sample.json --out outputs/townhouse_schematic.dxf
```

Trên Linux/WSL thay dòng kích hoạt bằng `source .venv/bin/activate`.

## Gắn vào Claude Code

Đặt repo trong workspace hoặc mở Claude Code ngay tại thư mục repo. Các skill nằm trong `skills/`; có thể sao chép từng thư mục vào `.claude/skills/` của dự án CAD. File `CLAUDE.md` hướng dẫn sử dụng CLI và giới hạn an toàn. **Không cần cài hai agent**.

## Dữ liệu và kiểm tra nguồn

- `sources/bibliography.yaml`: danh mục có thẩm định thư mục và cấp độ tiếp cận nội dung.
- `docs/SOURCE_REVIEW_POLICY.md`: điều kiện để nâng từ nguồn tham khảo sang quy tắc chạy máy.
- `sources/intake.yaml`: nguồn mới chờ kiểm chứng; quy trình review qua PR.
- `knowledge/insights.yaml`: nhận định nguồn công khai đã kiểm tra, chỉ cho phép tư vấn, không tự động sửa CAD.
- `research/source-reviews/R1-BATCH-003.md`: so sánh biểu ghi sách công khai, vấn đề dị bản chưa giải quyết, hướng thẩm định tiếp theo.
- `knowledge/fengshui/edition-evidence.yaml`, `terminology.yaml`, `rule-candidates.yaml`: dữ liệu nghiên cứu chỉ để rà soát, tuyệt đối chưa phải công thức áp dụng.
- `research/source-reviews/R1-BATCH-001.md`: ghi chép thẩm định cấp nội dung và các giới hạn còn mở.
- `docs/ROADMAP.md`: roadmap giai đoạn R0–R3.
- `knowledge/`: thiết kế ontology và quy tắc, không chứa sách PDF thương mại.

## Sử dụng với bản vẽ thực tế

Khi ghép AutoCAD MCP: nhập bản sao DWG/DXF → chuẩn hóa lớp phòng/khu đất và Bắc thực → kiểm tra số học → AI tạo các lựa chọn → kiến trúc sư duyệt → **mới được ghi bản sao CAD**. Nếu thiếu cao độ, khảo sát hoặc quy định địa phương, agent phải hỏi người thiết kế hoặc ghi `NEEDS_DATA`, không tự tạo số liệu rồi khẳng định đúng.

## Bản quyền

`LICENSE` (MIT) áp dụng **mã và tài liệu do dự án tự sáng tạo**. Không tự động cấp phép lại tác phẩm của tác giả/NXB, QCVN/TCVN, bản vẽ khách hàng hoặc nội dung trích dẫn bên ngoài. Xem `docs/RIGHTS.md`.


## R2 Batch 006-C: evidence-based comparison (v0.1.8)

Candidate metrics, evidence coverage, hard eligibility and explicit preference scoring are separate layers. Missing evidence stays unknown, known hard failures cannot win, and incompatible baselines block ranking. No architect selection/approval or CAD permission is inferred.

```powershell
vnai design candidates evaluate examples/batch006c/verified-circulation.json
vnai design candidates compare examples/batch006c/three-candidates.json --markdown outputs/comparison-v0.1.8.md
vnai design candidates rank examples/batch006c/three-candidates.json
vnai design candidates rank examples/batch006c/ranking-withheld.json
```

The synthetic area policy ranks A (0.916667), B (0.25), C (0.083333); changed-weights.json makes B the policy leader. These geometry-only preferences leave circulation proof unresolved. The strict circulation fixture blocks a definitive ranking when clearance is unknown, despite graph connectivity. See [evaluation contracts](docs/CANDIDATE_EVALUATION_CONTRACT.md) for units, denominators, normalization, applicability, digest dependencies, explicit scope, tie handling and exit codes. Markdown files use exclusive creation; preserve prior reports.


## R3 Batch 007-A: design replay and CAD readiness (v0.1.9)

Explicit generation provenance enables independent replay of original dimensions, areas, floors, adjacency and reservations. External revisions retain parent/child bindings; stale evidence and parent approval do not silently survive. Room-polygon readiness is separate from complete architectural drafting and CAD-write authorization.

```powershell
vnai design floorplan generate examples/batch006a/two-room.json --provenance
vnai design replay validate examples/batch007a/replay/valid-provenance.json
vnai design revision compare examples/batch007a/revision/valid-manual-revision.json
vnai design readiness report examples/batch007a/readiness/room-geometry-ready.json
vnai design benchmark run examples/batch007a/benchmark/benchmark-a.json
```

See [replay/revision/readiness contracts](docs/DESIGN_REPLAY_CAD_READINESS_CONTRACT.md), [benchmark protocol](docs/ARCHITECTURAL_BENCHMARK_PROTOCOL.md) and [human review template](docs/ARCHITECTURAL_BENCHMARK_REVIEW_TEMPLATE.md). All scenarios are synthetic; actual expert review remains pending. The 8x15 case reports unsupported qualitative hard separation. Legacy candidates without original provenance remain incomplete. Existing schematic DXF stays compatible; no new CAD writer is added.


## R3 Batch 007-B1: wall geometry (v0.1.10)

Selected allocations now derive explicit wall polygons, centerlines, exposed faces,
L/T/X junctions, union footprints and clear rooms without changing the source layout.
Confirm boundary semantics, thickness, alignment, no-wall intent and allocation/clear
requirement bases. New conflicts and stale opening/clearance evidence remain visible.

```powershell
vnai design walls generate examples/batch007b1/rectangle-inward.json
vnai design walls validate examples/batch007b1/shared-wall.json
vnai design walls report examples/batch007b1/t-junction.json --markdown outputs/walls-v0.1.10.md
vnai design walls preview examples/batch007b1/townhouse-benchmark.json --out outputs/townhouse-walls-v0.1.10.svg
```

The synthetic 4x5 m inward-wall oracle yields 16.56 m2 clear and 3.44 m2 wall union.
Townhouse preview intentionally exits 4 (CONFLICT): benchmark requirements are unchanged.
See [wall contract](docs/WALL_GEOMETRY_CONTRACT.md) and [generated previews](examples/batch007b1/previews).
Geometry generation does not grant architect approval or CAD permission. Opening cuts,
updated clearance and fresh architect review belong to 007-B2; existing DXF remains schematic.


## Wall-hosted opening drafting (v0.1.11)

Explicit door/window specifications now create real host cuts, finite leaf/frame/glazing
geometry, 90-degree swing arcs, surface sliding tracks, schedules and source-bound proposed
revisions. Full wall, selected plan cut and floor obstruction geometry are separate.
Windows never create walking edges or increase room clear floor area. Source conflicts
remain visible; no approval or CAD-write permission follows from successful geometry.

```powershell
vnai design openings draft examples/batch007b2/oracle-entrance.json
vnai design openings drafting-validate examples/batch007b2/fixed-window.json
vnai design openings schedule examples/batch007b2/interior-hinged.json --markdown outputs/opening-schedule-v0.1.11.md
vnai design openings preview examples/batch007b2/townhouse-benchmark.json --out outputs/townhouse-openings-v0.1.11.svg
```

Townhouse retains the exact B1 source and reports CONFLICT (exit 4). The independent
4m x .2m wall / .9m rough door oracle gives .8m2 source, .18m2 cut, .62m2 remaining.
See [opening drafting contract](docs/OPENING_DRAFTING_CONTRACT.md),
[fixtures](examples/batch007b2) and [actual generated previews](examples/batch007b2/previews).
Existing `design openings validate` and schematic DXF behavior remain compatible.

## R3 Batch 007-B3 - Stair geometry and sections (v0.1.12)

Explicit straight/L/U flights generate real tread/riser/landing geometry, absolute elevations,
true straight or explicitly developed multi-flight sections, floor-opening assessment,
continuous horizontal-prism headroom and fresh 006-B interface replay. Source B2 inputs
remain immutable; known conflicts and missing evidence stay visible. CAD writes remain false.

```powershell
vnai design stairs draft examples/batch007b3/straight.json
vnai design stairs schedule examples/batch007b3/u-shaped.json --markdown outputs/stair-schedule-v0.1.12.md
vnai design stairs preview examples/batch007b3/l-shaped.json --view section --out outputs/stair-section-v0.1.12.svg
```

These synthetic geometry examples may return INCOMPLETE (3); townhouse returns CONFLICT (4).
See [the stair contract](docs/STAIR_GEOMETRY_CONTRACT.md) for counting, headroom coverage,
limits, exit codes and the distinction between modeled geometry and architectural approval.


## R3 Batch 007-B4 ? integrated wall-aware concepts

The opt-in workflow reuses existing room generation and actual wall/door/stair engines,
checks clear areas/dimensions, and attempts only explicitly permitted partition/opening moves.
Every accepted revision replays original hard constraints; source/fixed geometry and review
history remain intact. New two-storey synthetic inputs include a measured before/after doorway
refinement and actual per-floor SVG. Synthetic dimensions are not regulatory defaults.

```powershell
vnai design integrated refine examples/batch007b4/residential-4x20-six-rooms.json --out outputs/integrated-v0.1.13.json
vnai design integrated preview outputs/integrated-v0.1.13.json --view comparison --out outputs/integrated-v0.1.13.svg
```

See [the integrated contract and architect walkthrough](docs/INTEGRATED_FLOORPLAN_CONTRACT.md).
Geometric success remains PROPOSED, with human/technical review pending and CAD writes disabled.


## R3 Batch 007-C — Architectural Dimensions, Annotation & CAD Layer Engine (v0.1.14)

Turns verified integrated floorplans, walls, hosted openings, and stairs into a deterministic,
CAD-neutral Drawing Intermediate Representation (`architectural-drafting-v1`) with actual measured
dimensions, closure-verified dimension chains, Vietnamese Unicode room annotations (interior
pole-of-inaccessibility placement), door/window/stair tags, source-grounded reference symbols, configurable CAD
layer policy (`vnai-cad-layers-v1`, project-level convention with `ezdxf_mapping`), bounded
collision detection, and scale-consistent SVG sheet/floor/section previews.

```powershell
vnai design drafting generate examples/batch007c/townhouse-6rooms-drafting.json --out outputs/townhouse-drafting-v0.1.14.json --markdown outputs/townhouse-drafting-v0.1.14.md
vnai design drafting validate outputs/townhouse-drafting-v0.1.14.json
vnai design drafting report outputs/townhouse-drafting-v0.1.14.json --markdown outputs/townhouse-drafting-report-v0.1.14.md
vnai design drafting layers outputs/townhouse-drafting-v0.1.14.json --markdown outputs/townhouse-layers-v0.1.14.md
vnai design drafting preview outputs/townhouse-drafting-v0.1.14.json --floor F1 --out outputs/townhouse-F1-v0.1.14.svg
vnai design drafting preview outputs/townhouse-drafting-v0.1.14.json --view sheet --out outputs/townhouse-sheet-v0.1.14.svg
```

See [the architectural drafting contract](docs/ARCHITECTURAL_DRAFTING_CONTRACT.md),
[Batch 007-C fixtures](examples/batch007c), and [generated SVG previews](examples/batch007c/previews).
Source geometry remains immutable (48/48 integrated checks verified), `cad_writes_permitted` stays
`false`, architectural approval stays `NOT_GRANTED`, and production DXF export belongs to Batch 007-D.
