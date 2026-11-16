# R1/BATCH-001 — Directly reviewed public source content

Checked: 2026-11-16. Reviewer type: source-based research pass (NOT professional sign-off).

## Decision matrix

| ID | Accessible material examined | Status | Allowed outcome |
|---|---|---|---|
| `ARCH-NDT-2023` | Publisher catalog/title, description and TOC; article itself inaccessible by book page | `toc_checked` | Core architecture source **candidate**; no numeric drafting rules |
| `ARCH-NGVD-2011` | Publisher page with TOC including drawing notations, space and stair topics | `toc_checked` | Core drawing/reference **candidate**; no dimensions imported |
| `CLIM-PDN-2023` | Publisher page and seven chapter names | `toc_checked` | Core climate source **candidate**; no meteorological formulas imported |
| `FENG-NTD-2011` | Public library record, 373 pages, first reprint | `metadata_verified` | Applied feng shui book **candidate**; no recipe/calculation imported |
| `FENG-NTD-2014` | Separate public library record, 414 pages, second revised reprint | `metadata_verified` | Separate edition; no assumed textual identity to 2011 |
| `FENG-KTH-2016` | Public article text on Northern Delta settlement, siting, screened entrances | `public_article_reviewed` | Contextual observations only (`OBS-001`, `OBS-002`) |
| `FENG-NVT-NVH-2022` | Public article text about worship spaces and adaptation to modern housing | `public_article_reviewed` | Household-conditional suggestions (`OBS-003`, `OBS-004`) |
| `STD-TCVN13967-2024` | VSQI public scope 1.1–1.3 and metadata | `official_scope_checked` | Flag for separate technical review (`OBS-005`) |

## Verified, but narrow, findings

- **Traditional northern settlements**: site setting, water, circulation and cultural beliefs were intertwined; the article includes exceptions to common 'ideal direction' narratives. This is a contextual research finding, **not** a measurable rule for today's houses. Source: `FENG-KTH-2016`, sections 'Lựa chọn địa điểm cư trú' and 'Tổ chức địa điểm cư trú'.
- **Entrance/privacy precedents**: the article describes some screened or offset gate arrangements, **and exceptions**. Do not turn into a universal 'gate must not face door' prohibition. Same source, section 'Tổ chức địa điểm cư trú'.
- **Worship-space options**: the authors discuss independent spaces where feasible and contemporary space sharing. Present as a choice only where requested; do not infer religion. Source: `FENG-NVT-NVH-2022`, concluding recommendations section.
- **Technical separation**: incense smoke, fire and room adjacency are mentioned by these authors; these need independent engineering evaluation, not an article-derived pass/fail. Same source.
- **TCVN 13967:2024**: official catalog gives broad scope (new single dwellings), but is not sufficient to implement any clause-level check. Source: `STD-TCVN13967-2024`, VSQI catalog's public scope 1.1–1.3.

## Important conflicting or incomplete metadata

- Publisher book URL for `ARCH-NDT-2023` was indexed as an official listing, but a direct fetch also returned a 404 in one check; **do not interpret web-health as publication legitimacy**. Keep alternate publisher catalog listings under research until stable.
- A separate *2014* revised 414-page edition of Nguyễn Tiến Đích was located, distinct from 2011/373 pages. Page references must **always identify the edition**.
- An article cited by an architect does not certify the article's feng shui methods as scientifically validated.

## Next research blockers

1. Legally acquire/borrow particular editions of Bát Trạch Minh Kính, Dương Trạch Tam Yếu and Nguyễn Tiến Đích.
2. Verify chapter/page-level formulations and competing interpretations with a named qualified reviewer.
3. Add paired positive/negative/missing-input tests from independent verified oracles before activating computational advice.
4. Obtain a licensed official TCVN text before extracting clause-specific technical review checks; flag effective dates separately.

## Bibliographic/public source links

- KTH: https://www.tapchikientruc.com.vn/chuyen-muc/phong-thuy-trong-chuc-moi-truong-cu-tru-truyen-thong-vung-dong-bang-bac-bo.html
- NVT/NVH: https://www.tapchikientruc.com.vn/chuyen-muc/khong-gian-tho-cung-to-tien-cua-nguoi-viet-tu-nha-o-nong-thon-truyen-thong-den-can-ho-chung-cu-hien-dai.html
- Thiềm (publisher): https://nxbxaydung.com.vn/nguyen-ly-thiet-ke-kien-truc-dan-dung-kien-truc-nha-o-b12049.html
- Giả/Diệp (publisher): https://nxbxaydung.com.vn/tuyen-hoa-thuc-hanh-co-so-kien-truc-b6398.html
- Phạm Đức Nguyên (publisher): https://nxbxaydung.com.vn/kien-truc-sinh-khi-hau-thiet-ke-sinh-khi-hau-trong-kien-truc-viet-nam-b5805.html
- Tiến Đích 2011: https://phucvu.thuvientphcm.gov.vn/Item/ItemDetail/478010
- Tiến Đích 2014: https://www.emiclib.com/Item/ItemDetail/2037490
- TCVN 13967:2024 catalog: https://tieuchuan.vsqi.gov.vn/tieuchuan/view?sohieu=TCVN+13967%3A2024
