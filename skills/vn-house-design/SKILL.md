---
name: vn-house-design
description: Thu thập brief nhà ở Việt Nam và kiểm tra diện tích hình học trước khi lên phương án CAD concept.
---

# VN House Design

## Dùng khi

Người dùng mô tả kích thước khu đất, số tầng, nhu cầu phòng, công năng, phong cách và muốn Claude lên phương án mặt bằng CAD.

## Các bước

1. Thu thập: địa điểm ở mức cần thiết cho quy chuẩn, ranh giới đất (đa giác hoặc kích thước), đơn vị, Bắc thực, mặt tiếp cận, khoảng lùi/giới hạn xây dựng nếu đã biết, số tầng, cao độ, danh sách phòng, target areas, nhu cầu gia đình, phong cách, ưu tiên phong thuỷ.
2. Chia dữ liệu `confirmed`, `missing`, `assumed`. Đối với hướng đất, cao độ và chỉ giới, không suy đoán.
3. Đề xuất **2–3 cách phân khu có lý do**, không tạo bản vẽ nếu thiếu ranh đất hoặc units đáng tin cậy.
4. Chuẩn hoá polygon phòng vào JSON theo `examples/townhouse_sample.json` (không ghi số liệu không có nguồn).
5. Chạy `vnai review <file> --markdown <report>`; xử lý `WARNING` và `NEEDS_DATA`, ghi các quyết định thiết kế.
6. DXF từ `vnai dxf` hiện **chỉ là sơ đồ hình học kiểm thử**, không gọi là bản CAD hoàn thiện. Để triển khai tường/cửa/dim dùng CAD adapter tương lai sau phê duyệt.
7. Khi người dùng sửa, giữ V1 và tạo V2, giải thích tác động diện tích và giữ lại các yêu cầu đã chốt.

## Kết quả phải trả

Brief, assumption register, phương án/khác biệt, bảng diện tích đo được, kết quả QA hình học, tài liệu nguồn, các hạng mục chưa thể xác nhận và review gate.

## R1 provenance check

For suggestions rooted in regional architecture or worship spaces, use only the non-executable observations in `knowledge/insights.yaml`, explicitly distinguishing historical case studies from authors' design preferences. Do not derive a numerical room size, stair count or cardinal-direction rule from a table of contents. Keep design geometry sourced from the client's confirmed dimensions and the tested geometry engine.


## R2 Batch 004: required brief/program gate before step 3

1. Collect a brief using `knowledge/architecture/design-brief.schema.json` and
   `docs/DESIGN_BRIEF_CONTRACT.md`; start from `examples/townhouse_4x20_brief.json`.
   Preserve stable requirement IDs, origin, type, confirmation and priority.
2. Keep mandatory requirements, preferences, assumptions and questions distinct.
   Do not invent footprints, room dimensions, floor assignments or orientations.
3. Run `vnai design brief validate <brief.json>` and `vnai design brief report <brief.json>`.
   INVALID (exit 1) needs correction; INCOMPLETE (exit 3) needs questions linked to requirement IDs.
   Input/read failures return exit 2. Preserve earlier briefs/reports with versioned filenames.
4. Run `vnai design program build <brief.json>` for declared rooms and hard/soft relationships.
   Explain missing information, conflicts and unresolved decisions. Area sums do not prove feasibility.
5. Obtain explicit architect approval of the brief/program before the layout steps above, even
   when VALID. Do not derive room minima or unsupported recommendations from general knowledge.
6. Keep Feng Shui and QCVN/TCVN reviews separate under the source review policy. VALID never
   grants specialist approval or authorization to change CAD. Any CAD write needs explicit approval.
7. Maintain this skill in `skills/vn-house-design/`; do not create a duplicate installed copy here.
