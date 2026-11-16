# Quy trình thẩm định nguồn và chuyển tri thức thành máy kiểm tra

## Định nghĩa rõ các tầng bằng chứng

1. `metadata_verified`: đã kiểm chứng tên, tác giả, ấn bản trên NXB/thư viện/cơ quan chính thức.
2. `toc_checked`: đã đối chiếu mục lục/giới thiệu chính thức nhưng **chưa đọc đầy đủ**.
3. `public_article_reviewed`: đã đọc văn bản công khai và ghi chú phạm vi/giới hạn.
4. `full_text_pending`: cần bản hợp pháp để thẩm định nội dung/chương/trang.
5. `expert_approved`: chỉ khi người có chuyên môn ký duyệt từng rule kèm bằng chứng, không áp lên cả cuốn sách mặc nhiên.

## Hệ phân loại tri thức

- `architectural_principle`: nguyên lý tổ chức không gian, nội thất, giao thông, khí hậu.
- `traditional_interpretation`: trường phái phong thủy, không phải khẳng định thực nghiệm.
- `measurable_engineering`: đại lượng đo, mô phỏng hoặc tính được, có phương pháp/độ không đảm bảo.
- `standard_reference`: nguồn quy phạm có phạm vi và thời điểm áp dụng; bộ checker chỉ cảnh báo.
- `cultural_case_study`: tập quán và ví dụ địa phương; không suy rộng thành quy tắc phổ quát.

## Điều kiện nâng một quy tắc từ candidate lên executable

1. Source ID có metadata đã đối chiếu và quyền sử dụng hợp lệ.
2. Đúng ấn bản, chương, trang/điều khoản; lưu bằng chứng review, không chỉ ISBN.
3. Mô tả chính xác cách tính, đơn vị, điều kiện, ngoại lệ, trường phái/phương án dị bản.
4. Bài test PASS, FAIL, NEEDS_DATA và ít nhất một edge case; trong lĩnh vực truyền thống, PASS/FAIL nghĩa là phù hợp công thức được chọn, **không** phải dự báo hiện thực.
5. Reviewer chuyên môn xác nhận (kiến trúc sư/kỹ sư hoặc nhà nghiên cứu chuyên về trường phái tương ứng) và hồ sơ PR.
6. Changelog, version, khả năng tái chạy báo cáo cũ, không viết đè quy tắc lịch sử.

**Ở bản 0.1.0 chưa có bất kỳ feng shui rule hay standard compliance rule ở trạng thái approved.**

## Ưu tiên khi mâu thuẫn

- Yêu cầu gia chủ là input thiết kế; ý kiến phong thủy là lớp tư vấn, không là phép xác nhận an toàn.
- Bộ tiêu chuẩn trong sản phẩm này không được tự động ép hình học theo rule. Tuy nhiên, rủi ro an toàn/pháp lý phải được nêu rõ, và hồ sơ có vấn đề chưa được coi là sẵn sàng thi công.
- Khi hai nguồn phong thủy xung đột, xuất hai diễn giải độc lập có school và ấn bản; không pha trộn, không tự chọn như sự thật duy nhất.
