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
    # Build from the repository's files (tracked, or new and not ignored), as CI
    # does from a fresh checkout. In the
    # working tree setuptools would reuse a stale *.egg-info/SOURCES.txt and ship
    # whatever an earlier build listed there.
    src = tmp_path / "src"
    tracked = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
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


# -- links ------------------------------------------------------------------

_SELF = re.compile(
    r"https://(?:github\.com/jp1337/certbot-dns-nicmanager/(?:blob|tree)/main"
    r"|raw\.githubusercontent\.com/jp1337/certbot-dns-nicmanager/main)/([^)\s\"#]*)(#[^)\s\"]*)?"
)
_LINK = re.compile(r"\]\(([^)\s]+)\)|(?:href|src)=\"([^\"]+)\"")


def _slug(heading: str) -> str:
    # GitHub's anchor rule: lower-case, drop punctuation except - and _, spaces to -.
    text = re.sub(r"[`*]", "", heading.strip().lower())
    return re.sub(r"[^\w\- ]", "", text).replace(" ", "-")


def _anchors(page: Path) -> set[str]:
    text = re.sub(r"```.*?```", "", page.read_text(), flags=re.S)
    return {_slug(h) for h in re.findall(r"^#{1,6} (.+)$", text, flags=re.M)}


def _markdown_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "*.md"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    return [ROOT / p for p in out]


def test_every_link_and_anchor_resolves():
    broken = []
    for page in _markdown_files():
        text = re.sub(r"```.*?```", "", page.read_text(), flags=re.S)
        for m in _LINK.finditer(text):
            link = m.group(1) or m.group(2)
            own = _SELF.match(link)
            if own:
                target, anchor = ROOT / own.group(1), (own.group(2) or "")
                if not own.group(1):  # the repository front page
                    target = ROOT / "README.md"
            elif re.match(r"[a-z]+:", link):
                continue  # other sites are out of scope
            else:
                path, _, frag = link.partition("#")
                target = (page.parent / path) if path else page
                anchor = f"#{frag}" if frag else ""
            rel = page.relative_to(ROOT)
            if not target.exists():
                broken.append(f"{rel}: {link} (no such file)")
            elif anchor and target.suffix == ".md" and anchor[1:] not in _anchors(target):
                broken.append(f"{rel}: {link} (no such heading)")
    assert not broken, "broken links:\n  " + "\n  ".join(broken)


def test_every_doc_page_is_reachable_from_its_index():
    for folder in ("docs", "docs-tech"):
        index = (ROOT / folder / "README.md").read_text()
        for page in (ROOT / folder).glob("*.md"):
            if page.name != "README.md":
                assert f"({page.name})" in index, (
                    f"{folder}/README.md does not link {page.name}"
                )
