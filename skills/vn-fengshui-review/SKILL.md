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
