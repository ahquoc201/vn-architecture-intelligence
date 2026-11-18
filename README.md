# Vietnam Architecture Intelligence (VNAI)

**Phiên bản 0.1.4 — nền tảng nghiên cứu có thể chạy, không phải hệ thống tự thiết kế hoặc phê duyệt hồ sơ thi công.**

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
