"""Claude Code skill installation and resumable project workflow (deterministic, not live LLM)."""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from vnai import project_workflow as pw
from vnai.cli import main
from vnai.skills_install import (
    MARKER,
    canonical_skills,
    check_skills,
    install_skills,
    validate_skill,
)

ROOT = Path(__file__).resolve().parents[1]
EX = ROOT / "examples"


# --- skills -----------------------------------------------------------------------------


def test_canonical_skills_valid_and_free_of_batch_ids():
    skills = canonical_skills(ROOT / "skills")
    assert set(skills) == {"vn-house-design", "vn-fengshui-review", "vn-technical-review"}
    for path in skills.values():
        assert validate_skill(path) == []
        for md in path.rglob("*.md"):
            assert not re.search(r"Batch \d{3}", md.read_text(encoding="utf-8")), md
    assert not re.search(r"Batch \d{3}", (ROOT / "CLAUDE.md").read_text(encoding="utf-8"))


def test_skill_install_check_and_preserve_user_edits(tmp_path):
    source = tmp_path / "src"
    shutil.copytree(ROOT / "skills", source)
    dest = tmp_path / "ws"
    assert check_skills(dest, source)["status"] == "NEEDS_ACTION"
    assert {s["state"] for s in check_skills(dest, source)["skills"]} == {"MISSING"}
    report = install_skills(dest, source)
    assert report["status"] == "INSTALLED"
    installed = dest / ".claude/skills/vn-house-design"
    assert (installed / "SKILL.md").is_file() and (installed / "reference/stages.md").is_file()
    assert (installed / MARKER).is_file()
    assert check_skills(dest, source)["status"] == "CURRENT"

    # Canonical change -> STALE -> reinstall updates the managed copy.
    (source / "vn-technical-review/SKILL.md").write_text(
        (source / "vn-technical-review/SKILL.md").read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )
    states = {s["skill"]: s["state"] for s in check_skills(dest, source)["skills"]}
    assert states["vn-technical-review"] == "STALE"
    assert install_skills(dest, source)["status"] == "INSTALLED"

    # Hand-edited copy -> MODIFIED and preserved unless --force.
    edited = installed / "SKILL.md"
    edited.write_text(edited.read_text(encoding="utf-8") + "\nlocal note\n", encoding="utf-8")
    report = install_skills(dest, source)
    assert report["status"] == "NEEDS_ACTION"
    assert "local note" in edited.read_text(encoding="utf-8")
    assert install_skills(dest, source, force=True)["status"] == "INSTALLED"
    assert "local note" not in edited.read_text(encoding="utf-8")

    # Unmanaged directory with the same name is never replaced silently.
    unmanaged = dest / ".claude/skills/vn-fengshui-review"
    shutil.rmtree(unmanaged)
    unmanaged.mkdir()
    (unmanaged / "SKILL.md").write_text("mine", encoding="utf-8")
    assert install_skills(dest, source)["status"] == "NEEDS_ACTION"
    assert (unmanaged / "SKILL.md").read_text(encoding="utf-8") == "mine"


def test_invalid_skill_frontmatter_is_reported(tmp_path):
    bad = tmp_path / "Bad_Name"
    bad.mkdir()
    (bad / "SKILL.md").write_text("---\nname: other\n---\nsee [x](missing.md)\n", "utf-8")
    errors = validate_skill(bad)
    assert any("name must equal" in e for e in errors)
    assert any("description required" in e for e in errors)
    assert any("broken link" in e for e in errors)


def test_skills_cli_and_doctor(tmp_path, capsys):
    assert main(["skills", "check", "--dest", str(tmp_path)]) == 3
    capsys.readouterr()
    assert main(["doctor", "--dest", str(tmp_path)]) == 3  # skills missing -> NOT_READY
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "NOT_READY"
    assert main(["skills", "install", "--dest", str(tmp_path)]) == 0
    capsys.readouterr()
    assert main(["doctor", "--dest", str(tmp_path)]) == 0


# --- negative and recovery scenarios -----------------------------------------------------


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "proj"
    pw.init_project(root, "neg")
    return root


@pytest.mark.parametrize(
    ("step", "fixture", "category", "exit_code"),
    [
        ("brief", "townhouse_4x20_brief.json", "INCOMPLETE", 3),
        ("floorplan", "batch006a/missing-footprint.json", "INCOMPLETE", 3),
        ("zoning", "batch005/zoning-unresolved.json", "INCOMPLETE", 3),
        ("floorplan", "batch006a/insufficient-area.json", "CONFLICT", 4),
        ("floorplan", "batch006a/search-budget.json", "SEARCH_EXHAUSTED", 6),
        ("openings", "batch006b/missing-openings.json", "INCOMPLETE", 3),
        ("opening-draft", "batch007b2/missing-dimensions.json", "INCOMPLETE", 3),
        ("stair-draft", "batch007b3/known-wall-collision.json", "CONFLICT", 4),
        ("candidate-review", "batch006b/stale-approval.json", "INVALID_OR_FAILED", 1),
        ("architectural-review", "batch006b/corridor-graph-only.json", "INCOMPLETE", 3),
    ],
)
def test_engine_refusals_are_recorded_not_crashes(project, step, fixture, category, exit_code):
    before = (EX / fixture).read_bytes()
    event = pw.run_step(project, step, EX / fixture)
    assert (event["category"], event["exit_code"]) == (category, exit_code)
    assert event["meaning_vi"] and event["cad_writes_permitted"] is False
    assert (EX / fixture).read_bytes() == before  # user data preserved
    assert (project / event["outputs"]["stdout"]["path"]).is_file()  # diagnostics kept
    status = pw.project_status(project)
    assert status["steps"][step]["category"] == category
    assert any(step in a for a in status["next_actions_vi"])


def test_unsupported_integrated_constraint(project):
    event = pw.run_step(project, "integrated", EX / "batch007b4/historical-8x15-separation.json")
    assert event["category"] == "UNSUPPORTED" and event["exit_code"] == 5


def test_refusals_without_ledger_mutation(project, tmp_path):
    ir = project / "drafting" / "fake-ir.json"
    ir.write_text("{}", encoding="utf-8")
    with pytest.raises(pw.WorkflowError, match="EXPORT_NOT_AUTHORIZED"):
        pw.run_step(project, "export", ir, floor="F1")
    with pytest.raises(pw.WorkflowError, match="không được hỗ trợ"):
        pw.record_decision(project, "cad_modification", ir, "sửa DWG", "KTS")
    with pytest.raises(pw.WorkflowError):
        pw.record_decision(project, "architect_approval", ir, "  ", "KTS")
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    with pytest.raises(pw.WorkflowError):
        pw.record_decision(project, "export_authorization", outside, "xuất", "KTS")
    with pytest.raises(pw.WorkflowError):
        pw.run_step(project, "preview", ir, floor="../../evil")
    with pytest.raises(pw.WorkflowError):
        pw.init_project(project, "again")
    assert pw.load_project(project)["events"] == []


def test_missing_project_and_cli_refusal(tmp_path, capsys):
    assert main(["project", "status", str(tmp_path)]) == 3
    assert json.loads(capsys.readouterr().out)["status"] == "REFUSED"


# --- end-to-end synthetic townhouse --------------------------------------------------------


@pytest.fixture(scope="module")
def demo_project(tmp_path_factory):
    root = tmp_path_factory.mktemp("demo") / "townhouse"
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/demo_synthetic_townhouse.py"), "--dir", str(root)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "RESULT: PASS" in result.stdout
    return root


def test_end_to_end_ledger_and_handoff(demo_project):
    data = pw.load_project(demo_project)
    runs = [e for e in data["events"] if e["type"] == "run"]
    assert [r["step"] for r in runs][:4] == ["brief", "integrated", "integrated-preview",
                                             "drafting"]
    exports = [r for r in runs if r["step"] == "export"]
    assert len(exports) == 2 and all(r.get("authorization_id") == "DEC-002" for r in exports)
    assert all(r["cad_writes_permitted"] is False for r in runs)
    decisions = [e for e in data["events"] if e["type"] == "decision"]
    assert {d["kind"] for d in decisions} == {"candidate_selection", "export_authorization"}
    assert all(d["synthetic"] for d in decisions)
    handoff = (demo_project / "reviews/HANDOFF.md").read_text(encoding="utf-8")
    assert "synthetic" in handoff and "PENDING_HUMAN_AUTOCAD_VERIFICATION" in handoff


def test_resume_from_artifacts_in_new_process(demo_project):
    result = subprocess.run(
        [sys.executable, "-m", "vnai", "project", "status", str(demo_project)],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    status = json.loads(result.stdout)
    assert status["status"] == "INTACT" and status["human_approval_recorded"] is False
    assert status["steps"]["verify"]["primary_status"] in {
        "LOSSLESS_EQUIVALENT", "NUMERICALLY_EQUIVALENT"}
    assert status["steps"]["audit"]["primary_status"] == "CLEAN"
    assert all(d["validity"] == "CURRENT" for d in status["decisions"])


def test_reexport_never_overwrites_and_tampering_is_stale(demo_project, tmp_path):
    copy = tmp_path / "copy"
    shutil.copytree(demo_project, copy)
    ir = sorted((copy / "drafting").glob("drawing-ir-v*.json"))[0]
    first = copy / "exports/export-F1-v001.dxf"
    digest = pw.sha256(first)
    again = pw.run_step(copy, "export", ir, floor="F1")
    assert again["outputs"]["dxf"]["path"] == "exports/export-F1-v002.dxf"
    assert pw.sha256(first) == digest
    # Edit the approved-for-export IR: evidence and authorization become stale.
    ir.write_text(ir.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    status = pw.project_status(copy)
    assert status["status"] == "STALE"
    validity = {d["kind"]: d["validity"] for d in status["decisions"]}
    assert validity["export_authorization"] == "STALE_TARGET_CHANGED"
    with pytest.raises(pw.WorkflowError, match="EXPORT_NOT_AUTHORIZED"):
        pw.run_step(copy, "export", ir, floor="F1")
    assert main(["project", "status", str(copy)]) == 4


def test_revised_candidate_supersedes_selection(project):
    spec = pw.import_file(project, EX / "batch006a/two-room.json", "candidates", "spec")
    first = pw.run_step(project, "floorplan", project / spec["artifact"], candidates=1)
    assert first["category"] == "OK"
    pw.record_decision(project, "candidate_selection",
                       project / first["outputs"]["report"]["path"], "chọn", "test",
                       synthetic=True)
    pw.record_decision(project, "architect_feedback",
                       project / first["outputs"]["report"]["path"], "đổi bếp", "test",
                       synthetic=True)
    second = pw.run_step(project, "floorplan", project / spec["artifact"], candidates=1)
    assert second["outputs"]["report"]["path"].endswith("-v002.json")
    assert (project / first["outputs"]["report"]["path"]).is_file()  # parent preserved
    validity = {d["kind"]: d["validity"] for d in pw.project_status(project)["decisions"]}
    assert validity["candidate_selection"] == "SUPERSEDED_BY_NEWER_RUN"


# --- skill behavioural evaluation set (structure only; not a live LLM run) ----------------


def test_skill_eval_cases_are_well_formed():
    data = json.loads((ROOT / "evals/vn-house-design/cases.json").read_text(encoding="utf-8"))
    assert data["evaluation_kind"] == "LIVE_CLAUDE_CODE_REQUIRED"
    ids = [c["id"] for c in data["cases"]]
    assert len(ids) == len(set(ids)) >= 9
    categories = {c["category"] for c in data["cases"]}
    assert categories >= {"initial_request", "requirement_change", "ambiguous", "multiple_options",
                          "explain_conflict", "dxf_export", "approval_request", "fengshui",
                          "building_code"}
    for case in data["cases"]:
        assert case["prompt_vi"] and case["expected_skill"]
        assert case["must"] and case["must_not"]
