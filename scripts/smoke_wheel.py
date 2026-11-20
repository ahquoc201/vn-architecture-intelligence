"""Build a wheel and verify runtime resources in a fresh venv outside the checkout.

Run: python scripts/smoke_wheel.py
Uses pip/cache/network to install the declared runtime dependencies. No CAD writes.
"""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import venv


def run() -> None:
    root = Path(__file__).resolve().parents[1]
    output = root / "outputs" / "wheel-smoke"
    output.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [sys.executable, "-m", "pip", "wheel", str(root), "--no-deps", "--wheel-dir", str(output)],
        check=True,
    )
    import tomllib

    version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    wheel = output / f"vn_architecture_intelligence-{version}-py3-none-any.whl"
    # Verify every packaged schema/vocabulary byte against its canonical source.
    from zipfile import ZipFile

    with ZipFile(wheel) as archive:
        patterns = (
            "knowledge/architecture/*.json",
            "knowledge/architecture/*.yaml",
            "knowledge/fengshui/*.json",
            "knowledge/fengshui/*.yaml",
            "knowledge/insights.yaml",
            "sources/bibliography.yaml",
        )
        for pattern in patterns:
            for source in root.glob(pattern):
                member = "vnai/_data/" + source.relative_to(root).as_posix()
                if archive.read(member) != source.read_bytes():
                    raise RuntimeError(f"Packaged data differs: {member}")
        for source in (root / "src/vnai").glob("*.py"):
            member = source.relative_to(root / "src").as_posix()
            if archive.read(member) != source.read_bytes():
                raise RuntimeError(f"Wheel code differs from tested source: {member}")
    results = []
    with tempfile.TemporaryDirectory(prefix="vnai-wheel-") as temporary:
        work = Path(temporary)
        env_dir = work / "venv"
        venv.EnvBuilder(with_pip=True).create(env_dir)
        python = env_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTHONHOME"}}
        subprocess.run(
            [str(python), "-m", "pip", "install", str(wheel) + "[cad]"],
            check=True,
            cwd=work,
            env=env,
        )
        for source in (root / "examples" / "batch005").glob("*.json"):
            shutil.copyfile(source, work / source.name)
        for source in (root / "examples/batch006a").glob("*.json"):
            shutil.copyfile(source, work / ("floorplan-" + source.name))
        for source in (root / "examples/batch006b").glob("*.json"):
            shutil.copyfile(source, work / ("review-" + source.name))
        for source in (root / "examples/batch006c").glob("*.json"):
            shutil.copyfile(source, work / ("evaluation-" + source.name))
        for source in (root / "examples/batch007a").glob("*/*.json"):
            shutil.copyfile(source, work / ("workflow-" + source.parent.name + "-" + source.name))
        for source in (root / "examples/batch007b1").glob("*.json"):
            shutil.copyfile(source, work / ("wall-" + source.name))
        for source in (root / "examples/batch007b2").glob("*.json"):
            shutil.copyfile(source, work / ("openingdraft-" + source.name))
        for source in (root / "examples/batch007b3").glob("*.json"):
            shutil.copyfile(source, work / ("stairdraft-" + source.name))
        for source in (root / "examples/batch007c").glob("*.json"):
            shutil.copyfile(source, work / ("drafting-" + source.name))
        shutil.copyfile(root / "examples/townhouse_4x20_brief.json", work / "brief.json")
        shutil.copyfile(root / "examples/townhouse_sample.json", work / "legacy.json")
        for name in (
            "residential-4x20-six-rooms",
            "oracle-area",
            "historical-4x20-loaded",
            "historical-8x15-separation",
        ):
            shutil.copyfile(
                root / "examples/batch007b4" / (name + ".json"),
                work / ("integrated-" + name + ".json"),
            )
        feasible = json.loads(
            (work / "integrated-residential-4x20-six-rooms.json").read_text(encoding="utf-8")
        )
        opening_spec = feasible["opening_specification"]
        next(o for o in opening_spec["openings"] if o["id"] == "ENTRANCE")["offset"] = 0.8
        alternate = feasible["refinements"][0]["passage_alternatives"][0]
        for key in ("passages", "clearance_regions"):
            updates = {r["id"]: r for r in alternate.get(key, [])}
            opening_spec[key] = [updates.get(r["id"], r) for r in opening_spec[key]]
        feasible["refinements"] = []
        (work / "integrated-feasible.json").write_text(json.dumps(feasible), encoding="utf-8")
        commands = [
            (
                [
                    "design",
                    "integrated",
                    "refine",
                    "integrated-residential-4x20-six-rooms.json",
                    "--out",
                    "integrated-stored.json",
                ],
                0,
            ),
            (["design", "integrated", "generate", "integrated-feasible.json"], 0),
            (["design", "integrated", "validate", "integrated-stored.json"], 0),
            (
                [
                    "design",
                    "integrated",
                    "report",
                    "integrated-stored.json",
                    "--markdown",
                    "integrated.md",
                ],
                0,
            ),
            (
                [
                    "design",
                    "integrated",
                    "preview",
                    "integrated-stored.json",
                    "--view",
                    "comparison",
                    "--out",
                    "integrated-comparison.svg",
                ],
                0,
            ),
            (
                [
                    "design",
                    "integrated",
                    "preview",
                    "integrated-stored.json",
                    "--view",
                    "after",
                    "--floor",
                    "F1",
                    "--out",
                    "integrated-F1.svg",
                ],
                0,
            ),
            (
                [
                    "design",
                    "integrated",
                    "preview",
                    "integrated-stored.json",
                    "--view",
                    "after",
                    "--floor",
                    "F2",
                    "--out",
                    "integrated-F2.svg",
                ],
                0,
            ),
            (
                [
                    "design",
                    "integrated",
                    "preview",
                    "integrated-stored.json",
                    "--view",
                    "section",
                    "--out",
                    "integrated-section.svg",
                ],
                0,
            ),
            (["design", "integrated", "validate", "integrated-oracle-area.json"], 6),
            (["design", "integrated", "validate", "integrated-historical-4x20-loaded.json"], 4),
            (["design", "integrated", "validate", "integrated-historical-8x15-separation.json"], 5),
            (["design", "stairs", "draft", "stairdraft-straight.json"], 3),
            (["design", "stairs", "drafting-validate", "stairdraft-stored.json"], 3),
            (
                [
                    "design",
                    "stairs",
                    "section",
                    "stairdraft-l-shaped.json",
                    "--markdown",
                    "stair-section.md",
                ],
                3,
            ),
            (
                [
                    "design",
                    "stairs",
                    "schedule",
                    "stairdraft-u-shaped.json",
                    "--markdown",
                    "stair-schedule.md",
                ],
                3,
            ),
            (
                [
                    "design",
                    "stairs",
                    "preview",
                    "stairdraft-straight.json",
                    "--view",
                    "plan",
                    "--out",
                    "stair-plan.svg",
                ],
                3,
            ),
            (
                [
                    "design",
                    "stairs",
                    "preview",
                    "stairdraft-u-shaped.json",
                    "--view",
                    "section",
                    "--out",
                    "stair-section.svg",
                ],
                3,
            ),
            (["design", "stairs", "draft", "stairdraft-missing-slab-opening.json"], 3),
            (["design", "stairs", "draft", "stairdraft-headroom-failure.json"], 4),
            (["design", "stairs", "draft", "stairdraft-unsupported-spiral.json"], 5),
            (["design", "stairs", "draft", "stairdraft-stale-opening-digest.json"], 1),
            (
                [
                    "design",
                    "stairs",
                    "preview",
                    "stairdraft-townhouse-benchmark.json",
                    "--view",
                    "plan",
                    "--out",
                    "townhouse-stairs.svg",
                ],
                4,
            ),
            (["sources", "validate"], 0),
            (["knowledge", "validate"], 0),
            (["fengshui", "knowledge", "validate"], 0),
            (["fengshui", "knowledge", "report"], 0),
            (["design", "brief", "validate", "brief.json"], 3),
            (["design", "brief", "report", "brief.json"], 3),
            (["design", "program", "build", "brief.json"], 3),
            (["design", "zoning", "validate", "zoning-proposed.json"], 3),
            (["design", "zoning", "report", "zoning-approved.json"], 0),
            (["geometry", "validate", "geometry-valid.json"], 0),
            (["geometry", "report", "geometry-linked-approved.json"], 0),
            (["review", "legacy.json"], 0),
            (
                [
                    "design",
                    "floorplan",
                    "generate",
                    "floorplan-alternatives.json",
                    "--candidates",
                    "3",
                ],
                0,
            ),
            (["design", "floorplan", "generate", "floorplan-missing-footprint.json"], 3),
            (["design", "floorplan", "generate", "floorplan-search-budget.json"], 6),
            (["design", "candidate", "review", "review-selected-only.json"], 0),
            (["design", "openings", "validate", "review-corridor-clearance.json"], 0),
            (["design", "circulation", "analyze", "review-corridor-graph-only.json"], 0),
            (["design", "stairs", "validate", "review-stairs-connected.json"], 0),
            (["design", "architectural-review", "review-corridor-clearance.json"], 0),
            (["design", "architectural-review", "review-missing-openings.json"], 3),
            (["design", "architectural-review", "review-swing-obstacle.json"], 1),
        ]
        commands.extend(
            [
                (["design", "candidates", "evaluate", "evaluation-verified-circulation.json"], 0),
                (["design", "candidates", "compare", "evaluation-three-candidates.json"], 0),
                (
                    [
                        "design",
                        "candidates",
                        "rank",
                        "evaluation-three-candidates.json",
                        "--markdown",
                        "ranking.md",
                    ],
                    0,
                ),
                (["design", "candidates", "rank", "evaluation-ranking-withheld.json"], 3),
                (["design", "candidates", "rank", "evaluation-all-ineligible.json"], 4),
            ]
        )
        commands.extend(
            [
                (["design", "replay", "validate", "workflow-replay-valid-provenance.json"], 0),
                (
                    ["design", "replay", "report", "workflow-replay-modified-room-dimensions.json"],
                    1,
                ),
                (
                    [
                        "design",
                        "revision",
                        "compare",
                        "workflow-revision-valid-manual-revision.json",
                    ],
                    0,
                ),
                (
                    [
                        "design",
                        "readiness",
                        "report",
                        "workflow-readiness-room-geometry-ready.json",
                        "--markdown",
                        "readiness.md",
                    ],
                    0,
                ),
                (
                    [
                        "design",
                        "readiness",
                        "report",
                        "workflow-readiness-selected-without-approval.json",
                    ],
                    3,
                ),
                (["design", "benchmark", "run", "workflow-benchmark-benchmark-a.json"], 0),
                (["design", "benchmark", "run", "workflow-benchmark-benchmark-c.json"], 5),
                (["design", "benchmark", "run", "workflow-benchmark-search-exhausted.json"], 6),
                (["dxf", "legacy.json", "--out", "legacy-smoke.dxf"], 0),
            ]
        )
        commands.extend(
            [
                (["design", "walls", "generate", "wall-rectangle-inward.json"], 0),
                (["design", "walls", "validate", "wall-stored.json"], 0),
                (
                    [
                        "design",
                        "walls",
                        "report",
                        "wall-rectangle-inward.json",
                        "--markdown",
                        "walls.md",
                    ],
                    0,
                ),
                (
                    [
                        "design",
                        "walls",
                        "preview",
                        "wall-rectangle-inward.json",
                        "--out",
                        "walls.svg",
                    ],
                    0,
                ),
                (["design", "walls", "generate", "wall-x-junction.json"], 0),
                (["design", "walls", "generate", "wall-missing-thickness.json"], 3),
                (["design", "walls", "generate", "wall-clear-area-violation.json"], 4),
                (["design", "walls", "generate", "wall-nonorthogonal-special.json"], 5),
                (
                    [
                        "design",
                        "walls",
                        "preview",
                        "wall-townhouse-benchmark.json",
                        "--out",
                        "townhouse.svg",
                    ],
                    4,
                ),
            ]
        )
        commands.extend(
            [
                (["design", "openings", "draft", "openingdraft-oracle-entrance.json"], 0),
                (["design", "openings", "drafting-validate", "openingdraft-stored.json"], 0),
                (
                    [
                        "design",
                        "openings",
                        "schedule",
                        "openingdraft-fixed-window.json",
                        "--markdown",
                        "opening-schedule.md",
                    ],
                    0,
                ),
                (
                    [
                        "design",
                        "openings",
                        "preview",
                        "openingdraft-fixed-window.json",
                        "--out",
                        "openings.svg",
                    ],
                    0,
                ),
                (["design", "openings", "draft", "openingdraft-missing-dimensions.json"], 3),
                (["design", "openings", "draft", "openingdraft-swing-fixed-collision.json"], 4),
                (["design", "openings", "draft", "openingdraft-unsupported-angle.json"], 5),
                (["design", "openings", "draft", "openingdraft-stale-wall-digest.json"], 1),
                (
                    [
                        "design",
                        "openings",
                        "preview",
                        "openingdraft-townhouse-benchmark.json",
                        "--out",
                        "townhouse-openings.svg",
                    ],
                    4,
                ),
            ]
        )
        commands.extend(
            [
                (["design", "drafting", "generate", "drafting-oracle-exterior-clear.json", "--out", "drafting-oracle-a.json"], 0),
                (["design", "drafting", "validate", "drafting-oracle-a.json"], 0),
                (["design", "drafting", "generate", "drafting-oracle-dimension-chain.json"], 0),
                (["design", "drafting", "generate", "drafting-oracle-stair-section.json"], 0),
                (["design", "drafting", "generate", "drafting-collision-example.json"], 4),
                (["design", "drafting", "generate", "drafting-townhouse-6rooms-drafting.json", "--out", "drafting-townhouse.json"], 0),
                (["design", "drafting", "validate", "drafting-townhouse.json"], 0),
                (["design", "drafting", "report", "drafting-townhouse.json", "--markdown", "drafting-townhouse.md"], 0),
                (["design", "drafting", "layers", "drafting-townhouse.json", "--markdown", "drafting-layers.md"], 0),
                (["design", "drafting", "preview", "drafting-townhouse.json", "--floor", "F1", "--out", "drafting-F1.svg"], 0),
                (["design", "drafting", "preview", "drafting-townhouse-6rooms-drafting.json", "--view", "sheet", "--scale", "50", "--out", "drafting-sheet-50.svg"], 0),
            ]
        )
        th100_geom_digest: str | None = None
        th100_pres_digest: str | None = None
        for args, expected in commands:
            result = subprocess.run(
                [str(python), "-I", "-X", "utf8", "-m", "vnai", *args],
                cwd=work,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=60,
            )
            if result.returncode != expected:
                raise RuntimeError(f"{args}: {result.returncode}, {result.stdout}, {result.stderr}")
            if args[:2] == ["design", "drafting"]:
                draft_rep = json.loads(result.stdout)
                if draft_rep["cad_writes_permitted"] or draft_rep["architect_approval"] != "NOT_GRANTED":
                    raise RuntimeError("Installed drafting engine granted CAD writes or approval")
                if args[2] == "generate" and args[3] == "drafting-oracle-exterior-clear.json":
                    clear_dims = [
                        d for d in draft_rep["dimensions"] if d["measurement_basis"] == "clear_room_interior"
                    ]
                    if sorted(round(d["measured_value"], 6) for d in clear_dims) != [3600.0, 4600.0]:
                        raise RuntimeError("Installed Oracle A clear dimensions failed")
                    if abs(draft_rep["annotations"]["rooms"][0]["clear_area_m2"] - 16.56) > 1e-10:
                        raise RuntimeError("Installed Oracle A clear area failed")
                if args[2] == "generate" and args[3] == "drafting-oracle-dimension-chain.json":
                    ch = next(
                        c for c in draft_rep["dimension_chains"] if c["chain_id"] == "CHAIN-F1-X-SOUTH"
                    )
                    if ch["reference_coordinates"] != [0.0, 1200.0, 2800.0, 4000.0] or ch["closure_status"] != "GEOMETRIC_CLOSED_EXACT":
                        raise RuntimeError("Installed Oracle B dimension chain failed")
                if args[2] == "generate" and args[3] == "drafting-townhouse-6rooms-drafting.json":
                    if draft_rep["collisions"] or draft_rep["source_digests"]["verification_coverage"]["verified"] != 48:
                        raise RuntimeError("Installed drafting townhouse benchmark check failed")
                    th100_geom_digest = draft_rep["geometry_and_dimensions_digest"]
                    th100_pres_digest = draft_rep["presentation_digest"]
                if args[2] == "preview":
                    import xml.etree.ElementTree as ET

                    if "--scale" in args:
                        if (
                            draft_rep["paper_space"]["scale_denominator"] != 50
                            or draft_rep["geometry_and_dimensions_digest"] != th100_geom_digest
                            or draft_rep["presentation_digest"] == th100_pres_digest
                            or draft_rep["collisions"]
                        ):
                            raise RuntimeError("Installed drafting 1:50 scale invariance check failed")

                    svg_file = work / args[-1]
                    ET.parse(svg_file)
                    svg_txt = svg_file.read_text(encoding="utf-8")
                    if 'preserveAspectRatio="xMidYMid meet"' not in svg_txt or "Phòng khách" not in svg_txt:
                        raise RuntimeError("Installed drafting SVG lost uniform scale or Vietnamese Unicode")
            if args[:2] == ["design", "integrated"]:
                integrated = json.loads(result.stdout)
                if (
                    integrated["cad_writes_permitted"]
                    or integrated["approval_inherited"]
                    or integrated["architect_approval"] != "NOT_GRANTED"
                ):
                    raise RuntimeError("Installed integrated workflow granted approval/CAD writes")
                if expected == 0:
                    state = integrated["candidates"][0]
                    if (
                        not state["verification_coverage"]["all_required_verified"]
                        or state["hard_violations"]
                        or state["required_unknown"]
                    ):
                        raise RuntimeError(
                            "Installed integrated proposal lacks complete supported geometric verification"
                        )
                    if len(state["engines"]["walls"]["rooms"]) != 6 or any(
                        abs(
                            r["clear_area_m2"]
                            - (3.23 if r["room_id"].startswith("BATH") else 20.52)
                        )
                        > 1e-12
                        for r in state["engines"]["walls"]["rooms"]
                    ):
                        raise RuntimeError("Installed integrated clear-area oracle failed")
                    stair = state["engines"]["stairs"]["stairs"][0]
                    if stair["final_elevation_m"] != 3.3 or [
                        f["risers"] for f in stair["flights"]
                    ] != [10, 10]:
                        raise RuntimeError("Installed integrated stair oracle failed")
                    if args[2] == "preview":
                        import xml.etree.ElementTree as ET

                        target = work / args[-1]
                        ET.parse(target)
                        if state["revision_id"] not in target.read_text(encoding="utf-8"):
                            raise RuntimeError("Integrated SVG lacks proposed revision binding")
            if args[:2] == ["design", "stairs"] and args[2] != "validate":
                stair_report = json.loads(result.stdout)
                if (
                    stair_report["cad_writes_permitted"]
                    or stair_report["approval_inherited"]
                    or stair_report["architect_approval"] != "NOT_GRANTED"
                ):
                    raise RuntimeError("Installed stair engine inferred approval/CAD permission")
                if args[2:] == ["draft", "stairdraft-straight.json"]:
                    flight = stair_report["stairs"][0]["flights"][0]
                    if (
                        flight["risers"] != 20
                        or flight["ordinary_treads"] != 19
                        or abs(flight["riser_height_m"] - 0.165) > 1e-12
                        or abs(flight["run_m"] - 4.75) > 1e-12
                        or stair_report["stairs"][0]["final_elevation_m"] != 3.3
                    ):
                        raise RuntimeError("Installed stair arithmetic oracle failed")
                    (work / "stairdraft-stored.json").write_text(result.stdout, encoding="utf-8")
                if args[2] == "preview":
                    svg = (work / args[-1]).read_text(encoding="utf-8")
                    if (
                        stair_report["stair_revision_id"] not in svg
                        or 'preserveAspectRatio="xMidYMid meet"' not in svg
                    ):
                        raise RuntimeError("Installed stair SVG lost its revision/scale binding")
                if args[2] in {"section", "schedule"} and not (work / args[-1]).is_file():
                    raise RuntimeError("Installed stair Markdown output is missing")
            if args[:3] == ["design", "floorplan", "generate"] and expected == 0:
                generated = json.loads(result.stdout)
                if len(generated["candidates"]) != 3 or any(
                    c["hard_validation"]["spatial_report"]["status"] != "VALID"
                    or c["approval_status"] != "PROPOSED"
                    or c["cad_writes_permitted"]
                    for c in generated["candidates"]
                ):
                    raise RuntimeError("Wheel generator violated its candidate contract")
            if args[:3] == ["design", "candidate", "review"]:
                selected = json.loads(result.stdout)
                if selected["review_state"] != "SELECTED" or selected["approval_record_valid"]:
                    raise RuntimeError("Wheel inferred approval from selection")
            if args[:2] == ["design", "architectural-review"] and expected == 0:
                reviewed = json.loads(result.stdout)
                if (
                    reviewed["physical_circulation_status"] != "GEOMETRICALLY_TRAVERSABLE"
                    or reviewed["fully_verified"]
                    or reviewed["technical_compliance"] != "NOT_EVALUATED"
                    or reviewed["cad_writes_permitted"]
                ):
                    raise RuntimeError("Wheel architectural review violated its bounded scope")
            if args[:2] == ["design", "candidates"]:
                evaluation = json.loads(result.stdout)
                if (
                    evaluation["cad_writes_permitted"]
                    or evaluation["architect_approval"] != "NOT_GRANTED_BY_EVALUATION"
                ):
                    raise RuntimeError("Wheel evaluation inferred CAD permission/approval")
                if args[2] == "rank" and expected == 0:
                    if (
                        evaluation["ranking_status"] != "RANKED"
                        or evaluation["winner_id"] != "A"
                        or (work / "ranking.md").read_text() != evaluation["markdown"]
                    ):
                        raise RuntimeError(
                            "Wheel ranking/Markdown differs from the tested policy oracle"
                        )
                elif args[2] == "rank" and evaluation["winner_id"] is not None:
                    raise RuntimeError("Wheel produced a winner without evidence")
                replay = subprocess.run(
                    [str(python), "-I", "-X", "utf8", "-m", "vnai", *args[:4]],
                    cwd=work,
                    env=env,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=60,
                )
                if replay.returncode != expected or json.loads(replay.stdout) != evaluation:
                    raise RuntimeError("Installed evaluation is not deterministic")
            if args[:2] in (
                ["design", "replay"],
                ["design", "revision"],
                ["design", "readiness"],
                ["design", "benchmark"],
            ):
                workflow = json.loads(result.stdout)
                if (
                    workflow["cad_writes_permitted"]
                    or workflow["standards_review"] != "NOT_EVALUATED"
                    or workflow["fengshui_review"] != "NOT_EVALUATED"
                ):
                    raise RuntimeError(
                        "Installed workflow crossed CAD/source governance boundaries"
                    )
                if args[1] == "readiness" and expected == 0:
                    if (
                        workflow["readiness_status"] != "READY_FOR_DRAFTING"
                        or workflow["scope"] != ["room_geometry"]
                        or workflow["approval_granted"]
                    ):
                        raise RuntimeError(
                            "Installed readiness inferred complete drafting approval"
                        )
                if (
                    args[1] == "replay"
                    and expected == 0
                    and workflow["replay_status"] != "VERIFIED"
                ):
                    raise RuntimeError("Installed replay failed its original-constraint oracle")
            if args[:2] == ["design", "openings"] and args[2] != "validate":
                opening = json.loads(result.stdout)
                if (
                    opening["cad_writes_permitted"]
                    or opening["approval_inherited"]
                    or opening["architect_approval"] != "NOT_GRANTED"
                ):
                    raise RuntimeError("Installed drafting inferred approval or CAD authorization")
                if args[2:] == ["draft", "openingdraft-oracle-entrance.json"]:
                    floor = opening["floors"][0]
                    for key, expected_area in (
                        ("source_wall_area_m2", 0.8),
                        ("plan_cut_area_m2", 0.18),
                        ("remaining_wall_plan_area_m2", 0.62),
                    ):
                        if abs(floor[key] - expected_area) > 1e-12:
                            raise RuntimeError(
                                "Installed door cut failed independent area oracle: " + key
                            )
                    (work / "openingdraft-stored.json").write_text(result.stdout, encoding="utf-8")
                if args[2] == "schedule":
                    windows = [r for r in opening["openings"] if r["type"].endswith("window")]
                    if (
                        len(windows) != 1
                        or windows[0]["graph_eligible"]
                        or windows[0]["floor_cut_applied"]
                    ):
                        raise RuntimeError("Installed window became a floor-level passage")
                    if "W01" not in (work / "opening-schedule.md").read_text(encoding="utf-8"):
                        raise RuntimeError("Installed opening schedule lost explicit window mark")
                if args[2] == "preview":
                    svg = (work / args[-1]).read_text(encoding="utf-8")
                    if (
                        opening["opening_revision_id"] not in svg
                        or 'preserveAspectRatio="xMidYMid meet"' not in svg
                    ):
                        raise RuntimeError(
                            "Installed opening preview lost revision binding/uniform scale"
                        )
            if args[:2] == ["design", "walls"]:
                walls = json.loads(result.stdout)
                if walls["cad_writes_permitted"] or walls["approval_inherited"]:
                    raise RuntimeError("Installed walls inferred approval/CAD permission")
                if args[2:] == ["generate", "wall-rectangle-inward.json"]:
                    if abs(walls["rooms"][0]["clear_area_m2"] - 16.56) > 1e-10:
                        raise RuntimeError("Installed wall clear-area oracle failed")
                    if abs(walls["floors"][0]["wall_union_area_m2"] - 3.44) > 1e-10:
                        raise RuntimeError("Installed wall union-area oracle failed")
                    (work / "wall-stored.json").write_text(result.stdout, encoding="utf-8")
                if args[3] == "wall-x-junction.json":
                    if abs(walls["floors"][0]["wall_union_area_m2"] - 6.75) > 1e-10:
                        raise RuntimeError("Installed X junction oracle failed")
                if args[2] == "preview":
                    svg = (work / args[-1]).read_text(encoding="utf-8")
                    if (
                        walls["wall_revision_id"] not in svg
                        or 'preserveAspectRatio="xMidYMid meet"' not in svg
                    ):
                        raise RuntimeError("Installed wall SVG lost its binding/scale")
                if args[2] == "report" and not (work / "walls.md").is_file():
                    raise RuntimeError("Installed wall Markdown missing")
            if args[0] == "dxf" and not (work / "legacy-smoke.dxf").is_file():
                raise RuntimeError("Existing schematic DXF behavior no longer works from wheel")
            results.append({"command": args, "exit_code": result.returncode})
        location = subprocess.check_output(
            [str(python), "-I", "-c", "import vnai; print(vnai.__file__)"],
            cwd=work,
            env=env,
            text=True,
        ).strip()
        if not Path(location).resolve().is_relative_to(env_dir.resolve()):
            raise RuntimeError("Smoke test imported checkout instead of wheel")
    report = {
        "engine_version": version,
        "python": sys.version.split()[0],
        "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        "canonical_data_and_code_verified": True,
        "fresh_virtualenv": True,
        "outside_checkout": True,
        "isolated_python": True,
        "cad_writes_permitted": False,
        "checks": results,
    }
    # Keep prior verification reports, including retries for the same engine version.
    index = 1
    destination = output / f"smoke-{version}-{index}.json"
    while destination.exists():
        index += 1
        destination = output / f"smoke-{version}-{index}.json"
    destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    run()
