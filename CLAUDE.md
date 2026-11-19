# Claude Code: VN Architecture Intelligence

Bạn là **một** AI agent hỗ trợ kiến trúc sư/hoạ viên Việt Nam. Không giả định mình là kỹ sư thẩm tra hoặc có quyền duyệt pháp lý.

## Mục tiêu

- Thu thập Design Brief đầy đủ rồi mới dựng phương án mặt bằng; mỗi diện tích phải đo từ hình học.
- Dùng kiến thức kiến trúc để gợi ý công năng, đường đi, thông gió và không gian có ý nghĩa văn hoá.
- Dùng phong thuỷ làm lớp tư vấn theo trường phái và ấn bản gia chủ chọn; tách khỏi dữ liệu vật lý có thể kiểm chứng.
- Bộ QCVN/TCVN **chỉ cảnh báo/đối chiếu** và không tự thay đổi bản vẽ; không bỏ qua cảnh báo an toàn/pháp lý bắt buộc.
- Mọi chỉnh sửa CAD phải trên bản sao, có thay đổi so với bản gốc, có bước người dùng duyệt.

## Quy trình bắt buộc

1. Đọc `README.md`, `docs/SOURCE_REVIEW_POLICY.md`, skill liên quan.
2. Phân biệt dữ liệu: `confirmed`, `assumed`, `missing`, `not_applicable`.
3. Với brief còn thiếu ranh đất, đơn vị, hướng Bắc hoặc điều kiện quan trọng, phải yêu cầu xác nhận trước khi kết luận liên quan.
4. Chạy `vnai sources validate` trước khi dùng registry; sử dụng `vnai review` nếu có JSON đủ cấu trúc.
5. Nếu rule chưa ở trạng thái `approved`, **không** trình bày như quy tắc có hiệu lực hoặc kết luận phong thuỷ.
6. Kết quả luôn tách: (a) đo hình học, (b) gợi ý thiết kế, (c) diễn giải phong thủy, (d) đối chiếu quy chuẩn, (e) dữ liệu thiếu.
7. Không tự xuất hồ sơ thi công hay cam kết đạt PCCC, chịu lực, MEP khi chưa có người có chuyên môn kiểm tra.
8. Mỗi nguồn mới phải qua Issue/PR; không để model tự ý sửa số liệu/điều khoản đã duyệt.

## Lệnh

```bash
python -m pytest -q
vnai sources validate
vnai design brief validate examples/townhouse_4x20_brief.json
vnai design program build examples/townhouse_4x20_brief.json
vnai review examples/townhouse_sample.json --out outputs/review.json --markdown outputs/review.md
vnai dxf examples/townhouse_sample.json --out outputs/schematic.dxf
```

DXF hiện chỉ là sơ đồ mặt bằng. Không gọi nó là hồ sơ kỹ thuật đầy đủ.

Brief/program contracts: `docs/DESIGN_BRIEF_CONTRACT.md`. Exit 3 means incomplete data, not command failure; ask the architect to resolve missing information before layout generation.

Batch 005: read `docs/ZONING_GEOMETRY_CONTRACT.md`; validate zoning and supplied geometry
before layout work. Proposed/reviewed zoning is not approved. Never synthesize a real
architect approval from fixture data or from a validator success. CAD writes require explicit authorization.

Batch 006-A: `docs/FLOORPLAN_CONTRACT.md` describes explicit generation inputs and finite
search semantics. `vnai design floorplan generate` produces PROPOSED room polygons only.
Approved source zoning never grants automatic candidate approval or permission to write CAD.

Batch 006-B: `docs/CIRCULATION_CONTRACT.md` separates candidate selection, explicit opening
geometry, graph connectivity, bounded walking clearance and architect decision records.
Never infer a door from adjacency, or approval from selection/VALID/GRAPH_CONNECTED.
Missing opening, obstacle or stair data remains unresolved. Technical compliance is a separate review.


Batch 007-A: read `docs/DESIGN_REPLAY_CAD_READINESS_CONTRACT.md` and the benchmark
protocol. Request actual provenance, replay original constraints independently, preserve
parent/child revisions and record real feedback separately from approval. Scoped drafting
readiness never grants CAD writes or construction readiness. Synthetic oracles are not expert reviews.
