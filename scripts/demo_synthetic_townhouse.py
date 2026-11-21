"""Deterministic end-to-end workflow demo on the synthetic two-storey 4 x 20 m townhouse.

Run: python scripts/demo_synthetic_townhouse.py --dir <new-empty-dir>

This replays what Claude Code does through the vn-house-design skill, using only
`vnai project` steps over existing engines. It is a scripted integration run, NOT a live
Claude Code conversation, and every human decision it records is marked synthetic.
No architect approval is recorded. Exit 0 only when every expectation holds.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from vnai import project_workflow as pw

ROOT = Path(__file__).resolve().parents[1]
REQUEST_VI = (
    "Tôi có mảnh đất 4 × 20 m, muốn xây nhà ba tầng, ba phòng ngủ, có phòng thờ, giếng trời, "
    "bếp và phòng khách. Phong cách hiện đại tối giản. Hãy lên phương án mặt bằng."
)


def expect(condition: bool, message: str, failures: list[str]) -> None:
    print(("  OK   " if condition else "  FAIL ") + message)
    if not condition:
        failures.append(message)


def run(project: Path) -> int:
    failures: list[str] = []
    pw.init_project(project, "demo-townhouse-synthetic")
    print(f"Yêu cầu (mô phỏng): {REQUEST_VI}")

    print("Stage A — brief từ yêu cầu tiếng Việt")
    brief = pw.import_file(project, ROOT / "examples/townhouse_4x20_brief.json", "brief", "brief")
    result = pw.run_step(project, "brief", project / brief["artifact"])
    expect(result["category"] == "INCOMPLETE", "brief thiếu hướng Bắc/tầng phòng -> INCOMPLETE "
           "(exit 3), không tạo mặt bằng", failures)

    print("Stage D — integrated benchmark (thông tin đã đủ, synthetic fixture)")
    spec = pw.import_file(project, ROOT / "examples/batch007b4/residential-4x20-six-rooms.json",
                          "candidates", "integrated-spec")
    integ = pw.run_step(project, "integrated", project / spec["artifact"], mode="refine")
    report = json.loads((project / integ["outputs"]["report"]["path"]).read_text("utf-8"))
    cov = report["candidates"][0]["verification_coverage"] if report["candidates"] else {}
    expect(integ["category"] == "OK" and integ["primary_status"] == "REFINED",
           "integrated refine -> REFINED", failures)
    expect(cov.get("verified") == 48 and cov.get("required_checks") == 48,
           f"supported checks {cov.get('verified')}/{cov.get('required_checks')}", failures)
    expect(report["architect_approval"] == "NOT_GRANTED" and not report["cad_writes_permitted"],
           "architect_approval NOT_GRANTED, cad_writes_permitted false", failures)
    pw.run_step(project, "integrated-preview", project / integ["outputs"]["report"]["path"],
                view="comparison")

    print("Stage E — checkpoint kiến trúc sư (chỉ chọn phương án, synthetic)")
    pw.record_decision(project, "candidate_selection", project / integ["outputs"]["report"]["path"],
                       "Demo: chọn phương án tích hợp duy nhất để vẽ thử.", "demo-script",
                       synthetic=True)

    print("Stage F — Drawing IR và preview")
    dsrc = pw.import_file(project, ROOT / "examples/batch007c/townhouse-6rooms-drafting.json",
                          "drafting", "drafting-input")
    draft = pw.run_step(project, "drafting", project / dsrc["artifact"])
    expect(draft["category"] == "OK", "drafting generate -> OK", failures)
    ir = project / draft["outputs"]["ir"]["path"]
    for floor in ("F1", "F2"):
        prev = pw.run_step(project, "preview", ir, floor=floor, view="plan")
        expect(prev["category"] == "OK", f"preview {floor}", failures)

    print("Stage G — DXF chỉ sau khi được cho phép rõ ràng")
    try:
        pw.run_step(project, "export", ir, floor="F1")
        expect(False, "export without authorization must be refused", failures)
    except pw.WorkflowError as exc:
        expect("EXPORT_NOT_AUTHORIZED" in str(exc), "export chưa được phép -> REFUSED", failures)
    pw.record_decision(project, "export_authorization", ir,
                       "Demo: xuất phương án này ra DXF (tệp mới).", "demo-script", synthetic=True)
    for floor in ("F1", "F2"):
        exp = pw.run_step(project, "export", ir, floor=floor)
        expect(exp["primary_status"] == "EXPORTED", f"export {floor} -> EXPORTED", failures)
        dxf = project / exp["outputs"]["dxf"]["path"]
        aud = pw.run_step(project, "audit", dxf)
        expect(aud["primary_status"] == "CLEAN", f"audit {floor} -> CLEAN", failures)
        ver = pw.run_step(project, "verify", ir, floor=floor, dxf=str(dxf))
        expect(ver["primary_status"] in {"LOSSLESS_EQUIVALENT", "NUMERICALLY_EQUIVALENT"},
               f"verify {floor} -> {ver['primary_status']}", failures)

    status = pw.project_status(project)
    expect(status["status"] == "INTACT", "ledger digests intact", failures)
    expect(not status["human_approval_recorded"], "không có approval thật nào được ghi", failures)
    handoff = project / "reviews" / "HANDOFF.md"
    handoff.write_text(
        pw.status_markdown(status)
        + "\n## Giới hạn\n\n- Fixture synthetic; mọi quyết định là synthetic, không phải KTS thật.\n"
        "- DXF cần kiểm tra thủ công trong AutoCAD (PENDING_HUMAN_AUTOCAD_VERIFICATION).\n"
        "- QCVN/TCVN và phong thủy: NOT_EVALUATED. Không phải hồ sơ thi công.\n",
        encoding="utf-8",
    )
    print(f"Handoff: {handoff}")
    print("RESULT:", "PASS" if not failures else f"FAIL ({len(failures)})")
    return 0 if not failures else 1


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", required=True, help="New project directory (must not exist)")
    args = parser.parse_args()
    project = Path(args.dir)
    if project.exists() and any(project.iterdir()):
        print(f"Refusing to reuse non-empty directory: {project}", file=sys.stderr)
        return 2
    return run(project)


if __name__ == "__main__":
    raise SystemExit(main())
