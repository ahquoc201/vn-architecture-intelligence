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
