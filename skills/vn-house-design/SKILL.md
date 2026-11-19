---
name: vn-house-design
description: Thu thập brief nhà ở Việt Nam và kiểm tra diện tích hình học trước khi lên phương án CAD concept.
---

# VN House Design

## Dùng khi

Người dùng mô tả kích thước khu đất, số tầng, nhu cầu phòng, công năng, phong cách và muốn Claude lên phương án mặt bằng CAD.

## Các bước

1. Thu thập: địa điểm ở mức cần thiết cho quy chuẩn, ranh giới đất (đa giác hoặc kích thước), đơn vị, Bắc thực, mặt tiếp cận, khoảng lùi/giới hạn xây dựng nếu đã biết, số tầng, cao độ, danh sách phòng, target areas, nhu cầu gia đình, phong cách, ưu tiên phong thuỷ.
2. Chia dữ liệu `confirmed`, `missing`, `assumed`. Đối với hướng đất, cao độ và chỉ giới, không suy đoán.
3. Đề xuất **2–3 cách phân khu có lý do**, không tạo bản vẽ nếu thiếu ranh đất hoặc units đáng tin cậy.
4. Chuẩn hoá polygon phòng vào JSON theo `examples/townhouse_sample.json` (không ghi số liệu không có nguồn).
5. Chạy `vnai review <file> --markdown <report>`; xử lý `WARNING` và `NEEDS_DATA`, ghi các quyết định thiết kế.
6. DXF từ `vnai dxf` hiện **chỉ là sơ đồ hình học kiểm thử**, không gọi là bản CAD hoàn thiện. Để triển khai tường/cửa/dim dùng CAD adapter tương lai sau phê duyệt.
7. Khi người dùng sửa, giữ V1 và tạo V2, giải thích tác động diện tích và giữ lại các yêu cầu đã chốt.

## Kết quả phải trả

Brief, assumption register, phương án/khác biệt, bảng diện tích đo được, kết quả QA hình học, tài liệu nguồn, các hạng mục chưa thể xác nhận và review gate.

## R1 provenance check

For suggestions rooted in regional architecture or worship spaces, use only the non-executable observations in `knowledge/insights.yaml`, explicitly distinguishing historical case studies from authors' design preferences. Do not derive a numerical room size, stair count or cardinal-direction rule from a table of contents. Keep design geometry sourced from the client's confirmed dimensions and the tested geometry engine.


## R2 Batch 004: required brief/program gate before step 3

1. Collect a brief using `knowledge/architecture/design-brief.schema.json` and
   `docs/DESIGN_BRIEF_CONTRACT.md`; start from `examples/townhouse_4x20_brief.json`.
   Preserve stable requirement IDs, origin, type, confirmation and priority.
2. Keep mandatory requirements, preferences, assumptions and questions distinct.
   Do not invent footprints, room dimensions, floor assignments or orientations.
3. Run `vnai design brief validate <brief.json>` and `vnai design brief report <brief.json>`.
   INVALID (exit 1) needs correction; INCOMPLETE (exit 3) needs questions linked to requirement IDs.
   Input/read failures return exit 2. Preserve earlier briefs/reports with versioned filenames.
4. Run `vnai design program build <brief.json>` for declared rooms and hard/soft relationships.
   Explain missing information, conflicts and unresolved decisions. Area sums do not prove feasibility.
5. Obtain explicit architect approval of the brief/program before the layout steps above, even
   when VALID. Do not derive room minima or unsupported recommendations from general knowledge.
6. Keep Feng Shui and QCVN/TCVN reviews separate under the source review policy. VALID never
   grants specialist approval or authorization to change CAD. Any CAD write needs explicit approval.
7. Maintain this skill in `skills/vn-house-design/`; do not create a duplicate installed copy here.


## R2 Batch 005: zoning and spatial validation before layout work

- Read `docs/ZONING_GEOMETRY_CONTRACT.md`. Use the validated source brief and
  deterministic program room instance IDs, preserving their requirement IDs.
- Record zoning using `vnai.zoning.create_zoning_proposal`; it only copies floors
  explicitly present in the brief and leaves other assignments/functional zones unresolved.
  Collect proposed decisions with provenance and rationale instead of inventing assignments.
- Run `vnai design zoning validate <file>` and `vnai design zoning report <file>`.
  Present unassigned_room_ids, missing decisions and source-brief questions to the architect.
- A proposed or reviewed assignment is not approved. Approval requires ordered architect
  decision records bound to the exact brief/revision/assignment digest. Only the human
  reviewer may supply a real approval record. Fixture records are synthetic examples only.
  If content changes, obtain a fresh revision/review; never regenerate approvals automatically.
- Run `vnai geometry validate <file>` and `vnai geometry report <file>` for supplied
  polygons. Keep frame/units/tolerances explicit; do not repair polygons or exempt overlaps
  automatically. Explain errors versus tolerance warnings and declared intentional relationships.
- VALID geometry means only the supported spatial checks passed; it is not evidence of
  a buildable, structurally safe or legally compliant design. Keep code/Feng Shui review separate.
  CAD modifications still need explicit authorization, even after architect-approved zoning.


## R2 Batch 006-A: preliminary polygon candidates

- Read `docs/FLOORPLAN_CONTRACT.md`. Generation requires a complete validated brief/program,
  approved source zoning, supplied rectangular floor envelopes, explicit per-room area/dimension
  bounds, a declaration of known fixed elements, and content-bound authorization for preliminary
  generation. Unknown footprint, floor assignments or fixed elements remain INCOMPLETE.
- Run `vnai design floorplan generate <spec.json> --candidates 3`. Use `--out` only for a new,
  versioned report file. Source room/requirement IDs remain authoritative. Never use the lot as
  a building footprint or silently turn preferences into hard minimum dimensions.
- Inspect all hard_validation/spatial_report results before comparing soft_scores. Scores rank
  only discovered valid candidates; they never excuse a failed hard constraint. Candidate geometry
  must be distinct; fewer alternatives are reported rather than invented.
- SEARCH_EXHAUSTED means the grid or operation budget found no valid candidate, not proof of
  mathematical infeasibility. INFEASIBLE is reserved for explicit area/dimensional contradictions.
  Report UNSUPPORTED constraints, including hard separation without a defined metric.
- Reserved circulation/stairwell/shaft polygons are only enforced when supplied. Explain that
  circulation connectivity, access, egress, doors, windows, stairs, structure and MEP are unresolved.
  Room polygons are preliminary concept proposals, not a complete architectural drawing.
- Every generated candidate stays PROPOSED even when its source zoning was approved. Obtain
  architect review before adoption. Never regenerate human approval records for generated output.
  CAD writes remain disabled and require separate explicit authorization in a future adapter.


## R2 Batch 006-B: candidate selection and circulation review

- Read `docs/CIRCULATION_CONTRACT.md`. Keep the generated candidate immutable; select its
  exact candidate_id and canonical candidate_digest in the review sidecar. Run
  `vnai design candidate review <file>`; SELECTED/REVIEWED does not mean APPROVED.
- Obtain explicit human records for review/approval, including provenance, timestamp and exact
  design_digest. Do not invent an architect identity, rewrite old approval records, or promote
  a proposal automatically. Changing doors/routes/stairs invalidates prior design approval.
- Collect explicit openings, boundary hosts, clear widths and hinge/slide metadata. Run
  `vnai design openings validate <file>`. Shared boundaries never imply a door. Request missing
  information; no minimum door/passage width may be invented from unverified standards.
- Run `vnai design circulation analyze <file>` and inspect components, entrance reachability and
  isolated rooms. GRAPH_CONNECTED means graph topology, not demonstrated walking clearance.
- Collect known fixed obstacles, local opening clearance regions and explicit width-checked
  walking paths when clearance matters. Unknown inventories/routes remain NOT_VERIFIED.
  Known geometric conflicts are reported as BLOCKED and must not be hidden by other passes.
- Run `vnai design stairs validate <file>` for actual stairwell/landing and entry/exit references.
  Envelope alignment or a stair graph edge does not validate treads, risers, headroom or safety.
- Run `vnai design architectural-review <file>` and present geometry, graph, clearance,
  technical-compliance and approval fields separately. Explain unresolved/unsupported evaluations
  and ask the architect to review exact content before adoption. Even bounded 2D traversal never
  establishes complete accessibility/egress certification or construction readiness.
- Keep QCVN/TCVN and Feng Shui review separate. cad_writes_permitted stays false, including for
  APPROVED review records. CAD modifications require explicit authorization in a future workflow.


## R2 Batch 006-C: compare alternatives before an architect decision

Read `docs/CANDIDATE_EVALUATION_CONTRACT.md` for input, metric units, evidence statuses, scope and exit codes. Keep one user-facing agent; these engines are tools.

1. Request 2-3 distinct proposals through `vnai design floorplan generate <input> --candidates 3`. Preserve original immutable candidates; attach explicit Batch 006-B opening/stair/obstacle/path sidecars for each. Collect and confirm inventories; never invent doors, stairs, directions or dimensions to improve a score.
2. Construct a versioned evaluation request with explicit criterion IDs, weights, directions, normalization bounds, required checks, optional/N/A policy, precision and tie tolerance. Agree trade-offs with the architect; example weights are synthetic, not defaults. Include entrance_reachability/circulation_clearance as required checks when the decision depends on circulation. Geometry-only evidence cannot establish physical traversal.
3. Run `vnai design candidates evaluate <request>` and explain observed values, evidence status, input declarations and hard eligibility separately. UNKNOWN is not zero or FAILED. N/A leaves the applicable denominator. Known hard failure prevents scoring; unsupported required work blocks an eligible claim. Recollect evidence when candidate/design/policy digests change; never reuse a favorable stale report.
4. Run `vnai design candidates compare <request> --markdown <new-versioned-path>`. Check exact source requirement/site/floor/inventory baselines. Different baselines require a documented explicit metric scope. Report verified pairwise trade-offs and remaining unknowns even when global scores are unavailable. Optional exclusions and effective weights must be disclosed; differently weighted active subsets cannot rank together.
5. Run `vnai design candidates rank <request>` only under the explicit policy. Explain why the leader changes with weights and why a tie has no unique winner. Withhold definitive ranking for missing critical evidence, unavailable required criteria or incompatible baselines. Partial ordering is conditional and requires allow_partial_ranking; no automatic selection follows from a policy leader.
6. Ask the architect to review trade-offs and supply unresolved requirements, then record feedback as a separate design decision/revised brief. Selection, REVIEWED and APPROVED remain separate Batch 006-B content-bound states. Never promote feedback or engine rank into approval. Preserve prior reports and version stamps.
7. Keep standards/QCVN/TCVN and optional source-grounded Feng Shui as separate advisory layers, subject to source-clause/edition/page and expert/test gates. No unverified aesthetic, safety or Feng Shui score; no CAD modifications or new authority is granted by evaluation.
