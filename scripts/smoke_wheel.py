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
            [str(python), "-m", "pip", "install", str(wheel)], check=True, cwd=work, env=env
        )
        for source in (root / "examples" / "batch005").glob("*.json"):
            shutil.copyfile(source, work / source.name)
        shutil.copyfile(root / "examples/townhouse_4x20_brief.json", work / "brief.json")
        shutil.copyfile(root / "examples/townhouse_sample.json", work / "legacy.json")
        commands = [
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
        ]
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
