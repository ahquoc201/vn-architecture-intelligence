---
name: vn-technical-review
description: Kiểm tra dữ liệu hình học và thông báo tình trạng đối chiếu tiêu chuẩn nhà ở Việt Nam mà không tự sửa bản vẽ.
---

# VN Technical Review — report only

1. Xác định loại công trình: nhà ở riêng lẻ, liên kế, căn hộ, hoặc kết hợp sử dụng; địa bàn, loại thiết kế, thời điểm áp dụng.
2. Đối chiếu registry với TCVN 13967:2024, TCVN 9411:2012, QCVN 02:2022/BXD và văn bản liên quan **trong đúng phạm vi**, không suy diễn quy định từ tiêu đề tài liệu.
3. Trước khi có engine điều khoản được chuyên gia duyệt, trả `NOT_EVALUATED`, không PASS/FAIL pháp lý.
4. Kiểm tra phần hình học bằng `vnai review` và tách báo cáo đo hình học khỏi báo cáo quy chuẩn.
5. Với rủi ro an toàn/PCCC/kết cấu/MEP, báo rõ cần kỹ sư kiểm tra trước khi triển khai. **Không** tự đổi CAD theo luật hoặc tự tuyên bố hồ sơ hợp pháp.
6. Mọi phát hiện phải kèm mức bằng chứng, điều khoản chính xác (nếu đã thẩm định), version và dữ liệu thiếu.
