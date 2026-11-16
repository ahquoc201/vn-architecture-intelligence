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
- [ ] Bảng thuật ngữ hướng/tọa, Môn–Chủ–Táo, trường phái và dị bản
- [ ] Lựa chọn một phương pháp Bát Trạch với nguồn ấn bản được xác minh
- [ ] Thẩm định test oracle từ người có chuyên môn, thêm thuật toán (không từ prompt)
- [ ] Dữ liệu nhà theo vùng và điều kiện tự nhiên; không gộp với rule pháp lý

## R2 — Engine thiết kế và quality gate
- [ ] Chuẩn hóa brief multi-floor, room type, walls/openings/doors, heights
- [ ] Kiểm tra giao thông, cửa, cầu thang, công năng, nội thất, bảng diện tích
- [ ] 2–3 phương án mặt bằng với quyết định thiết kế và thay đổi có thể tái tạo
- [ ] Đánh giá khí hậu vùng có mô hình/nguồn dữ liệu, không tự gán kết quả mô phỏng

## R3 — AutoCAD MCP & 3D
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
