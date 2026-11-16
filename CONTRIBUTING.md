# Contributing — bảo vệ chất lượng của nguồn và quy tắc

## Đề xuất nguồn mới

Mở issue bằng mẫu `Source proposal` hoặc thêm mục trong `sources/intake.yaml` qua PR. Cung cấp: nhan đề, tác giả, ấn bản, URL đáng tin, điểm mới, ví dụ ứng dụng thiết kế, quyền truy cập và nguồn đối chiếu.

## Nâng nguồn lên core_candidate

Mỗi nguồn cần `research/source-reviews/<source-id>.md`, ghi:
- bibliographic checks (publisher/library), ISBN/edition/author, ngày kiểm tra
- phạm vi nội dung thực sự xem: bìa, mục lục, phần đọc thử, chương/trang hay toàn văn
- khái niệm có thể giúp thiết kế CAD và giới hạn diễn giải
- có/không bằng chứng được chuyên gia trích dẫn (không suy ra ai cũng tin dùng)
- quyền sử dụng, các phần chưa thể thẩm định

## Thêm executable rule

Tuyệt đối không merge công thức/điều khoản `approved` khi chưa có bằng chứng **chương/trang/ấn bản**, trường phái hoặc phạm vi áp dụng, review của người có chuyên môn và test PASS/FAIL/NEEDS_DATA/edge. Mọi thay đổi phép tính cần changelog, version và regression tests.

## Reviewer

Nguồn về kiến trúc/thi công cần KTS/kỹ sư có chuyên môn. Diễn giải phong thủy cần người nghiên cứu trường phái và chỉ xác nhận *đúng theo hệ được chọn*, không xác nhận tác dụng dự báo. Rule pháp lý cần rà văn bản đang hiệu lực, ngoại lệ và điều kiện áp dụng.

## Quy trình

1. Issue ứng viên → 2. Metadata verified → 3. Content review → 4. Rule proposal → 5. Expert review + tests → 6. PR → 7. Release.

Không commit tài liệu có bản quyền hoặc bản vẽ khách hàng chưa được phép. Các tham chiếu dẫn nguồn không được sao chép nguyên văn dài.
