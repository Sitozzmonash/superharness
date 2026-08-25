from __future__ import annotations

import os
from pathlib import Path

import pytest

from super_harness import SkillCatalog, SkillInstaller, parse_skill
from super_harness.exceptions import SkillError


def _skill(root: Path, name: str, description: str = "A useful skill") -> Path:
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# Instructions\n\nDo the work.\n",
        encoding="utf-8",
    )
    return directory


def test_skill_progressive_discovery_precedence_activation_and_resources(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / ".git").mkdir(parents=True)
    explicit = _skill(tmp_path / "explicit", "review", "Explicit review")
    _skill(project / ".agents" / "skills", "review", "Project review")
    _skill(project / ".super-harness" / "skills", "secondary")
    (explicit / "references").mkdir()
    (explicit / "references" / "guide.txt").write_text("guide", encoding="utf-8")

    catalog = SkillCatalog.discover(cwd=project, explicit=[explicit], user_root=tmp_path / "user")
    assert [item.name for item in catalog.list()] == ["review", "secondary"]
    assert catalog.get("review").description == "Explicit review"
    assert catalog.collisions["review"]
    activated = catalog.activate("review")
    assert "Do the work" in activated.instructions
    assert activated.read_resource("references/guide.txt") == b"guide"
    with pytest.raises(SkillError, match="escapes"):
        activated.read_resource("../outside.txt")


def test_skill_validation_local_install_metadata_and_remove(tmp_path: Path) -> None:
    source = _skill(tmp_path / "source", "writer", "Write: concise docs")
    installer = SkillInstaller(tmp_path / "installed")
    installed = installer.install(source)

    assert installed.name == "writer"
    assert (installed.path.parent / ".super-harness-source.json").is_file()
    with pytest.raises(SkillError, match="already installed"):
        installer.install(source)
    installer.remove("writer")
    assert not installed.path.parent.exists()

    invalid = tmp_path / "invalid"
    invalid.mkdir()
    (invalid / "SKILL.md").write_text("# no frontmatter", encoding="utf-8")
    with pytest.raises(SkillError, match="frontmatter"):
        parse_skill(invalid)

    unsafe = tmp_path / "unsafe"
    unsafe.mkdir()
    (unsafe / "SKILL.md").write_text(
        "---\nname: ../escape\ndescription: unsafe\n---\nbody", encoding="utf-8"
    )
    with pytest.raises(SkillError, match="lowercase"):
        parse_skill(unsafe)


def test_pinned_codex_skill_is_compatible_external_fixture() -> None:
    root = Path(__file__).parents[1]
    fixture = root / "references" / "codex" / ".codex" / "skills" / "code-review"
    metadata = parse_skill(fixture, source="pinned-codex")
    assert metadata.name
    assert metadata.description


@pytest.mark.e2e
def test_install_pinned_github_subdirectory_skill(tmp_path: Path) -> None:
    if os.environ.get("SUPER_HARNESS_EXTERNAL_COMPAT") != "1":
        pytest.skip("set SUPER_HARNESS_EXTERNAL_COMPAT=1 for GitHub compatibility E2E")
    source = (
        "https://github.com/openai/codex/tree/"
        "7c6eb0eef113ddc16ae5b207ac9add364b489798/.codex/skills/code-review"
    )
    installed = SkillInstaller(tmp_path / "installed").install(source)
    assert installed.name
    assert installed.description
