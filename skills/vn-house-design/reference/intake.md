# Tiếp nhận yêu cầu bằng ngôn ngữ tự nhiên

Claude Code tự hiểu hội thoại và điền vào contract có sẵn (`docs/DESIGN_BRIEF_CONTRACT.md`,
schema `knowledge/architecture/design-brief.schema.json`). Không viết parser hay gọi LLM khác.

## 1. Phân loại từng thông tin

| Trạng thái | Ví dụ | Cách ghi vào brief |
|---|---|---|
| `confirmed` | "đất 4 × 20 m", "ba tầng", "3 phòng ngủ" | `confirmation: confirmed`, `origin: client_conversation` |
| `assumed` | đơn vị m khi người dùng chỉ ghi "4x20" | ghi giả định + hỏi xác nhận ở lượt sau |
| `missing` | hướng Bắc, mặt tiền, tầng của phòng | `value: null` + câu hỏi `Q-*` liên kết requirement |
| `not_applicable` | sân vườn với nhà phố liền kề | chỉ khi người dùng xác nhận |

Không biến sở thích ("rộng rãi", "nhiều ánh sáng") thành kích thước cứng. Không lấy lô đất làm
footprint công trình. Không tự đặt diện tích/kích thước phòng từ "kinh nghiệm" hay QCVN chưa duyệt.

## 2. Hỏi gì trước (chỉ những câu chặn bước kế tiếp)

Lượt đầu tối đa ~5 câu, gom nhóm, có ví dụ trả lời:

1. **Ranh đất & đơn vị**: kích thước chính xác/đa giác, đơn vị, mặt tiền tiếp giáp đường nào.
2. **Hướng**: góc Bắc thực (hoặc "chưa biết" — ghi missing, không đoán).
3. **Khoảng lùi / footprint xây dựng** nếu đã biết (nếu chưa: giữ missing; floorplan sẽ INCOMPLETE).
4. **Bố trí tầng**: phòng nào ở tầng nào (phòng thờ thường ở tầng trên cùng — chỉ là gợi ý, phải hỏi).
5. **Số người ở / nhu cầu đặc biệt** (người già, để xe, kinh doanh tầng trệt).

Câu hỏi về diện tích từng phòng, cửa, cầu thang, cao độ tầng để sau — hỏi khi tới stage cần dùng.
Nếu người dùng muốn "cứ lên phương án", giải thích ngắn bước nào bị chặn vì thiếu gì.

## 3. Ví dụ ánh xạ

> "Tôi có mảnh đất 4 × 20 m, muốn xây nhà ba tầng, ba phòng ngủ, có phòng thờ, giếng trời, bếp và
> phòng khách. Phong cách hiện đại tối giản. Hãy lên phương án mặt bằng."

- confirmed: lô chữ nhật 4 × 20 m (đơn vị m), 3 tầng, BED×3, WORSHIP×1, LIGHTWELL×1, KITCHEN×1,
  LIVING×1, style "hiện đại tối giản".
- missing: hướng Bắc, mặt tiền/đường, khoảng lùi/footprint, tầng của từng phòng, số người ở,
  diện tích/kích thước phòng, vệ sinh (không tự thêm WC — hỏi).
- Hành động: ghi brief-v001 với các `Q-*`, chạy step `brief` (mong đợi `INCOMPLETE`, exit 3 — bình
  thường), báo cáo bằng tiếng Việt kèm 3–5 câu hỏi trên. Không tạo mặt bằng ở lượt này.

## 4. Thay đổi yêu cầu sau đó

Ghi brief **phiên bản mới** (`brief-v002.json`), giữ bản cũ; nêu rõ requirement nào đổi. Mọi
`requirement_confirmation`/selection/approval của bản cũ trở thành STALE — hỏi lại.
