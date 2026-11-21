# Mã trạng thái và exit code của VNAI

`vnai project step` trả về đúng exit code của lệnh engine và ghi `category` vào ledger.

| Exit | category | Trạng thái engine thường gặp | Cách xử lý |
|---|---|---|---|
| 0 | OK | VALID, GENERATED, REFINED, VERIFIED, READY_FOR_DRAFTING, EXPORTED, CLEAN, LOSSLESS_EQUIVALENT, NUMERICALLY_EQUIVALENT | Trình bày kết quả; vẫn là PROPOSED, chưa phê duyệt |
| 1 | INVALID_OR_FAILED | INVALID, INVALID_INPUT, FAILED, NOT_READY, AUDIT_ERROR | Sửa cấu trúc/đầu vào; nêu lỗi cụ thể |
| 2 | INPUT_OR_IO_ERROR | lỗi đọc/ghi, tham số sai, tệp đầu ra đã tồn tại | Kiểm tra đường dẫn; không phải lỗi thiết kế |
| 3 | INCOMPLETE | INCOMPLETE, REFUSED (workflow, vd. EXPORT_NOT_AUTHORIZED) | Hỏi kiến trúc sư phần thiếu; không tự điền |
| 4 | CONFLICT | CONFLICT, INFEASIBLE, STALE, MISMATCH, RECOVERED_WITH_FIXES | Báo xung đột thật; giữ ràng buộc cứng; xin quyết định |
| 5 | UNSUPPORTED | UNSUPPORTED | Giải thích giới hạn engine; không tự chế cách lách |
| 6 | SEARCH_EXHAUSTED | SEARCH_EXHAUSTED | Hết không gian lưới/ngân sách; **không** chứng minh bất khả thi |
| 70 | ENGINE_CRASH | (exception) | Giữ nguyên đầu vào + stdout trong `manifests/runs/`, báo lỗi |

Lưu ý:

- Đọc `primary_status` (vd. `integrated_status`) chứ không chỉ `status`: integrated `generate` có thể
  có `status: VALID` (đầu vào hợp lệ) nhưng `integrated_status: SEARCH_EXHAUSTED` (exit 6).
- `GRAPH_CONNECTED`, `SELECTED`, `REVIEWED`, `READY_FOR_DRAFTING` không phải approval.
- `UNKNOWN`/`NOT_EVALUATED`/`NOT_VERIFIED` không bao giờ được trình bày như đạt.
- `project status` exit 4 = có artifact bị sửa/mất sau khi ghi nhận (STALE) → chạy lại bước liên quan.
