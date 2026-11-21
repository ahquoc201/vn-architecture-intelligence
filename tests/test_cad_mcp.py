"""Controlled AutoCAD MCP bridge: discovery, read-only enforcement, comparison, copy edits."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

ezdxf = pytest.importorskip("ezdxf")

from vnai import cad_bridge as cb  # noqa: E402
from vnai import cad_edit as ce  # noqa: E402
from vnai import project_workflow as pw  # noqa: E402
from vnai.cli import main  # noqa: E402
from vnai.dxf_manifest import compute_file_sha256, decode_ir_xdata  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
F1 = ROOT / "examples/batch007d/exports/townhouse-F1.dxf"
MOCK = Path(__file__).with_name("mock_autocad_mcp.py")
F1_SHA = compute_file_sha256(F1)


@pytest.fixture(scope="module")
def ir() -> dict:
    from vnai.drafting_engine import generate_drafting

    src = ROOT / "examples/batch007c/townhouse-6rooms-drafting.json"
    return generate_drafting(json.loads(src.read_text(encoding="utf-8")))


def _profile(tmp_path: Path, mode: str = "readonly", **extra) -> Path:
    log = tmp_path / "calls.log"
    profile = {
        "contract": cb.PROFILE_CONTRACT,
        "server_name": "autocad",
        "package": "mock",
        "pinned_version": "1.8.0",
        "command": [sys.executable, str(MOCK), "--mode", mode, "--dxf", str(F1), "--log", str(log)],
        "env": {"READ_ONLY": "true", "SECRET_TOKEN": "do-not-echo"},
        "read_tools": ["drawing_info", "entity_list"],
        "identity_tool": "drawing_info",
        "desktop_backend_values": ["com"],
        **extra,
    }
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(profile), encoding="utf-8")
    return path


def _calls(tmp_path: Path) -> list[str]:
    log = tmp_path / "calls.log"
    return log.read_text(encoding="utf-8").split() if log.exists() else []


# ----------------------------------------------------------------------------- discovery


def test_discovery_without_profile_keeps_layers_separate():
    rep = cb.discover(None)
    assert rep["status"] == "READY"
    assert rep["mcp_server_configured"] == "NOT_CONFIGURED"
    assert rep["mcp_server_connected"] == "NOT_ATTEMPTED"
    assert rep["desktop_autocad_connected"] == "NOT_VERIFIED"
    assert rep["live_document_inspected"] == "NOT_ATTEMPTED"
    assert rep["capabilities"]["live_cad_mutation"] == "UNSUPPORTED"
    assert rep["cad_writes_permitted"] is False


def test_discovery_connects_read_only_mock_and_probes_identity(tmp_path):
    rep = cb.discover(_profile(tmp_path), probe=True)
    assert rep["status"] == "CONNECTED_READ_ONLY"
    assert rep["read_only_enforcement"] == "VERIFIED_BY_TOOL_ADVERTISEMENT"
    assert rep["server"]["name"] == "mock-autocad-mcp"
    assert {t["name"] for t in rep["tools"]} == {"drawing_info", "entity_list"}
    assert rep["live_document_inspected"] == "INSPECTED"
    assert rep["live_document"]["document"]["name"] == "Tầng 1 — bản vẽ.dxf"
    # mock backend is never reported as a desktop AutoCAD session
    assert rep["desktop_autocad_connected"].startswith("NOT_DESKTOP")
    assert "do-not-echo" not in json.dumps(rep)
    assert _calls(tmp_path) == ["drawing_info"]


def test_leaky_server_is_not_enforced_and_every_call_refused(tmp_path):
    profile = _profile(tmp_path, "leaky")
    rep = cb.discover(profile, probe=True)
    assert rep["status"] == "READ_ONLY_NOT_ENFORCED"
    assert set(rep["unexpected_tools"]) == {"entity_move", "system_run_command"}
    with pytest.raises(cb.CadBridgeError) as exc:
        cb.mcp_read(profile, "drawing_info")
    assert exc.value.status == "READ_ONLY_NOT_ENFORCED"
    assert _calls(tmp_path) == []  # nothing reached the server


@pytest.mark.parametrize("tool", ["entity_move", "system_run_command", "unknown_tool"])
def test_write_or_unknown_tools_refused_at_adapter(tmp_path, tool):
    with pytest.raises(cb.CadBridgeError) as exc:
        cb.mcp_read(_profile(tmp_path), tool)
    assert exc.value.status == "REFUSED"
    assert _calls(tmp_path) == []


def test_profile_rejects_write_looking_allowlist_and_shell_string(tmp_path):
    bad = _profile(tmp_path, read_tools=["drawing_info", "entity_move"])
    with pytest.raises(cb.CadBridgeError, match="write/exec"):
        cb.load_profile(bad)
    bad = _profile(tmp_path, command="python server.py")
    with pytest.raises(cb.CadBridgeError, match="no shell string"):
        cb.load_profile(bad)


@pytest.mark.parametrize(
    ("mode", "status"),
    [("crash", "CONNECTION_FAILED"), ("garbage", "MCP_ERROR")],
)
def test_server_failures_are_reported_not_faked(tmp_path, mode, status):
    rep = cb.discover(_profile(tmp_path, mode))
    assert rep["status"] == "CONNECTION_FAILED"
    assert rep["mcp_server_connected"] == status
    assert rep["live_document_inspected"] == "NOT_ATTEMPTED"


def test_rpc_error_and_version_mismatch(tmp_path):
    with pytest.raises(cb.CadBridgeError) as exc:
        cb.mcp_read(_profile(tmp_path, "rpc_error"), "drawing_info")
    assert exc.value.status == "MCP_ERROR" and "busy" in str(exc.value)
    rep = cb.discover(_profile(tmp_path, pinned_version="2.0.0"))
    assert rep["status"] == "INCOMPATIBLE_VERSION"
    with pytest.raises(cb.CadBridgeError) as exc:
        cb.mcp_read(_profile(tmp_path, pinned_version="2.0.0"), "entity_list")
    assert exc.value.status == "INCOMPATIBLE_VERSION"


def test_missing_server_executable(tmp_path):
    rep = cb.discover(_profile(tmp_path, command=["vnai-no-such-mcp-server-exe"]))
    assert rep["mcp_server_connected"] == "CONNECTION_FAILED"


def test_mcp_read_returns_bounded_untrusted_payload(tmp_path, capsys):
    code = main(["cad", "mcp-read", "--profile", str(_profile(tmp_path)), "--tool", "entity_list",
                 "--args", '{"offset": 3}'])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["trust"] == "UNTRUSTED_THIRD_PARTY_DATA"
    assert out["result"]["offset"] == 3 and out["cad_writes_permitted"] is False


# ----------------------------------------------------------------------------- inspection


def test_headless_inspection_is_read_only_and_paged():
    rep = cb.inspect_dxf(F1, entity_type="MTEXT", limit=2)
    assert rep["status"] == "INSPECTED" and rep["source_unchanged"] is True
    assert compute_file_sha256(F1) == F1_SHA
    assert rep["units"]["unit"] == "mm"
    assert rep["page"]["total"] == 4 and len(rep["page"]["entities"]) == 2
    assert rep["entity_counts"]["DIMENSION"] == 25
    assert {"A-WALL-EXT", "A-DOOR", "A-DIMS"} <= {la["name"] for la in rep["layers"]}
    assert any(lay["name"] == "Layout1" for lay in rep["layouts"])
    dims = cb.inspect_dxf(F1, entity_type="DIMENSION", limit=1000)
    assert dims["page"]["limit"] == cb.MAX_PAGE
    assert all(isinstance(d["measurement"], float) for d in dims["page"]["entities"])
    texts = cb.inspect_dxf(F1, layer="A-ROOM-TEXT", entity_type="MTEXT")["page"]["entities"]
    assert any("Tầng" in t["text"] for t in texts)  # Vietnamese preserved


@pytest.mark.parametrize(("name", "status"), [("missing.dxf", "NOT_FOUND"), ("plan.dwg", "UNSUPPORTED")])
def test_inspection_missing_or_unsupported(tmp_path, name, status):
    path = tmp_path / name
    if name.endswith(".dwg"):
        path.write_bytes(b"AC1032")
    with pytest.raises(cb.CadBridgeError) as exc:
        cb.inspect_dxf(path)
    assert exc.value.status == status


# ----------------------------------------------------------------------------- comparison


def _modified_copy(tmp_path: Path, dx: float = 300.0, units: int | None = None) -> Path:
    doc = ezdxf.readfile(F1)
    for e in doc.modelspace():
        x = decode_ir_xdata(e)
        if x and x["src"] == "FRONT-F1" and e.dxftype() != "DIMENSION":
            e.translate(dx, 0, 0)
    doc.modelspace().add_line((0, 0), (1, 1))
    if units is not None:
        doc.header["$INSUNITS"] = units
    out = tmp_path / "architect-edited.dxf"
    doc.saveas(out)
    return out


def test_compare_fixture_matches_vnai(ir):
    rep = cb.compare_cad(ir, F1, floor_id="F1", expected_sha256=F1_SHA)
    assert rep["comparison_status"] == "VERIFIED_MATCH"
    assert rep["checks"]["drawing_digest"] == "VERIFIED_MATCH"
    assert rep["checks"]["ir_link"] in {"VERIFIED_MATCH", "GEOMETRY_MATCH_PRESENTATION_DIFFERS"}
    assert set(rep["summary"]) == {"VERIFIED_MATCH"}
    assert rep["visual_correctness"] == "NOT_EVALUATED"
    assert rep["autocad_handles_used_for_identity"] is False


def test_compare_detects_moved_door_and_unlinked_entities(ir, tmp_path):
    rep = cb.compare_cad(ir, _modified_copy(tmp_path), floor_id="F1")
    assert rep["comparison_status"] == "VERIFIED_MISMATCH"
    assert rep["by_source_geometry"]["FRONT-F1"]["status"] == "VERIFIED_MISMATCH"
    assert rep["by_source_geometry"]["ENTRANCE"]["status"] == "VERIFIED_MATCH"
    assert rep["unlinked_cad_entities"]["counts"] == {"LINE": 1}


def test_compare_stale_digest_and_unknown_units(ir, tmp_path):
    rep = cb.compare_cad(ir, F1, floor_id="F1", expected_sha256="0" * 64)
    assert rep["comparison_status"] == "STALE"
    rep = cb.compare_cad(ir, _modified_copy(tmp_path, units=0), floor_id="F1")
    assert rep["comparison_status"] == "INCOMPLETE" and rep["checks"]["units"] == "UNKNOWN"
    rep = cb.compare_cad(ir, F1, floor_id="F9")
    assert rep["comparison_status"] == "INCOMPLETE"


def test_cli_compare_exit_codes(ir, tmp_path, capsys):
    ir_path = tmp_path / "ir.json"
    ir_path.write_text(json.dumps(ir), encoding="utf-8")
    assert main(["cad", "compare", str(ir_path), str(F1), "--floor", "F1"]) == 0
    assert main(["cad", "compare", str(ir_path), str(_modified_copy(tmp_path)), "--floor", "F1"]) == 4
    assert main(["cad", "inspect", str(tmp_path / "nope.dxf")]) == 2
    capsys.readouterr()


# ----------------------------------------------------------------------------- proposals & edits

MOVE = [{"op": "translate_source_geometry", "source_geometry_id": "ENTRANCE", "dx": -200, "dy": 0}]


@pytest.fixture()
def project(tmp_path, ir):
    proj = tmp_path / "proj"
    pw.init_project(proj, "cad-demo")
    ir_src = tmp_path / "drawing-ir.json"
    ir_src.write_text(json.dumps(ir), encoding="utf-8")
    ir_in = proj / pw.import_file(proj, ir_src, "drafting")["artifact"]
    src = tmp_path / "architect" / "tang1.dxf"  # architect's original, outside the project
    src.parent.mkdir()
    shutil.copyfile(F1, src)
    return proj, ir_in, src


def _authorize(proj: Path, proposal: Path, synthetic: bool = True) -> dict:
    return pw.record_decision(proj, ce.AUTH_KIND, proposal, "Cho phép sửa bản sao theo đề xuất này",
                              "Test fixture", synthetic=synthetic)


def test_proposal_does_not_write_cad(project):
    proj, ir_in, src = project
    prop = ce.create_proposal(proj, src, ir_in, MOVE, floor="F1")
    assert prop["proposal_status"] == "PROPOSED" and prop["edit_permission"] == "NOT_GRANTED"
    assert compute_file_sha256(src) == F1_SHA
    assert not list((proj / "exports").glob("*.dxf"))
    assert prop["baseline_comparison_status"] == "VERIFIED_MATCH"
    assert len(prop["affected_entity_ids"]) >= 7  # door polylines, swing arc, tag, leader
    assert prop["constraint_impacts"]["dimensions_not_moved_become_stale"]
    eff = prop["expected_effects"][0]
    assert eff["bbox_after"][0] == pytest.approx(eff["bbox_before"][0] - 200)


@pytest.mark.parametrize("proxy", ["call_tool", "tool_search", "cad_batch", "invoke", "eval_expr"])
def test_proxy_tools_refused_even_with_override(tmp_path, proxy):
    bad = _profile(tmp_path, read_tools=["drawing_info", proxy], read_tool_overrides=[proxy])
    with pytest.raises(cb.CadBridgeError, match="proxy"):
        cb.load_profile(bad)


def _link_dir(link: Path, target: Path) -> None:
    try:
        os.symlink(target, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        if os.name != "nt":
            pytest.skip("cannot create directory links")
        import _winapi

        _winapi.CreateJunction(str(target), str(link))  # junction needs no privilege


@pytest.mark.parametrize("mode", ["traversal", "exports_link"])
def test_copy_destination_cannot_escape_exports(project, tmp_path, mode):
    proj, ir_in, src = project
    prop = proj / ce.create_proposal(proj, src, ir_in, MOVE, floor="F1")["proposal_path"]
    outside = tmp_path / "outside"
    outside.mkdir()
    if mode == "traversal":
        data = json.loads(prop.read_text(encoding="utf-8"))
        data["target_copy"] = "exports/../../outside/x.dxf"
        prop.write_text(json.dumps(data), encoding="utf-8")
    else:
        shutil.rmtree(proj / "exports")
        _link_dir(proj / "exports", outside)
    _authorize(proj, prop)
    with pytest.raises(pw.WorkflowError, match="PATH_REFUSED"):
        ce.apply_proposal(proj, prop)
    assert list(outside.iterdir()) == [] and compute_file_sha256(src) == F1_SHA


@pytest.mark.parametrize(
    "ops",
    [
        [],
        [{"op": "erase_entity", "entity_id": "DE-x"}],
        [{"op": "translate_source_geometry", "source_geometry_id": "NOPE", "dx": 1, "dy": 0}],
        [{"op": "translate_source_geometry", "source_geometry_id": "FRONT-F1", "dx": 1e9, "dy": 0}],
        [{"op": "translate_source_geometry", "source_geometry_id": "FRONT-F1", "dx": 1, "dy": 0,
          "lisp": "(command)"}],
        [{"op": "replace_text", "entity_id": "DE-0b7c8a87097d3301", "text": "a\nb"}],
    ],
)
def test_invalid_proposals_refused(project, ops):
    proj, ir_in, src = project
    with pytest.raises(pw.WorkflowError):
        ce.create_proposal(proj, src, ir_in, ops, floor="F1")


def test_unauthorized_apply_refused_and_wrong_target_kind(project):
    proj, ir_in, src = project
    prop = proj / ce.create_proposal(proj, src, ir_in, MOVE, floor="F1")["proposal_path"]
    with pytest.raises(pw.WorkflowError, match="NOT_AUTHORIZED"):
        ce.apply_proposal(proj, prop)
    with pytest.raises(pw.WorkflowError, match="CAD change proposal"):
        pw.record_decision(proj, ce.AUTH_KIND, ir_in, "ok", "x")
    # export authorization is a different decision and does not unlock CAD edits
    pw.record_decision(proj, "export_authorization", ir_in, "xuất DXF", "x", synthetic=True)
    with pytest.raises(pw.WorkflowError, match="NOT_AUTHORIZED"):
        ce.apply_proposal(proj, prop)
    with pytest.raises(pw.WorkflowError, match="không được hỗ trợ"):
        pw.record_decision(proj, "cad_modification", prop, "sửa bản gốc", "x")
    assert not list((proj / "exports").glob("*.dxf"))


def test_authorized_copy_edit_preserves_original_and_verifies(project, capsys):
    proj, ir_in, src = project
    prop = proj / ce.create_proposal(proj, src, ir_in, MOVE, floor="F1")["proposal_path"]
    _authorize(proj, prop)
    res = ce.apply_proposal(proj, prop)
    assert res["edit_status"] == "APPLIED_VERIFIED", res
    assert res["audit_status"] == "CLEAN" and res["source_unchanged"] is True
    assert res["readback"]["status"] == "VERIFIED_MATCH"
    assert res["vnai_comparison"]["unexpected_differences"] == []
    assert res["cad_writes_permitted"] is False
    assert res["copy_edit_permission"]["scope"] == "SINGLE_NEW_COPY"
    assert compute_file_sha256(src) == F1_SHA
    target = proj / res["target_copy"]
    assert target.parent == proj / "exports" and target.is_file()
    assert not list((proj / "exports").glob(".*partial"))
    # single use: the same authorization cannot be replayed
    with pytest.raises(pw.WorkflowError, match="NOT_AUTHORIZED"):
        ce.apply_proposal(proj, prop)
    status = pw.project_status(proj)
    assert status["cad_copy_edits"][0]["edit_status"] == "APPLIED_VERIFIED"
    assert status["cad_writes_permitted"] is False
    capsys.readouterr()


def test_replace_text_unicode(project):
    proj, ir_in, src = project
    ops = [{"op": "replace_text", "entity_id": "DE-0b7c8a87097d3301", "text": "Phòng vệ sinh tầng 1"}]
    prop = proj / ce.create_proposal(proj, src, ir_in, ops, floor="F1")["proposal_path"]
    _authorize(proj, prop)
    res = ce.apply_proposal(proj, prop)
    assert res["readback"]["actual_changed"] == ["DE-0b7c8a87097d3301"]
    doc = ezdxf.readfile(proj / res["target_copy"])
    assert any(e.dxftype() == "MTEXT" and e.text == "Phòng vệ sinh tầng 1" for e in doc.modelspace())
    # the copy now deviates from VNAI only on the edited id → reported as an expected difference
    assert res["vnai_comparison"]["status"] == "VERIFIED_MISMATCH"
    assert res["edit_status"] == "APPLIED_VERIFIED"


def test_stale_source_tampered_proposal_and_collision(project):
    proj, ir_in, src = project
    prop = proj / ce.create_proposal(proj, src, ir_in, MOVE, floor="F1")["proposal_path"]
    _authorize(proj, prop)
    # tamper the proposal scope after authorization → digest no longer matches
    data = json.loads(prop.read_text(encoding="utf-8"))
    data["operations"][0]["dy"] = -5000
    prop.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(pw.WorkflowError, match="NOT_AUTHORIZED"):
        ce.apply_proposal(proj, prop)

    prop2 = proj / ce.create_proposal(proj, src, ir_in, MOVE, floor="F1")["proposal_path"]
    _authorize(proj, prop2)
    (proj / json.loads(prop2.read_text(encoding="utf-8"))["target_copy"]).write_text("x")
    with pytest.raises(pw.WorkflowError, match="PATH_COLLISION"):
        ce.apply_proposal(proj, prop2)

    prop3 = proj / ce.create_proposal(proj, src, ir_in, MOVE, floor="F1")["proposal_path"]
    _authorize(proj, prop3)
    with src.open("ab") as fh:
        fh.write(b"\n")
    with pytest.raises(pw.WorkflowError, match="STALE"):
        ce.apply_proposal(proj, prop3)


def test_target_outside_exports_refused(project):
    proj, ir_in, src = project
    prop = proj / ce.create_proposal(proj, src, ir_in, MOVE, floor="F1")["proposal_path"]
    data = json.loads(prop.read_text(encoding="utf-8"))
    data["target_copy"] = str(src)  # try to point the "copy" at the original
    prop.write_text(json.dumps(data), encoding="utf-8")
    _authorize(proj, prop)  # even an authorization for this proposal cannot unlock it
    with pytest.raises(pw.WorkflowError, match="PATH_REFUSED"):
        ce.apply_proposal(proj, prop)
    assert compute_file_sha256(src) == F1_SHA


def test_write_failure_and_interruption_are_not_retried(project, monkeypatch):
    proj, ir_in, src = project
    prop = proj / ce.create_proposal(proj, src, ir_in, MOVE, floor="F1")["proposal_path"]
    _authorize(proj, prop)

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(ce.os, "link", boom)
    res = ce.apply_proposal(proj, prop)
    assert res["edit_status"] == "FAILED_NO_OUTPUT" and "disk full" in res["error"]
    assert not list((proj / "exports").glob("*.dxf*")) and not list((proj / "exports").glob(".*"))
    monkeypatch.undo()
    # simulate a crash between start and result: started event without a result
    prop2 = proj / ce.create_proposal(proj, src, ir_in, MOVE, floor="F1")["proposal_path"]
    auth = _authorize(proj, prop2)
    data = pw.load_project(proj)
    data["events"].append({"type": "cad_edit_started", "id": "CADE-099", "at": "x",
                           "authorization_id": auth["id"], "proposal_sha256": pw.sha256(prop2),
                           "target": "exports/x.dxf"})
    pw._save(proj, data)
    with pytest.raises(pw.WorkflowError, match="INTERRUPTED_UNCERTAIN"):
        ce.apply_proposal(proj, prop2)
    assert any(c["edit_status"] == "INTERRUPTED_UNCERTAIN"
               for c in pw.project_status(proj)["cad_copy_edits"])


def test_cli_project_cad_flow(project, tmp_path, capsys):
    proj, ir_in, src = project
    ops = tmp_path / "ops.json"
    ops.write_text(json.dumps(MOVE), encoding="utf-8")
    assert main(["project", "cad-propose", str(proj), "--source", str(src), "--ir", str(ir_in),
                 "--ops", str(ops), "--floor", "F1"]) == 0
    prop = json.loads(capsys.readouterr().out)["proposal_path"]
    assert main(["project", "cad-apply", str(proj), str(proj / prop)]) == 3
    assert "NOT_AUTHORIZED" in capsys.readouterr().out
    assert main(["project", "decide", str(proj), "--kind", ce.AUTH_KIND, "--target",
                 str(proj / prop), "--statement", "đồng ý", "--by", "KTS test", "--synthetic"]) == 0
    capsys.readouterr()
    assert main(["project", "cad-apply", str(proj), str(proj / prop)]) == 0
    assert json.loads(capsys.readouterr().out)["edit_status"] == "APPLIED_VERIFIED"
    assert main(["project", "cad-propose", str(proj), "--source", str(tmp_path / "x.dwg"),
                 "--ir", str(ir_in), "--ops", str(ops)]) == 2
    capsys.readouterr()
