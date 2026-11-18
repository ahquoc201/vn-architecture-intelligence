# R1 Batch 003 — Bát Trạch / Dương Trạch: bibliographic claim audit

**Date:** 2026-11-16
**Review level:** public library/catalog/retail metadata **only**
**Full texts inspected:** none
**Numerical/traditional interpretations approved:** **0**
**Rights for reproducing full books:** not evaluated

## Evidence checked

1. `BTMK-NLV-2009`: National Library of Vietnam bibliographic record as displayed through EMICLIB: *Bát trạch minh kính*, Gia Linh dịch/chú giải, NXB Hà Nội, 2009, **335 pages**. The catalog description is not a verified formula or a read-through of the book. https://www.emiclib.com/Item/ItemDetail/1323273
2. `BTMK-HONGDUC-2012`: public retail listing: *Bát Trạch Minh Kính*, NXB Hồng Đức, 2012, **384 pages**. Distinct claimed edition; never borrow page references from the 2009 entry. https://xemsachhay.com/bat-trach-minh-kinh-bo-kinh-dien-day-du-nhat-ve-phong-thuy-duong-trach/
3. `DTT-HONGBANG-2013`: public retail listing: *Dương Trạch Tam Yếu*, Triệu Cửu Phong, NXB Hồng Bàng, 2013, **576 pages**, barcode 8935095615285. https://minhkhai.com.vn/store2/index.aspx?isbn=8935095615285&q=view
4. `DTT-HONGDUC-2016-670`: Newshop retail record: NXB Hồng Đức, 2016, **670 pages**, barcode 8935088548224. https://newshop.vn/tu-kho-toan-thu-duong-trach-tam-yeu.html
5. `DTT-HONGDUC-2016-696`: Minh Khai retail record: NXB Hồng Đức, 2016, **696 pages**, barcode 8935088548224. https://minhkhai.com.vn/store2/index.aspx?isbn=8935088548224&q=view
6. `DTT-HONGDUC-2016-692`: Huy Hoang Books public retail record: 2016, NXB Hồng Đức, **692 pages**; the viewed listing does not establish the same barcode as records 4 and 5. https://www.huyhoangbook.vn/products/duong-trach-tam-yeu

**Open issue:** public sellers give *different page counts for the same listed 2016 barcode* (670 vs. 696); another 2016 listing says 692 pages without proving the same physical edition. This is a **catalog-claim discrepancy**, not proof that one seller is wrong or that any version has more authoritative teachings.

## Next reviewer actions (requires legally acquired text)

- Inspect title, copyright/imprint, translator, printing, table of contents, pagination and any revised material in **the exact physical or licensed digital edition**.
- Record page/chapter/figure for each claim and original-language wording when legally available. Separate directions of the house, doors, gates and cooking appliances, and distinguish **sitting vs facing**.
- For Bát Trạch: enumerate assumptions for calendrical cutoffs, house/person groupings, trigram and octant methods; document conflicting schools **before** encoding any algorithm.
- For Dương Trạch Tam Yếu: identify and map Môn, Chủ and Táo to modern house elements explicitly; ask the architect/household which entrance and cooking reference is relevant.
- Produce reviewer-authorized **oracle fixtures** for ordinary, boundary, missing-data and disputed-edition cases. In traditional systems, a matching oracle only means *matches a specified text's convention*, not empirical prediction.
- Record authorized reviewer, versioned signoff, ethical/copyright status and safety limits separately from test success.

## Implementation guardrails

- `knowledge/fengshui/edition-evidence.yaml`: independent observations of public metadata; this is not `full_text_reviewed`.
- `knowledge/fengshui/terminology.yaml`: working input vocabulary, **not authoritative translations**.
- `knowledge/fengshui/rule-candidates.yaml`: four unimplemented research questions; all `executable: false`.
- `vnai fengshui knowledge validate`: checks schema, source references and fails on premature permission changes.
- `vnai fengshui knowledge report`: JSON queue with explicit unresolved catalog differences and `cad_writes_permitted: false`.
- This batch does **not** add any Kua/cung-phi formula, auspicious-direction verdict, CAD write or technical-standard checker.

### Relation to existing evidence contract

`docs/R1_EVIDENCE_CONTRACT.md` and `research/editions/r1-batch002.yaml` remain valid. Metadata review is insufficient for promotion to executable rules. This corpus is a safe scaffold for an **architect-led**, source-verifiable future review.
