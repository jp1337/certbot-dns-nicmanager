"""docs/ is for whoever runs the plugin and ships to PyPI; docs-tech/ never does.

The boundary is checked on the artefact, not on MANIFEST.in: the test builds the
real sdist and reads its file list, so a `graft .`, an `include docs-tech/...`
or a setuptools default that starts picking up Markdown fails here whatever the
manifest seems to say.
"""

import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_BUILD_SDIST = "import sys, setuptools.build_meta as b; print(b.build_sdist(sys.argv[1]))"

# The sdist ships tests/ but not docs-tech/, so these checks only mean something
# in a git checkout; a packager running the suite from the sdist skips them.
pytestmark = pytest.mark.skipif(
    not (ROOT / ".git").exists(), reason="needs a git checkout of the repository"
)


def _sdist_names(tmp_path: Path) -> list[str]:
    # Build from the tracked files only, as CI does from a fresh checkout. In the
    # working tree setuptools would reuse a stale *.egg-info/SOURCES.txt and ship
    # whatever an earlier build listed there.
    src = tmp_path / "src"
    tracked = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.split("\0")
    for rel in filter(None, tracked):
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, src / rel)
    out = tmp_path / "dist"
    name = (
        subprocess.run(
            [
                sys.executable,
                "-c",
                _BUILD_SDIST,
                str(out),
            ],
            cwd=src,
            check=True,
            capture_output=True,
            text=True,
        )
        .stdout.strip()
        .splitlines()[-1]
    )
    with tarfile.open(out / name) as sdist:
        # Drop the "certbot_dns_nicmanager-X.Y.Z/" prefix.
        return [m.split("/", 1)[1] for m in sdist.getnames() if "/" in m]


def test_the_technical_docs_are_not_published(tmp_path):
    tech = [p for p in (ROOT / "docs-tech").rglob("*.md")]
    assert tech, "docs-tech/ is missing or empty: maintainer docs belong there"

    names = _sdist_names(tmp_path)
    assert "docs/TROUBLESHOOTING.md" in names, "the operator docs no longer ship"
    leaked = [n for n in names if n.startswith("docs-tech")]
    assert not leaked, f"maintainer docs ship to PyPI: {leaked}"


def test_no_maintainer_docs_hide_under_docs():
    for name in ("docs-tech", "decisions", "ARCHITECTURE.md"):
        assert not (ROOT / "docs" / name).exists(), (
            f"docs/{name} exists — everything under docs/ ships to PyPI; "
            f"maintainer documentation goes in docs-tech/"
        )


def test_operator_docs_do_not_point_into_docs_tech():
    # A published page that depends on an unpublished one is a dead end in the sdist.
    for page in (ROOT / "docs").rglob("*.md"):
        links = re.findall(r"\]\(([^)]*docs-tech[^)]*)\)", page.read_text())
        assert not links, f"{page.relative_to(ROOT)} links into docs-tech/: {links}"
