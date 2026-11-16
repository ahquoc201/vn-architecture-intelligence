# Hợp đồng dữ liệu và đầu ra

**V0.1** chỉ hỗ trợ site và room polygons đặt trong mặt phẳng XY, đơn vị **mm**; tất cả tọa độ phải đo cùng một hệ quy chiếu. Góc `true_north_degrees` là góc phương vị từ Bắc thực, đo theo chiều kim đồng hồ; không tự suy ra Bắc từ hướng đường.

`target_area_m2`: diện tích mong muốn; `area_m2`: đo từ đường bao. Sai lệch mặc định >5% sẽ cảnh báo, **đây là tolerance chất lượng theo brief, không phải mức pháp lý**.

Trong report:
- `MEASURED` là số đo hình học có thể tái lập từ dữ liệu đầu vào.
- `WARNING` là điều kiện hình học/brief cần xem lại; không phải kết luận trái quy chuẩn.
- `NEEDS_DATA` là thiếu thông tin để kết luận.
- `NOT_EVALUATED` là công cụ chưa có rule được duyệt; không có nghĩa PASS.

Ranh đất không đồng nghĩa với phạm vi được phép xây dựng; phòng chồng lấn ranh hoặc nằm ngoài khu đất được cảnh báo hình học. Đánh giá quy hoạch/giấy phép địa phương cần dữ liệu riêng.
