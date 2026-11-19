# Roadmap — dựa trên điều kiện nghiệm thu, không hứa ngày hoàn thành

## R0 — Research foundation (bản 0.1.0)
- [x] Source Registry và phân biệt metadata/content approval
- [x] Chọn nguồn chính/candidate, source-intake template
- [x] Prototype geometry review, DXF sơ đồ, pytest, CI
- [ ] Có bản hợp pháp và báo cáo review cấp chương/trang cho sách chính
- [ ] Có KTS và nhà nghiên cứu phong thủy phản biện quy ước tính

## R1 — Văn hóa, phong thủy, kiến trúc nhà Việt
- [x] Batch-001: kiểm tra trực tiếp hai bài báo công khai, phạm vi TCVN và tạo 5 insight advisory-only có provenance/test
- [ ] Chốt từng ấn bản sách đã đọc hợp pháp và review chương/trang trước khi tạo rule
- [x] R1 Batch-002: schema vector Bắc thực/hướng ra đường, engine phân loại 8 hướng có xử lý sai số ranh giới; ma trận câu hỏi ấn bản chưa duyệt
- [x] R1 Batch-003: bảng thuật ngữ làm rõ đầu vào, biểu ghi các ấn bản công khai và phát hiện số trang mâu thuẫn; **chưa** thẩm định thuật ngữ/công thức theo nguyên bản
- [ ] Bảng thuật ngữ hướng/tọa, Môn–Chủ–Táo và dị bản **được chuyên gia duyệt**
- [ ] Lựa chọn một phương pháp Bát Trạch với nguồn ấn bản được xác minh
- [ ] Thẩm định test oracle từ người có chuyên môn, thêm thuật toán (không từ prompt)
- [ ] Dữ liệu nhà theo vùng và điều kiện tự nhiên; không gộp với rule pháp lý

## R2 — Engine thiết kế và quality gate
- [x] R2 Batch-004: design brief schema v1, requirement governance, multi-floor room program, hard/soft relationships and tested planning-data gates
- [x] Batch-005: versioned floor zoning, explicit architect decision records, 2D spatial diagnostics and wheel data verification
- [x] Batch-006-A: bounded deterministic rectangle candidates, hard constraints, explicit reservations, distinct proposals and spatial validation
- [x] Batch-006-B: exact candidate review records, explicit openings, circulation/portal graphs, bounded width checks and stair connectivity
- [x] Batch-006-C: evidence-bound candidate metrics, explicit preference policy, scoped comparisons and conditional rankings; no automatic approval or CAD writes
- [x] Batch-007-A: original constraint replay, revision/feedback review, scoped CAD readiness and synthetic benchmarks
- [ ] Actual architect review and expert-reviewed architectural benchmark oracles
- [ ] Chuẩn hóa brief multi-floor, room type, walls/openings/doors, heights
- [ ] Kiểm tra giao thông, cửa, cầu thang, công năng, nội thất, bảng diện tích
- [ ] 2–3 phương án mặt bằng với quyết định thiết kế và thay đổi có thể tái tạo
- [ ] Đánh giá khí hậu vùng có mô hình/nguồn dữ liệu, không tự gán kết quả mô phỏng

## R3 — AutoCAD MCP & 3D
- [x] Batch-007-A: verification/review foundation before drafting; no new CAD writes
- [ ] Batch-007-B: wall/hosted-opening and detailed stair information contracts with reviewed fixtures before drafting exporters
- [ ] Import/export DWG qua AutoCAD MCP trên máy Windows, đọc được bản vẽ gốc
- [ ] Xuất bản vẽ V1 đầy đủ mặt bằng có dim, layer, cửa, cầu thang, nội thất
- [ ] Kiểm tra mở lại CAD, phép đo, diff, backup, human approval
- [ ] Tạo mặt đứng/mặt cắt/3D từ một model có cao độ thống nhất

## Source watch
- [x] Registry cho những domain phải theo dõi
- [x] Script kiểm tra URL cho phép tạo candidate report bằng tay/CI
- [ ] Discovery RSS/API được cơ quan nguồn xác nhận; mở Issue đề xuất nguồn mới
- [ ] Đối chiếu hiệu lực pháp lý theo ngày và cập nhật sau PR review

Không auto-merge từ nguồn web vào tri thức sản xuất.


## R3 Batch 007-B1 (v0.1.10): wall geometry

- [x] Explicit wall intent and semantics, deterministic topology, constructive orthogonal wall/junction geometry.
- [x] Union wall accounting, complete clear-room subtraction, original/clear requirement impact and stale-evidence reporting.
- [x] Actual SVG previews and unchanged townhouse benchmark input; CLI, schemas, independent oracles and wheel integration.
- [ ] Human architectural review of these proposed walls and expert test-oracle sign-off.
- [ ] Batch 007-B2: explicit opening hosts/cuts, remapping review and renewed physical circulation/clearance evidence.

See WALL_GEOMETRY_CONTRACT.md. No door/window cuts, detailed stairs, structural inference,
production CAD output or automatic approval is included. Source/expert gates remain unchanged.
