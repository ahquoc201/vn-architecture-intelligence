---
name: vn-fengshui-review
description: Đối chiếu ý tưởng nhà ở với kiến thức phong thủy truyền thống Việt Nam theo trường phái và ấn bản được xác minh.
---

# VN Feng Shui Review

## Dùng khi

Gia chủ chọn Bát Trạch, Dương Trạch, hoặc yêu cầu xét hướng đất/hướng cửa/bếp/giường/phòng thờ theo truyền thống.

## Giới hạn hiện tại

Chưa có thuật toán Bát Trạch/Dương Trạch được chuyên gia duyệt. Không tự tính cung mệnh hoặc tuyên bố tốt/xấu từ các nguồn đang ở `candidate`.

## Quy trình

1. Thu thập hướng Bắc **được đo**, frontage/entrance facing, trường phái và quy ước, thông tin gia chủ nếu tự nguyện cung cấp.
2. Đọc `sources/bibliography.yaml`; ghi source ID, evidence level, khác biệt dị bản, phạm vi nghiên cứu.
3. Với nguồn chưa duyệt: trả `NEEDS_SOURCE_REVIEW`, chỉ đưa khung câu hỏi/gợi ý văn hoá dưới dạng tùy chọn và không biến thành yêu cầu thiết kế bắt buộc.
4. Không đồng nhất kiến giải phong thủy với khí hậu hay pháp luật; nếu thay đổi vị trí cửa/bếp/tường có ảnh hưởng an toàn, báo cho kiến trúc sư.
5. Trong tương lai: chỉ gọi executable engine nếu rule có ấn bản, trang, review, test và version.

## Insight có nguồn (không thực thi)

Read `knowledge/insights.yaml` and `docs/R1_EVIDENCE_CONTRACT.md` to offer conditional architectural conversation starters. Insights `VNAI-OBS-001` to `VNAI-OBS-004` are **not** Bát Trạch/Dương Trạch formulas, certified design prescriptions, or evidence of outcomes. Cite `source_ids` and `source_locator` and ask the household whether these cultural preferences matter. Never activate CAD writing solely because a qualitative observation exists.

## Công cụ hướng Bắc thực (chỉ hình học)

Run `vnai fengshui orientation examples/townhouse_orientation.json` only when the
input explicitly confirms **true north in drawing XY**, and **frontage outward from
building to street**. Read `knowledge/fengshui/orientation-input.schema.json` and
`research/source-reviews/R1-BATCH-002.md` before relying on the result.

- `COMPUTED` means a numeric azimuth was derived from input vectors; **not** surveyed,
  feng-shui approved, technically compliant or ready for CAD edits.
- `NEEDS_REVIEW` with `AMBIGUOUS_BOUNDARY` means the uncertainty interval overlaps two
  compass sectors. Present both, never choose an auspicious sector.
- `NEEDS_DATA` means direction convention, true north or uncertainty needs confirmation.
- Do not derive Kua, Bát Trạch auspicious directions, Môn–Chủ–Táo or rule verdicts:
  `research/editions/r1-batch002.yaml` documents unreviewed editions.

## Nguồn và thuật ngữ chưa duyệt

1. Chạy `vnai fengshui knowledge validate` trước khi tham khảo dữ liệu. Nếu lỗi, dừng toàn bộ diễn giải từ corpus này.
2. Đọc `knowledge/fengshui/edition-evidence.yaml` để xác định **claim thư mục** đúng từng bản; các mâu thuẫn số trang phải xuất hiện trong báo cáo, không tự giải quyết.
3. Dùng `terminology.yaml` **chỉ để hỏi rõ dữ liệu đầu vào**, đặc biệt `Môn`, `Chủ`, `Táo`, tọa/hướng; không coi working_definition là lời trích nguyên tác.
4. Chạy `vnai fengshui knowledge report` và tôn trọng `NEEDS_SOURCE_REVIEW`. Các item trong `rule-candidates.yaml` là câu hỏi, không phải rule hay phép xem tốt/xấu.
5. Phân biệt rõ lựa chọn văn hóa (tùy gia chủ) với yêu cầu an toàn, QCVN/TCVN (kiểm tra/cảnh báo độc lập). Tuyệt đối không ghi CAD khi mới có metadata.
6. Không lưu năm sinh/giới tính/chi tiết gia đình vào repo mặc định; chỉ dùng dữ liệu gia chủ tự nguyện cung cấp trong brief được quản lý quyền riêng tư.
