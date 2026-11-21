"""Install the canonical project skills into a Claude Code ``.claude/skills`` directory.

One canonical source (``skills/`` in a checkout, ``vnai/_data/skills`` in a wheel) is copied
into managed installations marked with a digest file. Copies are never edited by hand: a
modified or unmanaged target is reported and left untouched unless ``force`` is given.
Plain file copies work on Windows Git Bash, PowerShell and WSL2 without symlink privileges.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

import yaml

from vnai import __version__
from vnai.resources import data_path

MARKER = ".vnai-installed.json"
MARKER_CONTRACT = "vnai-skill-install-v1"
NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
LINK_PATTERN = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")
MAX_DESCRIPTION = 1024
EXIT_CODES = {"CURRENT": 0, "INSTALLED": 0, "INVALID": 1, "NEEDS_ACTION": 3}


def canonical_root() -> Path:
    return data_path("skills")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _skill_files(skill_dir: Path) -> dict[str, str]:
    return {
        p.relative_to(skill_dir).as_posix(): _sha256(p)
        for p in sorted(skill_dir.rglob("*"))
        if p.is_file() and p.name != MARKER and "__pycache__" not in p.parts
    }


def _digest(files: dict[str, str]) -> str:
    canonical = json.dumps(files, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_skill(skill_dir: Path) -> list[str]:
    """Return frontmatter/path errors for one SKILL.md directory."""
    errors: list[str] = []
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return [f"{skill_dir.name}: SKILL.md missing"]
    text = skill_md.read_text(encoding="utf-8")
    if not text.startswith("---\n") and not text.startswith("---\r\n"):
        return [f"{skill_dir.name}: frontmatter must start on line 1"]
    parts = re.split(r"^---\s*$", text, maxsplit=2, flags=re.MULTILINE)
    if len(parts) < 3:
        return [f"{skill_dir.name}: unterminated frontmatter"]
    try:
        meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError as exc:
        return [f"{skill_dir.name}: invalid YAML frontmatter: {exc}"]
    if not isinstance(meta, dict):
        return [f"{skill_dir.name}: frontmatter must be a mapping"]
    name = meta.get("name")
    if name != skill_dir.name or not isinstance(name, str) or not NAME_PATTERN.match(name):
        errors.append(f"{skill_dir.name}: name must equal directory and match {NAME_PATTERN.pattern}")
    description = meta.get("description")
    if not isinstance(description, str) or not description.strip():
        errors.append(f"{skill_dir.name}: description required")
    elif len(description) > MAX_DESCRIPTION:
        errors.append(f"{skill_dir.name}: description exceeds {MAX_DESCRIPTION} characters")
    for path in sorted(skill_dir.rglob("*.md")):
        for target in LINK_PATTERN.findall(path.read_text(encoding="utf-8")):
            if "://" in target or target.startswith("mailto:"):
                continue
            if not (path.parent / target).resolve().exists():
                rel = path.relative_to(skill_dir).as_posix()
                errors.append(f"{skill_dir.name}/{rel}: broken link {target}")
    return errors


def canonical_skills(source: Path | None = None) -> dict[str, Path]:
    root = source or canonical_root()
    if not root.is_dir():
        raise OSError(f"Canonical skill source not found: {root}")
    return {p.name: p for p in sorted(root.iterdir()) if (p / "SKILL.md").is_file()}


def check_skills(dest_root: Path, source: Path | None = None) -> dict:
    """Compare installed copies under ``dest_root/.claude/skills`` with the canonical source."""
    skills_dir = Path(dest_root) / ".claude" / "skills"
    results = []
    errors: list[str] = []
    for name, src in canonical_skills(source).items():
        errors.extend(validate_skill(src))
        expected = _skill_files(src)
        target = skills_dir / name
        marker = target / MARKER
        if not target.exists():
            state = "MISSING"
        elif not marker.is_file():
            state = "UNMANAGED"
        else:
            recorded = json.loads(marker.read_text(encoding="utf-8"))
            actual = _skill_files(target)
            if actual != recorded.get("files"):
                state = "MODIFIED"
            elif recorded.get("skill_digest") != _digest(expected):
                state = "STALE"
            else:
                state = "CURRENT"
        results.append({"skill": name, "state": state, "path": target.as_posix()})
    if errors:
        status = "INVALID"
    elif all(r["state"] == "CURRENT" for r in results):
        status = "CURRENT"
    else:
        status = "NEEDS_ACTION"
    return {
        "contract": MARKER_CONTRACT,
        "status": status,
        "engine_version": __version__,
        "skills_dir": skills_dir.as_posix(),
        "skills": results,
        "errors": errors,
    }


def install_skills(dest_root: Path, source: Path | None = None, force: bool = False) -> dict:
    """Copy canonical skills into ``dest_root/.claude/skills`` without clobbering user edits."""
    report = check_skills(dest_root, source)
    if report["errors"]:
        return report
    canon = canonical_skills(source)
    skills_dir = Path(dest_root) / ".claude" / "skills"
    for entry in report["skills"]:
        state = entry["state"]
        if state == "CURRENT":
            entry["action"] = "UNCHANGED"
            continue
        if state in {"UNMANAGED", "MODIFIED"} and not force:
            entry["action"] = "REFUSED_PRESERVED_USER_COPY"
            continue
        src = canon[entry["skill"]]
        target = skills_dir / entry["skill"]
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(src, target, ignore=shutil.ignore_patterns("__pycache__", MARKER))
        files = _skill_files(target)
        (target / MARKER).write_text(
            json.dumps(
                {
                    "contract": MARKER_CONTRACT,
                    "note": "Generated copy. Edit the canonical skills/ source, then reinstall.",
                    "engine_version": __version__,
                    "skill_digest": _digest(files),
                    "files": files,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        entry["action"] = "INSTALLED"
        entry["state"] = "CURRENT"
    refused = any(e.get("action") == "REFUSED_PRESERVED_USER_COPY" for e in report["skills"])
    report["status"] = "NEEDS_ACTION" if refused else "INSTALLED"
    return report


def list_skills(source: Path | None = None) -> dict:
    skills = []
    for name, src in canonical_skills(source).items():
        text = (src / "SKILL.md").read_text(encoding="utf-8")
        meta = yaml.safe_load(re.split(r"^---\s*$", text, maxsplit=2, flags=re.MULTILINE)[1])
        skills.append(
            {
                "skill": name,
                "invoke": f"/{name}",
                "description": meta.get("description", ""),
                "digest": _digest(_skill_files(src)),
            }
        )
    return {"source": canonical_root().as_posix() if source is None else str(source),
            "skills": skills}
