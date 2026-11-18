# Feng Shui — research corpus (not executable yet)

Mục tiêu: Bát Trạch và Dương Trạch Tam Yếu như **các lớp diễn giải truyền thống** cho hướng nhà, cửa, bếp, không gian chủ, giường và phòng thờ. Chỉ sau khi có ấn bản/chương/trang/phép tính và người thẩm định, mới triển khai executable rules.

Không tính cung mệnh từ năm sinh bằng công thức chưa được thẩm định; không tự chọn giới tính/biến thể hoặc kết luận hướng tốt/xấu. Không khẳng định phong thủy dự báo vận mệnh có kiểm chứng khoa học.

Dữ liệu tính hướng địa lý là **kỹ thuật đo đạc**, độc lập với Bát Trạch. Xem `vnai.orientation`.

## R1 Batch 002 — phương vị hình học

Đã có `vnai fengshui orientation` (xem schema `orientation-input.schema.json`),
nhưng đây **chỉ** là phép tính góc và phân loại 8 hướng địa lý. Nếu đo gần ranh
phương vị, engine trả hai hướng có thể, không phán tốt/xấu. Cần xác nhận
**Bắc thực** và vector hướng **từ nhà ra đường**, không suy diễn từ cạnh mặt tiền.

Bảng câu hỏi về ấn bản cổ thư nằm tại `research/editions/r1-batch002.yaml`.

## R1 Batch 003 — nghiên cứu thư mục và câu hỏi quy tắc

- `edition-evidence.yaml`: các claim từ trang thư mục/nhà sách, **không phải** nội dung sách đã đọc; những số trang không đồng nhất được báo riêng.
- `terminology.yaml`: glossary làm rõ nghĩa **đầu vào**, chưa là định nghĩa kinh điển.
- `rule-candidates.yaml`: câu hỏi nghiên cứu, không có predicate, formula hay oracle được duyệt.
- `vnai fengshui knowledge validate`: đối chiếu nguồn và chặn đánh dấu approved/executable/CAD writes.
- `vnai fengshui knowledge report`: xuất hàng đợi thẩm định và bất đồng metadata.

Không dùng bất kỳ bản ghi nào ở đây để kết luận hợp/xung khắc, chọn hướng tốt/xấu hoặc tự sửa bản vẽ.
