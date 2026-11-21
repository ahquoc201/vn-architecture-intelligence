# Hướng dẫn nhanh cho kiến trúc sư

Bạn mô tả ngôi nhà bằng tiếng Việt; Claude Code chạy các công cụ `vnai` và hỏi lại khi thiếu thông tin.
Không cần biết Python, JSON hay dòng lệnh. Kết quả là **phương án concept**, không phải hồ sơ thi công.

## 1. Cài đặt một lần

Cần: Python 3.11+ , Git, Claude Code (`npm install -g @anthropic-ai/claude-code` hoặc app desktop).

**Windows (PowerShell hoặc Git Bash)**

```powershell
cd C:\CAD-AI\vn-architecture-intelligence
python -m venv .venv
.\.venv\Scripts\Activate.ps1        # Git Bash: source .venv/Scripts/activate
python -m pip install -e ".[dev,cad]"
vnai skills install
vnai doctor
```

**WSL2 Ubuntu**

```bash
cd ~/vn-architecture-intelligence
python3 -m venv .venv && source .venv/bin/activate
python -m pip install -e ".[dev,cad]"
vnai skills install && vnai doctor
```

`vnai doctor` phải báo `READY`. `vnai skills install` chép skill từ `skills/` vào `.claude/skills/`
(bản sao có kiểm digest, không cần quyền symlink). Sau khi cập nhật repo, chạy lại lệnh này; nếu bạn
đã tự sửa bản sao, lệnh sẽ từ chối ghi đè và báo `MODIFIED`.

Mở Claude Code trong thư mục repo (`claude`), gõ `/` để thấy `/vn-house-design`,
`/vn-fengshui-review`, `/vn-technical-review`. Nếu chưa thấy: `/reload-skills`.

## 2. Dự án mới

```text
/vn-house-design Tôi có mảnh đất 4 × 20 m, muốn xây nhà ba tầng, ba phòng ngủ, có phòng thờ,
giếng trời, bếp và phòng khách. Phong cách hiện đại tối giản. Hãy lên phương án mặt bằng.
```

Hoặc chỉ cần mô tả nhà — Claude tự nhận skill. Claude sẽ:

1. Tạo thư mục `projects/<ten-du-an>/` (không commit lên Git) với `brief/ zoning/ candidates/
   reviews/ drafting/ exports/ manifests/` và sổ ghi `project.json`.
2. Ghi brief, chạy kiểm tra, và hỏi tối đa vài câu thật cần (hướng Bắc, mặt tiền, tầng của phòng...).
3. Khi đủ dữ liệu: zoning → phương án → tường/cửa/cầu thang → đánh giá → bản vẽ SVG → DXF.

Mỗi bước Claude báo: đã xác nhận / đã tạo / đã kiểm tra / còn thiếu / cần bạn quyết định / bước tiếp.

## 3. Tiếp tục dự án cũ

```text
/vn-house-design Tiếp tục dự án projects/nha-pho-4x20
```

Claude đọc `project.json` (`vnai project status`), kiểm lại digest mọi tệp, và báo tệp nào bị sửa
(`STALE`) hoặc quyết định nào đã cũ (`SUPERSEDED`). Không dựa vào trí nhớ hội thoại.

## 4. Quyết định của bạn (tách biệt)

| Bạn nói | Claude ghi | Ý nghĩa |
|---|---|---|
| "Đúng, chốt brief" | requirement_confirmation | chỉ chốt yêu cầu |
| "Chọn phương án 2" | candidate_selection | chưa phải duyệt |
| "Sửa bếp rộng hơn" | architect_feedback | tạo bản sửa mới, giữ bản cũ |
| "Tôi (KTS ...) duyệt phương án này" | architect_approval | lời duyệt của bạn, gắn đúng tệp |
| "Xuất DXF tầng 1" | export_authorization | chỉ tạo tệp DXF **mới** |

Claude không thể tự duyệt, không xin phép xây dựng, không cam kết PCCC/kết cấu/MEP, và không sửa bản
vẽ CAD/DWG có sẵn của bạn.

## 5. Mở DXF trong AutoCAD

Tệp ở `projects/<du-an>/exports/export-F1-v001.dxf` (mỗi lần xuất tạo `-v002`, không ghi đè), kèm
manifest ở `manifests/`. Claude đã chạy audit (`CLEAN`) và round-trip (`LOSSLESS_EQUIVALENT`). Bạn vẫn
cần kiểm tra thủ công: đơn vị mm, layer `A-*`, font tiếng Việt hiển thị đúng, kích thước khớp
`drafting/*.md`. Trạng thái giữ `PENDING_HUMAN_AUTOCAD_VERIFICATION` đến khi bạn xác nhận.

**Bản vẽ có sẵn của bạn (v0.2.1):** Claude có thể *đọc* DXF (hoặc AutoCAD qua MCP chỉ đọc), đối chiếu
với phương án VNAI, lập đề xuất thay đổi, và — chỉ khi bạn đồng ý đúng đề xuất đó — tạo **bản sao DXF
mới** đã sửa. Bản gốc và tài liệu AutoCAD đang mở không bao giờ bị sửa. Cài đặt và checklist:
`docs/AUTOCAD_MCP_INTEGRATION.md`.

## 6. Lỗi thường gặp

| Hiện tượng | Cách xử lý |
|---|---|
| `vnai: command not found` | Kích hoạt `.venv` rồi `pip install -e ".[dev,cad]"` |
| Không thấy `/vn-house-design` | `vnai skills install`, rồi `/reload-skills` trong Claude Code |
| `doctor`: `import ezdxf` thiếu | `pip install -e ".[cad]"` (chỉ cần cho DXF) |
| Kết quả `INCOMPLETE` | Bình thường: trả lời câu hỏi còn thiếu |
| `CONFLICT` / `SEARCH_EXHAUSTED` | Đọc giải thích; quyết định đổi yêu cầu, engine không tự nới |
| `UNSUPPORTED` | Engine chưa hỗ trợ trường hợp này (vd. cầu thang xoắn) |
| `EXPORT_NOT_AUTHORIZED` | Nói rõ "xuất DXF ..." cho đúng bản vẽ hiện tại |
| Tiếng Việt lỗi font trong console | Lệnh `vnai project/skills/doctor` tự in UTF-8; dùng Windows Terminal |

## 7. Giới hạn hiện tại

Nhà ở thấp tầng, mặt bằng trực giao; cầu thang thẳng/L/U; không xoắn, không winders. Không có thiết
kế kết cấu/MEP, không kết luận QCVN/TCVN, không thuật toán phong thủy đã duyệt, không sửa trực tiếp
AutoCAD (MCP chỉ đọc). Chi tiết kỹ thuật: `docs/CLAUDE_WORKFLOW.md`.
