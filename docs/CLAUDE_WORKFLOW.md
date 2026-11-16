# Tích hợp với một Claude Code agent

## Một agent, ba skill và AutoCAD MCP sau này

Claude Code sử dụng skill `vn-house-design` để thu thập brief, `vn-fengshui-review` để tạo gợi ý có nguồn, và `vn-technical-review` để chỉ báo cáo những thiếu sót kỹ thuật. Không chạy ba autonomous agents cạnh tranh quyền sửa cùng DWG.

### Lệnh thiết lập local

```powershell
cd C:\CAD-AI
# Giải nén repo trong C:\CAD-AI\vn-architecture-intelligence
cd vn-architecture-intelligence
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,cad]"
python -m pytest -q
vnai sources validate
```

Từ workspace thiết kế CAD, sao chép thư mục `skills/vn-*` đến `.claude/skills/` (có thể dùng Git submodule/symlink để đồng bộ) và tham chiếu repo trong `CLAUDE.md` của workspace chính. Chỉ kết nối AutoCAD MCP trên Windows sau khi geometry review chạy ổn định và có thư mục backup độc lập.

### Prompt khởi động v0.1

> Bạn là một AI trợ lý kiến trúc Việt Nam, không phải người duyệt hồ sơ thi công. Hãy thu thập brief mặt bằng khu đất và các yêu cầu nhà ở, nêu rõ dữ liệu đã xác minh, chưa có và giả định. Dùng các skill trong repository; kiểm tra hình học bằng CLI trước khi đánh giá. Với phong thủy, chỉ đưa diễn giải theo nguồn đã thẩm định; với QCVN/TCVN chỉ lập báo cáo và không tự sửa bản vẽ. Nếu rule chưa có, báo NOT_EVALUATED. Không biến sơ đồ DXF prototype thành bản vẽ thi công.

### Khi tích hợp AutoCAD MCP

- Agent đọc bản sao DWG/DXF; nhận diện hoặc yêu cầu người thiết kế ánh xạ đường bao phòng, đối tượng cửa, chiều cao tầng.
- Chạy geometric QA rồi đề xuất 2–3 phương án, lưu decision log.
- Sau duyệt, sửa bản sao CAD, chạy lại QA, xuất diff. Không xóa hoặc sửa bản gốc.
- Xuất đầy đủ ký hiệu/dim/layout chỉ khi CAD adapter có chức năng và đã được kiểm tra mở lại.

Không mặc định thư viện `vnai` đã có công cụ vẽ tường/cửa/mặt đứng/mặt cắt hoặc chuyển mô hình 3D.
